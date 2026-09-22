# Changelog

All notable changes to this project are documented here. The format is
based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the
project follows [semantic versioning](https://semver.org/) (pre-1.0: minor
releases may break API, patch releases never do). The manifest schema is
versioned independently of the package — see `ROADMAP.md`.

## [Unreleased]

### Added

- OpenBao / HashiCorp Vault backend for the rubric vault
  (`darkroom.vault_openbao`, behind the `vault` extra): KV v2 storage
  with token-gated reads (`BAO_TOKEN`/`VAULT_TOKEN` in the operator
  process only — agents never hold credentials) and rubric-version
  resolution by bounded newest-first walk of KV history; configured via
  `[vault] backend/url/mount/path` in operator config, with
  `build_vault` selecting the backend everywhere. `vault seal` writes to
  the configured backend; new `vault migrate` moves a filesystem vault
  into it, archiving local copies. CI runs the backend tests against a
  real `bao server -dev` (#36)
- Container environments (behind the `containers` extra, testcontainers):
  the adapter's `[environment]` declares run-me facts — `app_image`,
  `app_port`, a `build` command, `app_env` templates with `{serve-var}`
  and `{service.host}`/`{service.port}` substitution, and
  `[[environment.services]]` — while containment *policy* is operator
  authority: `[containers] mode = off | auto | required` (`required`
  makes containment a control a builder cannot disable by editing the
  adapter), flowing to the drive via `--containers`/`DARKROOM_CONTAINERS`.
  Container mode runs each scenario in fresh containers on a private
  network, records **image digests as evidence** (an `environment` log
  item per scenario), and closes the assess-time vector: builder-authored
  code no longer executes with the operator's UID and environment (#37)
- The `container` drive step kind (`action = stop|start|pause|unpause`
  on a declared service or the app) — failure-injection scenarios,
  captured as log evidence (#37)

## [0.9.2] - 2026-09-22

### Fixed

- `darkroom auto` checkpoints its own gate write on convergence, leaving
  a clean tree — previously the post-checkpoint `evidence-gates.json`
  update left the tenant dirty, so a following per-scenario run was
  refused by the clean-tree guard. Found by the first tenant's
  multi-scenario live slate (#34)

## [0.9.1] - 2026-09-22

### Fixed

- Scenario-scoped runs verify against a scenario-scoped contract:
  `darkroom drive --scenario X` and the loop's assessor no longer fail
  verification for scenarios the run deliberately did not attempt —
  previously making per-scenario `darkroom auto` convergence impossible
  under a multi-scenario contract. Found by the first tenant dry run (#32)

## [0.9.0] - 2026-09-21

### Added

- The intent interview as a Claude Code skill
  (`skills/darkroom-interview/`): charter elicitation, scenario
  enumeration with negative space, threshold interviews (declined
  answers become low-confidence criteria, never silent guesses), rubric
  drafting under the capturable-evidence rule, a gaming self-audit
  before presentation, full artifact writing, and mechanical validation
  via `darkroom preflight`; README documents installation (#25)
- The darkroom home (`darkroom.homedir`): `~/.darkroom` (override:
  `DARKROOM_HOME`), mode 700, partitioned per project by the adapter's
  name — operator config, vault, drives, and loop state consolidated
  outside every builder-addressable path. `darkroom home init/path`;
  `vault seal`/`derive-contract` default their `--vault` to the home;
  agent mode auto-discovers `operator.toml` from the home and its
  missing `[vault]` path falls back to the home vault (#27)

- The drive engine (`darkroom.drive`): the exam as data — declarative
  per-scenario `.drive.toml` scripts executed against the system as a
  black box, a fresh server per scenario via the adapter's `serve`
  command with health-wait, every exchange captured through the existing
  producers into an ordinary evidence manifest. Step vocabulary: `http`
  (expect/save with dot-path extraction), `command`, `keygen` (Ed25519,
  via the new `crypto` extra), `sign(...)` interpolation, `assert`
  (captured as log evidence), `wait`. A failed expectation stops its
  scenario but keeps the evidence captured before it — a failing
  scenario is still judgeable (#28)

- `darkroom drive [--scenario] [--drives]` — the exam as a CLI: runs the
  drive scripts (defaulting to the project home's `drives/`), prints
  per-step results, and verifies the produced manifest against the
  contract in the same invocation; the adapter's `test` command can now
  simply be `darkroom drive`, wiring the loop to the external exam (#29)
- The harness diagnostics pipeline, restoring the source framework's
  builder-visible test log: drive writes `harness.log` beside the
  manifest (boot outcomes and per-step results — spec-level information,
  never criteria or scores); a scenario that cannot boot is a failed
  scenario, not a failed drive (later scenarios still run); the assessor
  captures the failing test command's output tail into its notes; the
  judge prompt gains `Harness notes:` and the builder prompt gains a
  `Harness diagnostics` section read from the latest run — so an empty
  repo bootstraps from feedback alone, no seeded skeleton required (#29)
- `examples/relay-service/` — a stdlib-only example tenant with specs,
  rubrics, a derived contract, and drive scripts; exercised green by CI (#29)

### Changed

- Loop state relocated from the tenant's `.darkroom/state` to the
  project's home, closing a leak where agent-mode judge evaluations
  (scores) were readable by the builder between iterations. Agent mode
  now ignores the tenant's advisory `[defaults] state`; explicit
  `--state` still wins everywhere (#27)

## [0.8.0] - 2026-09-20

### Added

- The rubric vault (`darkroom.vault`): `RubricVault` protocol (with a
  `version` read parameter reserved for secret-manager backends) and
  `FilesystemVault` — mode-700 storage outside builder-visible paths
  with every read appended to `audit.log`. `darkroom vault seal` moves
  rubrics out of the tenant tree (move, not copy: one authority);
  `darkroom vault derive-contract [--check]` regenerates the evidence
  contract from the rubrics' evidence declarations (rubric-as-root),
  demoting the tenant contract to a drift-checked cache (#21)
- Operator configuration (`darkroom.operator`): the authority-side file —
  judge/builder models, tool allowlists, invocation command templates,
  vault location, loop policy; no default location, explicitly never in
  the tenant repo (#22)
- Agent roles (`darkroom.agents`): `AgentJudge` (vaulted rubric +
  rendered evidence + escalating feedback instructions assembled into a
  prompt; honors the hook file contract) and `AgentBuilder` (feedback +
  iteration-memory tail; diagnostic instructions, model and tool
  escalation per the dials). Access asymmetry enforced in the
  constructed command: judge add-dirs never include tenant source,
  builder add-dirs never include the vault. Invocation is a swappable
  command template defaulting to the `claude` CLI;
  `darkroom auto --operator operator.toml` runs the loop fully
  agent-driven (#22)
- End-to-end agent-mode integration test: seal → derive-contract →
  `auto --operator` convergence with fake agents honoring the real
  prompt/file contract — vault reads audited, opacity structurally
  verified (no rubric anywhere in the tenant), gates ratcheted; README
  documents the loop in both modes (#23)

## [0.7.0] - 2026-09-20

### Added

- Convergence loop (`darkroom.loop`): the source framework's `make auto`
  as a testable state machine — stagnation accounting, the three
  escalation dials (diagnostic access, model escalation, judge feedback
  specificity), rollback-to-best-checkpoint, iteration memory in
  `builder-log.md`, clean-tree precondition, typed
  `ConvergenceResult`. Roles (assess/judge/build/checkpoint) are
  injected protocols; opacity is preserved by construction (the judge
  authors builder feedback; the loop never derives it from scores) (#18)
- Loop roles darkroom owns (`darkroom.roles`): `AdapterAssessor` (runs
  the adapter's test command, locates the newest run, verifies against
  the contract) and `GitCheckpointer` (checkpoints with
  `--allow-empty`, best-ref rollback without history rewrites, change
  listing) (#18)
- Shell-hook roles (`darkroom.hooks`): `CommandJudge` and
  `CommandBuilder` invoke operator-supplied commands under a documented
  file contract (`{manifest}`/`{evaluation_out}`/`{feedback_out}`;
  `{feedback}`/`{diagnostic}`/`{escalate_model}`) — the loop is runnable
  before built-in agent roles exist, and the contract is a public
  interface those roles will honor. A judge hook that writes no
  evaluation aborts the loop: a missing score is not a zero (#19)
- `darkroom auto --judge-cmd ... --build-cmd ...`: the convergence loop
  as a CLI — live per-iteration reporting, policy via flags (operator
  authority, never the tenant file), gates ratcheted automatically on
  convergence with the winning checkpoint as the retreat point (#19)

## [0.6.0] - 2026-09-20

### Added

- Project adapter (`darkroom.adapter`): `darkroom.toml` at the tenant
  root declaring run-me facts — commands with `{placeholder}`
  substitution, evidence/contract/gates paths, spec and rubric globs,
  advisory `[defaults]`. Carries the trust rule: the file is
  builder-writable, so judging/gating/loop authority never reads from it (#15)
- Preflight (`darkroom.preflight` + `darkroom preflight [--json]`): is
  the project wired for evidence-based delivery — adapter loads, a test
  command exists, spec glob resolves, specs pair with rubrics
  (normalized-stem matching), declared contract loads (#15)
- `darkroom run <command> [--scenario] [--seed] [--capture]`: execute an
  adapter command with substitution; `--capture` records the execution
  as command-transcript evidence (#15)
- Filesystem ticketing (`darkroom.tickets`), porting the source
  framework's `state/queue|locks|history` conventions: markdown tickets
  with flat frontmatter (yaml-compatible subset, no dependency),
  `O_CREAT|O_EXCL` claim locks with stale-age detection and `force`,
  dispositions appended on resolve; CLI `darkroom ticket
  new/list/resolve` with the state dir taken from the adapter's
  `[defaults]` (#16)

## [0.5.0] - 2026-09-19

### Added

- Evaluation score model (`darkroom.evaluation`): typed
  `Evaluation`/`ScenarioEvaluation`/`CriterionResult` with derived
  totals and 0-100 percentage, evidence citations as manifest item
  paths, and `rubric_version` provenance; strict JSON round-trip plus
  lenient `coerce_evaluation`/`normalize_percentage` absorbing observed
  LLM-judge drift (0-1 scales, `overall_score`/`pass_rate` synonyms,
  mapping-or-list criteria, string numbers) (#11)
- Judge renderers (`darkroom.render`): the consuming mirror of the
  producer protocol — `RenderedEvidence` (text + attachments),
  `JudgeRenderer` protocol dispatched on item kind via a registry, and
  built-ins covering all eight kinds; unknown kinds fall back to a
  descriptive line and broken evidence files render as stated defects
  rather than raising (#12)
- The contact sheet: `darkroom gallery <manifest> [--evaluation] [--embed]
  [-o]` renders a run as a single static HTML page — image strips with
  FAILURE flagging, playable videos, collapsible text evidence, and an
  optional score overlay (per-scenario badges, criterion verdicts linked
  to cited evidence, rubric-version chip). Relative media refs by
  default; `--embed` inlines data URIs for a shareable single file (#13)
- Peak gates (`darkroom.gates`): per-scenario high-water marks carrying
  run id (evidence), commit (retreat point), and rubric version — a
  version mismatch reports `stale-peak` (re-baseline), never
  `regression`. CLI: `darkroom gate check` (exit 1 on regression) and
  `darkroom gate update [--commit]` over a committed
  `evidence-gates.json` (#14)
- Run diffing (`darkroom.rundiff` and `darkroom diff <old> <new>`):
  scenario- and item-level changes between two manifests (#14)

## [0.4.0] - 2026-09-18

### Added

- Evidence contracts (`darkroom.contract`): TOML-declared per-scenario
  capture requirements — kinds, counts, named steps, and a `trials`
  dimension for run-series checking. Deliberately a pure projection of
  what a rubric's evidence declarations could generate (#9)
- Manifest verification (`darkroom.verify`): structural checks (paths
  resolve, files non-empty, manifests parse) plus contract satisfaction
  with typed findings; multi-manifest series supported (#9)
- `tomli` as a conditional dependency on Python 3.10 only (stdlib
  `tomllib` thereafter) (#9)
- First CLI, installed as `darkroom` and the terse alias `darkrm`:
  `verify <manifest…> [--contract] [--json]` (exit 1 on errors, 2 on
  usage problems; auto-discovers `evidence-contract.toml`) and
  `show <manifest>` for a human-readable run summary (#10)

## [0.3.0] - 2026-09-18

### Added

- `HTTPTranscriptProducer` (kind `http_transcript`): performs the request
  via stdlib urllib and captures the full exchange — status, headers,
  bodies (truncation-capped), duration, connection errors — with
  sensitive headers redacted by default; plus `EvidenceCapture.http()` (#8)

- First non-browser producers: `CommandTranscriptProducer` (runs the
  command itself — exit code, stdout/stderr with truncation caps,
  duration, timeout capture), `FileSnapshotProducer` (content copy with
  sha256 and guessed mime), and `DiffProducer` (unified diff with
  added/removed line counts) (#7)
- `EvidenceCapture.command()`, `.snapshot()`, and `.diff()` convenience
  methods; new kinds use the scenario-directory layout in both modes (#7)

- `VideoProducer` (kind `video`) filing finalized recordings into the run,
  plus `EvidenceCapture.video()` with a flat screencasts-directory
  fallback — the screencast directories finally have a producer (#6)
- Producers now populate `EvidenceItem.metadata`: screenshots record
  `full_page` and the viewport, element screenshots record the `selector`,
  videos record `size_bytes` (#6)

## [0.2.0] - 2026-09-18

### Added

- Pytest plugin, auto-loaded via the `pytest11` entry point: evidence-mode
  session hooks (`start_run`/`end_run` with manifest write), the
  `evidence` fixture named from the test node, full-page screenshot on
  failure for tests using a `page` fixture, and the `darkroom_project`
  ini option (#5)
- First integration tests, driving real pytest sessions via pytester (#5)

### Changed

- `darkroom.compat` documented as legacy-only; new projects use the
  plugin (#5)

## [0.1.0] - 2026-09-18

### Added

- Apache-2.0 `LICENSE` file (#1)
- Ruff configuration and lint fixes (#1)
- GitHub Actions CI: ruff lint + test matrix over Python 3.10–3.13 (#2)
- `ROADMAP.md` and design docs: vision, rubric lifecycle, generalization
  plan (#3)
- Tag-triggered release workflow publishing to PyPI via trusted
  publishing (#4)

### Changed

- Distribution renamed to `darkroom-ai` (the bare `darkroom` name is
  squatted on PyPI); the import name remains `darkroom` (#4)

### Fixed

- `test_v1_drops_scenario_file` asserted a tautology; it now verifies the
  v1 `scenario_file` field is dropped on load and never serialized (#1)
