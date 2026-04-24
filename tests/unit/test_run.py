"""Unit tests for EvidenceRun and module-level lifecycle functions."""

import json
from datetime import datetime
from pathlib import Path

from darkroom.model import EvidenceItem
from darkroom.run import (
    EvidenceRun,
    end_run,
    get_current_run,
    get_evidence_dir,
    is_evidence_mode,
    start_run,
)


class TestIsEvidenceMode:
    def test_true_when_set(self, monkeypatch):
        monkeypatch.setenv("EVIDENCE_MODE", "1")
        assert is_evidence_mode() is True

    def test_true_when_true_string(self, monkeypatch):
        monkeypatch.setenv("EVIDENCE_MODE", "true")
        assert is_evidence_mode() is True

    def test_true_when_yes(self, monkeypatch):
        monkeypatch.setenv("EVIDENCE_MODE", "yes")
        assert is_evidence_mode() is True

    def test_false_when_unset(self, monkeypatch):
        monkeypatch.delenv("EVIDENCE_MODE", raising=False)
        assert is_evidence_mode() is False

    def test_false_when_zero(self, monkeypatch):
        monkeypatch.setenv("EVIDENCE_MODE", "0")
        assert is_evidence_mode() is False


class TestGetEvidenceDir:
    def test_from_env(self, monkeypatch, tmp_path):
        monkeypatch.setenv("EVIDENCE_DIR", str(tmp_path / "custom"))
        assert get_evidence_dir() == tmp_path / "custom"

    def test_fallback(self, monkeypatch):
        monkeypatch.delenv("EVIDENCE_DIR", raising=False)
        result = get_evidence_dir()
        assert result == Path.cwd() / "evidence"


class TestRunLifecycle:
    def test_start_get_end(self, monkeypatch, tmp_path):
        monkeypatch.delenv("EVIDENCE_MODE", raising=False)
        monkeypatch.setenv("EVIDENCE_DIR", str(tmp_path))

        assert get_current_run() is None

        run = start_run(run_id="test-run", project="proj")
        assert get_current_run() is run
        assert run.run_id == "test-run"
        assert run.project == "proj"

        end_run()
        assert get_current_run() is None

    def test_end_run_returns_none_when_no_run(self):
        # Ensure clean state
        import darkroom.run as run_module
        run_module._current_run = None
        assert end_run() is None


class TestEvidenceRun:
    def test_creates_run_dir_in_evidence_mode(self, monkeypatch, tmp_path):
        monkeypatch.setenv("EVIDENCE_MODE", "1")
        monkeypatch.setenv("EVIDENCE_DIR", str(tmp_path))

        run = EvidenceRun(run_id="test-123")
        assert run.run_dir == tmp_path / "runs" / "test-123"
        assert run.run_dir.exists()

    def test_flat_structure_without_evidence_mode(self, monkeypatch, tmp_path):
        monkeypatch.delenv("EVIDENCE_MODE", raising=False)
        monkeypatch.setenv("EVIDENCE_DIR", str(tmp_path))

        run = EvidenceRun(run_id="test-456")
        assert run.run_dir == tmp_path
        assert (tmp_path / "screenshots").exists()
        assert (tmp_path / "screencasts").exists()

    def test_get_scenario_dir_evidence_mode(self, monkeypatch, tmp_path):
        monkeypatch.setenv("EVIDENCE_MODE", "1")
        monkeypatch.setenv("EVIDENCE_DIR", str(tmp_path))

        run = EvidenceRun(run_id="test")
        scenario_dir = run.get_scenario_dir("login_flow")
        assert scenario_dir == tmp_path / "runs" / "test" / "login_flow"
        assert scenario_dir.exists()

    def test_get_scenario_dir_non_evidence_mode(self, monkeypatch, tmp_path):
        monkeypatch.delenv("EVIDENCE_MODE", raising=False)
        monkeypatch.setenv("EVIDENCE_DIR", str(tmp_path))

        run = EvidenceRun(run_id="test")
        scenario_dir = run.get_scenario_dir("login_flow")
        assert scenario_dir == tmp_path / "screenshots"

    def test_record_evidence(self, monkeypatch, tmp_path):
        monkeypatch.setenv("EVIDENCE_MODE", "1")
        monkeypatch.setenv("EVIDENCE_DIR", str(tmp_path))

        run = EvidenceRun(run_id="test")
        item = EvidenceItem(
            kind="screenshot", mime="image/png",
            path=Path("scenario_a/01-login.png"),
            scenario="scenario_a", step="login",
            captured_at=datetime.now(),
        )
        run.record_evidence(item)

        assert len(run._manifest.scenarios) == 1
        assert run._manifest.scenarios[0].scenario == "scenario_a"
        assert len(run._manifest.scenarios[0].items) == 1

    def test_write_manifest(self, monkeypatch, tmp_path):
        monkeypatch.setenv("EVIDENCE_MODE", "1")
        monkeypatch.setenv("EVIDENCE_DIR", str(tmp_path))

        run = EvidenceRun(run_id="test-manifest", project="proj")
        item = EvidenceItem(
            kind="log", mime="application/json",
            path=Path("s/01-step.json"),
            scenario="s", step="step",
            captured_at=datetime(2026, 1, 1),
        )
        run.record_evidence(item)

        manifest_path = run.write_manifest()
        assert manifest_path is not None
        assert manifest_path.exists()

        with open(manifest_path) as f:
            data = json.load(f)
        assert data["schema_version"] == "2.0"
        assert data["run_id"] == "test-manifest"
        assert data["project"] == "proj"
        assert len(data["scenarios"]) == 1

    def test_write_manifest_returns_none_without_evidence_mode(self, monkeypatch, tmp_path):
        monkeypatch.delenv("EVIDENCE_MODE", raising=False)
        monkeypatch.setenv("EVIDENCE_DIR", str(tmp_path))

        run = EvidenceRun(run_id="test")
        assert run.write_manifest() is None

    def test_auto_generated_run_id(self, monkeypatch, tmp_path):
        monkeypatch.delenv("EVIDENCE_MODE", raising=False)
        monkeypatch.setenv("EVIDENCE_DIR", str(tmp_path))

        run = EvidenceRun()
        # Should be a timestamp-like string
        assert len(run.run_id) > 0
        assert "T" in run.run_id
