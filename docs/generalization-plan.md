# Generalization Plan

> How darkroom grows from the extracted evidence subsystem into the whole
> generalized Judge-Builder framework. [`ROADMAP.md`](../ROADMAP.md) maps
> this plan onto releases; [`vision.md`](vision.md) is the destination it
> aims at. The source framework referred to throughout is the
> judge-builder-framework pilot (Makefile + bash orchestration, symlinked
> into a single web-app project).

## Framing decision

Darkroom grows into the whole generalized framework as **one Python
package** — `darkroom.evidence` (exists today as the package root), plus
eventually `darkroom.judge`, `darkroom.loop`, and `darkroom.project` —
rather than staying a leaf library with orchestration remaining in bash.

Rationale: the source framework's shell-embedded convergence loop is its
largest complexity debt; the ticketing and escalation logic is exactly the
kind of state machine Python is good at; and a single installable
`darkroom` CLI is what the vision describes. Split into sibling packages
only if a real second consumer of the evidence layer alone appears.

## Phase 1 — Solidify the evidence core

Make what exists production-grade and adoptable.

1. **Pytest plugin** (entry point): auto `start_run`/`end_run` session
   hooks, an `evidence` fixture keyed off the test node,
   screenshot-on-failure — everything the pilot's `conftest.py`
   hand-wires. Retires the need for `compat.py` in new projects.
2. **New producer kinds**, proving the protocol is general:
   `CommandTranscriptProducer`, `HTTPTranscriptProducer`,
   `VideoProducer` (screencast dirs exist with no producer),
   `FileSnapshotProducer`/`DiffProducer`. Populate
   `EvidenceItem.metadata` (viewport, `full_page`, selector) — it
   round-trips but nothing writes it.
3. **Evidence contracts**: a declared per-scenario mapping of required
   evidence kinds, plus `darkroom verify <manifest>` checking that a
   manifest satisfies its contract and every path resolves.
4. **Housekeeping**: LICENSE, CI, release workflow, real integration
   tests.

## Phase 2 — The consumption side

The manifest is a handoff contract with only one side implemented.

1. **`JudgeRenderer` protocol** mirroring `EvidenceProducer`, dispatched
   on `EvidenceItem.kind`: renders an item into judge-consumable form
   (image reference for vision models, excerpt for transcripts,
   structured summary for JSON). This breaks the screenshots-only
   anchoring.
2. **Score data model**: typed `Evaluation`/`CriterionResult` records
   with schema-versioned serialization — replacing the JSON schema
   currently hard-coded in the source framework's judge-trigger prompt,
   and absorbing its score-normalization script.
3. **Regression gates as data**: `PeakRecord {scenario, score, run_id,
   commit}` — designed in the source framework, never built.
4. **Contact sheet**: `darkroom gallery <run>` renders a static HTML
   gallery from a manifest. First human-facing payoff; useful standalone
   with no judge in the loop.

## Phase 3 — Orchestration in Python

Retire the source framework's Makefile and `bin/` scripts, one subsystem
at a time, keeping the pilot project green at every step.

1. **Project adapter** (`darkroom.yaml`, living in the framework's space,
   not the tenant repo): commands `{build, seed, test, reset}`,
   spec/rubric globs, evidence requirements, workspace paths. Kills the
   symlinks-as-API — the root cause of both documented pilot defects
   (rubric leak to the Builder; judge glob churn) — and makes
   multi-tenancy fall out of `state/{project}` + `workspaces/{project}`
   partitioning.
2. **Convergence loop as a state machine**: assess → score → stagnation
   counter → the three escalation dials (diagnostic access, model
   escalation, feedback specificity) → regression rollback → checkpoint
   commit → iteration memory. Testable Python with thresholds in config.
3. **Agent invocation layer**: judge/builder triggers with prompt
   assembly from templates, consolidating logic currently split across
   `Makefile:build`, `trigger-judge.sh`, and the agent prompt files.
4. **Ticketing**: the `state/queue|locks|history` conventions are already
   project-agnostic; port as a small module keeping markdown+frontmatter
   tickets.
5. **Vault**: rubric isolation OS-enforced (permissions outside every
   builder-visible path), not prompt-enforced.

## Phase 4 — Prove generality

1. **`SpecAdapter` protocol** (`load` / `sanitize_for_builder` /
   `enumerate_criteria`), Gherkin as the first implementation.
2. **Test-runner adapters**: pytest first, then one genuinely different
   runner mapping native test IDs to scenario/step coordinates.
3. **A non-visual tenant**: a CLI tool or library driven to convergence
   judged purely on command transcripts and structured evidence — zero
   screenshots. A distributed-flavored tenant (e.g. a small replicated
   store judged on partition-trial evidence) would additionally exercise
   statistical rubrics. This is the acceptance test for the whole plan.

## Sequencing logic

Each phase ships something independently useful: Phase 1 makes darkroom
adoptable by any pytest project; Phase 2's gallery and verify commands
have standalone value; Phase 3 is where the source framework repo starts
shrinking; Phase 4 is the proof. Phases 1 and 2 depend on no
orchestration decisions and can proceed immediately.

The adoption gradient this creates is deliberate: evidence capture alone
(no AI), then judged evidence over human-written code, then the full
autonomous loop — each tier valuable without the next.
