# relay-service — the darkroom example tenant

A stdlib-only notes API demonstrating evidence-based delivery end to end:
sanitized specs (`scenarios/*.feature`), rubrics (`*.rubric.toml`),
a derived evidence contract, and drive scripts (`drives/`) executing the
scenarios against the running service as a black box.

```bash
cd examples/relay-service
darkroom preflight
darkroom drive --drives drives      # runs both scenarios, verifies the manifest
darkroom gallery evidence/runs/<run>/manifest.json
```

In a real project the drive scripts and rubrics live in the operator's
darkroom home (`darkroom home init`), outside the repo; they sit
in-tree here so the example is self-contained.
