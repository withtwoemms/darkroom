"""Pytest plugin wiring darkroom's run lifecycle into test sessions.

Auto-loaded via the ``pytest11`` entry point once darkroom-ai is
installed. The session hooks act only in evidence mode (``EVIDENCE_MODE``
set), so having the package installed leaves ordinary test runs
untouched; the ``evidence`` fixture and the failure screenshot work in
either mode, falling back to flat capture directories outside a run.

Replaces the hand-wired conftest.py hooks the original pilot project
carried; ``darkroom.compat`` remains only for that legacy caller.
"""

from __future__ import annotations

import contextlib

import pytest

from darkroom.capture import EvidenceCapture
from darkroom.run import end_run, is_evidence_mode, start_run


def _scenario_name(node_name: str) -> str:
    return node_name.replace("test_", "")


def pytest_addoption(parser):
    parser.addini(
        "darkroom_project",
        help="project name recorded in the evidence manifest",
        default="",
    )


def pytest_sessionstart(session):
    if is_evidence_mode():
        run = start_run(project=session.config.getini("darkroom_project"))
        print(f"\n[evidence] Starting run: {run.run_id}")
        print(f"[evidence] Run directory: {run.run_dir}")


def pytest_sessionfinish(session, exitstatus):
    if is_evidence_mode():
        manifest_path = end_run()
        if manifest_path:
            print(f"\n[evidence] Manifest written: {manifest_path}")


@pytest.fixture
def evidence(request) -> EvidenceCapture:
    """Evidence capture helper scoped to the current test's scenario.

    Usage::

        def test_login_flow(page, evidence):
            evidence.screenshot(page, "login_page")
            evidence.log("api_response", {"status": 200})
    """
    return EvidenceCapture(_scenario_name(request.node.name))


@pytest.hookimpl(tryfirst=True, hookwrapper=True)
def pytest_runtest_makereport(item, call):
    """Capture a full-page screenshot when a test with a page fixture fails."""
    outcome = yield
    report = outcome.get_result()

    if report.when == "call" and report.failed:
        page = item.funcargs.get("page")
        if page is not None:
            # evidence capture must never mask the original test failure
            with contextlib.suppress(Exception):
                EvidenceCapture(_scenario_name(item.name)).screenshot(
                    page, "FAILURE", full_page=True
                )
