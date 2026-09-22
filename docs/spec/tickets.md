# Tickets

**Format:** Markdown with flat frontmatter, over a filesystem layout ·
**Schema version:** 1.0 · **Root:** conventionally `state/` in the
operator home.

## Purpose

Tickets are the work queue between roles: a unit of work enqueued for
a role (builder, judge, or any other), claimed exclusively, and
resolved into history with a disposition. The filesystem is the
database, deliberately: `ls` is the queue view, `grep` searches
history, and git diffs the state — no daemon, no lock server, no
query language.

## Trust position

Written **operator-side** (the loop and operator tooling enqueue and
resolve). Tickets are builder-readable — a builder ticket *is* the
builder's work order — but must never carry judge material beyond the
feedback the operator chose to include: a ticket that embeds scores
or rubric text is a leak regardless of where it sits.

## Store layout

```
<root>/
  queue/<role>/<id>.md      open tickets, one file each
  locks/<id>.lock           claimed = lock file exists
  history/<role>/<id>.md    resolved tickets, disposition appended
```

- `<role>` is an open vocabulary (`builder`, `judge`, ...); the set of
  roles is simply the set of `queue/` subdirectories.
- Ticket ids are `YYYYmmdd-HHMMSS-<slug>` — the creation time plus a
  slug of the title (lowercase alphanumerics and hyphens, at most 40
  characters, `ticket` when the title yields nothing); collisions
  append `-2`, `-3`, ...
- Queue and history listings order by filename, which by construction
  is chronological.

## Ticket document

```
---
id: 20260922-081500-fix-note-persistence
role: builder
title: Fix note persistence
created_at: 2026-09-22T08:15:00
priority: high
---

The fetch after restart returns 404. See feedback for the failing
step transcript.
```

Frontmatter is a **flat `key: value` subset of YAML**, parsed line by
line — no nesting, no lists, no quoting rules. Reserved keys:

| Key | Required | Meaning |
|-----|----------|---------|
| `id` | yes | ticket id (matches the filename stem) |
| `role` | yes | owning queue |
| `title` | yes | one-line summary |
| `created_at` | yes | ISO 8601 |
| `disposition` | on resolved tickets | outcome (e.g. `done`, `wontfix`) |

Any other key is a free-form string field carried verbatim. The body
below the frontmatter is free markdown.

## Claiming

A ticket is claimed by creating `locks/<id>.lock` with
`O_CREAT | O_EXCL` — atomic on every platform, including Windows. The
lock file contains the claimant's pid and an ISO 8601 timestamp,
newline-terminated. Lock present = claimed; the lock is removed when
the claim ends (including on error). A crashed claimant leaves a
stale lock, detectable by the lock file's age and stealable by
force-removing it — stealing a live claim is on the caller.

## Resolution

Resolving appends a disposition section to the document, sets the
`disposition` frontmatter key, moves the file from `queue/<role>/` to
`history/<role>/` (same filename), and removes any lock:

```
## Disposition

disposition: done
resolved_at: 2026-09-22T09:02:11

<optional note>
```

History is append-only in spirit: resolved tickets are not edited
further, and re-opening is a new ticket.

## Versioning

The layout and frontmatter subset are the format; `1.0` names them.
New reserved keys arrive as minor bumps; consumers MUST carry
unknown frontmatter keys through untouched (they are user data, not
noise).

## Conformance

- Producers MUST write the four required frontmatter keys; `id` MUST
  match the filename stem; `created_at` MUST be ISO 8601.
- Claimants MUST use an exclusive-create on the lock path (never
  test-then-create) and MUST remove the lock when the claim ends.
- Resolvers MUST move (not copy) the ticket to history, append the
  disposition section, and remove any lock.
- Tickets in builder queues MUST NOT contain scores, rubric text, or
  evaluation excerpts beyond operator-issued feedback.
- Consumers MUST tolerate unknown frontmatter keys and unknown roles.
