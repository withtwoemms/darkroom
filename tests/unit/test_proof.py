"""Proofs: exposure and rubric in one sealed file. The judge still reads
rubric-shaped text; the engine still runs drive-shaped scripts; the
contract and the gates need no tenant-side file at all."""

import json
import sys
import textwrap

import pytest

from darkroom.adapter import loads_adapter
from darkroom.audit import audit
from darkroom.drive import DriveError, drive
from darkroom.homedir import default_proofs, default_state, exams_dir, gates_file
from darkroom.preludes import loads_preludes
from darkroom.proof import (
    ProofError,
    derive_contract,
    exposure,
    load_proofs,
    loads_proof,
    rubric,
    rubric_text,
)
from darkroom.vault import FilesystemVault, VaultError, runtime_contract, seal
from darkroom.vault_openbao import _rubric_half

if sys.version_info >= (3, 11):
    import tomllib
else:  # pragma: no cover
    import tomli as tomllib

PROOF = """
scenario = "note_created"
version = "2"

[[step]]
name = "create"
method = "POST"
url = "{base_url}/notes"
expect = { status = 201 }

[[step]]
name = "shot"
kind = "screenshot"

[[step]]
name = "id_present"
kind = "assert"
left = "{note_id}"
op = "!="
right = ""

[[criterion]]
id = "created"
points = 10
description = "a note is created"
witnesses = ["create"]

[[criterion]]
id = "visible"
points = 5
witnesses = ["id_present"]
"""

PRELUDES = """
[[prelude]]
name = "founded"
[[prelude.step]]
name = "found"
method = "POST"
url = "{base_url}/circles"
"""

INCLUDING = """
scenario = "member_joins"
include = ["founded"]

[[step]]
name = "join"
method = "POST"
url = "{base_url}/join"

[[criterion]]
id = "joined"
points = 1
witnesses = ["found", "join"]
"""


class TestLoadsProof:
    def test_steps_default_to_http(self):
        proof = loads_proof(PROOF)
        assert [s["kind"] for s in proof["step"]] == ["http", "screenshot", "assert"]

    @pytest.mark.parametrize(
        "mutation, message",
        [
            (lambda t: t.replace('scenario = "note_created"', ""), "needs a scenario"),
            (lambda t: t.split("[[criterion]]")[0], "at least one \\[\\[criterion\\]\\]"),
            (lambda t: t.replace('id = "visible"', ""), "every criterion needs an id"),
            (lambda t: t.replace('id = "visible"', 'id = "created"'), "defined twice"),
            (lambda t: t.replace("points = 5", 'points = "five"'), "needs numeric points"),
            (lambda t: t.replace('witnesses = ["create"]', ""), "cites no witnesses"),
        ],
    )
    def test_shape_is_enforced(self, mutation, message):
        with pytest.raises(ProofError, match=message):
            loads_proof(mutation(PROOF), "x.proof.toml")


class TestRubric:
    def test_evidence_derives_from_cited_steps(self):
        data = rubric(loads_proof(PROOF))
        by_id = {c["id"]: c["evidence"] for c in data["criterion"]}
        assert by_id["created"] == ["log", "http_transcript"]  # expect adds the log witness
        assert by_id["visible"] == ["log"]
        assert data["feature_id"] == "note-created" and data["version"] == "2"

    def test_a_cited_screenshot_rests_on_screenshot_evidence(self):
        text = PROOF.replace('witnesses = ["id_present"]', 'witnesses = ["shot"]')
        assert rubric(loads_proof(text))["criterion"][1]["evidence"] == ["screenshot"]

    def test_declared_evidence_is_kept(self):
        text = PROOF.replace('witnesses = ["create"]', 'witnesses = ["create"]\nevidence = ["video"]')
        data = rubric(loads_proof(text))
        assert data["criterion"][0]["evidence"] == ["video"]

    def test_unknown_witness_refused(self):
        text = PROOF.replace('witnesses = ["create"]', 'witnesses = ["creat"]')
        with pytest.raises(ProofError, match="cites witness 'creat' but no step"):
            rubric(loads_proof(text))

    def test_rubric_text_carries_criteria_and_never_steps(self):
        rendered = rubric_text(loads_proof(PROOF))
        parsed = tomllib.loads(rendered)
        assert "step" not in parsed
        assert parsed["scenario"] == "note_created"
        assert parsed["feature_id"] == "note-created"
        assert [c["id"] for c in parsed["criterion"]] == ["created", "visible"]
        assert parsed["criterion"][0]["description"] == "a note is created"
        assert parsed["criterion"][1]["evidence"] == ["log"]


class TestExposureAndPreludes:
    def test_exposure_is_drive_shaped(self):
        script = exposure(loads_proof(PROOF))
        assert script["scenario"] == "note_created"
        assert "criterion" not in script and "version" not in script
        assert [s["name"] for s in script["step"]] == ["create", "shot", "id_present"]

    def test_includes_expand_ahead_of_own_steps(self):
        preludes = loads_preludes(PRELUDES)
        script = exposure(loads_proof(INCLUDING), preludes)
        assert [s["name"] for s in script["step"]] == ["found", "join"]
        assert "include" not in script
        assert rubric(loads_proof(INCLUDING), preludes)["criterion"][0]["evidence"] == [
            "http_transcript"
        ]

    def test_witness_in_an_unexpanded_prelude_is_an_error(self):
        with pytest.raises(ProofError, match="unknown prelude|cites witness 'found'"):
            rubric(loads_proof(INCLUDING), {})


class TestDeriveContract:
    def test_kinds_and_trials_per_scenario(self):
        proof = loads_proof(PROOF.replace('version = "2"', 'version = "2"\ntrials = 3'))
        contract = derive_contract([proof], "press")
        assert contract.project == "press"
        [scenario] = contract.scenarios
        assert scenario.scenario == "note_created"
        assert [(r.kind, r.trials) for r in scenario.requirements] == [
            ("log", 3), ("http_transcript", 3),
        ]


def _home_with_proofs(tmp_path, monkeypatch, proofs: dict, preludes: str | None = None):
    monkeypatch.setenv("DARKROOM_HOME", str(tmp_path / "home"))
    proofs_dir = default_proofs("press")
    proofs_dir.mkdir(parents=True)
    for scenario, text in proofs.items():
        (proofs_dir / f"{scenario}.proof.toml").write_text(text)
    if preludes is not None:
        (proofs_dir.parent / "preludes.toml").write_text(preludes)
    return proofs_dir


class TestProofsVault:
    def test_lists_by_scenario_and_reads_the_rubric_half(self, tmp_path, monkeypatch):
        proofs_dir = _home_with_proofs(tmp_path, monkeypatch, {"note_created": PROOF})
        vault = FilesystemVault(proofs_dir.parent / "vault")
        assert vault.uses_proofs()
        assert vault.list() == ["note_created"]
        parsed = tomllib.loads(vault.read("note_created"))
        assert "step" not in parsed and parsed["criterion"][0]["id"] == "created"
        assert "read proof note_created" in (vault.root / "audit.log").read_text()

    def test_version_checked_and_missing_named(self, tmp_path, monkeypatch):
        proofs_dir = _home_with_proofs(tmp_path, monkeypatch, {"note_created": PROOF})
        vault = FilesystemVault(proofs_dir.parent / "vault")
        assert vault.read("note_created", version="2")
        with pytest.raises(VaultError, match="at version '2', not '9'"):
            vault.read("note_created", version="9")
        with pytest.raises(VaultError, match="no proof 'other'"):
            vault.read("other")

    def test_rubric_layout_untouched_without_proofs(self, tmp_path):
        vault = FilesystemVault(tmp_path / "vault")
        vault.initialize()
        (vault.root / "pay.rubric.toml").write_text('scenario = "pay"\n')
        assert not vault.uses_proofs()
        assert vault.list() == ["pay"]
        assert vault.read("pay") == 'scenario = "pay"\n'

    def test_seal_validates_proofs_in_place(self, tmp_path, monkeypatch):
        proofs_dir = _home_with_proofs(
            tmp_path, monkeypatch, {"note_created": PROOF, "member_joins": INCLUDING}, PRELUDES
        )
        adapter = loads_adapter('[project]\nname = "press"', root=tmp_path / "tenant")
        vault = FilesystemVault(proofs_dir.parent / "vault")
        assert seal(adapter, vault) == ["member_joins", "note_created"]
        assert (proofs_dir / "note_created.proof.toml").exists()  # nothing moved
        assert proofs_dir.stat().st_mode & 0o777 == 0o700
        assert "sealed 2 proof(s)" in (vault.root / "audit.log").read_text()

    def test_seal_refuses_a_broken_proof(self, tmp_path, monkeypatch):
        bad = PROOF.replace('witnesses = ["create"]', 'witnesses = ["nope"]')
        proofs_dir = _home_with_proofs(tmp_path, monkeypatch, {"note_created": bad})
        adapter = loads_adapter('[project]\nname = "press"', root=tmp_path / "tenant")
        with pytest.raises(VaultError, match="cites witness 'nope'"):
            seal(adapter, FilesystemVault(proofs_dir.parent / "vault"))


class TestRuntimeContract:
    def test_declared_contract_wins(self, tmp_path, monkeypatch):
        _home_with_proofs(tmp_path, monkeypatch, {"note_created": PROOF})
        root = tmp_path / "tenant"
        root.mkdir()
        (root / "contract.toml").write_text(
            'schema_version = "1"\nproject = "press"\n[[scenario]]\nname = "declared"\n'
        )
        adapter = loads_adapter(
            '[project]\nname = "press"\n[evidence]\ncontract = "contract.toml"', root=root
        )
        assert [s.scenario for s in runtime_contract(adapter).scenarios] == ["declared"]

    def test_derived_from_home_proofs(self, tmp_path, monkeypatch):
        _home_with_proofs(tmp_path, monkeypatch, {"note_created": PROOF})
        adapter = loads_adapter('[project]\nname = "press"', root=tmp_path / "tenant")
        contract = runtime_contract(adapter)
        assert [s.scenario for s in contract.scenarios] == ["note_created"]

    def test_none_without_proofs_or_contract(self, tmp_path, monkeypatch):
        monkeypatch.setenv("DARKROOM_HOME", str(tmp_path / "home"))
        adapter = loads_adapter('[project]\nname = "press"', root=tmp_path / "tenant")
        assert runtime_contract(adapter) is None

    def test_broken_proof_surfaces_as_vault_error(self, tmp_path, monkeypatch):
        _home_with_proofs(tmp_path, monkeypatch, {"x": "scenario = 'x'\n"})
        adapter = loads_adapter('[project]\nname = "press"', root=tmp_path / "tenant")
        with pytest.raises(VaultError, match="at least one"):
            runtime_contract(adapter)


class TestHomeLayout:
    def test_exams_dir_prefers_proofs(self, tmp_path, monkeypatch):
        monkeypatch.setenv("DARKROOM_HOME", str(tmp_path / "home"))
        assert exams_dir("press").name == "drives"
        default_proofs("press").mkdir(parents=True)
        assert exams_dir("press").name == "drives"  # an empty proofs/ is no signal
        (default_proofs("press") / "a.proof.toml").write_text(PROOF)
        assert exams_dir("press") == default_proofs("press")

    def test_gates_live_in_home_state_unless_declared(self, tmp_path, monkeypatch):
        monkeypatch.setenv("DARKROOM_HOME", str(tmp_path / "home"))
        root = tmp_path / "tenant"
        undeclared = loads_adapter('[project]\nname = "press"', root=root)
        assert gates_file(undeclared) == default_state("press") / "gates.json"
        declared = loads_adapter(
            '[project]\nname = "press"\n[evidence]\ngates = "g.json"', root=root
        )
        assert gates_file(declared) == root / "g.json"


class TestOpenBaoHalf:
    def test_stored_proof_is_handed_over_as_its_rubric(self):
        parsed = tomllib.loads(_rubric_half(PROOF))
        assert "step" not in parsed and parsed["scenario"] == "note_created"

    def test_stored_rubric_passes_through(self):
        text = 'scenario = "pay"\n[[criterion]]\nid = "a"\npoints = 1\n'
        assert _rubric_half(text) == text


class TestAuditOnProofs:
    def test_a_sound_proof_audits_clean(self, tmp_path, monkeypatch):
        proofs_dir = _home_with_proofs(
            tmp_path, monkeypatch, {"note_created": PROOF, "member_joins": INCLUDING}, PRELUDES
        )
        vault = FilesystemVault(proofs_dir.parent / "vault")
        findings = audit(vault, proofs_dir, loads_preludes(PRELUDES))
        assert findings == []


@pytest.mark.skipif(sys.platform == "win32", reason="sh")
class TestDriveOnProofs:
    def test_a_proof_runs_as_its_exposure(self, tmp_path, monkeypatch):
        proofs_dir = _home_with_proofs(
            tmp_path,
            monkeypatch,
            {
                "greets": textwrap.dedent("""
                    scenario = "greets"
                    [[step]]
                    name = "say"
                    kind = "command"
                    cmd = "echo hello"
                    expect = { exit_code = 0 }
                    [[criterion]]
                    id = "said"
                    points = 1
                    witnesses = ["say"]
                """),
            },
        )
        root = tmp_path / "tenant"
        root.mkdir()
        monkeypatch.setenv("EVIDENCE_DIR", str(root / "evidence"))
        adapter = loads_adapter('[project]\nname = "press"', root=root)
        report = drive(adapter, proofs_dir, containers_mode="off")
        assert report.ok
        [result] = report.results
        assert result.scenario == "greets" and [s.name for s in result.steps] == ["say"]
        [manifest] = list((root / "evidence" / "runs").glob("*/manifest.json"))
        data = json.loads(manifest.read_text())
        assert data["scenarios"][0]["scenario"] == "greets"

    def test_scenario_filter_and_empty_dir(self, tmp_path, monkeypatch):
        proofs_dir = _home_with_proofs(tmp_path, monkeypatch, {"note_created": PROOF})
        adapter = loads_adapter('[project]\nname = "press"', root=tmp_path / "tenant")
        with pytest.raises(DriveError, match="no exams for scenario 'other'"):
            drive(adapter, proofs_dir, scenario="other", containers_mode="off")


class TestLoadProofs:
    def test_keyed_by_scenario(self, tmp_path):
        (tmp_path / "a.proof.toml").write_text(PROOF)
        (tmp_path / "b.proof.toml").write_text(INCLUDING)
        assert sorted(load_proofs(tmp_path)) == ["member_joins", "note_created"]
