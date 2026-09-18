"""Unit tests for EvidenceCapture.command/snapshot/diff in both modes."""

import json
import sys

import darkroom.run as run_module
from darkroom.capture import EvidenceCapture
from darkroom.run import EvidenceRun


class TestInEvidenceMode:
    def test_command_recorded_in_manifest(self, monkeypatch, tmp_path):
        monkeypatch.setenv("EVIDENCE_MODE", "1")
        monkeypatch.setenv("EVIDENCE_DIR", str(tmp_path))
        run = EvidenceRun(run_id="test-cmd")
        run_module._current_run = run
        try:
            capture = EvidenceCapture("build_flow")
            path = capture.command("build", [sys.executable, "-c", "print('ok')"])
            assert path.exists()
            items = run._manifest.scenarios[0].items
            assert items[0].kind == "command_transcript"
            assert items[0].metadata["exit_code"] == 0
        finally:
            run_module._current_run = None

    def test_snapshot_and_diff_recorded(self, monkeypatch, tmp_path):
        monkeypatch.setenv("EVIDENCE_MODE", "1")
        monkeypatch.setenv("EVIDENCE_DIR", str(tmp_path))
        before = tmp_path / "before.cfg"
        after = tmp_path / "after.cfg"
        before.write_text("a=1\n")
        after.write_text("a=2\n")

        run = EvidenceRun(run_id="test-snap")
        run_module._current_run = run
        try:
            capture = EvidenceCapture("config_flow")
            capture.snapshot("original", before)
            capture.diff("change", before, after)
            kinds = [i.kind for i in run._manifest.scenarios[0].items]
            assert kinds == ["file_snapshot", "diff"]
        finally:
            run_module._current_run = None


class TestOutsideEvidenceMode:
    def test_command_writes_under_evidence_dir(self, monkeypatch, tmp_path):
        monkeypatch.delenv("EVIDENCE_MODE", raising=False)
        monkeypatch.setenv("EVIDENCE_DIR", str(tmp_path))
        capture = EvidenceCapture("flow")
        path = capture.command("probe", [sys.executable, "-c", "print('ok')"])
        assert path.exists()
        assert path.parent == tmp_path / "flow"
        assert json.loads(path.read_text())["exit_code"] == 0
        # no run, so no manifest anywhere
        assert not list(tmp_path.glob("runs/*"))
