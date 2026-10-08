# Proofs

**Format:** TOML (two files) · **Schema version:** 1.0 · **Location:**
one folder per scenario, `proofs/<scenario>/`, in the operator home
(`~/.darkroom/projects/<name>/proofs/`), holding `exposure.toml` and
`rubric.toml`.

## Purpose

A proof is the sealed exam for one scenario: the **exposure** — the
steps that drive the system under test as a black box and capture
what it does — and the **rubric** — the criteria that score what the
exposure produced. They share a lifecycle and a folder, not an author:
the exposure is QA's file and the rubric is product's, which is why
they are two files rather than one — each hat edits its own, and a
diff to the standard never hides in a diff to the mechanics. A
criterion's `witnesses` resolve against the exposure beside it (a
cited step that does not exist is a load error, not a judge-time
surprise), the evidence kinds a criterion rests on are derived from
the steps it cites instead of being restated, and the evidence
contract and gates no longer need a tenant-side file at all.

The hats, since the vocabulary runs through everything below:

| hat | writes | reads | never sees |
|-----|--------|-------|------------|
| product (the operator) | the spec (`scenarios/<name>.feature`), the rubric (`rubric.toml`) | surfaces, evidence | — |
| engineering (the builder) | the code, the surfaces (`scenarios/<name>.surfaces`) | the spec, feedback | the exposure, the rubric |
| QA (the operator) | the exposure (`exposure.toml`), backdrops | the spec, surfaces | — |
| review (the judge) | the verdict | the rubric, evidence, the surfaces' addresses | the code, the builder's prose |

Three people wear the four hats: the builder and the judge are agents;
product and QA are both the operator — one person, two hats, and the
hats separate *files*, not people. The discipline is in which file may
be touched to make a run go green: QA fixes the exposure, product never
quietly loosens the rubric, and neither edits the `.surfaces`.

And the photography vocabulary: the **spec** states the behavior, the
**backdrop** is the setup it is posed against, the **exposure**
produces the record, the **rubric** says what a good record shows,
the **judge** scores the record against it, the **gate** ratchets the
score, and the **proof** is the sealed exposure-plus-rubric. `darkroom
expose` runs the exposure (`darkroom drive` is the same command under
its older name).

## Trust position

Authored and held **operator-side**; the builder never reads a proof.
The vault hands the judge the *rubric half only* — `list` names
proofs by scenario and `read` renders the criteria as rubric-shaped
TOML with the steps absent — so a judge scores records and never sees
the exposure that produced them. What the builder learns of the exam
comes from the same two sanitized channels as before: the scenario
spec and the harness log (step names and failure details). Step names
that would reveal criteria or scoring are misauthored.

## `exposure.toml`

| Field | Type | Required | Meaning |
|-------|------|----------|---------|
| `scenario` | string | yes | the scenario this proof exposes; the folder is named after it |
| `backdrop` | array of strings | no | backdrops (below) expanded, in order, ahead of the exposure's own steps |
| `[serve]` | table | no | overrides of the adapter's `[serve.defaults]` for this scenario |
| `[browser]` | table | no | overrides of the adapter's `[browser.defaults]` |
| `record` | boolean | no | screencast the scenario (browser scenarios) |
| `[[step]]` | array of tables | yes | the exposure, in order — every step kind, field, interpolation form, and expectation of [drive-scripts.md](drive-scripts.md) 1.7 applies unchanged; `kind` defaults to `"http"` |

`version`, `trials`, and `[[criterion]]` are refused here: the
exposure produces records, it does not score them.

## `rubric.toml`

| Field | Type | Required | Meaning |
|-------|------|----------|---------|
| `version` | string (default `"1"`) | no | the rubric's version: bump when its **schema** changes — a criterion added or removed, an `id`, `points`, `witnesses`, `trials`, or a threshold a description states — never for a rewording of the same standard. Scores across a version change re-baseline and are never read as regression; a copy edit keeps the version so the gate's history stays one series |
| `trials` | integer (default 1) | no | how many runs each criterion's evidence must appear in |
| `scenario` | string | no | may restate the exposure's; must match if present |
| `[[criterion]]` | array of tables | yes (≥ 1) | the rubric |

`[[step]]`, `backdrop`, `[serve]`, `[browser]`, and `record` are refused
here: the rubric scores records, it does not drive. The file may be
absent while the exam is being written (the quickstart's stage 1):
the exposure then runs and is verified structurally, and sealing,
auditing, judging, and contract derivation refuse the folder by name
until the rubric arrives.

Every criterion carries:

| Field | Type | Required | Meaning |
|-------|------|----------|---------|
| `id` | string | yes | unique within the proof |
| `points` | number | yes | the criterion's weight |
| `description` | string | no | what a good record shows, in product's words — never a status code, a selector, or a step name; those are the exposure's business |
| `witnesses` | array of step names | one of `witnesses` / `evidence` | the steps whose records prove it; each must name a step in the expanded exposure, and never one from a backdrop |
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
neither is refused at load. `darkroom audit` refuses a cited step that
leaves no record — a bare `goto`, `click`, or `fill` without `expect` —
since it gates a run but gives the judge nothing to score.

### The rubric a judge receives

`rubric_text(proof)` renders, in this order: `feature_id` (the
scenario with underscores as dashes — kept so evaluation and gate
records key the way they always have), `version`, `scenario`, `trials`
(when not 1), then each `[[criterion]]` with `id`, `points`,
`description`, `confidence`, the (derived or declared) `evidence`, and
`witnesses`. No step appears. An OpenBao vault stores rubric text per
feature id and renders the same half on read.

## Backdrops

`~/.darkroom/projects/<name>/backdrops.toml` names step sequences many
exposures are posed against — creating a workspace, registering two
members. A backdrop is set before the sitting, reused across many,
and never the subject:

```toml
[[backdrop]]
name = "founded"

[[backdrop.step]]
name = "found"
method = "POST"
url = "{base_url}/workspaces"
save = { slug = "$.slug" }
```

An exposure with `backdrop = ["founded"]` runs those steps first,
names intact, so its own steps can use `{slug}`. Backdrops expand in
order; a step name that collides with the exposure's own, or a
backdrop that does not exist, is a load error. The authoring rule: a
witness is never in the backdrop — what the scenario proves is in its
own steps, so a change to shared setup never silently changes what
forty rubrics rest on. Drive scripts may carry `backdrop` too.

## Surfaces

The spec says what the product must do; the build decides how it is
reached. Engineering publishes that decision beside the spec, in
`scenarios/<name>.surfaces` — a plain columnar text, five sections:

```
[routes]
POST /notes                   → 201 {id, token}; the token is shown once
DELETE /notes/{id}            X-Note-Token header → 204; a wrong token → 403
                              and the note is untouched

[commands]
relay export                  writes notes.json; exit 0

[pages]
/                             the notes page: the form, and the list once saved
#notes li                     one item per saved note

[files]
notes.json                    the export, one object per note

[notes]
the token is compared in constant time; there is no "forgot my token"
```

Left of the first run of two spaces is the surface, the rest its
description (an indented line continues it). A route opens with an
HTTP method, then a path whose `{name}` segments match anything; a
page is a path (opening with `/`) or a selector (anything else —
`#notes li` is one selector); a command is the words a command step
must contain, in order; files and notes are for the reader. The file
is in the tenant because it is the builder's own: it tells QA what an
exposure can address, and tells product what was built.

The judge is handed the **inventory only** — the addresses, section by
section, with every description and the whole of `[notes]` stripped.
An address says what a transcript or screenshot is *of*; a
description says what it does, and that is the builder's account of
the change, which a judge must never be handed: a judge reading the
builder's prose starts scoring the prose. The trust rule behind the
whole map applies — builder-writable text may reach the judge only
where its manipulation is futile or caught — and an address is both:
it cannot argue, and a padded inventory is `surface-untouched` in the
audit. Builder prose reaches the operator and QA, the same way the
blocker channel does.

`darkroom audit` binds each exposure to its publication both ways:
`surface-unpublished` (warning — a step touches a surface the build
never published: QA is probing an interface engineering has not
declared, or the file is stale) and `surface-untouched` (info — a
published surface no step reaches: published, not proven). A page a
browser opens and a `GET` the exposure makes are one surface; files
and notes are never cross-checked. A scenario with no `.surfaces`
gets no findings; a malformed one is `surfaces-malformed` (error).

A scenario the builder has not touched since the file was introduced
has no publication to be held to. `darkroom surfaces` drafts one from
the addresses the scenario's exposure reaches on the current build —
descriptions blank, the notes saying it is a draft — and `--merge`
adds unpublished addresses to a file that already exists, its lines
kept verbatim. It is a baseline, not engineering's word: the builder
describes each surface and prunes what the build does not expose the
next time it works the scenario.

## The adapter's share

Three `darkroom.toml` tables let an exposure carry only what differs
from the project:

```toml
[serve.defaults]        # every exposure's [serve] starts here
ttl = 120
strict_mode = 1

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

`[evidence] keep_runs = N` prunes the evidence run directories to the
newest N after each drive, keeping any run a gate cites; unset keeps
everything.

## What is derived, and from where

| Was | Now |
|-----|-----|
| `evidence-contract.toml` in the tenant, `[evidence] contract` | derived at run time from the proofs' criteria — nothing committed. A declared contract file, when present, still wins |
| `evidence-gates.json` in the tenant, `[evidence] gates` | `~/.darkroom/projects/<name>/state/gates.json` unless `[evidence] gates` is declared |
| `feature_id` in the rubric | the scenario, dashed |
| `kind = "http"` on most steps | the default |
| `evidence = [...]` on most criteria | the cited steps' kinds |
| `Build:` prose in the spec | `scenarios/<name>.surfaces`, engineering's file |
| `drives/` + `vault/*.rubric.toml` | `proofs/<scenario>/` — the two layouts never mix: a home holding proofs is read as proofs, and `drives/` and vault rubrics are then ignored |

## What a run records

Every scenario bundle in the [manifest](manifest.md) (2.1) carries a
`provenance` object: `exposure_sha256`, the digest of the
`exposure.toml` as run, and `rubric_version`, the rubric's `version`
at the time. A verdict therefore names the exam it answered, and a
run made before an exposure was edited is distinguishable from one
made after.

## Migration

`darkroom migrate` pairs each `drives/<scenario>.drive.toml` with the
vault rubric whose `scenario` names it and writes
`proofs/<scenario>/exposure.toml` and `rubric.toml`, dropping `kind =
"http"`, `feature_id`, and any `evidence` the witnesses imply,
renaming `include` to `backdrop`, carrying `version` and `trials`.
Serve keys identical across ≥ 90% of the drives are printed as a
`[serve.defaults]` block; once darkroom.toml carries it, a re-run drops
those keys from each exposure. For every spec with a `Build:` note and
no `.surfaces` yet, a draft `.surfaces` is written beside it — the
note's backticked routes and selectors lifted into `[routes]` and
`[pages]`, the prose kept whole under `[notes]`, descriptions left for
engineering to add — and the spec itself is never edited. `--check`
plans without writing; `--force` overwrites existing proof folders.
Unpaired drives or rubrics are reported and left alone. Extracting
backdrops from the migrated exposures needs judgment and is the
authoring skill's job, not the tool's.

## Versioning

`1.0` names the shape above over drive-scripts 1.7's step vocabulary.
Step kinds, fields, and expectations continue to version in
[drive-scripts.md](drive-scripts.md); criterion fields version here.

## Example

`proofs/deletion_guarded/exposure.toml`:

```toml
scenario = "deletion_guarded"
backdrop = ["noted"]                # creates a note, saving {note_id} and {token}

[[step]]
name = "wrong_token_refused"
method = "DELETE"
url = "{base_url}/notes/{note_id}"
headers = { X-Note-Token = "not-it" }
expect = { status = 403 }

[[step]]
name = "note_survives"
url = "{base_url}/notes/{note_id}"
expect = { status = 200 }

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
```

`proofs/deletion_guarded/rubric.toml`:

```toml
version = "1"

[[criterion]]
id = "wrong_token_refused"
points = 10
description = "a wrong token is refused, and the note is still there afterwards"
witnesses = ["wrong_token_refused", "note_survives"]   # evidence: log, http_transcript

[[criterion]]
id = "right_token_deletes"
points = 10
description = "the holder's token deletes the note, and it cannot be fetched again"
witnesses = ["right_token_deletes", "gone"]
```

## Conformance

- A producer MUST name the folder after the exposure's `scenario`,
  MUST put the steps in `exposure.toml` and the criteria in
  `rubric.toml`, and MUST give every criterion an `id`, numeric
  `points`, and `witnesses` or `evidence`.
- A folder holding `exposure.toml` alone is a proof still being
  written: a consumer MAY expose it, MUST NOT seal, judge, or derive
  a contract from it, and MUST report it by name when asked to
  (`darkroom audit`: `no-rubric`; `darkroom vault seal` refuses).
- A consumer MUST refuse a criterion citing a witness that names no
  step in the expanded exposure.
- A consumer handing a proof to a judge MUST render the rubric half
  only; the steps MUST NOT reach the judge.
- A consumer MUST treat a home holding proofs as the exam and MUST NOT
  mix proofs with drive scripts and vault rubrics in one run.
- Derived evidence MUST follow the table above; declared `evidence`
  MUST be passed through unchanged.
- A run of a proof MUST record the exposure's digest and the rubric's
  version on the scenario's manifest bundle.
