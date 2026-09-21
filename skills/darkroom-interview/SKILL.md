---
name: darkroom-interview
description: Conduct the darkroom intent interview - distill a product description into scenarios, rubrics, and an evidence contract for evidence-based delivery. Use when a user wants to set up a project for darkroom, author scenarios or rubrics, define "done" for a feature, or prepare a project for the convergence loop.
---

# The darkroom intent interview

You are conducting the interview stage of evidence-based delivery: turning
a product description into the artifact set darkroom converges against.
The discipline comes from the rubric lifecycle (decomposition → interview
→ drafting → calibration → sign-off); your output is files, not prose.
The user is the operator — they see everything, including rubrics.
Sealing happens at the end, and only if they run the autonomous loop.

**The governing rule: a criterion that cannot be proven by capturable
evidence does not get written.** The capturable kinds are: `screenshot`,
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

## Stage 4 — Draft the rubrics

One rubric file per scenario:

```toml
feature_id = "client-approves-proof"   # dash-case
version = "1"
scenario = "client_approves_proof"     # snake_case, matches tests

[[criterion]]
id = "approval_persists"
points = 20
description = "Approving transitions the proof to 'approved' in storage; status survives reload"
evidence = ["http_transcript", "screenshot"]
```

Rules: every criterion names its evidence kinds (reject unprovable
criteria at this stage and say why); points encode the charter's
priorities; nondeterministic scenarios get a top-level `trials = N`;
low-confidence criteria carry `confidence = "low"` and few points.

## Stage 5 — Self-audit before presenting

Before showing each rubric, red-team it yourself: *how would a builder
score 100% while betraying the scenario's intent?* Hardcoded outputs,
state that renders but doesn't persist, messages that appear without the
behavior behind them. Tighten wording or add a guard criterion for every
exploit you find. Mention the exploits you closed — the user should see
the audit happened.

## Stage 6 — Write the artifacts

Lay down, creating directories as needed:

- `scenarios/<name>.feature` — the sanitized spec: plain behavioral
  description, **no criteria, points, or thresholds** (builders read
  these)
- `scenarios/<feature-id>.rubric.toml` — one per scenario
- `darkroom.toml` — if absent: `[project]` name, a `[commands] test`
  stub for their test runner, `[evidence]` dir + contract path,
  `[scenarios]` globs (`scenarios/*.feature`, `scenarios/*.rubric.toml`)
- `evidence-contract.toml` — derive it from the rubrics (union of each
  scenario's evidence kinds; carry `trials`)

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
