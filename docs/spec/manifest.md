# The Run Manifest

**Format:** JSON · **Schema version:** 2.0 · **File:** conventionally
`runs/<run_id>/manifest.json`, adjacent to the evidence files it
indexes.

## Purpose

The manifest is the inventory of a single evidence run: every artifact
captured, for which scenario, at which step, when, and where the bytes
live. It is the handoff between the capturing side and the judging
side — the judge scores *what the manifest indexes*, never what anyone
claims. Downstream, evaluations cite manifest item paths as the basis
for points, which is what makes a score auditable back to bytes.

## Trust position

Written by the **harness** — non-LLM machinery (the drive engine, the
pytest plugin, the capture API). Agents never author manifests; a
manifest an agent wrote by hand is fabricated evidence. Builder-side
processes may read it (it contains no scores), and verification and
judging consume it. In drive mode the harness runs operator-side, so
the manifest's integrity does not depend on tenant honesty.

## Schema

Top level:

| Field | Type | Required | Meaning |
|-------|------|----------|---------|
| `schema_version` | string | yes | `"2.0"` |
| `run_id` | string | yes | unique identifier for the run |
| `project` | string | yes (may be `""`) | project name |
| `timestamp` | string | yes (may be `""`) | run start, ISO 8601 |
| `scenarios` | array of scenario bundles | yes | evidence grouped by scenario |

Scenario bundle:

| Field | Type | Required | Meaning |
|-------|------|----------|---------|
| `scenario` | string | yes | scenario name |
| `items` | array of evidence items | yes | captured artifacts, in capture order |

Evidence item:

| Field | Type | Required | Meaning |
|-------|------|----------|---------|
| `kind` | string | yes | evidence kind (see below) |
| `mime` | string | yes | MIME type of the artifact |
| `path` | string | yes | POSIX path to the bytes, relative to the manifest's directory (absolute allowed) |
| `scenario` | string | yes | owning scenario (repeats the bundle's) |
| `step` | string | yes | the step within the scenario that produced it |
| `captured_at` | string | yes | ISO 8601 timestamp |
| `metadata` | object | no (default `{}`) | producer-specific facts |

### Evidence kinds

`kind` is an open vocabulary. Kinds with established meaning:
`screenshot`, `screenshot_element`, `video`, `log`,
`command_transcript`, `file_snapshot`, `file_diff`,
`http_transcript`. New kinds MAY be introduced; consumers treat an
unknown kind as opaque (renderable at worst as a file reference).
Contracts (see [contract.md](contract.md)) are the mechanism that
makes a kind *required*; the manifest merely records what was
captured.

### Item ordering

Items appear in capture order. Environment-level evidence (e.g. the
container image-digest record) precedes the scenario's step evidence.

## Versioning & migration

v1 manifests carry no `schema_version` field — its absence *is* the
version marker. The v1→v2 migration (the precedent for all future
major bumps):

- v1 `scenarios[].name` → v2 `scenario`; v1 `evidence[]` → v2
  `items[]`.
- v1 items carried `type` instead of `kind`/`mime`; the mapping:
  `screenshot` → (`screenshot`, `image/png`), `screenshot_element` →
  (`screenshot_element`, `image/png`), `log` → (`log`,
  `application/json`); any other `type` maps to (itself,
  `application/octet-stream`).
- v1 items had no `metadata`; migrated items get `{}`.

Consumers SHOULD load v1 transparently by this mapping; producers
MUST NOT emit v1.

## Example

```json
{
  "schema_version": "2.0",
  "run_id": "20260922T081500-3f2a",
  "project": "relay-service",
  "timestamp": "2026-09-22T08:15:00+00:00",
  "scenarios": [
    {
      "scenario": "note_created",
      "items": [
        {
          "kind": "http_transcript",
          "mime": "application/json",
          "path": "note_created/create.json",
          "scenario": "note_created",
          "step": "create",
          "captured_at": "2026-09-22T08:15:03+00:00",
          "metadata": {"status": 201}
        },
        {
          "kind": "log",
          "mime": "application/json",
          "path": "note_created/harness.json",
          "scenario": "note_created",
          "step": "environment",
          "captured_at": "2026-09-22T08:15:01+00:00",
          "metadata": {}
        }
      ]
    }
  ]
}
```

## Conformance

- Producers MUST be non-interactive machinery; evidence paths MUST
  point at bytes that exist at write time.
- Producers MUST write every required field; `path` MUST be POSIX
  style and SHOULD be relative to the manifest's directory.
- `captured_at` and `timestamp` MUST be ISO 8601.
- Consumers MUST ignore unrecognized fields and MUST NOT fail on
  unknown `kind` values.
- Consumers resolving `path` MUST resolve relative paths against the
  manifest file's parent directory.
