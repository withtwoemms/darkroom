"""Tests for the drive CLI, the shipped example, and the diagnostics pipeline."""

import shutil
import sys
from pathlib import Path

from darkroom.adapter import loads_adapter
from darkroom.cli import main
from darkroom.loop import LoopContext
from darkroom.roles import AdapterAssessor

EXAMPLE = Path(__file__).parent.parent.parent / "examples" / "relay-service"


class TestDriveCLI:
    def test_shipped_example_runs_green(self, tmp_path, capsys, monkeypatch):
        project = tmp_path / "relay-service"
        shutil.copytree(EXAMPLE, project)
        monkeypatch.chdir(project)
        monkeypatch.delenv("EVIDENCE_MODE", raising=False)
        monkeypatch.delenv("EVIDENCE_DIR", raising=False)

        assert main(["drive", "--drives", "drives"]) == 0
        out = capsys.readouterr().out
        assert "note_lifecycle:" in out and "deletion_guarded:" in out
        assert "verify: ok (contract)" in out
        assert "2/2 scenario(s) green" in out

        harness_logs = list(project.glob("evidence/runs/*/harness.log"))
        assert len(harness_logs) == 1
        assert "scenario note_lifecycle: ok" in harness_logs[0].read_text()


    def test_scenario_scoped_run_verifies_scoped_contract(
        self, tmp_path, capsys, monkeypatch
    ):
        project = tmp_path / "relay-service"
        shutil.copytree(EXAMPLE, project)
        monkeypatch.chdir(project)
        monkeypatch.delenv("EVIDENCE_MODE", raising=False)
        monkeypatch.delenv("EVIDENCE_DIR", raising=False)

        # the contract declares two scenarios; driving one must not fail
        # verification for the other
        assert main(["drive", "--drives", "drives", "--scenario", "note_lifecycle"]) == 0
        out = capsys.readouterr().out
        assert "verify: ok (contract)" in out
        assert "not present" not in out

    def test_boot_failure_is_a_failed_scenario_not_a_crash(
        self, tmp_path, capsys, monkeypatch
    ):
        root = tmp_path / "tenant"
        root.mkdir()
        (root / "darkroom.toml").write_text(
            '[project]\nname = "p"\n[commands]\nserve = "false"'
        )
        drives = tmp_path / "drives"
        drives.mkdir()
        (drives / "boots.drive.toml").write_text(
            'scenario = "boots"\n[[step]]\nname = "hit"\nkind = "http"\n'
            'url = "{base_url}/"\n'
        )
        (drives / "no_server.drive.toml").write_text(
            'scenario = "no_server"\n[[step]]\nname = "sh"\nkind = "command"\n'
            'cmd = "echo fine"\nexpect = { exit_code = 0 }\n'
        )
        monkeypatch.chdir(root)
        monkeypatch.delenv("EVIDENCE_MODE", raising=False)
        monkeypatch.delenv("EVIDENCE_DIR", raising=False)

        assert main(["drive", "--drives", str(drives)]) == 1
        out = capsys.readouterr().out
        assert "never became healthy" in out
        assert "1/2 scenario(s) green" in out  # the serverless scenario survived

        harness_log = next(root.glob("evidence/runs/*/harness.log")).read_text()
        assert "scenario boots: FAILED" in harness_log
        assert "never became healthy" in harness_log
        assert "scenario no_server: ok" in harness_log


class TestAssessorScoping:
    def test_scenario_scoped_assess_verifies_ok(self, tmp_path):
        root = tmp_path / "tenant"
        run = root / "evidence" / "runs" / "r1" / "flow"
        run.mkdir(parents=True)
        (run / "01-x.json").write_text("{}")
        (root / "evidence" / "runs" / "r1" / "manifest.json").write_text(
            '{"schema_version": "2.0", "run_id": "r1", "project": "",'
            ' "timestamp": "", "scenarios": [{"scenario": "flow", "items": ['
            '{"kind": "log", "mime": "application/json", "path": "flow/01-x.json",'
            ' "scenario": "flow", "step": "x", "captured_at": "2026-01-01T00:00:00",'
            ' "metadata": {}}]}]}'
        )
        (root / "evidence-contract.toml").write_text(
            '[[scenario]]\nname = "flow"\n[[scenario.requires]]\nkind = "log"\n'
            '[[scenario]]\nname = "other"\n[[scenario.requires]]\nkind = "log"\n'
        )
        adapter = loads_adapter(
            '[project]\nname = "p"\n[commands]\ntest = "true"\n'
            '[evidence]\ncontract = "evidence-contract.toml"',
            root=root,
        )
        scoped = AdapterAssessor().assess(
            LoopContext(adapter=adapter, scenario="flow")
        )
        assert scoped.verify_ok, scoped.notes  # "other" must not fail it

        unscoped = AdapterAssessor().assess(LoopContext(adapter=adapter))
        assert not unscoped.verify_ok  # full-contract semantics preserved


class TestAssessorDiagnostics:
    def test_failing_test_output_reaches_notes(self, tmp_path):
        root = tmp_path / "tenant"
        (root / "evidence" / "runs" / "r1").mkdir(parents=True)
        (root / "evidence" / "runs" / "r1" / "manifest.json").write_text(
            '{"schema_version": "2.0", "run_id": "r1", "project": "",'
            ' "timestamp": "", "scenarios": []}'
        )
        adapter = loads_adapter(
            '[project]\nname = "p"\n[commands]\n'
            f"test = \"{sys.executable} -c 'import sys;"
            " sys.stderr.write(chr(98)*3 + chr(111) + chr(111) + chr(109));"
            " sys.exit(3)'\"",
            root=root,
        )
        assessment = AdapterAssessor().assess(LoopContext(adapter=adapter))
        assert not assessment.tests_passed
        assert "test output:" in assessment.notes
        assert "bbboom" in assessment.notes
