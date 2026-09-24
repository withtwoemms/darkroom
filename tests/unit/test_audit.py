"""The witnessability audit: static rubric-vs-drive cross-checks."""

import textwrap

from darkroom.audit import audit, has_errors, producible_kinds
from darkroom.cli import main
from darkroom.vault import FilesystemVault

RUBRIC_NEEDS_LOG = """
feature_id = "expiry"
version = "1"
scenario = "expiry"

[[criterion]]
id = "expires"
points = 10
description = "d"
evidence = ["http_transcript", "log"]
"""

DRIVE_HTTP_ONLY = """
scenario = "expiry"

[[step]]
name = "poll"
kind = "http"
url = "{base_url}/x"
"""

DRIVE_WITH_ASSERT = DRIVE_HTTP_ONLY + """
[[step]]
name = "transition"
kind = "assert"
that = "{a} == {a}"
"""


def _vault(tmp_path, rubric_text):
    root = tmp_path / "vault"
    vault = FilesystemVault(root)
    vault.initialize()
    (root / "expiry.rubric.toml").write_text(textwrap.dedent(rubric_text))
    return vault


def _drives(tmp_path, drive_text):
    d = tmp_path / "drives"
    d.mkdir(exist_ok=True)
    (d / "expiry.drive.toml").write_text(textwrap.dedent(drive_text))
    return d


class TestAudit:
    def test_unproducible_kind_is_an_error(self, tmp_path):
        findings = audit(
            _vault(tmp_path, RUBRIC_NEEDS_LOG),
            _drives(tmp_path, DRIVE_HTTP_ONLY),
        )
        assert has_errors(findings)
        assert "['log']" in findings[0].message

    def test_assert_step_makes_log_witnessable(self, tmp_path):
        findings = audit(
            _vault(tmp_path, RUBRIC_NEEDS_LOG),
            _drives(tmp_path, DRIVE_WITH_ASSERT),
        )
        assert findings == []

    def test_missing_drive_is_a_warning(self, tmp_path):
        drives = tmp_path / "drives"
        drives.mkdir()
        findings = audit(_vault(tmp_path, RUBRIC_NEEDS_LOG), drives)
        assert [f.severity for f in findings] == ["warning"]
        assert "no drive script" in findings[0].message

    def test_record_flag_produces_video(self):
        assert "video" in producible_kinds({"record": True, "step": []})
        assert producible_kinds({"step": [{"kind": "wait"}]}) == set()

    def test_browser_steps_produce_log_and_screenshot(self):
        kinds = producible_kinds(
            {"step": [{"kind": "goto"}, {"kind": "screenshot"}]}
        )
        assert kinds == {"log", "screenshot"}


class TestAuditCli:
    def test_cli_reports_and_exits_nonzero(self, tmp_path, capsys, monkeypatch):
        root = tmp_path / "tenant"
        root.mkdir()
        (root / "darkroom.toml").write_text('[project]\nname = "press"\n')
        home = tmp_path / "home"
        monkeypatch.setenv("DARKROOM_HOME", str(home))
        project = home / "projects" / "press"
        (project / "drives").mkdir(parents=True)
        (project / "drives" / "expiry.drive.toml").write_text(
            textwrap.dedent(DRIVE_HTTP_ONLY)
        )
        vault = FilesystemVault(project / "vault")
        vault.initialize()
        (project / "vault" / "expiry.rubric.toml").write_text(
            textwrap.dedent(RUBRIC_NEEDS_LOG)
        )
        (project / "operator.toml").write_text('[judge]\nmodel = "m"\n')
        monkeypatch.chdir(root)

        assert main(["audit"]) == 1
        out = capsys.readouterr().out
        assert "error [expiry]" in out and "audit: 1 error(s)" in out

    def test_cli_clean_vault_exits_zero(self, tmp_path, capsys, monkeypatch):
        root = tmp_path / "tenant"
        root.mkdir()
        (root / "darkroom.toml").write_text('[project]\nname = "press"\n')
        home = tmp_path / "home"
        monkeypatch.setenv("DARKROOM_HOME", str(home))
        project = home / "projects" / "press"
        (project / "drives").mkdir(parents=True)
        (project / "drives" / "expiry.drive.toml").write_text(
            textwrap.dedent(DRIVE_WITH_ASSERT)
        )
        vault = FilesystemVault(project / "vault")
        vault.initialize()
        (project / "vault" / "expiry.rubric.toml").write_text(
            textwrap.dedent(RUBRIC_NEEDS_LOG)
        )
        (project / "operator.toml").write_text('[judge]\nmodel = "m"\n')
        monkeypatch.chdir(root)

        assert main(["audit"]) == 0
        assert "every criterion is witnessable" in capsys.readouterr().out
