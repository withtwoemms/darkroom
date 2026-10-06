"""Unit tests never write evidence into the repository.

Without ``EVIDENCE_DIR`` the capture layer falls back to ``./evidence``
— the repo root under pytest — and a test that drives a scenario leaves
files there. Those files were once committed by accident, and CI's test
run then dirtied the tree before the release build, which stamped the
wheel a dev version. Every unit test captures under its own tmp_path;
a test that needs the fallback behaviour deletes the variable itself.
"""

import pytest


@pytest.fixture(autouse=True)
def _evidence_under_tmp_path(tmp_path, monkeypatch):
    monkeypatch.setenv("EVIDENCE_DIR", str(tmp_path / "evidence"))
