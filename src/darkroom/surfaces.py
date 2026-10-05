"""The ``.surfaces`` file: engineering's published interface, audited.

The spec says what the product must do; the build decides how it is
reached. The builder publishes that decision beside the spec, in
``scenarios/<name>.surfaces`` — a plain columnar text, five sections::

    [routes]
    POST /notes                   → 201 {id, token}
    DELETE /notes/{id}            X-Note-Token; 204; wrong token → 403
                                  a continuation line indents

    [commands]
    relay export                  writes notes.json; exit 0

    [pages]
    /                             the form; the list after a save
    #notes li                     one item per saved note

    [files]
    notes.json                    the export, one object per note

    [notes]
    free prose for whoever reads the evidence — what it is about

Left of the first run of two spaces is the surface, the rest its
description. A route opens with an HTTP method, then a path whose
``{name}`` segments match anything; a page is a path (opening with
``/``) or a selector (anything else — ``#notes li`` is one selector);
a command is the words a command step must contain, in order; files
and notes are for the reader and are never cross-checked.

The audit binds the exposure to the publication both ways: a step
touching a surface the build never published is ``surface-unpublished``
(warning — QA is probing an interface engineering has not declared, or
the file is stale), and a published surface no step reaches is
``surface-untouched`` (info — published, not proven). A scenario with
no ``.surfaces`` gets no findings. ``darkroom migrate`` drafts one from
a spec's ``Build:`` note, the place engineering's half used to live.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

SURFACES_SUFFIX = ".surfaces"
SECTIONS = ("routes", "commands", "pages", "files", "notes")
HTTP_METHODS = frozenset({"GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"})

_SECTION = re.compile(r"^\[(\w+)\]\s*$")
_COLUMN_GAP = re.compile(r"\s{2,}")
_PLACEHOLDER = re.compile(r"\{[^}]*\}")
_BACKTICKED = re.compile(r"`([^`]+)`")
_BUILD_NOTE = re.compile(r"^\s*Build:\s*(.*)$")


class SurfacesError(Exception):
    pass


@dataclass(frozen=True)
class Surface:
    kind: str  # "route" | "page" | "selector" | "command" | "file"
    method: str = ""  # routes only
    target: str = ""  # a normalized path, a selector, a command's words, a file
    description: str = ""

    def __str__(self) -> str:
        return f"{self.method} {self.target}" if self.kind == "route" else self.target


@dataclass
class Surfaces:
    entries: list[Surface] = field(default_factory=list)
    notes: str = ""

    def of(self, *kinds: str) -> list[Surface]:
        return [s for s in self.entries if s.kind in kinds]


def surfaces_path(spec: Path) -> Path:
    """The ``.surfaces`` beside a spec: ``deletion_guarded.feature`` →
    ``deletion_guarded.surfaces``."""
    spec = Path(spec)
    return spec.with_name(spec.name.split(".", 1)[0] + SURFACES_SUFFIX)


def normalize_path(url: str) -> str:
    """The path a URL or template addresses, placeholders widened to ``*``:
    ``{base_url}/notes/{note_id}?x=1`` and ``/notes/{id}`` both become
    ``/notes/*``."""
    url = _PLACEHOLDER.sub("*", url)
    if url.startswith("*"):
        url = url[1:]  # an interpolated base_url
    if "://" in url:
        authority_and_path = url.split("://", 1)[1]
        url = "/" + authority_and_path.split("/", 1)[1] if "/" in authority_and_path else "/"
    path = url.split("?", 1)[0].split("#", 1)[0]
    if not path.startswith("/"):
        path = "/" + path
    return path.rstrip("/") or "/"


def route(method: str, url: str) -> Surface:
    return Surface("route", method.upper(), normalize_path(url))


def page(url: str) -> Surface:
    return Surface("page", target=normalize_path(url))


def selector(text: str) -> Surface:
    return Surface("selector", target=text.strip())


def command(cmd: str) -> Surface:
    return Surface("command", target=" ".join(_PLACEHOLDER.sub("*", cmd).split()))


def _split_columns(body: str) -> tuple[str, str]:
    parts = _COLUMN_GAP.split(body, maxsplit=1)
    return parts[0].strip(), (parts[1].strip() if len(parts) > 1 else "")


def _entry(section: str, body: str, line_no: int) -> Surface:
    if section == "routes":
        # method and path are the first two words however they are
        # aligned; the description is whatever follows the path
        words = body.split(maxsplit=2)
        if len(words) < 2 or words[0].upper() not in HTTP_METHODS:
            raise SurfacesError(
                f"line {line_no}: a route opens with an HTTP method and a path ('{body}')"
            )
        description = words[2].strip() if len(words) == 3 else ""
        return Surface("route", words[0].upper(), normalize_path(words[1]), description)
    target, description = _split_columns(body)
    if section == "pages":
        if target.startswith("/"):
            return Surface("page", target=normalize_path(target), description=description)
        return Surface("selector", target=target, description=description)
    if section == "commands":
        return Surface("command", target=" ".join(target.split()), description=description)
    return Surface("file", target=target, description=description)


def parse_surfaces(text: str) -> Surfaces:
    surfaces = Surfaces()
    section: str | None = None
    notes: list[str] = []
    for line_no, raw in enumerate(text.splitlines(), start=1):
        if not raw.strip():
            continue
        header = _SECTION.match(raw)
        if header:
            section = header.group(1).lower()
            if section not in SECTIONS:
                raise SurfacesError(
                    f"line {line_no}: unknown section [{section}] — one of "
                    + ", ".join(f"[{s}]" for s in SECTIONS)
                )
            continue
        if section is None:
            raise SurfacesError(f"line {line_no}: text before the first [section]")
        if section == "notes":
            notes.append(raw.strip())
            continue
        if raw[0].isspace() and surfaces.entries:
            # an indented line continues the previous entry's description
            last = surfaces.entries[-1]
            surfaces.entries[-1] = Surface(
                last.kind, last.method, last.target,
                (last.description + " " + raw.strip()).strip(),
            )
            continue
        surfaces.entries.append(_entry(section, raw.strip(), line_no))
    surfaces.notes = "\n".join(notes)
    return surfaces


def load_surfaces(path: Path) -> Surfaces:
    return parse_surfaces(Path(path).read_text())


def touched_surfaces(script: dict) -> list[Surface]:
    """Every surface an exposure's steps address, in step order, deduplicated."""
    seen: list[Surface] = []

    def _add(surface: Surface) -> None:
        if surface not in seen:
            seen.append(surface)

    for step in script.get("step", []):
        kind = step.get("kind", "http")
        if kind == "http" and step.get("url"):
            _add(route(step.get("method", "GET"), step["url"]))
        elif kind == "goto" and step.get("url"):
            _add(page(step["url"]))
        elif kind == "click" and step.get("selector"):
            _add(selector(step["selector"]))
        elif kind == "fill":
            for sel in step.get("fields", {}):
                _add(selector(sel))
        elif kind == "command" and step.get("cmd"):
            _add(command(step["cmd"]))
        visible = step.get("expect", {}).get("selector_visible")
        if visible:
            _add(selector(visible))
    return seen


def _paths_match(published: str, touched: str) -> bool:
    left, right = published.split("/"), touched.split("/")
    return len(left) == len(right) and all(
        a == b or a == "*" or b == "*" for a, b in zip(left, right, strict=True)
    )


def _words_match(published: str, touched: str) -> bool:
    """The published words occur in the touched command, contiguously, in
    order; a ``*`` on either side matches any one word."""
    want, have = published.split(), touched.split()
    if not want:
        return False
    for start in range(len(have) - len(want) + 1):
        window = have[start : start + len(want)]
        if all(a == b or a == "*" or b == "*" for a, b in zip(want, window, strict=True)):
            return True
    return False


def matches(published: Surface, touched: Surface) -> bool:
    if published.kind == "route" and touched.kind == "route":
        return published.method == touched.method and _paths_match(
            published.target, touched.target
        )
    if published.kind == "page" and touched.kind == "page":
        return _paths_match(published.target, touched.target)
    # a page a browser opens and a GET the exposure makes are one surface
    if published.kind == "page" and touched.kind == "route" and touched.method == "GET":
        return _paths_match(published.target, touched.target)
    if published.kind == "route" and touched.kind == "page" and published.method == "GET":
        return _paths_match(published.target, touched.target)
    if published.kind == "selector" and touched.kind == "selector":
        return published.target == touched.target
    if published.kind == "command" and touched.kind == "command":
        return _words_match(published.target, touched.target)
    return False


def cross_check(published: Surfaces, script: dict) -> list[tuple[str, str]]:
    """(code, message) pairs: ``surface-unpublished`` for a touched surface
    the build never published, ``surface-untouched`` for a published one no
    step reaches. Files are never cross-checked."""
    findings: list[tuple[str, str]] = []
    touched = touched_surfaces(script)
    checkable = published.of("route", "page", "selector", "command")
    for surface in touched:
        if not any(matches(p, surface) for p in checkable):
            findings.append(
                (
                    "surface-unpublished",
                    f"the exposure touches {surface.kind} '{surface}' but the build "
                    "publishes no such surface — QA is probing an interface engineering "
                    "has not declared, or the .surfaces is stale",
                )
            )
    for surface in checkable:
        if not any(matches(surface, t) for t in touched):
            findings.append(
                (
                    "surface-untouched",
                    f"the build publishes {surface.kind} '{surface}' but no step "
                    "reaches it — published, not proven",
                )
            )
    return findings


def build_notes(spec_text: str) -> list[str]:
    """Every ``Build:`` paragraph in a spec, as one string each — the
    place engineering's half used to be written, in product's file."""
    notes: list[str] = []
    current: list[str] | None = None
    for raw in spec_text.splitlines():
        opened = _BUILD_NOTE.match(raw)
        if opened:
            if current:
                notes.append(" ".join(current))
            current = [opened.group(1).strip()]
            continue
        if current is None:
            continue
        if not raw.strip():
            notes.append(" ".join(current))
            current = None
            continue
        current.append(raw.strip())
    if current:
        notes.append(" ".join(current))
    return [" ".join(n.split()) for n in notes if n.strip()]


def draft_surfaces(spec_text: str) -> str | None:
    """A ``.surfaces`` drafted from a spec's ``Build:`` notes, or None when
    it has none: every backticked ``METHOD /path`` becomes a route, every
    backticked path or selector a page, and the notes carry the prose
    verbatim so nothing is lost. Descriptions are engineering's to add."""
    notes = build_notes(spec_text)
    if not notes:
        return None
    routes: list[str] = []
    pages: list[str] = []
    for note in notes:
        for token in _BACKTICKED.findall(note):
            words = token.split()
            if len(words) >= 2 and words[0].upper() in HTTP_METHODS and words[1].startswith("/"):
                entry = f"{words[0].upper()} {words[1]}"
                if entry not in routes:
                    routes.append(entry)
            elif token.startswith("/") and " " not in token:
                if token not in pages:
                    pages.append(token)
            elif token[0] in "#.[" and "=" not in token.split("[")[0]:
                if token not in pages:
                    pages.append(token)
    lines = ["[routes]", *routes, "", "[commands]", "", "[pages]", *pages, "", "[files]", ""]
    lines += ["[notes]", *notes]
    return "\n".join(lines) + "\n"
