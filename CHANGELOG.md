# Changelog

All notable changes to this project are documented here. The format is
based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the
project follows [semantic versioning](https://semver.org/) (pre-1.0: minor
releases may break API, patch releases never do). The manifest schema is
versioned independently of the package — see `ROADMAP.md`.

## [Unreleased]

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
