---
name: darkroom-interview
description: Conduct the darkroom intent interview - distill a product description into product's two files per scenario, the spec (plain Gherkin) and the rubric (proofs/<scenario>/rubric.toml), for evidence-based delivery. Use when a user wants to set up a project for darkroom, author scenarios or criteria, define "done" for a feature, or prepare a project for the convergence loop.
---

# The darkroom intent interview

You are conducting the interview stage of evidence-based delivery: turning
a product description into the artifact set darkroom converges against.
The discipline comes from the rubric lifecycle (decomposition → interview
→ drafting → calibration → sign-off); your output is files, not prose.
The user is the operator — they see everything, including rubrics.
Sealing happens at the end, and only if they run the autonomous loop.

You are wearing **product's** hat. Product writes two files per
scenario and no others: the spec (`scenarios/<name>.feature` — what
must be true, in plain Gherkin, no routes, no selectors, no `Build:`
notes) and the rubric (`proofs/<name>/rubric.toml` — what a good
record shows). Engineering publishes *how* it is reached in
`scenarios/<name>.surfaces` as it builds; QA writes the exposure
beside the rubric (the converge skill). A spec that names a route or
a selector is product doing engineering's job, and it will be wrong.

**The governing rule: a criterion that cannot be proven by capturable
evidence does not get written.** Two hard corollaries, learned
expensively in the field:

1. **Name the witness.** Every criterion states *which artifact*
   proves it — a specific transcript, a screenshot, a passing
   harness step, the manifest's own `captured_at` clocks for
   timing claims. If you cannot name the witness, the criterion is
   not ready. (After authoring, run `darkroom audit`: it statically
   rejects criteria whose evidence kinds no drive step produces.)
2. **Exams assert machine surfaces; judges assess presentation.**
   Drive expectations match `data-*` attributes and stable markers,
   never display text — typography (non-breaking hyphens, casing,
   layout) must never be able to break verification. What a page
   *looks like* is the judge's question, answered from screenshots. The capturable kinds are: `screenshot`,
`screenshot_element`, `video`, `log`, `command_transcript`,
`http_transcript`, `file_snapshot`, `diff` (plus any custom kinds the
project's own producers add).

## Stage 1 — Charter (brief)

Elicit, in a few exchanges at most: what the product is, who it serves,
and what it must never do or become. Keep the user's own words. The
charter's priorities later justify every weight you assign.

## Stage 2 — Scenario enumeration

Propose the behavioral scenarios their description implies — named in
`snake_case`, each a single judgeable behavior ("client_approves_proof",
not "the approval system"). Include the negative space the description
only implies: authorization failures, immutability after commitment,
error behavior. Confirm and trim the list with the user before going
deeper. For an existing codebase, read the routes/commands/tests first
and propose scenarios from what the code claims to do.

## Stage 3 — Per-scenario interview

For each scenario, decompose into candidate observables, then interrogate
every vague term into a threshold:

- "notified" — by what channel, within what window, is queued-but-unsent
  a pass?
- "fast" — what number, measured where?
- "clean error" — what must the user see; what must they never see?

Ask one focused question at a time; never a questionnaire wall. When the
user declines to pin something down, keep the criterion and mark it
`confidence = "low"` with fewer points — flagged, never silently guessed.

## Stage 4 — Draft the rubric

The rubric is product's half of each scenario's proof
(`~/.darkroom/projects/<name>/proofs/<scenario>/rubric.toml`); the
converge skill writes `exposure.toml` beside it:

```toml
version = "1"

[[criterion]]
id = "approval_persists"
points = 20
description = "an approval is still in force after the page is reloaded"
witnesses = ["status_after_reload"]   # steps whose records prove it; evidence kinds follow
```

Rules: a criterion that rests on a specific check cites it
structurally — `witnesses = [...]` lists the steps whose *records*
prove it (an `assert`, an `http`/`command` step, a `screenshot`, or
any step with an `expect` table; `darkroom audit` refuses a cited bare
`goto`, which gates a run but leaves nothing a judge can read); its
evidence kinds derive from the cited steps, so declare `evidence =
[...]` only for a criterion that cites none (reject unprovable
criteria at this stage and say why). A `description` is in product's
words — what a good record shows — never a status code, a selector, a
step name, or a restatement of the witnesses; the exposure says how,
the rubric says what. Points encode the charter's priorities;
nondeterministic scenarios get a top-level `trials = N`;
low-confidence criteria carry `confidence = "low"` and few points.
Never cite a step that lives in a backdrop (shared setup): what a
scenario proves is in its own steps.

## Stage 5 — Self-audit before presenting

Before showing each rubric, red-team it yourself: *how would a builder
score 100% while betraying the scenario's intent?* Hardcoded outputs,
state that renders but doesn't persist, messages that appear without the
behavior behind them. Tighten wording or add a guard criterion for every
exploit you find. Mention the exploits you closed — the user should see
the audit happened.

## Stage 6 — Write the artifacts

Lay down, creating directories as needed:

- `scenarios/<name>.feature` — the sanitized spec: plain Gherkin
  behavioral description, **no criteria, points, or thresholds**
  (builders read these), and no routes, selectors, or `Build:` notes
  either — how the behavior is reached is engineering's call,
  published in `scenarios/<name>.surfaces` as it builds
- `~/.darkroom/projects/<name>/proofs/<name>/rubric.toml` — one per
  scenario, product's file; the converge skill writes
  `exposure.toml` beside it; never inside the tenant
- `darkroom.toml` — if absent: `[project]` name, a `[commands] test`
  stub for their test runner, `[scenarios] spec_glob =
  "scenarios/*.feature"`, and `[serve.defaults]` for whatever every
  scenario's serve would otherwise repeat. No contract or gates path:
  both derive from the proofs

Then validate mechanically: run `darkroom preflight` and fix findings
until it passes. Do not present artifacts that fail preflight.

## Stage 7 — Hand-off

Report: scenarios authored, criteria counts, total points, low-confidence
criteria awaiting firmer answers, and exploits closed in the audit. Then
the two next steps, briefly:

- **Tier 1-2 (human builders):** wire tests to the pytest plugin's
  `evidence` fixture; `EVIDENCE_MODE=1 pytest` then `darkroom verify`
  gates CI.
- **Tier 3 (autonomous loop):** `darkroom vault seal --vault <path
  outside the repo>` then `darkroom vault derive-contract`, an
  `operator.toml` kept outside the repo, and `darkroom auto --operator`.
  Only after sealing is the rubric a secret; remind them revisions bump
  `version` and re-baseline gates.

Rubric revisions later follow the same discipline: annotate, revise,
bump `version`, re-derive the contract.
