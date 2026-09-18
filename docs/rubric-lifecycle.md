# The Life of a Rubric

> A design-fiction companion to [`vision.md`](vision.md). This document
> outlines how a rubric comes into being in a fully-realized darkroom --
> from scenario to sealed, versioned criteria -- and how it evolves once
> the loop is running. The governing rule throughout: **a criterion that
> cannot be proven by capturable evidence does not get written.**

## Preconditions

A rubric is never authored from a blank page. Before drafting begins,
three inputs exist:

- **The charter** -- the product's one-page identity, which supplies the
  priorities that weighting will encode.
- **A scenario** -- the behavioral narrative being graded ("a client
  approves a proof and the press is notified"). The rubric belongs to the
  scenario, not the other way around.
- **References and counterexemplars** -- any exemplar evidence the user
  has supplied ("judged like this" / "never this").

## Stage 1 -- Decomposition

Darkroom parses the scenario into **candidate observables**: every claim
the narrative makes or implies, restated as a checkable fact. For the
proof-approval scenario:

- The proof page renders for an authenticated client, approve action visible
- Approving persists -- the proof's status transitions in the database
- The press is actually notified -- a message leaves the system
- An approved proof is immutable -- re-approval and edits are refused
- An unauthorized client cannot approve someone else's proof

Note the last two: decomposition deliberately includes the *negative
space* the narrative only implies. A scenario says what happens; a rubric
must also pin what must not.

## Stage 2 -- The Interview

Each candidate observable is interrogated until it is gradeable. The
system bears the burden of converting vagueness into thresholds, and
shows its work:

> "Notified" -- by email, in-app, or either? Within what window? Is a
> queued-but-unsent message a pass?
>
> Should approval be reversible by the press, or by no one?
>
> You said clients "sign off" -- is a typed name required, or is the
> button click the signature?

Answers become thresholds. Questions the user declines to answer become
**low-confidence criteria** -- scored gently, flagged for firming up
later -- rather than silent assumptions.

## Stage 3 -- Drafting

Each surviving observable becomes a criterion with a fixed anatomy:

```yaml
feature_id: proof-approval
version: 1
scenarios:
  client_approves_proof:
    weight: critical
    criteria:
      approval_persists:
        points: 20
        description: >
          Approving transitions the proof to 'approved' in storage;
          status survives a page reload.
        evidence: [db_snapshot, screenshot]
        confidence: high
      press_notified:
        points: 15
        description: >
          Within 5s of approval, a notification addressed to the press
          appears in the outbox with the proof's identifier.
        evidence: [http_transcript, log]
        confidence: high
      approval_immutable:
        points: 15
        description: >
          A second approval attempt and any edit to an approved proof
          are refused with an explanatory message.
        evidence: [http_transcript, screenshot]
        confidence: high
      signoff_feels_deliberate:
        points: 5
        description: >
          The approval interaction reads as a commitment, not a casual
          click (confirmation step or equivalent weight).
        evidence: [screenshot, video]
        confidence: low        # user declined to specify; graded gently
```

Two rules bind the draft:

1. **Every criterion names the evidence kinds that can prove it.** This
   is where the scenario's *evidence contract* is co-generated -- the
   union of the rubric's `evidence` fields is what the harness must
   capture. A criterion with no capturable proof is rejected at draft
   time, not discovered as ungradeable downstream.
2. **Points encode the charter.** Persistence and notification carry the
   weight because the charter says presses run their business on this;
   the felt-quality criterion is real but small, and low-confidence
   besides.

## Stage 4 -- Adversarial Calibration

Before sealing, the draft rubric is attacked three ways:

- **The gaming audit.** A red-team agent is handed the rubric -- the
  full, unsealed rubric -- and asked one question: *how would you score
  100% while betraying the scenario's intent?* Hardcode the notification
  text? Render the approved badge without a database write? Each exploit
  found tightens a criterion or adds a guard criterion (this is where
  "survives a page reload" entered `approval_persists`). The audit ends
  when the red team's best exploit is judged more expensive than doing
  the work honestly.
- **The reliability trial.** Several independent judge instances score
  the same fixture evidence against the draft. Criteria with high
  score variance are ambiguous *by demonstration* and get rewritten
  until judges converge. A criterion humans can argue about is a
  criterion judges will be inconsistent on.
- **The coverage check.** Does the criteria set span the scenario's
  claims? Do the points sum to the stated scenario weight? Is any
  criterion unreachable given the declared evidence contract?

Calibration artifacts -- the exploits found, the variance numbers -- are
retained with the rubric version. A rubric's trustworthiness is itself
evidenced.

## Stage 5 -- Sign-off and Sealing

The user reviews the calibrated draft the way they would review code:
criteria as the diff, calibration results as the CI run. Approval does
three things atomically:

1. The rubric becomes **version 1** and enters the vault -- readable by
   judges only, OS-enforced.
2. The **sanitized scenario** is derived and published to the builder
   side: the narrative, stripped of criteria, thresholds, and weights.
3. The **evidence contract** is published to the harness side: the
   capture requirements, without the criteria they serve.

Three artifacts, three audiences, one source of truth.

## Stage 6 -- Revision (the grease pencil)

Once the loop runs, rubric authorship shifts from specification to
reaction. The user annotates developed frames in the gallery -- "this
empty state is technically correct but feels dead" -- and each
annotation compiles into a **proposed rubric diff**:

```diff
   criteria:
+    empty_state_invites_action:
+      points: 5
+      description: >
+        The no-proofs-yet state names a next step and links to it.
+      evidence: [screenshot]
+      confidence: high         # promoted: the annotation was specific
```

A proposed diff runs an abbreviated calibration (gaming spot-check,
reliability spot-check), then goes to the user for the same sign-off as
version 1. On approval the version bumps, and:

- Every evaluation records the rubric version that scored it -- a score
  is never ambiguous about what "good" meant at the time.
- Peak scores and regression gates recompute under the new version.
- The vault's diff history accumulates into the product's most valuable
  artifact: the quality bar, made precise one reaction at a time.

## Failure Modes This Lifecycle Is Designed Against

| Failure | Countermeasure |
|---|---|
| Criteria that sound rigorous but can't be checked | Evidence-kind requirement at draft time (Stage 3) |
| Builders satisfying the letter while betraying intent | Gaming audit before sealing (Stage 4) |
| Judge non-determinism blamed on the judge | Reliability trial: ambiguity is a rubric defect (Stage 4) |
| Silent assumptions where the user was vague | Low-confidence criteria, flagged not guessed (Stage 2) |
| Taste drift invisible until scores stop making sense | Versioned diffs; evaluations pinned to rubric version (Stage 6) |
| Rubric leakage collapsing the feedback loop | Vault sealing with OS enforcement; sanitized derivation (Stage 5) |
