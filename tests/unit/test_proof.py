"""Proofs: a folder of two files — QA's exposure and product's rubric.
The judge still reads rubric-shaped text; the engine still runs
drive-shaped scripts; the contract and the gates need no tenant-side
file at all; the manifest names the exam each run answered."""

import json
import sys
import textwrap

import pytest

from darkroom.adapter import loads_adapter
from darkroom.audit import audit
from darkroom.backdrops import loads_backdrops
from darkroom.drive import DriveError, drive
from darkroom.homedir import (
    default_proofs,
    default_state,
    exam_is_operator_side,
    exams_dir,
    gates_file,
)
from darkroom.proof import (
    EXPOSURE_FILE,
    RUBRIC_FILE,
    ProofError,
    derive_contract,
    exposure,
    exposure_source,
    load_proof,
    load_proofs,
    loads_proof,
    provenance,
    rubric,
    rubric_source,
    rubric_text,
)
from darkroom.vault import FilesystemVault, VaultError, runtime_contract, seal
from darkroom.vault_openbao import _rubric_half

if sys.version_info >= (3, 11):
    import tomllib
else:  # pragma: no cover
    import tomli as tomllib

EXPOSURE = """
scenario = "note_created"

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
"""

RUBRIC = """
version = "2"

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

BACKDROPS = """
[[backdrop]]
name = "founded"
[[backdrop.step]]
name = "found"
method = "POST"
url = "{base_url}/workspaces"
"""

POSED_EXPOSURE = """
scenario = "member_joins"
backdrop = ["founded"]

[[step]]
name = "join"
method = "POST"
url = "{base_url}/join"
"""

POSED_RUBRIC = """
[[criterion]]
id = "joined"
points = 1
witnesses = ["found", "join"]
"""


def _proof(exposure_text=EXPOSURE, rubric_text=RUBRIC):
    return loads_proof(exposure_text, rubric_text, "note_created")


class TestLoadsProof:
    def test_halves_merge_and_steps_default_to_http(self):
        proof = _proof()
        assert proof["scenario"] == "note_created" and proof["version"] == "2"
        assert [s["kind"] for s in proof["step"]] == ["http", "screenshot", "assert"]

    @pytest.mark.parametrize(
        "mutate_exposure, mutate_rubric, message",
        [
            (lambda t: t.replace('scenario = "note_created"', ""), None, "needs a scenario"),
            (None, lambda t: t.split("[[criterion]]")[0], "at least one \\[\\[criterion\\]\\]"),
            (None, lambda t: t.replace('id = "visible"', ""), "every criterion needs an id"),
            (None, lambda t: t.replace('id = "visible"', 'id = "created"'), "defined twice"),
            (None, lambda t: t.replace("points = 5", 'points = "five"'), "needs numeric points"),
            (None, lambda t: t.replace('witnesses = ["create"]', ""), "cites no witnesses"),
            (None, lambda t: 'scenario = "other"\n' + t, "names scenario 'other'"),
            (None, lambda t: '[[step]]\nname = "x"\n' + t, "'step' belongs to the exposure"),
            (lambda t: 'version = "3"\n' + t, None, "'version' belongs to the rubric"),
            (lambda t: t + "\nbroken = [", None, "exposure.toml"),
        ],
    )
    def test_shape_is_enforced(self, mutate_exposure, mutate_rubric, message):
        exposure_text = mutate_exposure(EXPOSURE) if mutate_exposure else EXPOSURE
        rubric_text_ = mutate_rubric(RUBRIC) if mutate_rubric else RUBRIC
        with pytest.raises(ProofError, match=message):
            loads_proof(exposure_text, rubric_text_, "note_created")

    def test_a_rubric_may_name_its_scenario(self):
        proof = loads_proof(EXPOSURE, 'scenario = "note_created"\n' + RUBRIC)
        assert proof["scenario"] == "note_created"


class TestFolder:
    def test_load_proof_reads_both_files(self, tmp_path):
        folder = tmp_path / "note_created"
        folder.mkdir()
        (folder / EXPOSURE_FILE).write_text(EXPOSURE)
        (folder / RUBRIC_FILE).write_text(RUBRIC)
        proof = load_proof(folder)
        assert proof["scenario"] == "note_created" and len(proof["criterion"]) == 2

    def test_folder_is_named_after_its_scenario(self, tmp_path):
        folder = tmp_path / "other"
        folder.mkdir()
        (folder / EXPOSURE_FILE).write_text(EXPOSURE)
        (folder / RUBRIC_FILE).write_text(RUBRIC)
        with pytest.raises(ProofError, match="named after its scenario"):
            load_proof(folder)

    def test_an_exposure_alone_runs_but_cannot_be_judged(self, tmp_path):
        folder = tmp_path / "note_created"
        folder.mkdir()
        (folder / EXPOSURE_FILE).write_text(EXPOSURE)
        proof = load_proof(folder)
        assert [s["name"] for s in exposure(proof)["step"]] == ["create", "shot", "id_present"]
        with pytest.raises(ProofError, match="no rubric.toml"):
            rubric(proof)
        assert derive_contract([proof]).scenarios == []
        with pytest.raises(ProofError, match="'version' belongs to the rubric"):
            loads_proof('version = "1"\n' + EXPOSURE, None)

    def test_the_exposure_is_required(self, tmp_path):
        folder = tmp_path / "note_created"
        folder.mkdir()
        (folder / RUBRIC_FILE).write_text(RUBRIC)
        assert not load_proofs(tmp_path)  # not a proof folder at all

    def test_sources_round_trip(self):
        proof = _proof()
        again = loads_proof(exposure_source(proof), rubric_source(proof), "note_created")
        assert again == proof
        assert "criterion" not in exposure_source(proof)
        assert rubric_source(proof).startswith('version = "2"')
        assert "[[step]]" not in rubric_source(proof)

    def test_provenance_names_the_exam(self, tmp_path):
        folder = tmp_path / "note_created"
        folder.mkdir()
        (folder / EXPOSURE_FILE).write_text(EXPOSURE)
        (folder / RUBRIC_FILE).write_text(RUBRIC)
        record = provenance(folder, load_proof(folder))
        assert record["rubric_version"] == "2" and len(record["exposure_sha256"]) == 64
        (folder / EXPOSURE_FILE).write_text(EXPOSURE + "\n# touched\n")
        assert provenance(folder, load_proof(folder))["exposure_sha256"] != record["exposure_sha256"]


class TestRubric:
    def test_evidence_derives_from_cited_steps(self):
        data = rubric(_proof())
        by_id = {c["id"]: c["evidence"] for c in data["criterion"]}
        assert by_id["created"] == ["log", "http_transcript"]  # expect adds the log witness
        assert by_id["visible"] == ["log"]
        assert data["feature_id"] == "note-created" and data["version"] == "2"

    def test_a_cited_screenshot_rests_on_screenshot_evidence(self):
        text = RUBRIC.replace('witnesses = ["id_present"]', 'witnesses = ["shot"]')
        assert rubric(_proof(rubric_text=text))["criterion"][1]["evidence"] == ["screenshot"]

    def test_declared_evidence_is_kept(self):
        text = RUBRIC.replace('witnesses = ["create"]', 'witnesses = ["create"]\nevidence = ["video"]')
        assert rubric(_proof(rubric_text=text))["criterion"][0]["evidence"] == ["video"]

    def test_unknown_witness_refused(self):
        text = RUBRIC.replace('witnesses = ["create"]', 'witnesses = ["creat"]')
        with pytest.raises(ProofError, match="cites witness 'creat' but no step"):
            rubric(_proof(rubric_text=text))

    def test_rubric_text_carries_criteria_and_never_steps(self):
        rendered = rubric_text(_proof())
        parsed = tomllib.loads(rendered)
        assert "step" not in parsed
        assert parsed["scenario"] == "note_created"
        assert parsed["feature_id"] == "note-created"
        assert [c["id"] for c in parsed["criterion"]] == ["created", "visible"]
        assert parsed["criterion"][0]["description"] == "a note is created"
        assert parsed["criterion"][1]["evidence"] == ["log"]


class TestExposureAndBackdrops:
    def test_exposure_is_drive_shaped(self):
        script = exposure(_proof())
        assert script["scenario"] == "note_created"
        assert "criterion" not in script and "version" not in script
        assert [s["name"] for s in script["step"]] == ["create", "shot", "id_present"]

    def test_backdrops_expand_ahead_of_own_steps(self):
        backdrops = loads_backdrops(BACKDROPS)
        posed = loads_proof(POSED_EXPOSURE, POSED_RUBRIC, "member_joins")
        script = exposure(posed, backdrops)
        assert [s["name"] for s in script["step"]] == ["found", "join"]
        assert "backdrop" not in script
        assert rubric(posed, backdrops)["criterion"][0]["evidence"] == ["http_transcript"]

    def test_witness_in_an_unexpanded_backdrop_is_an_error(self):
        posed = loads_proof(POSED_EXPOSURE, POSED_RUBRIC, "member_joins")
        with pytest.raises(ProofError, match="unknown backdrop|cites witness 'found'"):
            rubric(posed, {})


class TestDeriveContract:
    def test_kinds_and_trials_per_scenario(self):
        proof = _proof(rubric_text=RUBRIC.replace('version = "2"', 'version = "2"\ntrials = 3'))
        contract = derive_contract([proof], "press")
        assert contract.project == "press"
        [scenario] = contract.scenarios
        assert scenario.scenario == "note_created"
        assert [(r.kind, r.trials) for r in scenario.requirements] == [
            ("log", 3), ("http_transcript", 3),
        ]


def _home_with_proofs(tmp_path, monkeypatch, proofs: dict, backdrops: str | None = None):
    """``proofs`` maps scenario -> (exposure text, rubric text)."""
    monkeypatch.setenv("DARKROOM_HOME", str(tmp_path / "home"))
    proofs_dir = default_proofs("press")
    proofs_dir.mkdir(parents=True)
    for scenario, (exposure_text, rubric_text_) in proofs.items():
        folder = proofs_dir / scenario
        folder.mkdir()
        (folder / EXPOSURE_FILE).write_text(exposure_text)
        (folder / RUBRIC_FILE).write_text(rubric_text_)
    if backdrops is not None:
        (proofs_dir.parent / "backdrops.toml").write_text(backdrops)
    return proofs_dir


ONE = {"note_created": (EXPOSURE, RUBRIC)}
TWO = {"note_created": (EXPOSURE, RUBRIC), "member_joins": (POSED_EXPOSURE, POSED_RUBRIC)}


class TestProofsVault:
    def test_lists_by_scenario_and_reads_the_rubric_half(self, tmp_path, monkeypatch):
        proofs_dir = _home_with_proofs(tmp_path, monkeypatch, ONE)
        vault = FilesystemVault(proofs_dir.parent / "vault")
        assert vault.uses_proofs()
        assert vault.list() == ["note_created"]
        parsed = tomllib.loads(vault.read("note_created"))
        assert "step" not in parsed and parsed["criterion"][0]["id"] == "created"
        assert "read proof note_created" in (vault.root / "audit.log").read_text()

    def test_version_checked_and_missing_named(self, tmp_path, monkeypatch):
        proofs_dir = _home_with_proofs(tmp_path, monkeypatch, ONE)
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
        proofs_dir = _home_with_proofs(tmp_path, monkeypatch, TWO, BACKDROPS)
        adapter = loads_adapter('[project]\nname = "press"', root=tmp_path / "tenant")
        vault = FilesystemVault(proofs_dir.parent / "vault")
        assert seal(adapter, vault) == ["member_joins", "note_created"]
        assert (proofs_dir / "note_created" / EXPOSURE_FILE).exists()  # nothing moved
        assert proofs_dir.stat().st_mode & 0o777 == 0o700
        assert (proofs_dir / "note_created").stat().st_mode & 0o777 == 0o700
        assert "sealed 2 proof(s)" in (vault.root / "audit.log").read_text()

    def test_seal_and_audit_refuse_an_exposure_without_its_rubric(self, tmp_path, monkeypatch):
        proofs_dir = _home_with_proofs(tmp_path, monkeypatch, ONE)
        bare = proofs_dir / "bare"
        bare.mkdir()
        (bare / EXPOSURE_FILE).write_text(EXPOSURE.replace("note_created", "bare"))
        adapter = loads_adapter('[project]\nname = "press"', root=tmp_path / "tenant")
        vault = FilesystemVault(proofs_dir.parent / "vault")
        with pytest.raises(VaultError, match="bare: no rubric.toml"):
            seal(adapter, vault)
        [finding] = [f for f in audit(vault, proofs_dir) if f.code == "no-rubric"]
        assert finding.severity == "error" and finding.scenario == "bare"
        # the contract still derives from the proof that has one
        assert [s.scenario for s in runtime_contract(adapter).scenarios] == ["note_created"]

    def test_seal_refuses_a_broken_proof(self, tmp_path, monkeypatch):
        bad = RUBRIC.replace('witnesses = ["create"]', 'witnesses = ["nope"]')
        proofs_dir = _home_with_proofs(tmp_path, monkeypatch, {"note_created": (EXPOSURE, bad)})
        adapter = loads_adapter('[project]\nname = "press"', root=tmp_path / "tenant")
        with pytest.raises(VaultError, match="cites witness 'nope'"):
            seal(adapter, FilesystemVault(proofs_dir.parent / "vault"))


class TestRuntimeContract:
    def test_declared_contract_wins(self, tmp_path, monkeypatch):
        _home_with_proofs(tmp_path, monkeypatch, ONE)
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
        _home_with_proofs(tmp_path, monkeypatch, ONE)
        adapter = loads_adapter('[project]\nname = "press"', root=tmp_path / "tenant")
        contract = runtime_contract(adapter)
        assert [s.scenario for s in contract.scenarios] == ["note_created"]

    def test_none_without_proofs_or_contract(self, tmp_path, monkeypatch):
        monkeypatch.setenv("DARKROOM_HOME", str(tmp_path / "home"))
        adapter = loads_adapter('[project]\nname = "press"', root=tmp_path / "tenant")
        assert runtime_contract(adapter) is None

    def test_none_while_every_proof_is_an_exposure_alone(self, tmp_path, monkeypatch):
        monkeypatch.setenv("DARKROOM_HOME", str(tmp_path / "home"))
        folder = default_proofs("press") / "note_created"
        folder.mkdir(parents=True)
        (folder / EXPOSURE_FILE).write_text(EXPOSURE)
        adapter = loads_adapter('[project]\nname = "press"', root=tmp_path / "tenant")
        assert runtime_contract(adapter) is None
        assert runtime_contract(adapter, proofs_dir=default_proofs("press")) is None

    def test_broken_proof_surfaces_as_vault_error(self, tmp_path, monkeypatch):
        _home_with_proofs(tmp_path, monkeypatch, {"x": ('scenario = "x"\n', "")})
        adapter = loads_adapter('[project]\nname = "press"', root=tmp_path / "tenant")
        with pytest.raises(VaultError, match="at least one"):
            runtime_contract(adapter)


class TestHomeLayout:
    def test_exams_dir_prefers_proofs(self, tmp_path, monkeypatch):
        monkeypatch.setenv("DARKROOM_HOME", str(tmp_path / "home"))
        assert exams_dir("press").name == "drives"
        assert not exam_is_operator_side("press")
        default_proofs("press").mkdir(parents=True)
        (default_proofs("press") / "stray.txt").write_text("")
        assert exams_dir("press").name == "drives"  # an empty proofs/ is no signal
        folder = default_proofs("press") / "note_created"
        folder.mkdir()
        (folder / EXPOSURE_FILE).write_text(EXPOSURE)
        assert exams_dir("press") == default_proofs("press")
        assert exam_is_operator_side("press")

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
    def test_a_stored_whole_proof_is_handed_over_as_its_rubric(self):
        parsed = tomllib.loads(_rubric_half(EXPOSURE + RUBRIC))
        assert "step" not in parsed and parsed["scenario"] == "note_created"

    def test_stored_rubric_passes_through(self):
        text = 'scenario = "pay"\n[[criterion]]\nid = "a"\npoints = 1\n'
        assert _rubric_half(text) == text


class TestAuditOnProofs:
    def test_a_sound_proof_audits_clean(self, tmp_path, monkeypatch):
        proofs_dir = _home_with_proofs(tmp_path, monkeypatch, TWO, BACKDROPS)
        vault = FilesystemVault(proofs_dir.parent / "vault")
        assert audit(vault, proofs_dir, loads_backdrops(BACKDROPS)) == []


@pytest.mark.skipif(sys.platform == "win32", reason="sh")
class TestDriveOnProofs:
    def test_a_proof_runs_as_its_exposure_and_the_manifest_names_it(self, tmp_path, monkeypatch):
        exposure_text = textwrap.dedent("""
            scenario = "greets"
            [[step]]
            name = "say"
            kind = "command"
            cmd = "echo hello"
            expect = { exit_code = 0 }
        """)
        rubric_text_ = textwrap.dedent("""
            version = "4"
            [[criterion]]
            id = "said"
            points = 1
            witnesses = ["say"]
        """)
        proofs_dir = _home_with_proofs(tmp_path, monkeypatch, {"greets": (exposure_text, rubric_text_)})
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
        [bundle] = data["scenarios"]
        assert bundle["scenario"] == "greets"
        assert bundle["provenance"] == provenance(proofs_dir / "greets", load_proof(proofs_dir / "greets"))
        assert bundle["provenance"]["rubric_version"] == "4"

    def test_scenario_filter_and_empty_dir(self, tmp_path, monkeypatch):
        proofs_dir = _home_with_proofs(tmp_path, monkeypatch, ONE)
        adapter = loads_adapter('[project]\nname = "press"', root=tmp_path / "tenant")
        with pytest.raises(DriveError, match="no exams for scenario 'other'"):
            drive(adapter, proofs_dir, scenario="other", containers_mode="off")


class TestLoadProofs:
    def test_keyed_by_scenario(self, tmp_path, monkeypatch):
        proofs_dir = _home_with_proofs(tmp_path, monkeypatch, TWO)
        assert sorted(load_proofs(proofs_dir)) == ["member_joins", "note_created"]
