# The Evidence Contract

**Format:** TOML · **Schema version:** 1.0 · **File:** conventionally
`evidence-contract.toml`.

## Purpose

The contract answers, before any judging happens: *did this run
capture enough to be judged?* It declares, per scenario, the evidence
kinds a run must contain — with counts, named steps, and a trial
dimension — so that insufficiency fails fast at verification time
instead of being discovered downstream by a judge who cannot find
what a criterion cites.

## Trust position

The contract is a **pure projection of the rubric's evidence
declarations** — kinds, counts, steps, trials, and nothing else. This
is a design invariant, not a convenience: because it carries no
criteria, no points, and no thresholds, it is safe for builder eyes,
and rubric-derived contracts are byte-equivalent to hand-written
ones. It is authored (or derived via `derive_contract`) operator-side
and read by verification and by both roles.

A contract that leaks scoring information — criterion text, point
values, pass thresholds — is nonconforming regardless of field shape.

## Schema

Top level:

| Field | Type | Required | Meaning |
|-------|------|----------|---------|
| `schema_version` | string | no (default `"1.0"`) | contract schema version |
| `project` | string | no (default `""`) | project name |
| `[[scenario]]` | array of tables | yes | one per contracted scenario |

Scenario table:

| Field | Type | Required | Meaning |
|-------|------|----------|---------|
| `name` | string | yes | scenario name (matches the manifest's `scenario`) |
| `[[scenario.requires]]` | array of tables | no | capture requirements |

Requirement table:

| Field | Type | Required | Meaning |
|-------|------|----------|---------|
| `kind` | string | yes | evidence kind that must appear |
| `min_count` | integer ≥ 1 | no (default 1) | minimum matching items |
| `steps` | array of strings | no (default none) | steps that must each have a matching item |
| `trials` | integer ≥ 1 | no (default 1) | number of supplied runs in which the requirement must hold |

`trials` is the statistical dimension: 1 for deterministic scenarios;
higher for nondeterministic domains judged over a series of runs
rather than a single manifest.

## Scoping

A run that deliberately exercised one scenario is verified against
the contract *scoped* to that scenario: verification of a scoped run
considers only the selected scenario's requirements, and a scenario
absent from the contract scopes to an empty contract (structural
checks plus an uncontracted-scenario warning) — never to the full
contract.

## Versioning

`schema_version` follows the shared policy in [README.md](README.md).
An absent `schema_version` means `"1.0"`.

## Example

```toml
schema_version = "1.0"
project = "relay-service"

[[scenario]]
name = "note_created"

  [[scenario.requires]]
  kind = "http_transcript"
  min_count = 2
  steps = ["create", "fetch"]

  [[scenario.requires]]
  kind = "log"

[[scenario]]
name = "note_survives_restart"

  [[scenario.requires]]
  kind = "http_transcript"
  trials = 3
```

## Conformance

- Producers MUST NOT include criteria text, point values, weights, or
  pass thresholds — the contract is builder-readable by design.
- Every `[[scenario]]` MUST carry a non-empty `name`; every
  requirement MUST carry a non-empty `kind`; `min_count` and `trials`
  MUST be ≥ 1.
- A verifier MUST treat a scenario present in the manifest but absent
  from the contract as a warning, not a failure.
- A verifier checking a scenario-scoped run MUST scope the contract
  as described above.
- Consumers MUST ignore unrecognized fields.
