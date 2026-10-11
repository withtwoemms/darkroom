# Delivering a slice

How one body of work travels from a ticket to a gated behaviour, which
skill owns which file, and what each hand-off must be true before the
next begins. The format specs say what each file *is*; this page says
who writes it, when, and what the next stage refuses to accept.

A **slice** is a set of scenarios shipped together: one product idea,
several behaviours, one closing regression.

## Who writes what

Four hats. On a small team one person wears several, which is fine;
what must not happen is one hat editing another's file to make a run
go green.

| hat | writes | never writes |
|-----|--------|--------------|
| product | `scenarios/<name>.feature`, `proofs/<name>/rubric.toml` | the exposure, the surfaces |
| engineering | the build, `scenarios/<name>.surfaces` | the rubric, the exposure |
| QA | `proofs/<name>/exposure.toml`, `backdrops.toml` | the rubric |
| review | the evaluation | everything else |

The spec is product's description of what must be true, in plain
Gherkin with no routes and no selectors: how a behaviour is reached is
engineering's call. The `.surfaces` file is engineering's publication
of the addresses it chose. The exposure drives those addresses and
captures evidence. The rubric says what a good record shows, in
product's words. The audit holds the exposure and the publication to
each other, both ways.

## The chain

```
ticket ──▶ interview ──▶ author ──▶ converge ──▶ status / chronicle
 charter    spec +        rubric     campaigns,   the standing
 rulings    scenarios     shape +    regression,  report; the
                          exposure   deploy       narrative
```

### 1. The ticket carries the charter

Before anything is authored, the ticket should hold what the product
is, who it serves, what it must never do, and **every ruling already
made, with its reason**. Conclusions without reasons rot: a later
reader cannot tell a deliberate constraint from an accident.

A ticket is ready for the interview when a reader who was not in the
conversation could answer "why this and not the obvious alternative?"
for each ruling.

### 2. The interview turns the charter into scenarios

`darkroom-interview`, product's hat. Enumerate the behaviours the
description implies, including the negative space it only implies:
authorisation failures, immutability after commitment, error
behaviour. Interrogate every vague term into a threshold — *notified*
by what channel within what window; *fast* measured where. A term the
product declines to pin down becomes a criterion marked
`confidence = "low"` with few points: flagged, never silently guessed.

Output: one `.feature` per scenario. Nothing is ready for the next
stage while a threshold is still a feeling.

### 3. The author stage shapes the proof

`darkroom-author`. Rubric first, in product's words, with the witness
*names* it intends; then the exposure built to produce exactly those.
Writing the rubric first is the point: an exposure written first
produces whatever it happens to produce, and the rubric ends up
describing the exposure instead of the product.

Four rules bite here more than anywhere else, and each exists because
skipping it cost a real project real money:

- **A witness is never in a backdrop.** What a scenario proves lives
  in its own steps. The moment a rubric cites shared setup, every
  scenario posed against that backdrop depends on it, and one edit
  silently re-scores them all. A scenario that proves something about
  the setup itself must own those steps rather than pose against them.
- **Absence is witnessed positively.** "The field is gone" is not a
  selector that fails to appear; it is a state attribute that does, a
  count that resolves to zero, or a body an assert inspects.
- **Address only what is published.** Read the `.surfaces` first. On a
  new feature there is nothing to read yet, so the exposure is written
  to the spec's intent and the audit flags `surface-unpublished` until
  engineering publishes. That is expected, and it is also where the
  next stage's most expensive failure begins.
- **Machine surfaces, never display text.** Typography is the judge's
  business, from screenshots, and must never be able to break a gate.

The stage ends at two checks, both free: `darkroom audit` clean, and a
dry run whose only red steps are genuinely unbuilt ones. A red step
that *should* pass against the build as it exists is an authoring
defect, and fixing it costs nothing compared to discovering it inside
a campaign.

### 4. Converge runs it

`darkroom-converge`, one scenario at a time. Commit both repos first:
the loop refuses a dirty tree rather than mix its checkpoints with
uncommitted work.

The pattern worth recognising on a scenario whose surfaces did not
exist yet: iteration 1 builds and publishes them, the judge scores
zero because the exposure's steps address shapes that were guessed,
and the next iterations are the builder bending its code toward those
guesses. **Stop and realign the exposure to what was published.** On
one measured slice, three such scenarios took five iterations each
where two would have done, and that accounted for most of the slice's
cost.

A `HARNESS-BLOCKER.md` means the builder believes the exam is wrong.
Read it in full. Often it is right, and the brief contains the fix.

### 5. The slice closes, not the scenario

A scenario's gate is not the end. Close the slice with:

- `darkroom surfaces --merge`, then `darkroom audit` clean;
- the **full regression**, not the slice's own scenarios. A later
  campaign can change a surface an earlier campaign gated against, and
  nothing but the full suite will notice. On one measured slice the
  closing regression found four stale exams and one real product
  defect that a campaign had introduced four hours earlier;
- a red rerun alone before it is called a regression;
- deploy, then verify the live surface. A green gate and a live
  surface are two different claims.

Now that a full suite can cost minutes rather than an hour, running it
*between* campaigns within a slice is cheaper than discovering the
drift at the end.

## What a tenant must decide before authoring

Two questions have no home in any format spec, and both bite at the
author stage:

**Does the exam need infrastructure the product does not have?** A
scenario may need somewhere for a message to land, a clock it can
scale, a second service to observe. That is a tenant-side decision
(`[[environment.services]]`, `[serve.env]`, a seam the product reads)
and it belongs in the ticket, not in a surprise mid-exposure.

**Which claims can no exposure witness at all?** Some truths are
outside every driver: an operating-system notification arriving, an
install gesture a person performs, a signature over a byte sequence the
engine cannot reproduce. Decide these *before* writing criteria. A
criterion no record can prove is not a high bar, it is an unprovable
one, and the audit will refuse it. State the claim as a manual check
alongside the gate, the way a live-surface probe sits alongside a green
run, and let the rubric claim only what the record shows.

## The skills

Five ship inside the package, version-locked to the engine.

| skill | stage | owns |
|-------|-------|------|
| `darkroom-interview` | 2 | the charter and the specs |
| `darkroom-author` | 3 | the shape of the proof: rubric, then exposure |
| `darkroom-converge` | 4–5 | the run, the triage, the regression |
| `darkroom-status` | any | the standing report, every number from `darkroom status` |
| `darkroom-chronicle` | after | the narrative, from the dossier |

`darkroom-author` also runs over an existing corpus: extracting
backdrops from repeated openings, and rewriting migrated rubrics into
product's words.
