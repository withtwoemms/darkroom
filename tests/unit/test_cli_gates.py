"""Unit tests for the gate and diff CLI subcommands."""

import json
from datetime import datetime
from pathlib import Path

from darkroom.cli import main
from darkroom.evaluation import (
    CriterionResult,
    Evaluation,
    ScenarioEvaluation,
    dump_evaluation,
)
from darkroom.manifest import dump_manifest
from darkroom.model import EvidenceItem, RunManifest, ScenarioBundle


def _write_evaluation(path: Path, earned: float, run_id="r2") -> Path:
    dump_evaluation(
        Evaluation(
            run_id=run_id,
            evaluated_at=datetime(2026, 9, 19),
            rubric_version="1",
            scenarios=[
                ScenarioEvaluation(
                    scenario="flow",
                    criteria=[
                        CriterionResult(
                            criterion="c",
                            passed=earned >= 10,
                            points_earned=earned,
                            points_possible=10,
                        )
                    ],
                )
            ],
        ),
        path,
    )
    return path


class TestGateCommands:
    def test_update_then_check_ok(self, tmp_path, capsys, monkeypatch):
        monkeypatch.chdir(tmp_path)
        evaluation = _write_evaluation(tmp_path / "eval.json", earned=9)
        assert main(["gate", "update", str(evaluation), "--commit", "abc123"]) == 0
        out = capsys.readouterr().out
        assert "gates written" in out and "1 peak(s)" in out
        gates = json.loads((tmp_path / "evidence-gates.json").read_text())
        assert gates["peaks"][0]["score"] == 90.0
        assert gates["peaks"][0]["commit"] == "abc123"

        assert main(["gate", "check", str(evaluation)]) == 0
        assert "held [flow]" in capsys.readouterr().out

    def test_check_regression_exits_one(self, tmp_path, capsys, monkeypatch):
        monkeypatch.chdir(tmp_path)
        high = _write_evaluation(tmp_path / "high.json", earned=10)
        main(["gate", "update", str(high)])
        capsys.readouterr()

        low = _write_evaluation(tmp_path / "low.json", earned=6)
        assert main(["gate", "check", str(low)]) == 1
        out = capsys.readouterr().out
        assert "regression [flow]" in out and "FAILED" in out

    def test_check_without_gates_file_is_ok(self, tmp_path, capsys, monkeypatch):
        monkeypatch.chdir(tmp_path)
        evaluation = _write_evaluation(tmp_path / "eval.json", earned=9)
        assert main(["gate", "check", str(evaluation)]) == 0
        assert "ungated [flow]" in capsys.readouterr().out


class TestDiffCommand:
    def _write_manifest(self, run_dir: Path, steps) -> Path:
        run_dir.mkdir(parents=True)
        manifest_path = run_dir / "manifest.json"
        dump_manifest(
            RunManifest(
                run_id=run_dir.name,
                scenarios=[
                    ScenarioBundle(
                        scenario="flow",
                        items=[
                            EvidenceItem(
                                kind="log",
                                mime="application/json",
                                path=Path(f"flow/{step}.json"),
                                scenario="flow",
                                step=step,
                                captured_at=datetime(2026, 1, 1),
                            )
                            for step in steps
                        ],
                    )
                ],
            ),
            manifest_path,
        )
        return manifest_path

    def test_diff_reports_changes(self, tmp_path, capsys):
        old = self._write_manifest(tmp_path / "r1", ["a"])
        new = self._write_manifest(tmp_path / "r2", ["a", "b"])
        assert main(["diff", str(old), str(new)]) == 0
        out = capsys.readouterr().out
        assert "diff: r1 -> r2" in out
        assert "+ flow: log:b" in out

    def test_diff_no_changes(self, tmp_path, capsys):
        old = self._write_manifest(tmp_path / "r1", ["a"])
        new = self._write_manifest(tmp_path / "r2", ["a"])
        assert main(["diff", str(old), str(new)]) == 0
        assert "no differences" in capsys.readouterr().out
