"""Unit tests for EvidenceCapture.video in both modes."""

import darkroom.run as run_module
from darkroom.capture import EvidenceCapture
from darkroom.run import EvidenceRun


class TestVideoInEvidenceMode:
    def test_video_recorded_in_run(self, monkeypatch, tmp_path):
        monkeypatch.setenv("EVIDENCE_MODE", "1")
        monkeypatch.setenv("EVIDENCE_DIR", str(tmp_path))
        source = tmp_path / "raw.webm"
        source.write_bytes(b"v")

        run = EvidenceRun(run_id="test-video")
        run_module._current_run = run
        try:
            capture = EvidenceCapture("flow")
            path = capture.video("walkthrough", source)
            assert path.exists()
            assert not source.exists()
            bundle = run._manifest.scenarios[0]
            assert bundle.items[0].kind == "video"
            assert bundle.items[0].step == "walkthrough"
        finally:
            run_module._current_run = None


class TestVideoFallback:
    def test_video_lands_in_screencasts(self, monkeypatch, tmp_path):
        monkeypatch.delenv("EVIDENCE_MODE", raising=False)
        monkeypatch.setenv("EVIDENCE_DIR", str(tmp_path))
        source = tmp_path / "raw.webm"
        source.write_bytes(b"v")

        capture = EvidenceCapture("flow")
        path = capture.video("walkthrough", source)
        assert path.parent == tmp_path / "screencasts"
        assert "flow" in path.name and "walkthrough" in path.name
        assert path.suffix == ".webm"
        assert path.exists()

    def test_keep_source_copies_in_fallback(self, monkeypatch, tmp_path):
        monkeypatch.delenv("EVIDENCE_MODE", raising=False)
        monkeypatch.setenv("EVIDENCE_DIR", str(tmp_path))
        source = tmp_path / "raw.webm"
        source.write_bytes(b"v")

        capture = EvidenceCapture("flow")
        path = capture.video("walkthrough", source, keep_source=True)
        assert source.exists() and path.exists()
