# Changelog

All notable changes to this project are documented here. The format is
based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the
project follows [semantic versioning](https://semver.org/) (pre-1.0: minor
releases may break API, patch releases never do). The manifest schema is
versioned independently of the package — see `ROADMAP.md`.

## [Unreleased]

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
