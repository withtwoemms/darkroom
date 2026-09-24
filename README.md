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
builder's reach, and the manifest -- not the code -- is what you
review, diff, and gate on.

This is proven live, not aspirational: a greenfield example app -- its
API, its security behaviors, its full UI and design language, even
its Makefile -- was delivered by agents under darkroom, every behavior
converging to a gated 100 on captured evidence, for single-digit
dollars of metered spend per campaign, with the exams' screencasts as
the receipts.

The name references the [*dark factory* pattern](https://withtwoemms.github.io/blog/2026/03/a-dark-factory-pattern/)
-- lights-off autonomous production -- and the *clean room* pattern -- independent
implementation from specification. A darkroom is a controlled,
light-sealed environment where evidence is developed and evaluated
without contamination from the implementation side.

**New here? Start with the [Quickstart](docs/quickstart.md)** -- four
stages, ~15 minutes: first evidence, the exam, the convergence loop
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
| `crypto` | Ed25519 keygen/signing steps in drive scripts |
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

The **exam** is data, held operator-side -- one drive script per
scenario. The engine boots the app fresh, executes the steps against
it as a black box, and captures every exchange as evidence:

```toml
scenario = "note_saved"
record = true          # screencast the whole scenario

[[step]]
name = "save"
kind = "http"
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

Step kinds cover HTTP, commands, Ed25519 keygen/signing, assertions,
waits, container failure injection, and real browser interaction
(`goto`/`click`/`fill`/`screenshot`, with viewport control and
headless passkey ceremonies via a virtual authenticator). A failing
scenario keeps its evidence -- a failing scenario is still judgeable,
which is the point.

`darkroom verify` checks each run against an **evidence contract**
(per-scenario required kinds, counts, steps, trials), so "this build
produced its proof" is a CI gate before any judging happens.

The **loop** -- `darkroom auto` -- runs assess → judge → build to
convergence. Judge and builder can be shell hooks (see the
Quickstart's zero-spend demo) or full agents configured operator-side:

```toml
# ~/.darkroom/projects/quicknotes/operator.toml -- never in the tenant
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
(`~/.darkroom/projects/<name>/`, mode 700): operator config, drive
scripts, loop state, and the **vault** of sealed rubrics -- the judge
reads them; the builder never can. `darkroom vault seal` moves
rubrics out of the tenant; `derive-contract` regenerates the
builder-safe contract from them; the OpenBao backend adds token-gated
reads and server-side audit. The loop stagnation-escalates
(diagnostic access, model escalation, sharper feedback), rolls back
regressions to the best checkpoint, and ratchets
`evidence-gates.json` on convergence -- a red gate always means
something real (rubric changes re-baseline; they never masquerade as
regressions).

Every agent invocation is **metered** (model, tokens, cost) into loop
state; `darkroom dossier` assembles the cross-run record -- score
trajectories, checkpoints, escalations, gates, spend -- into one
operator-facing bundle.

## Evidence capture without the loop

The capture layer stands alone. Installing the package registers a
pytest plugin -- tests request the `evidence` fixture and runs become
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

Every artifact -- manifest, contract, evaluation, gates, tickets,
drive scripts, role hooks, dossier -- is a written, versioned format
with conformance rules and a trust-boundary map: see
[docs/spec/](docs/spec/). Any harness in any language can emit a
darkroom manifest; any judge infrastructure can consume one.

## Claude skills

- `skills/darkroom-interview/` -- the intent interview: charter,
  scenario enumeration, thresholds, rubric drafting under the
  capturable-evidence rule, gaming self-audit, preflight-validated
  artifacts.
- `skills/darkroom-chronicle/` -- narrates a project's delivery from
  its dossier: progression, what the judge witnessed, sticking
  points, novelties, spend.

```bash
cp -r skills/darkroom-interview ~/.claude/skills/   # or per-project .claude/skills/
```

## Documentation

- [Quickstart](docs/quickstart.md) -- first evidence to real agents in four stages
- [docs/spec/](docs/spec/) -- the format specifications (the handoff contracts, frozen at 1.0)
- [ROADMAP.md](ROADMAP.md) -- milestones from foundation through v1 and beyond
- [CHANGELOG.md](CHANGELOG.md) -- the release-by-release record
- [The Judge & Builder: implementing a dark factory](https://withtwoemms.github.io/blog/2026/03/a-dark-factory-pattern/) -- the pattern essay: why evaluation must be structurally separated from implementation
- [docs/vision.md](docs/vision.md) -- design fiction: building a web app in the dark
- [docs/rubric-lifecycle.md](docs/rubric-lifecycle.md) -- how a rubric is made, hardened, and revised
- [docs/generalization-plan.md](docs/generalization-plan.md) -- how darkroom absorbed the Judge-Builder framework

## Development

```bash
make venv       # create virtualenv and install deps
make test-unit  # run unit tests
make test       # run all tests with coverage
make help       # see all targets
```

Licensed under Apache-2.0.
