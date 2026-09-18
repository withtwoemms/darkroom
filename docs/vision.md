# Vision: Building a Web App in the Dark

> A design fiction. This document imagines using a fully-realized darkroom to
> create an entirely new web application, unhindered by current limitations.
> Nothing here is a roadmap commitment; it is a picture of where the arrow
> points, written so the generalization work has something to aim at.

## The core inversion

Today you trust an app because you read the code and clicked around it
yourself. With a capable darkroom, trust comes from a different place
entirely: **every behavior of the app is continuously developed into
evidence, and judged against criteria the builders never saw.** Code becomes
an implementation detail. You never verify claims -- you review prints. The
manifest is the roll of film; a run is a development session; your job is
intent and taste.

## Day one: exposing intent

```
$ darkroom new bookbinder
```

You describe the app conversationally -- "a web app where small presses
manage print runs, quotes, and client proofs." Darkroom distills that into
three artifacts:

- **Scenarios** -- readable, sanitized descriptions of behavior ("a client
  approves a proof and the press is notified"). You edit these freely;
  they are the shared language.
- **Rubrics** -- the scoring criteria, generated with you, then **sealed in
  the vault**. Only judges ever see them. This is the load-bearing secret:
  builders cannot teach to a test they cannot read. (How a rubric is made,
  hardened, and revised is outlined in [rubric-lifecycle.md](rubric-lifecycle.md).)
- **An evidence contract** -- for each scenario, what must be developed as
  proof: screenshots at each step, a video of the full flow, the HTTP
  transcript, the DB state before and after, the accessibility tree, a
  performance trace. Non-visual features get non-visual contracts: an API
  endpoint's evidence is its request/response transcripts and latency
  histogram; a background job's evidence is queue-state snapshots and log
  excerpts.

Nothing an agent *says* will ever count as evidence. Only what the
instrumented harness captured.

## Lights out

You go to bed. The dark factory runs: builders implement, the harness
executes scenarios and develops a roll per iteration, judges score each roll
against sealed rubrics, feedback flows back stripped of scores and criteria.
Stagnation escalates automatically -- diagnostic access, bigger models,
sharper feedback. Regressions roll back to the last peak. Every iteration is
a checkpoint commit paired with its judged manifest, so the app's entire
history can be scrubbed like a flipbook.

## Morning: the contact sheet

This is where darkroom stops being infrastructure and becomes the product.
You open the gallery and you do not see diffs or logs -- **you see your app
existing**:

- A contact sheet per scenario: a strip of frames, one per step, with the
  judge's score and notes pinned beside it. The signup flow at iteration 14
  next to iteration 15, side by side.
- Tap a frame to enlarge: the full-res screenshot, the DOM snapshot behind
  it, the network waterfall under it, the judge's reasoning attached.
- Scenarios that converged overnight are marked **fixed** -- like a print
  pulled from the fixer bath, no longer light-sensitive. Their peak evidence
  and peak commit form a regression gate; anything that later scores below
  it auto-reverts.

You flip through the album over coffee. Twenty minutes in, you have *seen*
more of your app's real behavior than a week of PR review would show you.

## You are the meta-judge

Where the judge's score and your taste disagree, you annotate the frame
directly: "this empty state is technically correct but feels dead -- needs a
call to action." That annotation does not go to the builder as an
instruction; it becomes a **rubric revision**, versioned in the vault. You
are not managing implementation -- you are refining what *good* means, and
the loop re-converges under the new definition. Over months, the vault
becomes the most valuable artifact you own: a precise, executable definition
of your product's quality bar.

## Evidence-first everything else

Once evidence is the ground truth, the rest of the workflow reorganizes
around it:

- **PRs become evidence diffs.** A change ships with before/after contact
  sheets, judged. Reviewers look at behavior first, code second -- or never.
- **Deploys are gated on a judged manifest** of the release candidate. "All
  scenarios at or above peak" is the merge criterion, mechanically enforced.
- **The gallery is the living documentation.** Every feature has timestamped
  photographic proof of its behavior. Onboarding a new engineer is handing
  them the album. Compliance and audit get a tamper-evident chain of custody
  from intent to rubric version to evidence to score to commit.
- **Design review, QA, and demo prep collapse into one artifact** -- the
  same contact sheet serves all three audiences.

## What your day actually contains

The economic shift is the point: you spend nearly zero time verifying
claims, reproducing bugs, or reading code to establish trust. Your day
compresses to the two things only a human can supply -- **deciding what good
means, and arbitrating when the judge and your taste diverge.** Everything
between intent and evidence runs in the dark, which is exactly where it
belongs.

## What this implies for darkroom

The center of gravity is not the capture library -- that is the easy part,
and mostly built. It is:

1. **The manifest as a first-class artifact**: reviewable, diffable,
   gate-able, and portable across evidence kinds.
2. **The consumption side**: renderers that make evidence legible to judges
   (per-kind, machine-oriented) and to humans (the contact sheet, the
   gallery).
3. **Evidence contracts**: a declared mapping from scenario to required
   proof, so "did we capture enough to judge this?" is checkable before any
   judging happens.
4. **Kind-plurality from the start**: screenshots are one kind among many.
   HTTP transcripts, DB snapshots, command output, traces, and videos are
   peers, not afterthoughts.
