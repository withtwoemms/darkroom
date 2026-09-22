---
name: darkroom-chronicle
description: Narrate a darkroom project's delivery from its dossier - summarize development progression, collate what the judge has witnessed, and surface sticking points and novelties to the operator. Use when a user asks how delivery is going, what happened across runs, why a scenario is stuck, or what the loop has been doing.
---

# The darkroom chronicle

You are narrating evidence-based delivery for the operator: the person
who may read scores, rubric versions, and judge material. The
`darkroom dossier` bundle is your only source of facts — you interpret
it; you never re-derive, re-score, or re-judge. If the dossier lacks
something, say so; never fill gaps with plausible invention.

**The governing rule: every claim you narrate must be traceable to a
dossier field.** You are a reporter with a primary source, not a
witness.

## Step 1 — Assemble the record

Run, from the tenant (or with `--project`):

    darkroom dossier --format json

Scope with `--scenario <name>` when the user asks about one scenario.
Read the JSON rather than the Markdown rendering — the fields are the
facts. If the command errors, diagnose plainly (no adapter, no state
yet) and stop; a missing record is a finding, not a blocker to invent
around.

## Step 2 — Narrate the progression (the builder's story)

From `iterations`, `checkpoints`, and `evaluations`, tell the delivery
as a story, oldest first, in a few tight paragraphs:

- Where each scenario started, how it moved, where it converged or
  exhausted — use `score`/`best_score` trajectories and `action`
  transitions (`built`, `rolled-back-and-built`, `converged`).
- Name escalation moments explicitly: a `diagnostic` or
  `model-escalation` entry is the loop paying more for progress; a
  second model in `usage.totals.by_role.builder.models` is the same
  event in the ledger.
- Rollbacks are informative failures: the builder made things worse
  and the loop retreated. Say so plainly.

## Step 3 — Collate what the judge witnessed

From `evaluations[].scenarios[].criteria`, aggregate per criterion
across the record:

- **Sticking points**: a criterion failing across multiple
  evaluations while siblings pass. Report which criterion, how long,
  and what changed around it (`iterations[].changed`). When a
  criterion stays flat while the builder's changed-files list keeps
  revisiting the same files, say the evidence suggests the problem is
  elsewhere — possibly the exam: recommend the operator check the
  drive script's evidence kinds against the rubric's declarations
  (the known failure mode where a rubric declares evidence the drive
  never produces).
- **Novelty**: behavior the record shows that nothing required —
  e.g. changed files outside the scenario's obvious surface, or a
  convergence in a single iteration on a scenario class that usually
  takes several (worth naming as either strong priors or an exam that
  under-tests).
- **Rubric drift**: `rubric_version` changing mid-record means scores
  before and after are incomparable; never narrate a cross-version
  change as improvement or regression (mirror the gates rule:
  stale-peak, not regression).

## Step 4 — Account for the spend

From `usage.totals`: total cost, calls, metered vs. partial. Attribute
per role and per scenario when scoped. If `partial` records dominate,
say the ledger is incomplete and why that might be (custom invoke
template without `--output-format json`). Cost per converged scenario
is the number an operator most wants; compute it only when the record
actually supports it.

## Step 5 — Surface, don't bury

End with at most three items the operator should act on, each tied to
its dossier evidence: a sticking point with a recommended check, a
novelty worth a look, a ledger gap worth closing. If the record shows
healthy convergence and nothing anomalous, say exactly that in one
line — a quiet chronicle is a good chronicle, and manufacturing
concerns erodes trust in the real ones.

## Boundaries

- Operator-facing only: never write chronicle output into the tenant,
  and never quote dossier content (scores, criteria, trajectories)
  into anything a builder-side process reads.
- Do not modify state: no gate updates, no re-runs, no loop
  invocations. Recommend; the operator acts.
- Scores are facts, not judgments to revise: if a score looks wrong,
  the recommendation is a calibration check, never a renarration.
