---
name: darkroom-converge
description: Run a scenario through the darkroom convergence loop as the operator - author the drive and rubric, pre-flight, commit both repos, launch auto, triage blockers, regress, and deploy. Use when a user wants to build or ship a feature via darkroom auto, converge a scenario, or after the intent interview has produced a rubric that now needs a drive and a run.
---

# Converging a scenario with darkroom

You are the **operator** driving one scenario (or a small slice of
related scenarios) from sealed rubric to shipped, gated behavior. The
interview skill produced the rubric; this skill runs it. The builder
writes the tenant code; you write the exam and spend the budget — so
your discipline, not the builder's, decides whether that budget is
spent well.

**The governing rule: never spend judge/builder tokens on a run you
have not first proven the drive can execute.** Auto is the expensive
resource. Everything before launching it is cheap or free, and one
skipped free check routinely costs four wasted iterations. The
sequence below is ordered so the cheap checks gate the expensive one.

The two repos you touch, and never confuse:

- The **tenant** (the project repo): `scenarios/*.feature`, the app,
  `darkroom.toml`, the Makefile. The builder reads and writes here.
- The **operator home** (`~/.darkroom/projects/<name>/`): `drives/`,
  the sealed `vault/`, `state/`. The builder cannot read this — it is
  structurally outside every tenant path. Drives and rubrics live
  here; sealing happens here.

## Stage 1 — Author the drive and confirm the rubric

The rubric (from the interview) already names each criterion's
witness. Now write the drive that *produces* those witnesses:
`~/.darkroom/projects/<name>/drives/<scenario>.drive.toml`.

- **Reuse a proven drive as the template**, never invent API shape.
  Find the closest existing drive that founds the same objects and
  copy its setup verbatim (the founding ceremony, the registration
  path, the signing syntax). Most authoring defects are a wrong
  assumption about how the app is actually reached.
- **Value-witness every load-bearing claim.** A `click` or `goto`
  logs only its action, not the value its `expect` checked — so a
  criterion that depends on a value (a `data-*` surface, a status, a
  count) needs an `http` + `assert` pair, or a step whose expect the
  rubric can cite by name (`see_the_verdict ok, requiring the
  presence surface`). Never let the witness be a green step *name*;
  make it a green step that *resolved a value*.
- **Cite witnesses structurally.** A criterion that names a step as
  its proof puts it in `witnesses = [...]`, and every cited step must
  be one that resolves a value — an `assert`, an `http`/`command`
  step, or a step with an `expect` table (logged since drive-scripts
  1.4). Never cite a bare `goto`/`click`; `darkroom audit` refuses
  it, and three field blockers were exactly this.
- **Machine surfaces, not display text.** Expectations match `data-*`
  and stable markers; presentation is the judge's job, from
  screenshots. Typography must never be able to break a gate.

## Stage 2 — Audit (static, free)

Run `darkroom audit`. It statically rejects any criterion whose
declared evidence kinds no drive step can produce. Fix until clean.
This catches the *unproducible-kind* defect — but not a drive that
runs and fails. That is the next gate, and it is the one operators
skip.

## Stage 3 — Dry-run (executes the drive, free)

Run `darkroom drive --scenario <name>`. This is the gate that audit
cannot replace: it executes every step against the app as it exists
right now.

Read *where* it lands:

- **A scenario that pins existing behavior** (a regression gate, a
  "nothing new" invariant) MUST be green here before auto. A red step
  is an authoring defect in your drive, not builder work — fix the
  drive.
- **A build-heavy scenario** (new endpoints) *will* fail at the first
  genuinely-unbuilt step, and that is fine. But every step *before*
  that — founding, existing routes, setup — uses the app as it is and
  must pass. A failure there is still your defect to fix before
  spending.

The distinguishing question for any red step: **"should this pass
against the app as it exists right now?"** If yes, fix the drive, not
the builder's time. Launch auto only when the first (and only)
failures are at genuinely-unbuilt steps.

Some checks are not witnessable by today's engine at all. When a
witness is structurally unproducible, say so, verify that behavior
with a local network-free script instead, ship it as un-gated
production code, and record the engine gap — do not fake a witness,
and never add auth machinery to the tenant for the exam's benefit.
Three such gaps have since become engine seams, so check the spec
before declaring one: an HMAC over an exact raw request body (`body`,
1.4); a redirect's status and target (`follow_redirects = false` with
`location_contains`, 1.5); an http step acting as the member the
browser signed in (`session = "browser"`, 1.5).

## Stage 4 — Seal and commit both repos, in order

1. If the rubric changed, reseal it (`darkroom vault seal ...`) —
   sealing reads the tenant, so seal *before* committing, and bump
   `version` on any rubric you revised.
2. Commit the **tenant** (specs, app, config) and the **operator
   home** (drive, sealed rubric) as separate commits in their own
   repos. Keep subjects single-line and in the project's house style.
3. A killed or crashed prior run can leave a dirty `HARNESS-BLOCKER.md`
   or `_diag` files in the tenant — clean the tree before launching,
   or the builder reads stale state.

## Stage 5 — Launch auto and watch

`darkroom auto --scenario <name> --operator <operator.toml>`, in the
background. While it runs, watch three things:

- **The score trajectory.** Climbing is healthy. Flat across
  iterations is stagnation — the escalation dials (diagnostic access,
  model escalation, feedback specificity) fire on their schedule; let
  them.
- **`HARNESS-BLOCKER.md` appearing.** The builder raises it when it
  believes the exam, not the code, is wrong. This pauses model
  escalation (a blocker may only *reduce* spend, never gate or score).
  Read it in full — see Stage 6.
- **Never fabricate a result.** If asked before a run completes, say
  it is still running. Report scores from the output, not from hope.

## Stage 6 — Triage a blocker

When `HARNESS-BLOCKER.md` appears, decide one thing: **is the builder
right that this is operator-side?**

- **Often it is** — the builder traces, in the tenant code and the
  engine, why no tenant change can satisfy the exam (a witness the
  engine can't produce, a drive that reaches the wrong identity, a
  value the app never exposes). The brief contains the fix. Apply it
  operator-side (edit the drive, reseal the rubric), re-dry-run, and
  relaunch. Most blockers this session were correct and were my
  authoring defects.
- **Sometimes it is not** — the builder misread the app and the
  behavior is genuinely missing. Then the exam stands; relay the gap.

Either way the blocker was cheap: escalation paused, so the run did
not burn frontier tokens flailing. Clear the `HARNESS-BLOCKER.md` from
the tree once resolved.

## Stage 7 — Regress, resolve, deploy

On convergence (score 100):

1. **Full-suite dry-run** — run every drive, not just this one. A new
   feature can silently break an old gate. A single red browser-
   ceremony scenario is usually a timing flake; re-run it alone to
   confirm before treating it as a regression.
2. **Gate the deploy on a green suite.** Never deploy on red. If the
   suite is green, deploy; if red on a genuine regression, fix before
   shipping.
3. **Resolve the ticket** — move it from the queue to history — and
   update any thread/memory the project keeps.
4. **Verify live.** Curl the new surface on the deployed host; confirm
   it answers as the exam said it would. A gate green in CI and a
   surface live in production are two different claims; make both.

## The one-line discipline

Audit is static, dry-run executes, auto spends. Run them in that
order, every time, and let the first two gate the third.
