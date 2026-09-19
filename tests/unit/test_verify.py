"""Unit tests for manifest verification."""

from datetime import datetime
from pathlib import Path

from darkroom.contract import loads_contract
from darkroom.manifest import dump_manifest
from darkroom.model import EvidenceItem, RunManifest, ScenarioBundle
from darkroom.verify import verify


def _make_run(run_dir: Path, scenario: str, items: list[tuple[str, str]]) -> Path:
    """Write a run dir with real item files; items are (kind, step) pairs."""
    run_dir.mkdir(parents=True, exist_ok=True)
    bundle = ScenarioBundle(scenario=scenario, items=[])
    for index, (kind, step) in enumerate(items, start=1):
        rel = Path(scenario) / f"{index:02d}-{step}.bin"
        abs_path = run_dir / rel
        abs_path.parent.mkdir(parents=True, exist_ok=True)
        abs_path.write_bytes(b"content")
        bundle.add(
            EvidenceItem(
                kind=kind,
                mime="application/octet-stream",
                path=rel,
                scenario=scenario,
                step=step,
                captured_at=datetime(2026, 1, 1),
            )
        )
    manifest_path = run_dir / "manifest.json"
    dump_manifest(
        RunManifest(run_id=run_dir.name, scenarios=[bundle]), manifest_path
    )
    return manifest_path


CONTRACT = loads_contract(
    """
[[scenario]]
name = "approve_flow"

  [[scenario.requires]]
  kind = "screenshot"
  min_count = 2
  steps = ["before", "after"]
"""
)


class TestStructural:
    def test_clean_manifest_passes(self, tmp_path):
        manifest = _make_run(tmp_path / "r1", "approve_flow", [("log", "state")])
        result = verify([manifest])
        assert result.ok and not result.findings

    def test_unresolved_path_is_error(self, tmp_path):
        manifest = _make_run(tmp_path / "r1", "approve_flow", [("log", "state")])
        (tmp_path / "r1" / "approve_flow" / "01-state.bin").unlink()
        result = verify([manifest])
        assert not result.ok
        assert result.errors[0].code == "unresolved-path"

    def test_empty_file_is_error(self, tmp_path):
        manifest = _make_run(tmp_path / "r1", "approve_flow", [("log", "state")])
        (tmp_path / "r1" / "approve_flow" / "01-state.bin").write_bytes(b"")
        result = verify([manifest])
        assert result.errors[0].code == "empty-file"

    def test_unreadable_manifest_is_parse_error(self, tmp_path):
        bad = tmp_path / "manifest.json"
        bad.write_text("{not json")
        result = verify([bad])
        assert result.errors[0].code == "parse-error"


class TestContractSatisfaction:
    def test_satisfied_contract(self, tmp_path):
        manifest = _make_run(
            tmp_path / "r1",
            "approve_flow",
            [("screenshot", "before"), ("screenshot", "after")],
        )
        result = verify([manifest], CONTRACT)
        assert result.ok

    def test_missing_kind_count(self, tmp_path):
        manifest = _make_run(
            tmp_path / "r1", "approve_flow", [("screenshot", "before")]
        )
        result = verify([manifest], CONTRACT)
        codes = [f.code for f in result.errors]
        assert codes.count("unsatisfied-requirement") == 2  # count + missing step
        messages = " ".join(f.message for f in result.errors)
        assert "found 1" in messages and "missing step 'after'" in messages

    def test_missing_scenario(self, tmp_path):
        manifest = _make_run(tmp_path / "r1", "other_flow", [("log", "x")])
        result = verify([manifest], CONTRACT)
        assert any(f.code == "missing-scenario" for f in result.errors)

    def test_uncontracted_scenario_is_warning(self, tmp_path):
        manifest = _make_run(
            tmp_path / "r1",
            "approve_flow",
            [("screenshot", "before"), ("screenshot", "after")],
        )
        extra = _make_run(tmp_path / "r2", "surprise_flow", [("log", "x")])
        result = verify([manifest, extra], CONTRACT)
        assert result.ok  # warnings do not fail verification
        assert any(
            f.code == "uncontracted-scenario" and f.scenario == "surprise_flow"
            for f in result.warnings
        )


class TestTrials:
    TRIALS_CONTRACT = loads_contract(
        """
[[scenario]]
name = "partition_recovery"

  [[scenario.requires]]
  kind = "command_transcript"
  trials = 2
"""
    )

    def _series(self, tmp_path, satisfied_runs: int, total: int):
        paths = []
        for n in range(total):
            items = (
                [("command_transcript", "trial")] if n < satisfied_runs else []
            )
            paths.append(
                _make_run(tmp_path / f"r{n}", "partition_recovery", items)
            )
        return paths

    def test_enough_trials(self, tmp_path):
        result = verify(self._series(tmp_path, 2, 3), self.TRIALS_CONTRACT)
        assert result.ok

    def test_insufficient_trials(self, tmp_path):
        result = verify(self._series(tmp_path, 1, 3), self.TRIALS_CONTRACT)
        finding = next(f for f in result.errors if f.code == "insufficient-trials")
        assert "1/3 runs" in finding.message
        assert "needs 2" in finding.message
