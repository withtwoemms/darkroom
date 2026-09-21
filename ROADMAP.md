# darkroom Roadmap

> *Major milestones from foundation through v1. `CHANGELOG.md` is the source of truth for incremental updates.*

---

## Vision

darkroom is the evidence subsystem for autonomous software delivery: typed evidence capture, a versioned manifest contract, and the machinery for judging work by what was *captured*, never by what was *claimed*. The long-form design fiction lives in [`docs/vision.md`](docs/vision.md); the short version: every behavior of a system is continuously developed into evidence, judged against criteria its builders never saw, and the manifest — not the code — becomes the artifact you review, diff, and gate on.

**Target users:**

- Teams running Judge-Builder loops who need an honest, non-fabricatable signal between builder and judge
- Test-suite authors who want evidence capture (screenshots, transcripts, snapshots) as a typed, manifest-backed byproduct of runs they already have
- Framework builders composing convergence loops — assess, score, escalate, roll back — over any scored artifact

---

## How This Document Relates to CHANGELOG

This roadmap tracks **major milestones** on the path to v1. For incremental updates — every patch and minor release, including bug fixes, new producers, renderer refinements, and small API additions — see `CHANGELOG.md`. The CHANGELOG is the source of truth; this roadmap exists only to surface the structural waypoints that connect releases into a coherent trajectory.

A note on schema versioning: the **manifest schema** (currently `2.0`) is versioned independently of the package and moves more conservatively — it is the handoff contract between builder-side and judge-side, and changes only with a documented migration path (the transparent v1→v2 loader sets the precedent).

---

## Milestone Timeline

| Version | Milestone | Status |
|---------|-----------|--------|
| v0.x | Evidence core extracted from the Judge-Builder framework: frozen `EvidenceItem` records, `EvidenceProducer` protocol, `RunManifest` with schema-versioned serialization (v2.0, transparent v1 upgrade), run lifecycle (`start_run`/`end_run`, `EVIDENCE_MODE`/`EVIDENCE_DIR`), `EvidenceCapture` API, legacy `compat` shim, zero core dependencies with Playwright as an extra | Complete |
| **v0.1.0** | **Publishable foundation** — LICENSE file, CI (test matrix 3.10–3.13, coverage, lint), tag-triggered release workflow with PyPI trusted publishing, distribution-name resolution (`darkroom` is squatted on PyPI; shipped as `darkroom-ai` keeping `import darkroom`), CHANGELOG seeded, `docs/vision.md` + roadmap committed | Complete |
| v0.2.0 | **Pytest plugin** — entry point registering session hooks (`start_run`/`end_run`), an `evidence` fixture keyed off the test node, screenshot-on-failure; first real integration tests; `compat` documented as legacy-only | Complete |
| v0.3.0 | **Producer plurality** — `EvidenceItem.metadata` populated by existing producers; `VideoProducer` (screencast dirs exist today with no producer); `CommandTranscriptProducer`, `FileSnapshotProducer`/`DiffProducer`, `HTTPTranscriptProducer` — the first non-browser evidence kinds | Complete |
| v0.4.0 | **Evidence contracts + first CLI** — declared per-scenario required-evidence kinds; manifest validation against contract; `darkroom verify <manifest>` console entry point. Two design questions to settle here: *rubric-as-root* (deriving the sanitized scenario and evidence contract from the rubric rather than treating them as sibling files — see [docs/rubric-lifecycle.md](docs/rubric-lifecycle.md)) and *statistical rubrics* (criteria over N trials rather than a single run — required for nondeterministic domains such as distributed systems, implying a trial-count dimension on contracts) | Complete |
| v0.5.0 | **Consumption side** — `JudgeRenderer` protocol dispatched on `EvidenceItem.kind`; typed `Evaluation`/`CriterionResult` score model with normalization; `darkroom gallery <run>` static-HTML contact sheet; manifest diffing and `PeakRecord` regression gates | Complete |
| v0.6.0 | **Project adapter + ticketing** — `darkroom.toml` (commands with placeholder substitution, spec/rubric globs, evidence paths, advisory defaults; trust rule: builder-writable, so no judging/gating/loop authority) replacing the framework's symlinks-as-API; preflight validation + `darkroom run`; `state/queue|locks|history` ticketing conventions as a Python module | Complete |
| v0.7.0 | **Convergence loop** — the assess → score → stagnate → escalate → roll back → checkpoint state machine, with the three escalation dials (diagnostic access, model escalation, feedback specificity) as configuration; roles as injected protocols with shell-hook judge/builder implementations, and `darkroom auto` running a fully automated convergence (proven end-to-end in CI) | Complete |
| v0.8.0 | **Agent invocation + vault** — judge/builder trigger layer with prompt assembly from templates (invocation as a swappable command template, `claude` CLI default); rubric isolation (the vault) replacing prompt-enforced opacity as a pluggable store — OS-permission filesystem default with audited reads, secret-manager backends (OpenBao/HashiCorp) as the graduation path; rubric-as-root contract derivation; operator config as the authority side of the trust split; end-to-end agent-mode convergence proven in CI | Complete |
| v0.8.x | **The intent interview as a Claude skill** (`skills/darkroom-interview/`) — the rubric lifecycle conducted as a conversation: charter, scenario enumeration with negative space, threshold interviews, drafting under the capturable-evidence rule, gaming self-audit, preflight-validated artifacts. Proven on a greenfield example app | Complete |
| v0.9.0 | **The exam line: operator home + drive** — `~/.darkroom` per-project operator home (auto-discovered operator config, vault, drives, and state; relocates loop state out of the tenant, closing the builder-readable-scores leak); `darkroom drive`: the harness as a distributable engine plus declarative per-scenario scripts (`http`/`command`/`keygen`/`sign`/`assert`/`wait` steps captured via existing producers; serve/health lifecycle; environment seam for container backends) — the exam leaves the tenant entirely, builders own their tests, and any HTTP service or CLI in any language becomes a tenant; loop integration via `test = "darkroom drive"`; an example app's drive scripts as the living example | Planned |
| v0.10.0 | **Hardened backends** — OpenBao/HashiCorp vault backend (`[vault]` extra: KV v2 versioned rubric reads, token-gated access, server-side audit a compromised builder cannot edit); container environments (`[containers]` extra: SUT containment at assess time — builder-authored code runs without filesystem access to the operator home — hermetic per-run environments with image digests recorded as evidence, and a container step kind enabling failure-injection scenarios) | Planned |
| v0.11.0 | **The spec** — `docs/spec/`: manifest, contract, evaluation, gates, tickets, drive scripts, and the role hook contract written as format specifications independent of the Python implementation; warts surfaced by spec review fixed before the 1.0 freeze. The standard play: neutral formats other harnesses can emit and consume | Planned |
| **v1.0.0** | **Generality proven live, API frozen** — a greenfield example app (fully non-visual: `http_transcript` + `log` evidence only) converges under `darkroom auto --operator` with real agents and real spend; the source framework's pilot migrates and its Makefile/bin orchestration retires onto darkroom; manifest schema and public API declared stable as written spec | Planned |

---

## v0.2–v0.4 — The Evidence Line

**Theme:** Make capture adoptable by any pytest project, plural in kind, and checkable for sufficiency — before any judging exists.

**Motivation:**
The extracted core works but carries its pilot's fingerprints: users hand-wire session hooks that a plugin should own, screenshots are the only substantive evidence kind, and nothing can answer "did this run capture enough to be judged?" until a judge fails to find what it needs. The evidence line removes each limitation in dependency order:

- **v0.2.0 — Adoption.** The pytest plugin makes darkroom a one-line `pip install` + zero-conf experience for the ecosystem it already targets. It also retires the reason `compat.py` exists for new projects.
- **v0.3.0 — Plurality.** Non-browser producers (command transcripts, file snapshots, HTTP transcripts, video) prove the `EvidenceProducer` protocol is actually general rather than a screenshot API with extension points. This is the prerequisite for ever judging non-visual work.
- **v0.4.0 — Sufficiency.** Evidence contracts invert the check: instead of judges discovering missing evidence downstream, `darkroom verify` fails the run at capture time. First CLI surface; the manifest becomes gate-able.

**Why three releases and not one:**
Each release hardens against a different user. The plugin's design risk is pytest-integration ergonomics (fixture naming, hook ordering) — feedback comes from test-suite authors. Producer design risk is the shape of non-visual evidence — feedback comes from what judges can actually consume. Contract design risk is expressiveness vs. ceremony — feedback requires both prior layers in real use. Bundling them would force contract decisions before a single non-visual producer had been exercised.

---

## v0.5 — The Consumption Side

**Theme:** The manifest is a handoff contract with only one side implemented. Build the consumer.

**Motivation:**
In the source framework, everything downstream of the manifest is improvised: the evaluation JSON schema lives inside a shell script's prompt string, score normalization exists because the judge drifts (`get-score.sh`), regression gates were designed but never built, and the only human-facing view of evidence is `ls`. v0.5.0 makes each of these a typed, tested artifact:

- `JudgeRenderer` mirrors `EvidenceProducer` on the consuming side — per-kind rendering (image reference for vision models, excerpt for transcripts, structured summary for JSON) is what breaks the screenshots-only anchoring.
- The `Evaluation` model absorbs schema-pinning and normalization into one versioned place.
- `PeakRecord` gates make "never ship below peak" a mechanical property instead of a Makefile convention.
- `darkroom gallery` is the first human-facing payoff of the vision's contact sheet — useful standalone, with no judge in the loop at all.

**Status:** Planned. Pure library + CLI work; no orchestration decisions required, so it can proceed in parallel with v0.6 planning.

---

## v0.6–v0.8 — The Orchestration Line

**Theme:** Retire the source framework's 546-line Makefile and `bin/` scripts into testable Python, one subsystem per release, with the pilot project as the regression test.

**Motivation:**
The Judge-Builder framework's control loop works but is unmaintainable and single-tenant: the convergence loop is shell embedded in Make, prompt assembly is split across three files, the target project is reached through symlinks (the root cause of both documented defects — the rubric leak and the judge's glob churn), and the builder/judge boundary is enforced only by CLI flags and prompts. The orchestration line replaces each subsystem where it hurts most:

- **v0.6.0 — Ground truth for "a project."** The `darkroom.yaml` adapter kills the symlinks and makes multi-tenancy fall out of workspace partitioning. Ticketing ports nearly as-is; it is already project-agnostic.
- **v0.7.0 — The loop as a state machine.** Stagnation counters, escalation dials, rollback, checkpointing, and iteration memory become inspectable, unit-testable Python with thresholds in config.
- **v0.8.0 — The boundary as an OS property.** Prompt assembly consolidates into templates; rubric isolation moves from "the prompt says don't look" to filesystem enforcement. A soft boundary becoming hard is the last prerequisite for trusting unattended runs.

**Why the pilot migrates at every release:**
Each release lands with the source framework's pilot project running on it. The pilot is the only existing end-to-end workload; keeping it green at every step is what distinguishes generalization from rewrite.

---

## v0.9–v0.11 — The Post-Parity Arc

**Theme:** From parity to trustworthiness and portability — the exam
leaves the tenant, authority gets a home, boundaries harden from
prompt-enforced to structural, and the formats become a spec.

**Motivation:**
Parity (v0.8) reproduced the source framework's capability; the
post-parity arc removes its residual weaknesses. Three run deep:

- **The harness lived in builder-writable space.** A tenant-resident
  test suite is an exam the examinee can edit; the defenses were
  prompt rules and tamper-evidence. `darkroom drive` dissolves the
  problem instead of mitigating it: the engine is a pip-installed
  package, the per-scenario scripts are operator-side data, and the
  system is driven as a black box over real interfaces. Corollaries:
  builders freely write their *own* tests (nobody grades their own
  final — but everyone does practice problems), and any HTTP service or
  CLI in any language becomes a tenant with no Python in its repo.
- **Operator material was scattered, and one piece leaked.** Loop state
  defaulted inside the tenant, leaving judge evaluations — scores —
  readable by the builder between iterations. The per-project home
  (`~/.darkroom`, mode 700, the `~/.ssh` precedent) consolidates
  operator config, vault, drives, and state outside every
  builder-addressable path, and turns required flags into discovered
  defaults.
- **Prevention has a same-UID ceiling; detection does not.** The
  hardened backends convert remaining soft boundaries into detected,
  attributable events: a secret-manager vault (OpenBao) adds token-gated
  reads and server-side audit no compromised builder can edit —
  rubric exposure becomes a rotatable incident, not an invisible
  corruption; containerized environments contain builder-authored code
  at assess time and stamp image digests into the evidence, making the
  run's environment part of the chain of custody.

The spec (v0.11) then writes the accumulated contract stack — manifest,
contract, evaluation, gates, tickets, drives, role hooks — as formats
independent of the implementation, deliberately *before* 1.0 freezes
them: a spec review finds warts an implementation hides, and neutral
formats other tools can emit are the difference between a framework and
a standard.

---

## v1.0 — The Proof

**Theme:** 1.0 is earned by evidence, not by a date.

The gate is **a greenfield example app converging live**: a tenant whose
scenarios and rubrics were authored by the intent-interview skill,
driven by `darkroom drive`, judged purely on `http_transcript` and
`log` evidence — zero screenshots — under `darkroom auto --operator`
with real agents and real spend. If that loop closes, the
generalization is real end to end: intake, exam, producers, renderers,
contracts, vault, and the loop, all exercised with no pixels and no
hand-wiring. The source framework's pilot then migrates and its
Makefile/bin orchestration retires; the manifest schema and public API
freeze under semantic versioning as the written spec.

---

## Guiding Principle

> "If it happened, it can be captured.
> If it can be captured, it can be judged.
> If it can be judged, it can be trusted."
