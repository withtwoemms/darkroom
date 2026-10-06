# darkroom

Evidence-based autonomous software delivery: agents build, sealed
exams judge, and every claim ships with proof.

**darkroom** runs a convergence loop in which a builder agent works
toward criteria it is never shown. A non-LLM harness drives the
system under test as a black box and captures typed evidence
(HTTP transcripts, command output, screenshots, screencasts); a judge
scores that evidence against rubrics sealed in a vault the builder
cannot address; gates ratchet so no scenario ships below its peak.
The exam lives outside the repository, the scores live outside the
builder's reach, and the manifest, not the code, is what you review,
diff, and gate on.

This is proven live, not aspirational. A greenfield example app was
delivered by agents under darkroom: its API, its security behaviors,
its full UI and design language, even its Makefile, every behavior
converging to a gated 100 on captured evidence, for single-digit
dollars of metered spend per campaign, with the exams' screencasts as
the receipts.

The name references the [*dark factory* pattern](https://withtwoemms.github.io/blog/2026/03/a-dark-factory-pattern/)
(lights-off autonomous production) and the *clean room* pattern
(independent implementation from specification). A darkroom is a controlled,
light-sealed environment where evidence is developed and evaluated
without contamination from the implementation side.

**New here? Start with the [Quickstart](https://github.com/withtwoemms/darkroom/blob/main/docs/quickstart.md)**: four
stages, ~15 minutes, covering first evidence, the exam, the convergence loop
with zero spend, then real agents. Its runnable stages are executed
by CI, so it cannot rot.

## Install

```bash
pip install darkroom-ai
```

The core is dependency-free. Extras add capabilities:

| extra | adds |
|---|---|
| `playwright` | browser steps, screenshots, screencasts, WebAuthn ceremonies |
| `crypto` | Ed25519 keygen/signing steps in exposures |
| `vault` | the OpenBao / HashiCorp Vault rubric backend |
| `containers` | containerized system-under-test environments |
| `all` | everything above |

The distribution is named `darkroom-ai` (the bare `darkroom` name is
squatted on PyPI); the import name is `darkroom` throughout. The CLI
installs as `darkroom` (alias: `darkrm`).

## How it works

A tenant repository declares only run-me facts in `darkroom.toml`:

```toml
[project]
name = "quicknotes"

[commands]
serve = "make serve PORT={port}"
test = "darkroom drive"
```

A tenant that needs a database beside the app declares it once, as a
fact, and every scenario gets a fresh one:

```toml
[[environment.services]]
name = "postgres"
image = "postgres:16"
port = 5432
env = { POSTGRES_PASSWORD = "exam" }
```

```toml
serve = "make serve PORT={port} DATABASE_URL=postgres://postgres:exam@{postgres.host}:{postgres.port}/postgres"
```

An image whose entrypoint wants arguments declares them as `command`
(a Postgres tuned for throwaway exams, say):

```toml
[[environment.services]]
name = "postgres"
image = "postgres:16"
port = 5432
env = { POSTGRES_PASSWORD = "exam" }
command = ["postgres", "-c", "fsync=off", "-c", "synchronous_commit=off"]
```

A service is handed to the app once its port accepts a connection —
which, for a JVM store, is seconds before it can answer. Declare
`ready_path` and the engine also waits for an HTTP response there:

```toml
[[environment.services]]
name = "objects"
image = "adobe/s3mock:latest"
port = 9090
ready_path = "/"
```

What every scenario shares, the adapter says once — an exam then
carries only what differs:

```toml
[serve.defaults]        # every scenario's [serve] starts here
ttl = 120

[serve.env]             # the engine sets the served process's environment
APP_TTL_SECONDS = "{ttl}"
APP_DATABASE_URL = "postgresql://postgres:exam@{postgres.host}:{postgres.port}/postgres"

[browser.defaults]
webauthn = true
```

The **exam** is data, held operator-side as one **proof** per scenario
— a folder in the project's darkroom home
(`~/.darkroom/projects/<name>/proofs/<scenario>/`), never in the repo
the builder works in. A proof is two files with two authors: the
**exposure** (QA's — the steps that drive the app as a black box and
capture every exchange as evidence) and the **rubric** (product's —
the criteria that score what was captured). The quickstart's stage 4
puts them there, and `darkroom auto` refuses to run while exam
material is still inside the tenant:

```toml
# proofs/note_saved/exposure.toml
scenario = "note_saved"
record = true          # screencast the whole scenario

[[step]]
name = "save"
method = "POST"
url = "{base_url}/notes"
json = { text = "first light" }
expect = { status = 201 }
save = { note_id = "$.id" }

[[step]]
name = "read_back"
url = "{base_url}/notes/{note_id}"
expect = { status = 200, body_contains = "first light" }
```

```toml
# proofs/note_saved/rubric.toml
version = "1"

[[criterion]]
id = "saved_and_readable"
points = 10
description = "a saved note reads back with its text"
witnesses = ["save", "read_back"]     # evidence kinds follow from the steps cited
```

`darkroom expose` runs the exposure (`darkroom drive`, its older
name, still does). The builder, for its part, publishes the interface
it chose beside each spec — `scenarios/<name>.surfaces`, the routes,
commands, pages, and files the build exposes — and `darkroom audit`
holds every exposure to that publication both ways: a step probing
something unpublished, a published surface nothing proves. Setup
many exposures share (founding, joining, signing in) is named once in
the home's `backdrops.toml` and posed ahead with `backdrop = [...]`.

Step kinds cover HTTP, commands, Ed25519 keygen/signing, assertions,
waits, container failure injection, and real browser interaction
(`goto`/`click`/`fill`/`screenshot`, with viewport control and
headless passkey ceremonies via a virtual authenticator). A failing
scenario keeps its evidence: a failing scenario is still judgeable,
which is the point.

`darkroom verify` checks each run against an **evidence contract**
(per-scenario required kinds, counts, steps, trials) — derived from
the proofs' criteria at run time, so a tenant on proofs commits no
contract at all — and "this build produced its evidence" is a CI gate
before any judging happens.

The **loop**, `darkroom auto`, runs assess → judge → build to
convergence. Judge and builder can be shell hooks (see the
Quickstart's zero-spend demo) or full agents configured operator-side:

```toml
# ~/.darkroom/projects/quicknotes/operator.toml (never in the tenant)
[judge]
model = "claude-opus-5"

[builder]
model = "claude-sonnet-5"
escalated_model = "claude-opus-5"

[loop]
max_iterations = 6
```

```bash
darkroom auto --scenario note_saved     # operator config discovered from the home
```

Authority lives in the per-project **darkroom home**
(`~/.darkroom/projects/<name>/`, mode 700): operator config, proofs,
backdrops, loop state, and the **vault**, through which the judge is
handed each proof's rubric — criteria, never steps — and the addresses
of the build's published surfaces, never the builder's prose about
them; the builder reads none of it. `darkroom vault seal` validates the proofs (or, on
the older layout, moves rubrics out of the tenant); the OpenBao
backend adds token-gated reads and server-side audit. Every manifest
names the exam it answered — the exposure's digest and the rubric's
version — so a verdict is never ambiguous about what it judged. The loop
stagnation-escalates (diagnostic access, model escalation, sharper
feedback), rolls back regressions to the best checkpoint, and ratchets
the gates in the home's state on convergence. A red gate always means
something real: rubric changes re-baseline; they never masquerade as
regressions. Projects on the older drive-script + rubric layout keep
working; `darkroom migrate` turns each pair into a proof folder and
each spec's `Build:` note into a draft `.surfaces`.

Every agent invocation is **metered** (model, tokens, cost) into loop
state, and `darkroom dossier` assembles the cross-run record into
one operator-facing bundle: score trajectories, checkpoints,
escalations, gates, spend.

## Evidence capture without the loop

The capture layer stands alone. Installing the package registers a
pytest plugin; tests request the `evidence` fixture and runs become
manifest-backed:

```python
def test_login_flow(page, evidence):
    evidence.screenshot(page, "after_login", full_page=True)
    evidence.log("api_response", {"status": 200})
```

```bash
EVIDENCE_MODE=1 EVIDENCE_DIR=./evidence pytest
```

The same API is importable directly (`EvidenceCapture`,
`start_run`/`end_run`), and `darkroom gallery` renders any run as a
static contact sheet.

## The formats are a spec

Every artifact (manifest, contract, evaluation, gates, tickets,
drive scripts, role hooks, dossier) is a written, versioned format
with conformance rules and a trust-boundary map: see
[docs/spec/](https://github.com/withtwoemms/darkroom/tree/main/docs/spec). Any harness in any language can emit a
darkroom manifest; any judge infrastructure can consume one.

## Claude skills

Four skills ship inside the package, version-locked to the engine:

- `darkroom-interview`: the intent interview, covering charter,
  scenario enumeration, thresholds, rubric drafting under the
  capturable-evidence rule (with structured witness citations),
  gaming self-audit, preflight-validated artifacts.
- `darkroom-converge`: the operator's run-a-scenario loop — author the
  drive, audit, dry-run before spending, commit both repos, launch
  auto, triage blockers, regress, deploy.
- `darkroom-status`: the standing report — where every scenario's
  campaign stands now, blockers with their triage, what is shipped
  versus merely gated, the queue, spend — in one fixed shape, every
  number from `darkroom status`.
- `darkroom-chronicle`: narrates a project's delivery from its dossier,
  covering progression, what the judge witnessed, sticking points,
  novelties, spend.

Install them either way:

```bash
# as a Claude Code plugin, pinned to the release you are running
claude plugin marketplace add withtwoemms/darkroom
claude plugin install darkroom@darkroom          # -> darkroom:interview, :converge, :status, :chronicle

# or from the installed package
darkroom skills install                          # symlinks into ~/.claude/skills (--copy to copy)
darkroom skills check                            # exit 1 if any installed copy drifts from this engine
```

`darkroom skills check` compares every installed copy against the
packaged one by content hash, so a stale or hand-edited skill is
reported rather than quietly steering an operator wrong.

## Documentation

- [Quickstart](https://github.com/withtwoemms/darkroom/blob/main/docs/quickstart.md) -- first evidence to real agents in four stages
- [docs/spec/](https://github.com/withtwoemms/darkroom/tree/main/docs/spec) -- the format specifications (the handoff contracts, frozen at 1.0)
- [ROADMAP.md](https://github.com/withtwoemms/darkroom/blob/main/ROADMAP.md) -- milestones from foundation through v1 and beyond
- [CHANGELOG.md](https://github.com/withtwoemms/darkroom/blob/main/CHANGELOG.md) -- the release-by-release record
- [The Judge & Builder: implementing a dark factory](https://withtwoemms.github.io/blog/2026/03/a-dark-factory-pattern/) -- the pattern essay: why evaluation must be structurally separated from implementation
- [docs/vision.md](https://github.com/withtwoemms/darkroom/blob/main/docs/vision.md) -- design fiction: building a web app in the dark
- [docs/rubric-lifecycle.md](https://github.com/withtwoemms/darkroom/blob/main/docs/rubric-lifecycle.md) -- how a rubric is made, hardened, and revised
- [docs/generalization-plan.md](https://github.com/withtwoemms/darkroom/blob/main/docs/generalization-plan.md) -- how darkroom absorbed the Judge-Builder framework

## Development

```bash
make venv       # create virtualenv and install deps
make test-unit  # run unit tests
make test       # run all tests with coverage
make help       # see all targets
```

Licensed under Apache-2.0.
