"""Dossier assembly: builder-log parsing, bundle shape, the tenant guard."""

import json
import subprocess

import pytest

from darkroom.adapter import loads_adapter
from darkroom.cli import main
from darkroom.dossier import (
    _parse_builder_log,
    assemble_dossier,
    dumps_dossier_markdown,
)

BUILDER_LOG = """\
## iteration 1 — 2026-09-22T10:00:00

scenario: pay_invoices
score: 50.0 (best 50.0) · stagnation: 0 · action: built
changed: app.py

## iteration 2 — 2026-09-22T10:05:00

scenario: pay_invoices
score: 50.0 (best 50.0) · stagnation: 1 · action: built
escalation: diagnostic
changed: app.py, db.py

## iteration 3 — 2026-09-22T10:11:00

scenario: pay_invoices
score: 100.0 (best 100.0) · stagnation: 0 · action: converged
"""

EVALUATION = {
    "run_id": "r1",
    "evaluated_at": "2026-09-22T10:04:00",
    "rubric_version": "1",
    "scenarios": [
        {
            "scenario": "pay_invoices",
            "criteria": [
                {"criterion": "settles", "passed": False,
                 "points_earned": 5, "points_possible": 10},
            ],
        },
        {
            "scenario": "other_flow",
            "criteria": [
                {"criterion": "works", "passed": True,
                 "points_earned": 10, "points_possible": 10},
            ],
        },
    ],
}


class TestParseBuilderLog:
    def test_full_entries(self):
        iterations = _parse_builder_log(BUILDER_LOG)
        assert [i["number"] for i in iterations] == [1, 2, 3]
        assert iterations[0]["scenario"] == "pay_invoices"
        assert iterations[1]["escalation"] == ["diagnostic"]
        assert iterations[1]["changed"] == ["app.py", "db.py"]
        assert iterations[2]["score"] == 100.0
        assert iterations[2]["action"] == "converged"

    def test_pre_scenario_format_still_parses(self):
        legacy = "## iteration 1 — t\n\nscore: 10.0 (best 10.0) · stagnation: 0 · action: built\n"
        iterations = _parse_builder_log(legacy)
        assert iterations[0]["score"] == 10.0
        assert "scenario" not in iterations[0]

    def test_garbage_is_tolerated(self):
        assert _parse_builder_log("random\ntext\n") == []


@pytest.fixture()
def project(tmp_path):
    root = tmp_path / "tenant"
    root.mkdir()
    adapter = loads_adapter(
        '[project]\nname = "press"\n[evidence]\ndir = "evidence"',
        root=root,
    )
    state = tmp_path / "state"
    loop = state / "loop"
    loop.mkdir(parents=True)
    (state / "builder-log.md").write_text(BUILDER_LOG)
    (loop / "evaluation-1.json").write_text(json.dumps(EVALUATION))
    (loop / "usage.jsonl").write_text(
        json.dumps({
            "role": "builder", "iteration": 1, "model": "claude-sonnet-5",
            "duration_seconds": 3.0, "recorded_at": "t",
            "input_tokens": 100, "output_tokens": 50, "cost_usd": 0.02,
            "partial": False, "scenario": "pay_invoices",
        }) + "\n"
        + json.dumps({
            "role": "judge", "iteration": 1, "model": "claude-opus-5",
            "duration_seconds": 2.0, "recorded_at": "t",
            "input_tokens": None, "output_tokens": None, "cost_usd": None,
            "partial": True, "scenario": "other_flow",
        }) + "\n"
    )
    return adapter, state


class TestAssembleDossier:
    def test_bundle_shape(self, project):
        adapter, state = project
        bundle = assemble_dossier(adapter, state)
        assert bundle["schema_version"] == "1.0"
        assert bundle["project"] == "press"
        assert len(bundle["iterations"]) == 3
        assert bundle["evaluations"][0]["rubric_version"] == "1"
        assert bundle["usage"]["totals"]["calls"] == 2
        assert bundle["usage"]["totals"]["metered_calls"] == 1
        assert bundle["usage"]["totals"]["cost_usd"] == 0.02
        assert bundle["gates"] is None  # no gates file in this tenant

    def test_scenario_scoping(self, project):
        adapter, state = project
        bundle = assemble_dossier(adapter, state, scenario="pay_invoices")
        assert all(
            i["scenario"] == "pay_invoices" for i in bundle["iterations"]
        )
        scenarios = [
            s["scenario"]
            for e in bundle["evaluations"]
            for s in e["scenarios"]
        ]
        assert scenarios == ["pay_invoices"]
        assert bundle["usage"]["totals"]["calls"] == 1

    def test_empty_state_assembles(self, tmp_path):
        root = tmp_path / "bare"
        root.mkdir()
        adapter = loads_adapter('[project]\nname = "bare"', root=root)
        bundle = assemble_dossier(adapter, tmp_path / "no-state")
        assert bundle["iterations"] == []
        assert bundle["evaluations"] == []
        assert bundle["usage"]["totals"]["calls"] == 0

    def test_markdown_render(self, project):
        adapter, state = project
        text = dumps_dossier_markdown(assemble_dossier(adapter, state))
        assert "# dossier: press" in text
        assert "failing: settles" in text
        assert "escalated: diagnostic" in text
        assert "$0.0200" in text

    def test_checkpoints_from_git(self, project):
        adapter, state = project
        subprocess.run(["git", "init", "-q"], cwd=adapter.root, check=True)
        for key, value in (
            ("user.email", "t@example.com"), ("user.name", "t"),
            ("commit.gpgsign", "false"),
        ):
            subprocess.run(
                ["git", "config", key, value], cwd=adapter.root, check=True
            )
        (adapter.root / "a.txt").write_text("x")
        subprocess.run(["git", "add", "-A"], cwd=adapter.root, check=True)
        subprocess.run(
            ["git", "commit", "-q", "-m", "auto: iteration 1 (50.0%)"],
            cwd=adapter.root, check=True,
        )
        bundle = assemble_dossier(adapter, state)
        assert bundle["checkpoints"][0]["subject"] == "auto: iteration 1 (50.0%)"


class TestDossierCli:
    def _tenant(self, tmp_path, monkeypatch):
        root = tmp_path / "tenant"
        root.mkdir()
        (root / "darkroom.toml").write_text('[project]\nname = "press"\n')
        monkeypatch.chdir(root)
        monkeypatch.setenv("DARKROOM_HOME", str(tmp_path / "home"))
        return root

    def test_stdout_markdown(self, tmp_path, monkeypatch, capsys):
        self._tenant(tmp_path, monkeypatch)
        assert main(["dossier"]) == 0
        assert "# dossier: press" in capsys.readouterr().out

    def test_refuses_output_inside_tenant(self, tmp_path, monkeypatch, capsys):
        root = self._tenant(tmp_path, monkeypatch)
        code = main(["dossier", "--out", str(root / "dossier.md")])
        assert code == 2
        assert "refusing" in capsys.readouterr().out

    def test_writes_json_outside_tenant(self, tmp_path, monkeypatch, capsys):
        self._tenant(tmp_path, monkeypatch)
        out = tmp_path / "home" / "dossier.json"
        assert main(["dossier", "--format", "json", "--out", str(out)]) == 0
        bundle = json.loads(out.read_text())
        assert bundle["schema_version"] == "1.0"
