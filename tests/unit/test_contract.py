"""Unit tests for contract parsing and validation."""

import pytest

from darkroom.contract import (
    CURRENT_CONTRACT_SCHEMA_VERSION,
    EvidenceRequirement,
    load_contract,
    loads_contract,
)

FULL_CONTRACT = """
schema_version = "1.0"
project = "bookbinder"

[[scenario]]
name = "client_approves_proof"

  [[scenario.requires]]
  kind = "screenshot"
  steps = ["proof_awaiting_approval", "proof_approved"]

  [[scenario.requires]]
  kind = "http_transcript"
  min_count = 2

[[scenario]]
name = "press_notified"

  [[scenario.requires]]
  kind = "log"
  trials = 5
"""


class TestLoadsContract:
    def test_full_document(self):
        contract = loads_contract(FULL_CONTRACT)
        assert contract.schema_version == "1.0"
        assert contract.project == "bookbinder"
        assert len(contract.scenarios) == 2

        approve = contract.for_scenario("client_approves_proof")
        assert approve is not None
        shots, http = approve.requirements
        assert shots.kind == "screenshot"
        assert shots.steps == ("proof_awaiting_approval", "proof_approved")
        assert shots.min_count == 1 and shots.trials == 1
        assert http.min_count == 2

        notified = contract.for_scenario("press_notified")
        assert notified.requirements[0].trials == 5

    def test_defaults(self):
        contract = loads_contract("")
        assert contract.schema_version == CURRENT_CONTRACT_SCHEMA_VERSION
        assert contract.scenarios == []
        assert contract.for_scenario("anything") is None

    def test_missing_scenario_name_rejected(self):
        with pytest.raises(ValueError, match="missing a name"):
            loads_contract('[[scenario]]\n[[scenario.requires]]\nkind = "log"')

    def test_missing_kind_rejected(self):
        with pytest.raises(ValueError, match="missing a kind"):
            loads_contract('[[scenario]]\nname = "s"\n[[scenario.requires]]\nmin_count = 1')

    def test_bad_counts_rejected(self):
        with pytest.raises(ValueError, match="min_count"):
            EvidenceRequirement(kind="log", min_count=0)
        with pytest.raises(ValueError, match="trials"):
            EvidenceRequirement(kind="log", trials=0)


class TestLoadContract:
    def test_from_file(self, tmp_path):
        path = tmp_path / "evidence-contract.toml"
        path.write_text(FULL_CONTRACT)
        contract = load_contract(path)
        assert contract.project == "bookbinder"
