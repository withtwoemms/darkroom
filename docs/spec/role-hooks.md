# The Role Hook Contract

**Format:** command templates + file contract · **Schema version:**
1.1 · **Where:** operator config (judge/builder command templates).

## Purpose

The convergence loop drives two roles — a judge and a builder — that
the operator supplies as commands. Darkroom supplies the file
contract: which paths a hook receives, what it must read, and what it
must write. Anything that honors the contract is a conforming role: a
shell script, a `claude -p` one-liner, another vendor's agent. The
built-in agent roles honor exactly the same shapes, so the contract —
not the implementation — is the public interface.

## Trust position

Hook command templates live in **operator config** and run
operator-side. The contract is also where the judge/builder
information boundary is enforced in practice:

- the judge receives the **manifest** (evidence), never tenant
  source;
- the builder receives **feedback**, never the evaluation — scores
  cross the boundary only as operator-mediated feedback at a
  configured specificity;
- harness diagnostics flow through two deliberately different
  channels (below).

## Judge hook

The template is formatted with these placeholders and run via
`sh -c` in the project root:

| Placeholder | Direction | Meaning |
|-------------|-----------|---------|
| `{manifest}` | read | path to the run manifest to judge |
| `{evaluation_out}` | **must write** | path where the hook writes evaluation JSON — strict form or any shape the lenient coercion of [evaluation.md](evaluation.md) absorbs |
| `{feedback_out}` | should write | path for builder-safe feedback markdown; may be omitted or left empty |
| `{scenario}` | read | scenario name for scoped runs, else empty |
| `{stagnation}` | read | consecutive non-improving iterations |
| `{feedback_level}` | read | operator's feedback-specificity dial (0, 1, 2) |

**A missing score is not a zero**: a judge hook that fails or writes
no evaluation aborts the loop. Scoring absence as zero would let an
infrastructure failure masquerade as a quality signal.

## Builder hook

| Placeholder | Direction | Meaning |
|-------------|-----------|---------|
| `{feedback}` | read | path to the judge's feedback file |
| `{scenario}` | read | scenario name for scoped runs, else empty |
| `{stagnation}` | read | consecutive non-improving iterations |
| `{diagnostic}` | read | `1` when the diagnostic escalation dial has fired, else `0` |
| `{escalate_model}` | read | `1` when the model-escalation dial has fired, else `0` |

The builder hook's only judge-derived input is the feedback file. It
writes no contract files; its output is the tenant's working tree,
which the loop checkpoints.

## Harness diagnostics channels

Two channels exist so that empty repositories can bootstrap from
feedback without the judge's material leaking:

| Channel | Audience | Content |
|---------|----------|---------|
| `harness.log`, beside the manifest | **builder-visible** | step names and failure details — spec-level information only (the sanitized scenarios already state them); criteria and scores never appear |
| harness notes, embedded in the judge's inputs and surfaced in the evaluation's `notes` | judge/operator | the same diagnostics in the judge's context, so an exam defect (missing evidence, boot failure) is attributed to the exam, not the application |

## The blocker channel *(1.1)*

A builder that concludes the exam itself is defective — no
tenant-side change can pass it — may raise a **blocker**: a file
named `HARNESS-BLOCKER.md` at the project root stating precisely
why, citing what was reproduced. The loop detects it in the
iteration's changed files, records it on the iteration, surfaces it
to the operator, and (by default policy) **pauses model escalation
while it stands** — frontier spend cannot fix an operator-side
defect. Blocker content is builder-authored and spec-level: it may
cite steps, transcripts, and diagnostics, never rubric text or
scores (it has no access to them). Field precedent: builders
invented this channel unprompted, and were right each time.

The invariant that keeps this safe: **a builder-writable signal may
only reduce resources spent on the builder** — a blocker never halts
the loop, never alters scoring or stagnation accounting, never
touches gates, and never changes any outcome. The loop runs to
convergence or exhaustion regardless; the exhaust record, blocker
flagged, is itself the operator's evidence. Extensions that would
let a blocker terminate a run hand the builder a stop button and
MUST NOT be implemented.

## Execution semantics

- Hooks run via `sh -c` in the project root, non-interactively, under
  operator-configured timeouts.
- Hook stdout/stderr are captured, not inherited — a hook
  communicates through its contract files, not its output stream.
- Contract files live under operator-side state, one set per
  iteration, so a run's role I/O is auditable after the fact.

## Versioning

`1.0` named the placeholder sets and the rules above; `1.1` added
the blocker channel. New placeholders arrive as minor bumps; a template using only `1.0`
placeholders remains valid. Unknown placeholders in a template are a
configuration error, not a formatting no-op.

## Example

A complete judge hook as a single command template:

```
claude -p --model claude-opus-5 < prompts/judge.md \
  MANIFEST={manifest} EVAL_OUT={evaluation_out} FEEDBACK_OUT={feedback_out}
```

or, minimally, a script: `judge.sh {manifest} {evaluation_out}
{feedback_out}` that scores the manifest however the operator sees
fit and writes the two files.

## Conformance

- A judge hook MUST write an evaluation to `{evaluation_out}`; loops
  MUST abort when it does not, and MUST NOT score absence as zero.
- Feedback written to `{feedback_out}` MUST be builder-safe: no
  scores, no criteria text, no rubric excerpts beyond the configured
  feedback level's disclosures.
- Loop implementations MUST NOT pass tenant source paths to the
  judge, and MUST NOT pass evaluations (or their paths) to the
  builder.
- Diagnostics surfaced to the builder MUST be limited to spec-level
  information (step names, failure details); the same diagnostics
  SHOULD reach the judge so exam defects are attributed to the exam.
- Hook templates MUST treat every placeholder value as a path or
  scalar to pass through, never as content to interpret.
