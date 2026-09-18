"""Unit tests for EvidenceCapture backward compatibility."""

import json
from unittest.mock import MagicMock

import darkroom.run as run_module
from darkroom.capture import EvidenceCapture
from darkroom.run import EvidenceRun


class TestEvidenceCaptureLog:
    def test_log_in_evidence_mode(self, monkeypatch, tmp_path):
        monkeypatch.setenv("EVIDENCE_MODE", "1")
        monkeypatch.setenv("EVIDENCE_DIR", str(tmp_path))

        run = EvidenceRun(run_id="test-log")
        run_module._current_run = run
        try:
            capture = EvidenceCapture("my_scenario")
            path = capture.log("api_call", {"status": 200})

            assert path.exists()
            with open(path) as f:
                content = json.load(f)
            assert content["scenario"] == "my_scenario"
            assert content["step"] == "api_call"
            assert content["data"] == {"status": 200}
        finally:
            run_module._current_run = None

    def test_log_without_evidence_mode(self, monkeypatch, tmp_path):
        monkeypatch.delenv("EVIDENCE_MODE", raising=False)
        monkeypatch.setenv("EVIDENCE_DIR", str(tmp_path))
        run_module._current_run = None

        capture = EvidenceCapture("my_scenario")
        path = capture.log("step", {"key": "value"})

        assert path.exists()
        assert "screenshots" in str(path)

    def test_step_count_increments(self, monkeypatch, tmp_path):
        monkeypatch.setenv("EVIDENCE_MODE", "1")
        monkeypatch.setenv("EVIDENCE_DIR", str(tmp_path))

        run = EvidenceRun(run_id="test-count")
        run_module._current_run = run
        try:
            capture = EvidenceCapture("scenario")
            capture.log("step_a", {"a": 1})
            assert capture.step_count == 1
            capture.log("step_b", {"b": 2})
            assert capture.step_count == 2
        finally:
            run_module._current_run = None


class TestEvidenceCaptureScreenshot:
    def test_screenshot_in_evidence_mode(self, monkeypatch, tmp_path):
        monkeypatch.setenv("EVIDENCE_MODE", "1")
        monkeypatch.setenv("EVIDENCE_DIR", str(tmp_path))

        run = EvidenceRun(run_id="test-screenshot")
        run_module._current_run = run
        try:
            mock_page = MagicMock()
            capture = EvidenceCapture("login_flow")
            path = capture.screenshot(mock_page, "login_page")

            mock_page.screenshot.assert_called_once()
            call_kwargs = mock_page.screenshot.call_args
            assert call_kwargs[1]["full_page"] is False
            assert "login_page" in str(path)
        finally:
            run_module._current_run = None

    def test_screenshot_without_evidence_mode(self, monkeypatch, tmp_path):
        monkeypatch.delenv("EVIDENCE_MODE", raising=False)
        monkeypatch.setenv("EVIDENCE_DIR", str(tmp_path))
        run_module._current_run = None

        mock_page = MagicMock()
        capture = EvidenceCapture("scenario")
        path = capture.screenshot(mock_page, "step")

        mock_page.screenshot.assert_called_once()
        assert "screenshots" in str(path)

    def test_screenshot_element_returns_none_when_not_found(self, monkeypatch, tmp_path):
        monkeypatch.delenv("EVIDENCE_MODE", raising=False)
        monkeypatch.setenv("EVIDENCE_DIR", str(tmp_path))
        run_module._current_run = None

        mock_page = MagicMock()
        mock_page.query_selector.return_value = None

        capture = EvidenceCapture("scenario")
        result = capture.screenshot_element(mock_page, "step", "#missing")

        assert result is None
