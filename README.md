# darkroom

Evidence capture and manifest management for autonomous software delivery.

**darkroom** is the evidence subsystem of the [Judge-Builder framework](https://github.com/withtwoemms). It provides typed records for evidence items, a producer protocol for capturing diverse evidence kinds, and manifest serialization for the handoff between Builder and Judge.

The name references the *dark factory* pattern -- lights-off autonomous production -- and the *clean room* pattern -- independent implementation from specification. A darkroom is a controlled, light-sealed environment where evidence is developed and evaluated without contamination from the implementation side.

## Install

```bash
pip install darkroom-ai            # core: manifests, run lifecycle, pytest plugin,
                                   # log/command/HTTP/file-snapshot/diff/video producers
pip install darkroom-ai[playwright] # adds the screenshot producers
```

The distribution is named `darkroom-ai` (the bare `darkroom` name is squatted on PyPI); the import name is `darkroom` throughout.

## Usage

### With pytest (recommended)

Installing the package registers a pytest plugin -- no conftest wiring
needed. Tests request the `evidence` fixture; the scenario name derives
from the test name:

```python
def test_login_flow(page, evidence):
    evidence.screenshot(page, "login_page")
    evidence.screenshot(page, "after_login", full_page=True)
    evidence.log("api_response", {"status": 200})
```

Run in evidence mode to get a manifest-backed run (otherwise captures
fall back to flat directories and the session hooks stay out of the way):

```bash
EVIDENCE_MODE=1 EVIDENCE_DIR=./evidence pytest
```

The plugin starts the run at session start, records a full-page
screenshot for any failing test that used a `page` fixture, and writes
`manifest.json` at session end. Set the manifest's project name via ini:

```ini
[pytest]
darkroom_project = my-project
```

### CLI

Installed as `darkroom` (alias: `darkrm`):

```bash
darkroom show evidence/runs/<run>/manifest.json     # summarize a run
darkroom verify evidence/runs/<run>/manifest.json   # structural checks
darkroom verify runs/*/manifest.json --contract evidence-contract.toml
```

`verify` exits nonzero when a run fails its evidence contract -- a
declared set of per-scenario capture requirements -- making "this build
produced its proof" a CI gate. A contract is TOML:

```toml
[[scenario]]
name = "client_approves_proof"

  [[scenario.requires]]
  kind = "screenshot"
  steps = ["proof_awaiting_approval", "proof_approved"]

  [[scenario.requires]]
  kind = "http_transcript"
```

Requirements may declare `trials = N` for nondeterministic scenarios
checked across a series of runs (pass several manifests to `verify`).

### Direct API

```python
from darkroom import EvidenceCapture
from darkroom.run import start_run, end_run

run = start_run(project="my-project")

evidence = EvidenceCapture("login_flow")
evidence.screenshot(page, "login_page")
evidence.log("api_response", {"status": 200})

manifest_path = end_run()  # writes manifest.json
```

## Manifest Format (v2)

```json
{
  "schema_version": "2.0",
  "run_id": "2026-03-17T13-43-29",
  "project": "my-project",
  "timestamp": "2026-03-17T13:44:02.049178",
  "scenarios": [
    {
      "scenario": "login_flow",
      "items": [
        {
          "kind": "screenshot",
          "mime": "image/png",
          "path": "login_flow/01-login_page.png",
          "scenario": "login_flow",
          "step": "login_page",
          "captured_at": "2026-03-17T13:43:48.707534",
          "metadata": {}
        }
      ]
    }
  ]
}
```

All `path` values are relative to the manifest file's parent directory. Absolute paths (starting with `/`) are also accepted. v1 manifests are loaded transparently by `load_manifest`.

## Documentation

- [ROADMAP.md](ROADMAP.md) -- milestones from foundation through v1
- [docs/vision.md](docs/vision.md) -- design fiction: building a web app in the dark
- [docs/rubric-lifecycle.md](docs/rubric-lifecycle.md) -- how a rubric is made, hardened, and revised
- [docs/generalization-plan.md](docs/generalization-plan.md) -- how darkroom absorbs the Judge-Builder framework

## Development

```bash
make venv       # create virtualenv and install deps
make test-unit  # run unit tests
make test       # run all tests with coverage
make help       # see all targets
```
