---
name: darkroom-status
description: Report where a darkroom project stands right now - convergence per scenario, blockers, what is shipped versus merely gated, the ticket queue, and the metered equivalent with how the agents are billed - in one fixed shape, from the engine's own status command. Use when a user asks for a status, a convergence update, "where are we", what's running, what's blocked, what it cost, or what's next.
---

# The darkroom status report

You are answering "where do things stand?" for the operator, in a
shape they can read the same way every time. The chronicle narrates a
finished record; the converge skill runs one scenario; this skill is
the standing report across both, and it is mostly *facts the engine
already has* plus a small amount of judgment the engine cannot make.

**The governing rule: every number in the report comes from
`darkroom status`, never from your own reading of loop files.** Run
`darkroom status --format json` (add `--scenario <name>` to narrow,
`--stale-after <seconds>` if the project's iterations run long) and
render from it. A report assembled by hand from six files is a report
that drifts, and drift is how an operator gets told a run converged
that did not. If the command cannot answer something, say "unknown";
never fill the gap with something plausible.

## The shape (always in this order)

1. **Headline** — one line: what changed since the last report, or
   "nothing has run since <time>". Lead with the outcome the operator
   would ask for first.

2. **Convergence** — from the command, per scenario with a campaign:
   state, iterations, score trajectory, best, gate, metered figure. States are
   exactly the engine's: `converged`, `running`, `blocked`, `stopped`,
   `exhausted`. A run in progress is *running* with its last score;
   never predict where it will land. A `stopped` campaign is one with
   no recent activity and no convergence — say so and say how long
   ago it last moved; do not call it exhausted unless the engine did.
   When a `HARNESS-BLOCKER.md` is present, quote its brief verbatim
   and give the one judgment this section needs: is the builder right
   that the defect is operator-side (an exposure step, a criterion, a witness) or is the
   behavior genuinely missing? That is the converge skill's Stage 6
   triage; apply it here and name the fix.

3. **Shipped state** — the engine cannot know this, so each line is a
   *separate claim* with its own source, and an unknown stays unknown:
   - merged: from git/GitHub (branch vs main, PR state);
   - released: from the package index or the tag (never "should be");
   - deployed: from the deploy tool's own record (release number,
     time), never from the fact that a deploy was started;
   - live-verified: from a probe of the live surface, quoting what it
     answered. A green gate and a live surface are two different
     claims; make both or say which one is missing.
   Consult the project's own record (memory, tickets, docs) for where
   these are kept; if the project keeps none, say that.

4. **Queue** — from the command: the ticket queue in priority order,
   then what is waiting on the user (rulings, pushes, manual
   walkthroughs), stated as items they can act on.

5. **Metered equivalent** — from the command: the metered figure for
   the campaigns in this report and the project total, judge and
   builder separately, *with how the agents are billed* (the bundle's
   `metering`). The CLI's `cost_usd` is the API list price of the
   tokens used; under a claude.ai login it is a reference equivalent
   drawn against the plan, not a charge — say which, every time, and
   never call it "spend" unless `metering.billing` is `metered`.

## Rules of the report

- Report scores from the output, not from hope. If asked before a run
  completes, the state is `running` and the last score is the last
  score.
- One red scenario in a full-suite run is not a regression until it
  has been rerun alone; report it as "red once, rerun pending" until
  then.
- Numbers you gave earlier in the same conversation are not sources;
  re-run the command. (A commit count reported from memory was wrong
  by an order of magnitude once. Once was enough.)
- Match length to what changed: a quiet hold is three lines; a slice
  landing is the full shape.
- Keep the operator's vocabulary — scenario names as the engine
  prints them, ticket titles as filed — and never invent a label the
  reader would have to decode.
