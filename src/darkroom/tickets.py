"""Filesystem ticketing: the ad-hoc issue tracker, ported from the source
framework's ``state/`` conventions.

The filesystem is the database, deliberately: ``ls`` is the queue view,
``grep`` searches history, git diffs the state. Layout under a store
root::

    queue/<role>/<id>.md      open tickets (role = builder, judge, ...)
    locks/<id>.lock           claimed = lock file exists
    history/<role>/<id>.md    resolved tickets, disposition appended

Tickets are markdown files with flat ``key: value`` frontmatter — a
YAML-compatible subset parsed by hand, so the source framework's
existing tickets remain readable and no yaml dependency is taken.
Claiming uses ``O_CREAT | O_EXCL`` lock files (atomic everywhere,
including Windows); a crashed claimant leaves a stale lock, detectable
by age and stealable with ``force``.
"""

from __future__ import annotations

import os
import re
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path


@dataclass
class Ticket:
    id: str
    role: str
    title: str
    body: str = ""
    created_at: datetime = field(default_factory=datetime.now)
    fields: dict[str, str] = field(default_factory=dict)


class TicketError(Exception):
    pass


class AlreadyClaimed(TicketError):
    pass


def _slug(text: str, max_length: int = 40) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return slug[:max_length] or "ticket"


def _serialize(ticket: Ticket) -> str:
    lines = [
        "---",
        f"id: {ticket.id}",
        f"role: {ticket.role}",
        f"title: {ticket.title}",
        f"created_at: {ticket.created_at.isoformat()}",
    ]
    for key, value in ticket.fields.items():
        lines.append(f"{key}: {value}")
    lines.append("---")
    lines.append("")
    if ticket.body:
        lines.append(ticket.body.rstrip())
        lines.append("")
    return "\n".join(lines)


def _parse(text: str, role: str) -> Ticket:
    match = re.match(r"\A---\n(.*?)\n---\n?(.*)\Z", text, re.DOTALL)
    if not match:
        raise TicketError("ticket has no frontmatter")
    front, body = match.groups()

    fields: dict[str, str] = {}
    for line in front.splitlines():
        if ":" not in line:
            continue
        key, _, value = line.partition(":")
        fields[key.strip()] = value.strip()

    created_raw = fields.pop("created_at", "")
    try:
        created_at = datetime.fromisoformat(created_raw)
    except ValueError:
        created_at = datetime.now()

    return Ticket(
        id=fields.pop("id", ""),
        role=fields.pop("role", role),
        title=fields.pop("title", ""),
        body=body.strip(),
        created_at=created_at,
        fields=fields,
    )


class TicketStore:
    def __init__(self, root: Path):
        self.root = Path(root)

    # --- paths ---

    def _queue_dir(self, role: str) -> Path:
        return self.root / "queue" / role

    def _history_dir(self, role: str) -> Path:
        return self.root / "history" / role

    def _lock_path(self, ticket_id: str) -> Path:
        return self.root / "locks" / f"{ticket_id}.lock"

    def _ticket_path(self, role: str, ticket_id: str) -> Path:
        return self._queue_dir(role) / f"{ticket_id}.md"

    # --- lifecycle ---

    def enqueue(self, role: str, title: str, body: str = "", **fields) -> Ticket:
        created_at = datetime.now()
        base = f"{created_at.strftime('%Y%m%d-%H%M%S')}-{_slug(title)}"
        ticket_id = base
        queue_dir = self._queue_dir(role)
        queue_dir.mkdir(parents=True, exist_ok=True)
        suffix = 1
        while self._ticket_path(role, ticket_id).exists():
            suffix += 1
            ticket_id = f"{base}-{suffix}"
        ticket = Ticket(
            id=ticket_id,
            role=role,
            title=title,
            body=body,
            created_at=created_at,
            fields={k: str(v) for k, v in fields.items()},
        )
        self._ticket_path(role, ticket_id).write_text(_serialize(ticket))
        return ticket

    def queue(self, role: str) -> list[Ticket]:
        queue_dir = self._queue_dir(role)
        if not queue_dir.is_dir():
            return []
        tickets = [_parse(p.read_text(), role) for p in sorted(queue_dir.glob("*.md"))]
        return tickets

    def roles(self) -> list[str]:
        queue_root = self.root / "queue"
        if not queue_root.is_dir():
            return []
        return sorted(p.name for p in queue_root.iterdir() if p.is_dir())

    def get(self, role: str, ticket_id: str) -> Ticket:
        path = self._ticket_path(role, ticket_id)
        if not path.exists():
            raise TicketError(f"no open ticket '{ticket_id}' in queue '{role}'")
        return _parse(path.read_text(), role)

    # --- claiming ---

    def is_claimed(self, ticket_id: str) -> bool:
        return self._lock_path(ticket_id).exists()

    def lock_age(self, ticket_id: str) -> float | None:
        """Seconds since the lock was taken, or None if unclaimed."""
        lock = self._lock_path(ticket_id)
        if not lock.exists():
            return None
        return max(0.0, datetime.now().timestamp() - lock.stat().st_mtime)

    @contextmanager
    def claim(self, ticket: Ticket, force: bool = False):
        """Hold the ticket's lock for the duration of the block.

        ``force`` steals an existing lock — for stale locks left by a
        crashed claimant (check :meth:`lock_age` first); stealing a live
        claim is on the caller.
        """
        lock = self._lock_path(ticket.id)
        lock.parent.mkdir(parents=True, exist_ok=True)
        if force:
            lock.unlink(missing_ok=True)
        try:
            fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError:
            raise AlreadyClaimed(
                f"ticket '{ticket.id}' is already claimed"
            ) from None
        try:
            os.write(fd, f"{os.getpid()} {datetime.now().isoformat()}\n".encode())
            os.close(fd)
            yield ticket
        finally:
            lock.unlink(missing_ok=True)

    # --- resolution ---

    def resolve(self, ticket: Ticket, disposition: str, note: str = "") -> Path:
        """Append the disposition and move the ticket to history."""
        source = self._ticket_path(ticket.role, ticket.id)
        if not source.exists():
            raise TicketError(f"no open ticket '{ticket.id}' to resolve")

        resolved = _parse(source.read_text(), ticket.role)
        resolved.fields["disposition"] = disposition
        text = _serialize(resolved)
        text += (
            f"\n## Disposition\n\n"
            f"disposition: {disposition}\n"
            f"resolved_at: {datetime.now().isoformat()}\n"
        )
        if note:
            text += f"\n{note.rstrip()}\n"

        history_dir = self._history_dir(ticket.role)
        history_dir.mkdir(parents=True, exist_ok=True)
        destination = history_dir / source.name
        destination.write_text(text)
        source.unlink()
        self._lock_path(ticket.id).unlink(missing_ok=True)
        return destination

    def history(self, role: str) -> list[Ticket]:
        history_dir = self._history_dir(role)
        if not history_dir.is_dir():
            return []
        return [_parse(p.read_text(), role) for p in sorted(history_dir.glob("*.md"))]
