# Proofs

**Format:** TOML · **Schema version:** 1.0 · **File:** one proof per
scenario, named `<scenario>.proof.toml`, in the operator home's
`proofs/` directory (`~/.darkroom/projects/<name>/proofs/`).

## Purpose

A proof is the sealed exam for one scenario as one file: the
**exposure** — the steps that drive the system under test as a black
box and capture what it does — and the **rubric** — the criteria that
score what the exposure produced. Drive scripts and vault rubrics
carried the same two halves in two files only because drives arrived
two releases after rubrics; they were always one secret with one
lifecycle. In a proof a criterion's `witnesses` resolve inside the same
file (a cited step that does not exist is a load error, not a
judge-time surprise), the evidence kinds a criterion rests on are
derived from the steps it cites instead of being restated, and the
evidence contract and gates no longer need a tenant-side file at all.

The photography vocabulary, for orientation: the **spec** states the
behavior, the **exposure** produces the record, the **rubric** says
what a good record shows, the **judge** scores the record against it,
the **gate** ratchets the score, and the **proof** is the sealed
exposure-plus-rubric. `darkroom expose` runs the exposure (`darkroom
drive` is the same command under its older name).

## Trust position

Authored and held **operator-side**; the builder never reads a proof.
The vault hands the judge the *rubric half only* — `list` names
proofs by scenario and `read` renders the criteria as rubric-shaped
TOML with the steps absent — so a judge scores records and never sees
the exposure that produced them. What the builder learns of the exam
comes from the same two sanitized channels as before: the scenario
spec and the harness log (step names and failure details). Step names
that would reveal criteria or scoring are misauthored.

## Document shape

| Field | Type | Required | Meaning |
|-------|------|----------|---------|
| `scenario` | string | yes | the scenario this proof exposes and scores |
| `version` | string (default `"1"`) | no | the rubric's version: bump when the standard changes, not the mechanics — scores across a version change re-baseline, never read as regression |
| `trials` | integer (default 1) | no | how many runs each criterion's evidence must appear in |
| `include` | array of strings | no | preludes (below) expanded, in order, ahead of the proof's own steps |
| `[serve]` | table | no | overrides of the adapter's `[serve.defaults]` for this scenario |
| `[browser]` | table | no | overrides of the adapter's `[browser.defaults]` |
| `record` | boolean | no | screencast the scenario (browser scenarios) |
| `[[step]]` | array of tables | yes | the exposure, in order — every step kind, field, interpolation form, and expectation of [drive-scripts.md](drive-scripts.md) 1.7 applies unchanged; `kind` defaults to `"http"` |
| `[[criterion]]` | array of tables | yes (≥ 1) | the rubric |

Every criterion carries:

| Field | Type | Required | Meaning |
|-------|------|----------|---------|
| `id` | string | yes | unique within the proof |
| `points` | number | yes | the criterion's weight |
| `description` | string | no | what a good record shows, for the judge |
| `witnesses` | array of step names | one of `witnesses` / `evidence` | the steps whose resolved records prove it; each must name a step in the (expanded) exposure |
| `evidence` | array of evidence kinds | one of `witnesses` / `evidence` | the kinds the criterion rests on; omitted, it is derived from the witnesses |
| `confidence` | string | no | passed through to the judge |

### Derived evidence

A criterion that cites witnesses need not say what kinds of evidence
they produce — the step kind says:

| step kind | evidence kind |
|-----------|---------------|
| `http` | `http_transcript` |
| `command` | `command_transcript` |
| `screenshot` | `screenshot` |
| `assert`, `goto`, `click`, `fill`, `container` | `log` |
| `wait`, `keygen` | none |

A cited step carrying an `expect` table adds `log` (the expectation
witness of drive-scripts 1.4) ahead of its own kind. A criterion that
declares `evidence` keeps its declaration verbatim; one that declares
neither is refused at load.

### The rubric a judge receives

`rubric_text(proof)` renders, in this order: `feature_id` (the
scenario with underscores as dashes — kept so evaluation and gate
records key the way they always have), `version`, `scenario`, `trials`
(when not 1), then each `[[criterion]]` with `id`, `points`,
`description`, `confidence`, the (derived or declared) `evidence`, and
`witnesses`. No step appears. An OpenBao vault stores the whole proof
and renders this half on read.

## Preludes

`~/.darkroom/projects/<name>/preludes.toml` names step sequences many
proofs share — founding a circle, registering two members:

```toml
[[prelude]]
name = "founded"

[[prelude.step]]
name = "found"
method = "POST"
url = "{base_url}/circles"
save = { slug = "$.slug" }
```

A proof with `include = ["founded"]` runs those steps first, names
intact, so its criteria can cite `found` as a witness. Includes expand
in order; a step name that collides with the proof's own, or a prelude
that does not exist, is a load error. Drive scripts may include
preludes too.

## The adapter's share

Three `darkroom.toml` tables let a proof carry only what differs from
the project:

```toml
[serve.defaults]        # every exposure's [serve] starts here
ttl = 120
key_approval = 0

[serve.env]             # the engine sets the served process's environment
APP_TTL_SECONDS = "{ttl}"
APP_PORT = "{port}"
APP_DATABASE_URL = "postgresql://exam@{postgres.host}:{postgres.port}/app"

[browser.defaults]
webauthn = true
```

`[serve.env]` templates see `{port}`, every serve variable, and each
declared service's `{name.host}` / `{name.port}`; a template with no
value for a placeholder fails the scenario's boot by name. The
`serve` command's own `{...}` substitution is unchanged.

## What is derived, and from where

| Was | Now |
|-----|-----|
| `evidence-contract.toml` in the tenant, `[evidence] contract` | derived at run time from the proofs' criteria — nothing committed. A declared contract file, when present, still wins |
| `evidence-gates.json` in the tenant, `[evidence] gates` | `~/.darkroom/projects/<name>/state/gates.json` unless `[evidence] gates` is declared |
| `feature_id` in the rubric | the scenario, dashed |
| `kind = "http"` on most steps | the default |
| `evidence = [...]` on most criteria | the cited steps' kinds |
| `drives/` + `vault/*.rubric.toml` | `proofs/` — the two layouts never mix: a home holding proofs is read as proofs, and `drives/` and vault rubrics are then ignored |

## The spec's surfaces doc string

A scenario spec names every surface the builder must produce — routes
with their outcomes, selectors with their state attributes — in a
Gherkin doc string whose media type is `surfaces`, on whichever step
claims it:

```gherkin
    And the surfaces hold:
      """surfaces
      POST /notes                        → 201 {id, token}
      DELETE /notes/{id}  X-Note-Token   → 204; wrong token → 403; after → 404
      #delete-button [data-state=armed|fired]
      """
```

A doc string is legal Gherkin wherever a step is (``` ``` ``` fences
work too), so the spec stays a `.feature` any tool can parse — the
media type is what marks this one as the contract; a step's untyped
doc string is its own business. Left of the arrow is the surface: a
line opening with an HTTP method is a route (`{name}` segments match
anything), anything else a selector (its first token is what a step
must cite). Implementation advice for the builder stays in the
feature's prose, not in the contract. `darkroom audit` cross-checks
the declared surfaces against the scenario's exposure both ways —
`surface-undeclared` (warning: a step touches a surface the spec never
names, so the builder was never told) and `surface-untouched` (info: a
declared surface no step reaches — declared, not proven). Specs are
matched to scenarios by file stem; several surfaces doc strings in one
spec add up; a spec without one declares nothing and gets no findings.

## Migration

`darkroom migrate` pairs each `drives/<scenario>.drive.toml` with the
vault rubric whose `scenario` names it and writes
`proofs/<scenario>.proof.toml`, dropping `kind = "http"`, `feature_id`,
and any `evidence` the witnesses imply, carrying `version` and
`trials`. Serve keys identical across ≥ 90% of the drives are printed
as a `[serve.defaults]` block; once darkroom.toml carries it, a re-run
drops those keys from each proof. `--check` plans without writing;
`--force` overwrites existing proofs. The tenant is never written.
Unpaired drives or rubrics are reported and left alone.

## Versioning

`1.0` names the shape above over drive-scripts 1.7's step vocabulary.
Step kinds, fields, and expectations continue to version in
[drive-scripts.md](drive-scripts.md); criterion fields version here.

## Example

```toml
scenario = "deletion_guarded"
version = "1"
include = ["noted"]                 # a prelude that creates a note, saving {note_id} and {token}

[[step]]
name = "wrong_token_refused"
method = "DELETE"
url = "{base_url}/notes/{note_id}"
headers = { X-Note-Token = "not-it" }
expect = { status = 403 }

[[step]]
name = "right_token_deletes"
method = "DELETE"
url = "{base_url}/notes/{note_id}"
headers = { X-Note-Token = "{token}" }
expect = { status = 204 }

[[step]]
name = "gone"
url = "{base_url}/notes/{note_id}"
expect = { status = 404 }

[[criterion]]
id = "wrong_token_refused"
points = 10
description = "a wrong token is refused with 403 and the note survives"
witnesses = ["wrong_token_refused"]           # evidence: log, http_transcript

[[criterion]]
id = "right_token_deletes"
points = 10
description = "the holder's token deletes; the note is then 404"
witnesses = ["right_token_deletes", "gone"]
```

## Conformance

- A producer MUST name the file `<scenario>.proof.toml` with the
  `scenario` field matching the stem, and MUST give every criterion an
  `id`, numeric `points`, and `witnesses` or `evidence`.
- A consumer MUST refuse a criterion citing a witness that names no
  step in the expanded exposure.
- A consumer handing a proof to a judge MUST render the rubric half
  only; the steps MUST NOT reach the judge.
- A consumer MUST treat a home holding proofs as the exam and MUST NOT
  mix proofs with drive scripts and vault rubrics in one run.
- Derived evidence MUST follow the table above; declared `evidence`
  MUST be passed through unchanged.
