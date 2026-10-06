# relay-service — the darkroom example tenant

A stdlib-only notes API demonstrating evidence-based delivery end to end,
with each hat's file where it belongs:

| hat | file |
|-----|------|
| product | `scenarios/<name>.feature` — what the service must do; `proofs/<name>/rubric.toml` — what a good record shows |
| engineering | `app.py`, and `scenarios/<name>.surfaces` — the routes and pages the build exposes for that scenario |
| QA | `proofs/<name>/exposure.toml` — the steps that drive the service as a black box and capture every exchange |
| review | the judge, scoring the record against the rubric with the surfaces for context |

```bash
cd examples/relay-service
darkroom preflight
darkroom expose --drives proofs     # runs both scenarios, verifies the manifest against the derived contract
darkroom gallery evidence/runs/<run>/manifest.json
```

In a real project the proof folders live in the operator's darkroom
home (`darkroom home init`), outside the repo, and `darkroom expose`
finds them there without `--drives`; they sit in-tree here so the
example is self-contained. The `.surfaces` files stay in the tenant
either way — they are the builder's own publication, and `darkroom
audit` holds each exposure to them.

## The UI slice (browser steps, since 0.12)

The service also renders a notes page, and `proofs-ui/` exercises it
through a real browser — `goto` with title/selector expectations,
`fill` + `click` driving a submission, and full-page screenshots as
evidence. It is kept as its own slice so the HTTP slate above stays
runnable without a browser installed.

```bash
pip install 'darkroom-ai[playwright]' && playwright install chromium
darkroom expose --drives proofs-ui --scenario notes_page
```
