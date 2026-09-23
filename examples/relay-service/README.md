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

## The UI slice (browser steps, since 0.12)

The service also renders a notes page, and `drives-ui/` exercises it
through a real browser — `goto` with title/selector expectations,
`fill` + `click` driving a submission, and full-page screenshots as
evidence. It is kept as its own slice (separate drives directory and
`evidence-contract-ui.toml`) so the HTTP slate above stays runnable
without a browser installed.

```bash
pip install 'darkroom-ai[playwright]' && playwright install chromium
darkroom drive --drives drives-ui --scenario notes_page
darkroom verify evidence/runs/<run>/manifest.json --contract evidence-contract-ui.toml
```
