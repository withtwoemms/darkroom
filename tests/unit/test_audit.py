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


def _proof(where, rubric_text, exposure_text, scenario="expiry"):
    folder = where / scenario
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "exposure.toml").write_text(textwrap.dedent(exposure_text))
    (folder / "rubric.toml").write_text(textwrap.dedent(rubric_text))
    return folder


def _vault(tmp_path, rubric_text, exposure_text):
    """A vault whose proofs hold one scenario; returns (vault, proofs dir)."""
    proofs = tmp_path / "proofs"
    _proof(proofs, rubric_text, exposure_text)
    vault = FilesystemVault(tmp_path / "vault", proofs=proofs)
    vault.initialize()
    return vault, proofs


class TestAudit:
    def test_unproducible_kind_is_an_error(self, tmp_path):
        findings = audit(*_vault(tmp_path, RUBRIC_NEEDS_LOG, DRIVE_HTTP_ONLY))
        assert has_errors(findings)
        assert "['log']" in findings[0].message

    def test_assert_step_makes_log_witnessable(self, tmp_path):
        findings = audit(*_vault(tmp_path, RUBRIC_NEEDS_LOG, DRIVE_WITH_ASSERT))
        assert findings == []

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
        _proof(project / "proofs", RUBRIC_NEEDS_LOG, DRIVE_HTTP_ONLY)
        (project / "operator.toml").write_text('[judge]\nmodel = "m"\n')
        monkeypatch.chdir(root)

        assert main(["audit"]) == 1
        out = capsys.readouterr().out
        assert "expiry:" in out and "  error:" in out
        assert "audit: 1 error(s)" in out and "by code:" in out

    def test_cli_clean_vault_exits_zero(self, tmp_path, capsys, monkeypatch):
        root = tmp_path / "tenant"
        root.mkdir()
        (root / "darkroom.toml").write_text('[project]\nname = "press"\n')
        home = tmp_path / "home"
        monkeypatch.setenv("DARKROOM_HOME", str(home))
        project = home / "projects" / "press"
        _proof(project / "proofs", RUBRIC_NEEDS_LOG, DRIVE_WITH_ASSERT)
        (project / "operator.toml").write_text('[judge]\nmodel = "m"\n')
        monkeypatch.chdir(root)

        assert main(["audit"]) == 0
        assert "every criterion is witnessable" in capsys.readouterr().out


RUBRIC_CITES = """
feature_id = "expiry"
version = "1"
scenario = "expiry"

[[criterion]]
id = "expires"
points = 10
description = "d"
evidence = ["log"]
witnesses = ["transition"]
"""

DRIVE_GOTO_BARE = """
scenario = "expiry"

[[step]]
name = "transition"
kind = "goto"
url = "{base_url}/x"
"""

DRIVE_GOTO_EXPECT = DRIVE_GOTO_BARE + """expect = { body_contains = "x" }
"""


class TestWitnessCitations:
    def test_cited_assert_is_a_witness(self, tmp_path):
        findings = audit(*_vault(tmp_path, RUBRIC_CITES, DRIVE_WITH_ASSERT))
        assert findings == []

    def test_missing_cited_step_is_an_error(self, tmp_path):
        findings = audit(*_vault(tmp_path, RUBRIC_CITES, DRIVE_HTTP_ONLY))
        assert has_errors(findings)
        assert "witness 'transition'" in findings[-1].message

    def test_bare_goto_cannot_be_a_witness(self, tmp_path):
        findings = audit(*_vault(tmp_path, RUBRIC_CITES, DRIVE_GOTO_BARE))
        assert has_errors(findings)
        assert "leaves no record" in findings[-1].message

    def test_goto_with_expect_is_a_witness(self, tmp_path):
        findings = audit(*_vault(tmp_path, RUBRIC_CITES, DRIVE_GOTO_EXPECT))
        assert findings == []

    def test_expect_makes_log_producible(self):
        assert "log" in producible_kinds(
            {"step": [{"kind": "http", "expect": {"status": 200}}]}
        )
