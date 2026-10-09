# relay-service — the darkroom example tenant

A stdlib-only notes service demonstrating evidence-based delivery end
to end, with each hat's file where it belongs:

| hat | file |
|-----|------|
| product | `scenarios/<name>.feature` — what the service must do; `proofs/<name>/rubric.toml` — what a good record shows |
| engineering | `app.py`, and `scenarios/<name>.surfaces` — the routes and pages the build exposes for that scenario |
| QA | `proofs/<name>/exposure.toml` — the steps that drive the service as a black box and capture every exchange; `proofs/backdrops.toml` — setup exposures are posed against |
| review | the judge, scoring the record against the rubric with the surfaces for context |

```bash
cd examples/relay-service
darkroom preflight
darkroom expose --drives proofs     # the HTTP slate; verifies the manifest against the derived contract
darkroom gallery evidence/runs/<run>/manifest.json
```

In a real project the proof folders and `backdrops.toml` live in the
operator's darkroom home (`darkroom home init`), outside the repo, and
`darkroom expose` finds them there without `--drives`; they sit
in-tree here so the example is self-contained (a `backdrops.toml`
beside the proofs a `--drives` names wins over the home's). The
`.surfaces` files stay in the tenant either way — they are the
builder's own publication, and `darkroom audit` holds each exposure to
them.

## What each scenario shows

| scenario | the darkroom idea it carries |
|----------|------------------------------|
| `note_lifecycle` | an `http` exposure: create, fetch, archive twice; witnesses cited by name |
| `deletion_guarded` | posed against the `token_in_hand` backdrop — the saved note is setup, not the subject; runs at production posture (`[serve.defaults] open_delete = 0` keeps the exam-only bridge off) |
| `read_once_note` | absence and finality witnessed positively: the second read answers `410` with its reason, and so does every other door |
| `notes_page` (ui) | browser steps; the page states "nothing yet" itself (`main[data-note-state="empty"]`) rather than a selector failing to appear; Save is proven by the list it produces |
| `archived_note_shows_its_state` (ui) | a selector narrowed to a state is the same surface as the one published (`#notes li[data-archived]`); the page names its latest state |

## The UI slice (browser steps, since 0.12)

The service also renders a notes page, and `proofs-ui/` exercises it
through a real browser — `goto` with title/selector expectations,
`fill` + `click` driving a submission, state attributes as machine
surfaces, and full-page screenshots as evidence. It is kept as its
own slice so the HTTP slate above stays runnable without a browser
installed.

```bash
pip install 'darkroom-ai[playwright]' && playwright install chromium
darkroom expose --drives proofs-ui
```
