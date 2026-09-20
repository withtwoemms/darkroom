"""Unit tests for the project adapter and preflight."""

from pathlib import Path

import pytest

from darkroom.adapter import find_adapter, loads_adapter
from darkroom.preflight import preflight

FULL_ADAPTER = """
schema_version = "1.0"

[project]
name = "bookbinder"

[commands]
build = "make build"
test = "EVIDENCE_MODE=1 pytest -k {scenario}"

[evidence]
dir = "proof"
contract = "evidence-contract.toml"
gates = "gates.json"

[scenarios]
spec_glob = "scenarios/*.feature"
rubric_glob = "scenarios/*.rubric.toml"

[defaults]
trials = 3
"""


class TestAdapterModel:
    def test_full_document(self, tmp_path):
        adapter = loads_adapter(FULL_ADAPTER, root=tmp_path)
        assert adapter.name == "bookbinder"
        assert adapter.evidence_dir == Path("proof")
        assert adapter.gates_path == Path("gates.json")
        assert adapter.defaults == {"trials": 3}
        assert adapter.resolve(adapter.evidence_dir) == tmp_path / "proof"

    def test_defaults(self, tmp_path):
        adapter = loads_adapter('[project]\nname = "p"', root=tmp_path)
        assert adapter.evidence_dir == Path("evidence")
        assert adapter.contract_path is None
        assert adapter.spec_glob == ""

    def test_missing_name_rejected(self, tmp_path):
        with pytest.raises(ValueError, match="missing"):
            loads_adapter("[commands]\ntest = 'x'", root=tmp_path)

    def test_empty_command_rejected(self, tmp_path):
        with pytest.raises(ValueError, match="non-empty"):
            loads_adapter('[project]\nname = "p"\n[commands]\ntest = ""', root=tmp_path)

    def test_command_substitution(self, tmp_path):
        adapter = loads_adapter(FULL_ADAPTER, root=tmp_path)
        assert (
            adapter.command("test", scenario="approve_flow")
            == "EVIDENCE_MODE=1 pytest -k approve_flow"
        )

    def test_missing_substitution_named(self, tmp_path):
        adapter = loads_adapter(FULL_ADAPTER, root=tmp_path)
        with pytest.raises(ValueError, match=r"\{scenario\}"):
            adapter.command("test")

    def test_unknown_command(self, tmp_path):
        adapter = loads_adapter(FULL_ADAPTER, root=tmp_path)
        with pytest.raises(KeyError, match="deploy"):
            adapter.command("deploy")

    def test_find_adapter_walks_up(self, tmp_path):
        (tmp_path / "darkroom.toml").write_text('[project]\nname = "p"')
        nested = tmp_path / "src" / "deep"
        nested.mkdir(parents=True)
        assert find_adapter(nested) == tmp_path / "darkroom.toml"

    def test_find_adapter_none(self, tmp_path):
        assert find_adapter(tmp_path) is None


def _project(tmp_path, adapter_text=FULL_ADAPTER, specs=(), rubrics=(), contract=True):
    (tmp_path / "darkroom.toml").write_text(adapter_text)
    scenario_dir = tmp_path / "scenarios"
    scenario_dir.mkdir(exist_ok=True)
    for name in specs:
        (scenario_dir / name).write_text("Feature: x")
    for name in rubrics:
        (scenario_dir / name).write_text("")
    if contract:
        (tmp_path / "evidence-contract.toml").write_text(
            '[[scenario]]\nname = "s"\n[[scenario.requires]]\nkind = "log"'
        )
    return tmp_path / "darkroom.toml"


class TestPreflight:
    def test_wired_project_passes(self, tmp_path):
        adapter = _project(
            tmp_path,
            specs=["staff_login.feature"],
            rubrics=["staff-login.rubric.toml"],
        )
        result = preflight(adapter)
        assert result.ok, [f.message for f in result.errors]
        assert not result.warnings

    def test_normalized_stem_pairing(self, tmp_path):
        # underscore spec pairs with dash rubric (source-framework convention)
        adapter = _project(
            tmp_path,
            specs=["pay_invoices.feature"],
            rubrics=["pay-invoices.rubric.toml"],
        )
        assert preflight(adapter).ok

    def test_missing_test_command_is_error(self, tmp_path):
        adapter = _project(
            tmp_path,
            adapter_text='[project]\nname = "p"\n[commands]\nbuild = "make"',
            contract=False,
        )
        result = preflight(adapter)
        assert any(f.code == "missing-command" for f in result.errors)

    def test_no_specs_is_error(self, tmp_path):
        adapter = _project(tmp_path, specs=[])
        result = preflight(adapter)
        assert any(f.code == "no-specs" for f in result.errors)

    def test_unpaired_spec_is_warning(self, tmp_path):
        adapter = _project(tmp_path, specs=["lonely.feature"], rubrics=[])
        result = preflight(adapter)
        assert result.ok  # warnings only
        codes = {f.code for f in result.warnings}
        assert "unpaired-spec" in codes

    def test_declared_missing_contract_is_error(self, tmp_path):
        adapter = _project(
            tmp_path,
            specs=["a.feature"],
            rubrics=["a.rubric.toml"],
            contract=False,
        )
        result = preflight(adapter)
        assert any(f.code == "missing-contract" for f in result.errors)

    def test_unparseable_contract_is_error(self, tmp_path):
        adapter = _project(
            tmp_path, specs=["a.feature"], rubrics=["a.rubric.toml"], contract=False
        )
        (tmp_path / "evidence-contract.toml").write_text("[[scenario]]\n")  # no name
        result = preflight(adapter)
        assert any(f.code == "contract-error" for f in result.errors)

    def test_unloadable_adapter(self, tmp_path):
        bad = tmp_path / "darkroom.toml"
        bad.write_text("[project")
        result = preflight(bad)
        assert any(f.code == "adapter-error" for f in result.errors)


class TestPreflightAndRunCLI:
    def test_preflight_cli(self, tmp_path, capsys, monkeypatch):
        _project(tmp_path, specs=["a.feature"], rubrics=["a.rubric.toml"])
        monkeypatch.chdir(tmp_path)
        from darkroom.cli import main

        assert main(["preflight"]) == 0
        assert "ok:" in capsys.readouterr().out
        assert main(["preflight", "--json"]) == 0
        import json as json_module

        assert json_module.loads(capsys.readouterr().out)["ok"] is True

    def test_run_executes_command(self, tmp_path, monkeypatch):
        (tmp_path / "darkroom.toml").write_text(
            '[project]\nname = "p"\n[commands]\ntouchit = "touch made-{scenario}.txt"'
        )
        monkeypatch.chdir(tmp_path)
        from darkroom.cli import main

        assert main(["run", "touchit", "--scenario", "x"]) == 0
        assert (tmp_path / "made-x.txt").exists()

    def test_run_propagates_exit_code(self, tmp_path, monkeypatch):
        (tmp_path / "darkroom.toml").write_text(
            '[project]\nname = "p"\n[commands]\nfail = "exit 7"'
        )
        monkeypatch.chdir(tmp_path)
        from darkroom.cli import main

        assert main(["run", "fail"]) == 7

    def test_run_missing_placeholder(self, tmp_path, capsys, monkeypatch):
        (tmp_path / "darkroom.toml").write_text(
            '[project]\nname = "p"\n[commands]\ntest = "pytest -k {scenario}"'
        )
        monkeypatch.chdir(tmp_path)
        from darkroom.cli import main

        assert main(["run", "test"]) == 2
        assert "{scenario}" in capsys.readouterr().out

    def test_run_capture_writes_transcript(self, tmp_path, capsys, monkeypatch):
        (tmp_path / "darkroom.toml").write_text(
            '[project]\nname = "p"\n[commands]\nsay = "echo hello"'
        )
        monkeypatch.chdir(tmp_path)
        monkeypatch.setenv("EVIDENCE_DIR", str(tmp_path / "evidence"))
        monkeypatch.delenv("EVIDENCE_MODE", raising=False)
        from darkroom.cli import main

        assert main(["run", "say", "--capture"]) == 0
        out = capsys.readouterr().out
        assert "transcript:" in out
        import json as json_module

        transcript_path = Path(out.split("transcript: ")[1].strip())
        transcript = json_module.loads(transcript_path.read_text())
        assert transcript["stdout"].strip() == "hello"
