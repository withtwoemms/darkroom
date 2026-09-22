# Regression Gates

**Format:** JSON · **Schema version:** 1.0 · **File:** conventionally
`evidence-gates.json`, committed to the tenant repository.

## Purpose

A gate asserts that no future run ships a scenario below its recorded
peak. The gates file holds one **peak record** per scenario — the
high-water score, the run that earned it, the commit to retreat to,
and the rubric version that defined "good" at the time. Gates turn
"never ship below peak" from a team convention into a mechanical
check.

The governing principle: **a red gate must always mean something
real.** Every rule below exists to protect that property.

## Trust position

Written **operator-side** — by the loop on convergence (which
checkpoints its own gate write) or by an explicit operator `gate
update`. The file lives in the tenant repository and is committed, so
deliberate gate edits stay visible in history: the floor is public,
and tampering with it is attributable. The builder may *read* gates —
peak scores are targets already met, not a Goodhart channel — but a
builder-side process MUST NOT write them; the score authority behind
a peak is the evaluation, which the builder never sees.

## Schema

Top level:

| Field | Type | Required | Meaning |
|-------|------|----------|---------|
| `schema_version` | string | no (default `"1.0"`) | gates schema version |
| `project` | string | no (default `""`) | project name |
| `peaks` | array | yes | one record per gated scenario, sorted by scenario name |

Peak record:

| Field | Type | Required | Meaning |
|-------|------|----------|---------|
| `scenario` | string | yes | scenario name |
| `score` | number | yes | peak score, 0–100 |
| `run_id` | string | no (default `""`) | the run that earned the peak — the evidence |
| `recorded_at` | string | yes | ISO 8601 timestamp of the recording |
| `rubric_version` | string | no (default `""`) | rubric version the peak was scored under |
| `commit` | string | no (default `""`) | the retreat point: the commit that achieved the peak |

## Check semantics

Checking compares an evaluation against the gates file. It is pure —
a check changes nothing. Per scenario in the evaluation, exactly one
finding:

| Finding | Condition | Meaning |
|---------|-----------|---------|
| `ungated` | scenario has no scored criteria, or no recorded peak | nothing to compare; not a failure |
| `stale-peak` | peak's `rubric_version` ≠ evaluation's | scores are incomparable across rubric versions; **re-baseline needed, never a regression** |
| `regression` | same rubric version, score < peak | the only red state |
| `held` | same rubric version, score ≥ peak | the gate held |

The regression/stale-peak distinction is the heart of the format: a
rubric change silently converting into a "regression" would make red
gates ambiguous, and an ambiguous red gate destroys the trust the
whole mechanism exists to provide.

## Update semantics

Updating ratchets peaks from an evaluation; it never lowers one:

- `ungated` with a score → the score becomes the scenario's first peak.
- `stale-peak` → **re-baseline**: the new score becomes the peak under
  the new rubric version (even if numerically lower than the old peak
  — the old number was measured on a different scale).
- `held` with score ≥ peak → the peak advances (equal scores refresh
  `run_id`/`commit`/`recorded_at` to the newest achieving run).
- `regression` → the old peak is kept; the regression is reported,
  not recorded.
- Scenarios absent from the evaluation keep their peaks untouched.

Every new peak records the evaluation's `run_id` and
`rubric_version`, the supplied `commit`, and the recording time.

## Versioning

`schema_version` follows the shared policy in [README.md](README.md).
An absent `schema_version` means `"1.0"`.

## Example

```json
{
  "schema_version": "1.0",
  "project": "relay-service",
  "peaks": [
    {
      "scenario": "note_created",
      "score": 100.0,
      "run_id": "20260922T081500-3f2a",
      "recorded_at": "2026-09-22T08:17:02+00:00",
      "rubric_version": "2",
      "commit": "9c1e2f4"
    }
  ]
}
```

## Conformance

- Scores MUST be on the 0–100 scale; `recorded_at` MUST be ISO 8601.
- A checker MUST report a rubric-version mismatch as `stale-peak`,
  MUST NOT report it as `regression`, and MUST compare scores only
  under equal rubric versions.
- An updater MUST NOT lower a peak within a rubric version and MUST
  re-baseline on a version change; peaks it writes MUST carry the
  evaluating run's `run_id` and `rubric_version`.
- Writers MUST be operator-side processes; the file SHOULD be
  committed so gate movements remain attributable in history.
- Consumers MUST ignore unrecognized fields.
