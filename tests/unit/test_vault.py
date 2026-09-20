"""Unit tests for the rubric vault: sealing, audited reads, derivation."""

import pytest

from darkroom.adapter import loads_adapter
from darkroom.cli import main
from darkroom.contract import loads_contract
from darkroom.vault import (
    FilesystemVault,
    RubricVault,
    VaultError,
    derive_contract,
    dumps_contract,
    seal,
)

RUBRIC = """
feature_id = "pay-invoices"
version = "2"
scenario = "pay_invoices"

[[criterion]]
id = "invoice_settles"
points = 30
description = "settlement is recorded"
evidence = ["http_transcript", "log"]

[[criterion]]
id = "receipt_visible"
points = 10
description = "receipt renders"
evidence = ["screenshot", "log"]
"""


def _vault_with(tmp_path, rubrics: dict) -> FilesystemVault:
    vault = FilesystemVault(tmp_path / "vault")
    vault.initialize()
    for feature_id, text in rubrics.items():
        (vault.root / f"{feature_id}.rubric.toml").write_text(text)
    return vault


class TestFilesystemVault:
    def test_list_and_read(self, tmp_path):
        vault = _vault_with(tmp_path, {"pay-invoices": RUBRIC})
        assert isinstance(vault, RubricVault)
        assert vault.list() == ["pay-invoices"]
        assert "invoice_settles" in vault.read("pay-invoices")

    def test_reads_are_audited(self, tmp_path):
        vault = _vault_with(tmp_path, {"pay-invoices": RUBRIC})
        vault.read("pay-invoices")
        vault.read("pay-invoices", version="2")
        audit = (vault.root / "audit.log").read_text()
        assert audit.count("read pay-invoices") == 2
        assert "version=current" in audit and "version=2" in audit

    def test_missing_rubric(self, tmp_path):
        vault = _vault_with(tmp_path, {})
        with pytest.raises(VaultError, match="no rubric"):
            vault.read("ghost")

    def test_version_mismatch_refused(self, tmp_path):
        vault = _vault_with(tmp_path, {"pay-invoices": RUBRIC})
        with pytest.raises(VaultError, match="version '2', not '1'"):
            vault.read("pay-invoices", version="1")

    def test_permissions_tightened(self, tmp_path):
        vault = FilesystemVault(tmp_path / "vault")
        vault.initialize()
        assert (vault.root.stat().st_mode & 0o777) == 0o700


class TestSeal:
    def _tenant(self, tmp_path):
        root = tmp_path / "tenant"
        (root / "scenarios").mkdir(parents=True)
        (root / "scenarios" / "pay-invoices.rubric.toml").write_text(RUBRIC)
        (root / "scenarios" / "pay_invoices.feature").write_text("Feature: x")
        return loads_adapter(
            '[project]\nname = "p"\n[scenarios]\n'
            'spec_glob = "scenarios/*.feature"\n'
            'rubric_glob = "scenarios/*.rubric.toml"',
            root=root,
        )

    def test_moves_rubrics_out_of_tenant(self, tmp_path):
        adapter = self._tenant(tmp_path)
        vault = FilesystemVault(tmp_path / "vault")
        sealed = seal(adapter, vault)
        assert sealed == ["pay-invoices"]
        assert not list((adapter.root / "scenarios").glob("*.rubric.toml"))
        assert vault.list() == ["pay-invoices"]
        assert "sealed 1 rubric(s)" in (vault.root / "audit.log").read_text()

    def test_specs_stay(self, tmp_path):
        adapter = self._tenant(tmp_path)
        seal(adapter, FilesystemVault(tmp_path / "vault"))
        assert (adapter.root / "scenarios" / "pay_invoices.feature").exists()

    def test_nothing_to_seal(self, tmp_path):
        adapter = self._tenant(tmp_path)
        seal(adapter, FilesystemVault(tmp_path / "vault"))
        with pytest.raises(VaultError, match="nothing to seal"):
            seal(adapter, FilesystemVault(tmp_path / "vault2"))


class TestDeriveContract:
    def test_rubric_as_root(self, tmp_path):
        vault = _vault_with(tmp_path, {"pay-invoices": RUBRIC})
        contract = derive_contract(vault, project="press")
        assert contract.project == "press"
        scenario = contract.for_scenario("pay_invoices")  # from rubric's field
        kinds = [r.kind for r in scenario.requirements]
        assert kinds == ["http_transcript", "log", "screenshot"]  # deduped, ordered

    def test_scenario_name_fallback_from_feature_id(self, tmp_path):
        rubric = RUBRIC.replace('scenario = "pay_invoices"\n', "")
        vault = _vault_with(tmp_path, {"pay-invoices": rubric})
        contract = derive_contract(vault)
        assert contract.for_scenario("pay_invoices") is not None

    def test_trials_propagate(self, tmp_path):
        rubric = RUBRIC + "\ntrials = 5\n"
        # top-level key must come before tables; prepend instead
        rubric = "trials = 5\n" + RUBRIC
        vault = _vault_with(tmp_path, {"pay-invoices": rubric})
        contract = derive_contract(vault)
        assert all(
            r.trials == 5
            for r in contract.for_scenario("pay_invoices").requirements
        )

    def test_dumps_round_trips(self, tmp_path):
        vault = _vault_with(tmp_path, {"pay-invoices": RUBRIC})
        contract = derive_contract(vault, project="press")
        assert loads_contract(dumps_contract(contract)) == contract


class TestVaultCLI:
    def _project(self, tmp_path, monkeypatch):
        root = tmp_path / "tenant"
        (root / "scenarios").mkdir(parents=True)
        (root / "scenarios" / "pay-invoices.rubric.toml").write_text(RUBRIC)
        (root / "darkroom.toml").write_text(
            '[project]\nname = "press"\n[scenarios]\n'
            'rubric_glob = "scenarios/*.rubric.toml"\n'
            '[evidence]\ncontract = "evidence-contract.toml"'
        )
        monkeypatch.chdir(root)
        return root

    def test_seal_then_derive_then_check(self, tmp_path, capsys, monkeypatch):
        root = self._project(tmp_path, monkeypatch)
        vault_dir = tmp_path / "vault"

        assert main(["vault", "seal", "--vault", str(vault_dir)]) == 0
        assert "sealed 1 rubric(s)" in capsys.readouterr().out

        assert main(["vault", "derive-contract", "--vault", str(vault_dir)]) == 0
        capsys.readouterr()
        contract = loads_contract((root / "evidence-contract.toml").read_text())
        assert contract.for_scenario("pay_invoices") is not None

        assert main([
            "vault", "derive-contract", "--vault", str(vault_dir), "--check"
        ]) == 0
        assert "ok:" in capsys.readouterr().out

        # tamper with the tenant cache → drift detected
        (root / "evidence-contract.toml").write_text(
            'schema_version = "1.0"\nproject = "press"\n'
        )
        assert main([
            "vault", "derive-contract", "--vault", str(vault_dir), "--check"
        ]) == 1
        assert "DRIFT" in capsys.readouterr().out
