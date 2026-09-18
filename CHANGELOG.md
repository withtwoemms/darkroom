# Changelog

All notable changes to this project are documented here. The format is
based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the
project follows [semantic versioning](https://semver.org/) (pre-1.0: minor
releases may break API, patch releases never do). The manifest schema is
versioned independently of the package — see `ROADMAP.md`.

## [Unreleased]

### Added

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
