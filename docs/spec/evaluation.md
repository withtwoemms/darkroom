# The Evaluation

**Format:** JSON · **Schema version:** 1.0 · **File:** operator-side
run state (never inside the tenant).

## Purpose

The evaluation is what a judge — an LLM judge, a human, or any scorer
— hands back for a run: per-criterion points with the manifest items
cited as basis. It is the score half of the manifest handoff, and the
citation requirement is what makes every point auditable back to
captured bytes.

Scores are percentages on a **0–100 scale**. `rubric_version` records
what "good" meant at scoring time: evaluations are comparable only
under the same rubric version, and gates carry the version forward
for exactly this reason.

## Trust position

Written by the **judge**, held **operator-side** (run state in the
operator home). The builder MUST NOT be able to read evaluations:
scores visible between iterations are a Goodhart channel — the
builder optimizes the number instead of the behavior. What the
builder receives instead is *feedback*, a separate operator-mediated
document derived from the evaluation at a configured specificity.

## Schema

Top level:

| Field | Type | Required | Meaning |
|-------|------|----------|---------|
| `schema_version` | string | no (default `"1.0"`) | evaluation schema version |
| `run_id` | string | yes | the evaluated run |
| `evaluated_at` | string | yes | ISO 8601 timestamp |
| `project` | string | no (default `""`) | project name |
| `rubric_version` | string | no (default `""`) | rubric version the scoring used |
| `notes` | string | no (default `""`) | judge-level notes (incl. harness notes) |
| `summary` | object | emitted, ignored on load | derived totals (below) |
| `scenarios` | array | yes | per-scenario results |

Scenario:

| Field | Type | Required | Meaning |
|-------|------|----------|---------|
| `scenario` | string | yes | scenario name |
| `criteria` | array | yes | per-criterion results |

Criterion result:

| Field | Type | Required | Meaning |
|-------|------|----------|---------|
| `criterion` | string | yes | criterion identifier |
| `passed` | boolean | yes | whether the criterion passed |
| `points_earned` | number | yes | points awarded |
| `points_possible` | number | yes | points available |
| `evidence` | array of strings | no (default `[]`) | **manifest item paths cited as basis** |
| `notes` | string | no (default `""`) | judge's reasoning for this criterion |

Summary (derived; producers emit it for human readers, consumers
recompute rather than trust it):

| Field | Meaning |
|-------|---------|
| `total_earned` / `total_possible` | sums over all criteria |
| `percentage` | `100 × earned / possible`; `0.0` when no points possible |
| `all_passed` | every criterion of every scenario passed (false when empty) |

## Strict vs. lenient loading

Two loading disciplines exist deliberately, and conforming consumers
choose by provenance:

- **Strict** — for documents written by conforming producers: required
  fields as tabled above.
- **Lenient coercion** — for raw LLM-judge output, which drifts.
  A lenient consumer SHOULD absorb: scores on a 0–1 scale
  (values in [0, 1] scale by 100), `overall_score`/`pass_rate` as
  synonyms for `percentage`, `total_earned_score`/`total_max_score` as
  synonyms for the totals, scenarios and criteria given as mappings
  (name → body) rather than arrays, `name`/`id` as synonyms for
  `scenario`/`criterion`, `earned`/`possible` as synonyms for the
  point fields, numbers as strings, a bare string as a one-element
  `evidence` list, and a missing `passed` derived as
  `possible > 0 and earned >= possible`.

Lenient coercion is a normalization boundary: what is stored and
compared downstream is always the strict form.

## Versioning

`schema_version` follows the shared policy in [README.md](README.md).
An absent `schema_version` means `"1.0"`.

## Example

```json
{
  "schema_version": "1.0",
  "run_id": "20260922T081500-3f2a",
  "evaluated_at": "2026-09-22T08:16:40+00:00",
  "project": "relay-service",
  "rubric_version": "2",
  "notes": "Harness notes: all steps completed; no diagnostics.",
  "summary": {
    "total_earned": 25.0,
    "total_possible": 25.0,
    "percentage": 100.0,
    "all_passed": true
  },
  "scenarios": [
    {
      "scenario": "note_created",
      "criteria": [
        {
          "criterion": "persists",
          "passed": true,
          "points_earned": 15.0,
          "points_possible": 15.0,
          "evidence": ["note_created/create.json", "note_created/fetch.json"],
          "notes": "POST 201 then GET returns the note verbatim."
        },
        {
          "criterion": "validates_input",
          "passed": true,
          "points_earned": 10.0,
          "points_possible": 10.0,
          "evidence": ["note_created/reject.json"],
          "notes": "Empty body rejected with 422."
        }
      ]
    }
  ]
}
```

## Conformance

- Producers MUST cite evidence as manifest item `path` values from
  the run being evaluated; a criterion awarded points with no citable
  evidence SHOULD say why in `notes`.
- `evaluated_at` MUST be ISO 8601; scores MUST be on the 0–100 scale
  in stored form.
- An evaluation MUST NOT be written anywhere a builder-side process
  can read; feedback to the builder is a separate derived document.
- Consumers MUST recompute totals rather than trust `summary`, MUST
  compare scores only under equal `rubric_version`, and MUST ignore
  unrecognized fields.
