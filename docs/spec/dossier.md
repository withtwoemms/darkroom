# The Dossier

**Format:** JSON (with a canonical Markdown rendering) · **Schema
version:** 1.0 · **Produced by:** `darkroom dossier`, deterministically
assembled from operator-side state.

## Purpose

The dossier is the cross-run record of a project's delivery, collated
into one bundle: iteration memory, per-criterion score trajectories,
checkpoint subjects, gate peaks, and the usage ledger. It exists so
that narration tooling — and the operator — reads one document instead
of spelunking four file kinds. Assembly is zero-LLM and side-effect
free; *interpretation* (sticking-point detection, novelty callouts,
progress narration) belongs to the layer above, which consumes this
format.

## Trust position

**Operator-facing only.** The dossier carries score trajectories and
per-criterion results, so writing it anywhere a builder-side process
can read reopens the scores side-channel the operator home closed. A
conforming producer refuses to write the bundle inside the tenant.

## Schema

Top level:

| Field | Type | Meaning |
|-------|------|---------|
| `schema_version` | string | `"1.0"` |
| `project` | string | project name |
| `generated_at` | string | ISO 8601 assembly time |
| `scenario` | string or null | the scenario filter, or null for the whole project |
| `iterations` | array | loop iteration entries, oldest first |
| `evaluations` | array | evaluation summaries, ordered by `evaluated_at` |
| `checkpoints` | array | `auto:` checkpoint commits from tenant history, oldest first |
| `gates` | array or null | current peak records, or null when no gates file exists |
| `usage` | object | the usage ledger and its totals |

Iteration entry (parsed from iteration memory; all fields beyond
`number`/`at` optional — the parser tolerates format drift):

| Field | Type | Meaning |
|-------|------|---------|
| `number` | integer | iteration number |
| `at` | string | timestamp |
| `scenario` | string | owning scenario, when recorded |
| `score` / `best_score` | number | the iteration's score and best-so-far |
| `stagnation` | integer | consecutive non-improving iterations |
| `action` | string | `converged`, `built`, or `rolled-back-and-built` |
| `escalation` | array of strings | fired dials (`diagnostic`, `model-escalation`) |
| `changed` | array of strings | files changed by the iteration |

Evaluation summary:

| Field | Type | Meaning |
|-------|------|---------|
| `file` | string | source filename in loop state |
| `run_id`, `evaluated_at`, `rubric_version` | strings | as in [evaluation.md](evaluation.md) |
| `scenarios[]` | array | per scenario: `scenario`, `score` (0–100 or null), `criteria[]` with `criterion`/`passed`/`points_earned`/`points_possible` |

Checkpoint: `{commit, subject}`. Gate entries mirror
[gates.md](gates.md) peak records with `recorded_at` serialized.

Usage:

| Field | Type | Meaning |
|-------|------|---------|
| `records` | array | usage records as written by the metering layer (role, iteration, model, tokens, cost, duration, `partial`, `scenario`) |
| `totals.calls` | integer | all agent calls |
| `totals.metered_calls` | integer | calls with parsed cost |
| `totals.cost_usd` | number or null | summed metered cost (null when nothing was metered) |
| `totals.input_tokens` / `output_tokens` | integer or null | summed where known |
| `totals.by_role` | object | per role: `calls`, `cost_usd`, `models` (in order of first use — an escalation appears as a second model) |

## Scenario scoping

With a scenario filter, every section narrows to that scenario:
iterations attributed to other scenarios drop out (entries with no
attribution are kept — pre-attribution records cannot be assigned),
evaluation summaries keep only the matching scenario blocks, gates
and usage records filter by scenario.

## Versioning

`schema_version` follows the shared policy in [README.md](README.md).
Sections are independently optional-empty: a consumer MUST render a
bundle with empty arrays or null sections rather than fail — early
projects have little history, and that is itself information.

## Conformance

- Producers MUST assemble deterministically from recorded state — no
  model calls, no scoring, no interpretation.
- Producers MUST NOT write the bundle inside the tenant, and SHOULD
  refuse an output path that resolves there.
- Consumers MUST ignore unrecognized fields and tolerate missing
  optional iteration fields.
- Interpretation layers MUST NOT feed dossier content back to
  builder-side processes.
