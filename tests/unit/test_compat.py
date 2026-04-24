"""Unit tests for legacy compatibility functions."""

import re

from darkroom.compat import ensure_dirs, timestamp


class TestEnsureDirs:
    def test_creates_directories(self, monkeypatch, tmp_path):
        import darkroom.compat as compat_module

        monkeypatch.setattr(compat_module, "SCREENSHOTS_DIR", tmp_path / "screenshots")
        monkeypatch.setattr(compat_module, "SCREENCASTS_DIR", tmp_path / "screencasts")
        monkeypatch.setattr(compat_module, "LOGS_DIR", tmp_path / "logs")

        ensure_dirs()

        assert (tmp_path / "screenshots").exists()
        assert (tmp_path / "screencasts").exists()
        assert (tmp_path / "logs").exists()


class TestTimestamp:
    def test_format(self):
        ts = timestamp()
        assert re.match(r"\d{8}-\d{6}", ts)
