# darkroom

Evidence capture and manifest management for autonomous software delivery.

**darkroom** is the evidence subsystem of the [Judge-Builder framework](https://github.com/withtwoemms). It provides typed records for evidence items, a producer protocol for capturing diverse evidence kinds, and manifest serialization for the handoff between Builder and Judge.

The name references the *dark factory* pattern -- lights-off autonomous production -- and the *clean room* pattern -- independent implementation from specification. A darkroom is a controlled, light-sealed environment where evidence is developed and evaluated without contamination from the implementation side.

## Install

```bash
pip install darkroom-ai            # core (LogProducer, manifests, EvidenceRun)
pip install darkroom-ai[playwright] # adds ScreenshotProducer
```

The distribution is named `darkroom-ai` (the bare `darkroom` name is squatted on PyPI); the import name is `darkroom` throughout.

## Usage

```python
from darkroom import EvidenceCapture
from darkroom.run import start_run, end_run

# Start a run (typically in a pytest session hook)
run = start_run(project="my-project")

# Per-scenario capture (typically via a pytest fixture)
evidence = EvidenceCapture("login_flow")
evidence.screenshot(page, "login_page")
evidence.screenshot(page, "after_login", full_page=True)
evidence.log("api_response", {"status": 200})

# End the run -- writes manifest.json
manifest_path = end_run()
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
