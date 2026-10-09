"""Run selection: --tag keeps tagged proofs, --touching keeps proofs whose
own steps reach an address by the audit's matching rules, and the run
names its selection so a partial run is never read as the gate."""

import pytest

from darkroom.backdrops import BACKDROP_MARK
from darkroom.contract import EvidenceContract, ScenarioContract, scoped_contract
from darkroom.drive import (
    DriveError,
    DriveReport,
    ScenarioResult,
    StepResult,
    _write_harness_log,
    select_proofs,
)
from darkroom.proof import ProofError, validate_proof
from darkroom.surfaces import Surface, SurfacesError, parse_address, touches


class TestParseAddress:
    @pytest.mark.parametrize(
        "text, kind, target",
        [
            ("POST /notes/{id}/archive", "route", "/notes/*/archive"),
            ("get /notes", "route", "/notes"),
            ("/", "page", "/"),
            ("/notes/{id}", "page", "/notes/*"),
            ("#save", "selector", "#save"),
            ("#notes li[data-archived]", "selector", "#notes li[data-archived]"),
            ("main[data-note-state]", "selector", "main[data-note-state]"),
            ("li:first-child", "selector", "li:first-child"),
            ("make deploy ID=…", "command", "make deploy ID=…"),
            ("relay.py export", "command", "relay.py export"),
        ],
    )
    def test_kinds_are_told_apart_the_way_a_surfaces_file_tells_them(self, text, kind, target):
        address = parse_address(text)
        assert (address.kind, address.target) == (kind, target)
        if kind == "route":
            assert address.method == text.split()[0].upper()

    def test_a_kind_prefix_settles_an_ambiguous_address(self):
        assert parse_address("command: main li").kind == "command"
        assert parse_address("selector: main li").kind == "selector"
        assert parse_address("page: notes").target == "/notes"
        assert parse_address("route: DELETE /notes/{id}") == Surface("route", "DELETE", "/notes/*")

    def test_empty_and_malformed_are_refused(self):
        with pytest.raises(SurfacesError):
            parse_address("   ")
        with pytest.raises(SurfacesError):
            parse_address("route: /notes")


def _script(*steps, scenario="s"):
    return {"scenario": scenario, "step": list(steps)}


class TestTouches:
    def test_a_selector_narrowed_to_a_state_is_the_element_published(self):
        script = _script({"kind": "click", "selector": '#notes li[data-archived="true"]'})
        assert touches(script, [parse_address("#notes li")])
        assert touches(script, [parse_address("#notes li[data-archived]")])
        assert not touches(script, [parse_address("#notes-list")])

    def test_a_placeholder_path_matches_the_concrete_paths(self):
        script = _script({"kind": "goto", "url": "{base_url}/notes/1"})
        assert touches(script, [parse_address("/notes/{id}")])
        assert touches(script, [parse_address("GET /notes/{id}")])  # a page opened is a GET
        assert not touches(script, [parse_address("/notes")])

    def test_a_route_matches_by_method_and_path(self):
        script = _script({"kind": "http", "method": "POST", "url": "{base_url}/notes/{note_id}/archive"})
        assert touches(script, [parse_address("POST /notes/{id}/archive")])
        assert not touches(script, [parse_address("DELETE /notes/{id}/archive")])

    def test_a_command_matches_by_its_words(self):
        script = _script({"kind": "command", "cmd": "make register-partner ID=acme NAME='Acme Bank'"})
        assert touches(script, [parse_address("make register-partner ID=…")])
        assert not touches(script, [parse_address("make deploy")])

    def test_a_visible_expectation_counts_and_a_backdrop_step_never_does(self):
        own = {"kind": "goto", "url": "{base_url}/", "expect": {"selector_visible": "#note-form"}}
        posed = {"kind": "click", "selector": "#save", BACKDROP_MARK: "note_saved"}
        script = _script(posed, own)
        assert touches(script, [parse_address("#note-form")])
        assert not touches(script, [parse_address("#save")])

    def test_any_of_several_addresses_is_enough(self):
        script = _script({"kind": "click", "selector": "#save"})
        assert touches(script, [parse_address("/nowhere"), parse_address("#save")])


class _Folder:
    def __init__(self, name):
        self.name = name


SCRIPTS = {
    "note_lifecycle": {"scenario": "note_lifecycle", "tags": ["notes"], "step": [{"kind": "http", "method": "POST", "url": "{base_url}/notes"}]},
    "notes_page": {"scenario": "notes_page", "tags": ["page"], "step": [{"kind": "click", "selector": "#save"}]},
    "deletion_guarded": {"scenario": "deletion_guarded", "step": [{"kind": "http", "method": "DELETE", "url": "{base_url}/notes/{note_id}"}]},
}
FOLDERS = [_Folder(n) for n in SCRIPTS]


def _load(folder):
    return SCRIPTS[folder.name]


class TestSelectProofs:
    def test_nothing_narrowed_is_all(self):
        kept, selection = select_proofs(FOLDERS, _load)
        assert [f.name for f in kept] == list(SCRIPTS) and selection == "all"

    def test_tags_keep_the_union_in_original_order(self):
        kept, selection = select_proofs(FOLDERS, _load, tags=["page", "notes"])
        assert [f.name for f in kept] == ["note_lifecycle", "notes_page"]
        assert selection == "--tag page --tag notes"

    def test_touching_keeps_whoever_reaches_the_address(self):
        kept, selection = select_proofs(FOLDERS, _load, touching=["#save", "DELETE /notes/{id}"])
        assert [f.name for f in kept] == ["notes_page", "deletion_guarded"]
        assert selection == "--touching '#save' --touching 'DELETE /notes/{id}'"

    def test_scenario_and_tag_intersect(self):
        kept, selection = select_proofs(FOLDERS, _load, scenario="notes_page", tags=["notes"])
        assert kept == [] and selection == "--scenario notes_page --tag notes"
        kept, _ = select_proofs(FOLDERS, _load, scenario="notes_page", tags=["page"])
        assert [f.name for f in kept] == ["notes_page"]

    def test_a_malformed_address_is_a_drive_error(self):
        with pytest.raises(DriveError, match="route address"):
            select_proofs(FOLDERS, _load, touching=["route: /notes"])


class TestTagsKey:
    def _proof(self, tags):
        return {"scenario": "s", "tags": tags, "criterion": [{"id": "c", "points": 1, "witnesses": ["a"]}], "step": [{"name": "a"}]}

    def test_a_list_of_names_passes(self):
        assert validate_proof(self._proof(["notes", "page"]))["tags"] == ["notes", "page"]

    @pytest.mark.parametrize("tags", ["notes", [""], [1], ["ok", " "]])
    def test_anything_else_is_refused_by_name(self, tags):
        with pytest.raises(ProofError, match="tags is a list of non-empty strings"):
            validate_proof(self._proof(tags))


class TestSelectionIsNamed:
    def test_the_harness_log_opens_with_the_selection(self, tmp_path):
        class _Run:
            evidence_mode = True
            run_dir = tmp_path

        report = DriveReport(
            results=[ScenarioResult("notes_page", [StepResult("open", "goto", True)])],
            selection="--tag page",
        )
        _write_harness_log(_Run(), report)
        lines = (tmp_path / "harness.log").read_text().splitlines()
        assert lines[0] == "selection: --tag page"
        assert lines[1] == "scenario notes_page: ok"

    def test_a_full_run_says_all(self, tmp_path):
        class _Run:
            evidence_mode = True
            run_dir = tmp_path

        _write_harness_log(_Run(), DriveReport())
        assert (tmp_path / "harness.log").read_text().splitlines()[0] == "selection: all"


class TestScopedContract:
    def _contract(self):
        return EvidenceContract(
            schema_version="1.0", project="relay",
            scenarios=[ScenarioContract("a"), ScenarioContract("b")],
        )

    def test_one_name_as_before(self):
        assert [s.scenario for s in scoped_contract(self._contract(), "a").scenarios] == ["a"]

    def test_a_selection_keeps_each_chosen_scenario_and_drops_the_rest(self):
        scoped = scoped_contract(self._contract(), ["b", "zzz"])
        assert [s.scenario for s in scoped.scenarios] == ["b"]

    def test_none_is_the_whole_contract(self):
        contract = self._contract()
        assert scoped_contract(contract, None) is contract
