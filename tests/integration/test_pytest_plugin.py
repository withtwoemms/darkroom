"""End-to-end tests of the pytest plugin.

Each test drives a real pytest session in a subprocess via pytester, so
the plugin loads through its ``pytest11`` entry point exactly as it does
for an installed user, and the inner session owns its module-global run
state without touching this (outer) session's.
"""

import json


def _fake_page_conftest() -> str:
    """A conftest defining a playwright-free stand-in for the page fixture."""
    return """
        import pytest

        class FakePage:
            def screenshot(self, path, full_page=False):
                from pathlib import Path
                Path(path).parent.mkdir(parents=True, exist_ok=True)
                Path(path).write_bytes(b"png-bytes")

        @pytest.fixture
        def page():
            return FakePage()
    """


class TestEvidenceFixture:
    def test_fixture_is_registered_and_names_scenario(self, pytester):
        pytester.makepyfile(
            """
            def test_login_flow(evidence):
                assert evidence.scenario == "login_flow"
            """
        )
        result = pytester.runpytest_subprocess()
        result.assert_outcomes(passed=1)


class TestEvidenceModeSession:
    def test_run_lifecycle_writes_manifest(self, pytester, monkeypatch):
        evidence_dir = pytester.path / "evidence"
        monkeypatch.setenv("EVIDENCE_MODE", "1")
        monkeypatch.setenv("EVIDENCE_DIR", str(evidence_dir))
        pytester.makepyfile(
            """
            def test_checkout(evidence):
                evidence.log("cart_state", {"items": 2})
            """
        )
        result = pytester.runpytest_subprocess()
        result.assert_outcomes(passed=1)
        assert "[evidence] Starting run:" in result.stdout.str()
        assert "[evidence] Manifest written:" in result.stdout.str()

        manifests = list(evidence_dir.glob("runs/*/manifest.json"))
        assert len(manifests) == 1
        manifest = json.loads(manifests[0].read_text())
        assert manifest["schema_version"] == "2.0"
        scenarios = {b["scenario"] for b in manifest["scenarios"]}
        assert scenarios == {"checkout"}
        item = manifest["scenarios"][0]["items"][0]
        assert item["kind"] == "log"
        assert item["step"] == "cart_state"
        assert (manifests[0].parent / item["path"]).exists()

    def test_project_name_from_ini(self, pytester, monkeypatch):
        evidence_dir = pytester.path / "evidence"
        monkeypatch.setenv("EVIDENCE_MODE", "1")
        monkeypatch.setenv("EVIDENCE_DIR", str(evidence_dir))
        pytester.makeini(
            """
            [pytest]
            darkroom_project = bookbinder
            """
        )
        pytester.makepyfile(
            """
            def test_anything(evidence):
                evidence.log("step", {"ok": True})
            """
        )
        result = pytester.runpytest_subprocess()
        result.assert_outcomes(passed=1)
        manifest = json.loads(
            next(evidence_dir.glob("runs/*/manifest.json")).read_text()
        )
        assert manifest["project"] == "bookbinder"

    def test_failure_screenshot_recorded_in_manifest(self, pytester, monkeypatch):
        evidence_dir = pytester.path / "evidence"
        monkeypatch.setenv("EVIDENCE_MODE", "1")
        monkeypatch.setenv("EVIDENCE_DIR", str(evidence_dir))
        pytester.makeconftest(_fake_page_conftest())
        pytester.makepyfile(
            """
            def test_broken_flow(page):
                assert False
            """
        )
        result = pytester.runpytest_subprocess()
        result.assert_outcomes(failed=1)

        manifest_path = next(evidence_dir.glob("runs/*/manifest.json"))
        manifest = json.loads(manifest_path.read_text())
        items = manifest["scenarios"][0]["items"]
        assert manifest["scenarios"][0]["scenario"] == "broken_flow"
        assert items[0]["kind"] == "screenshot"
        assert items[0]["step"] == "FAILURE"
        assert (manifest_path.parent / items[0]["path"]).exists()


class TestOutsideEvidenceMode:
    def test_session_hooks_stay_silent(self, pytester, monkeypatch):
        monkeypatch.delenv("EVIDENCE_MODE", raising=False)
        monkeypatch.delenv("EVIDENCE_DIR", raising=False)
        pytester.makepyfile(
            """
            def test_plain():
                assert True
            """
        )
        result = pytester.runpytest_subprocess()
        result.assert_outcomes(passed=1)
        assert "[evidence]" not in result.stdout.str()
        assert not (pytester.path / "evidence").exists()

    def test_capture_falls_back_to_flat_dirs(self, pytester, monkeypatch):
        monkeypatch.delenv("EVIDENCE_MODE", raising=False)
        monkeypatch.setenv("EVIDENCE_DIR", str(pytester.path / "evidence"))
        pytester.makepyfile(
            """
            def test_notes(evidence):
                path = evidence.log("api_state", {"status": 200})
                assert path.exists()
            """
        )
        result = pytester.runpytest_subprocess()
        result.assert_outcomes(passed=1)
        assert not list((pytester.path / "evidence").glob("runs/*"))

    def test_failure_screenshot_still_captured(self, pytester, monkeypatch):
        monkeypatch.delenv("EVIDENCE_MODE", raising=False)
        monkeypatch.setenv("EVIDENCE_DIR", str(pytester.path / "evidence"))
        pytester.makeconftest(_fake_page_conftest())
        pytester.makepyfile(
            """
            def test_broken(page):
                assert False
            """
        )
        result = pytester.runpytest_subprocess()
        result.assert_outcomes(failed=1)
        shots = list((pytester.path / "evidence" / "screenshots").glob("*FAILURE*"))
        assert len(shots) == 1
