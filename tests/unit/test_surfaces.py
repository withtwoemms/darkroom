"""The .surfaces file: engineering's published interface, cross-checked
against the exposure's steps by the audit, drafted by migrate from a
spec's Build: note."""

import sys
import textwrap

import pytest

from darkroom.audit import audit, has_errors

if sys.version_info >= (3, 11):
    import tomllib
else:  # pragma: no cover
    import tomli as tomllib
from darkroom.proof import EXPOSURE_FILE, RUBRIC_FILE
from darkroom.surfaces import (
    SurfacesError,
    build_notes,
    cross_check,
    draft_surfaces,
    normalize_path,
    parse_surfaces,
    surfaces_path,
    touched_surfaces,
)
from darkroom.vault import FilesystemVault

SURFACES = """\
[routes]
POST /notes                        → 201 {id, token}
DELETE /notes/{id}                 X-Note-Token; 204; wrong token → 403
                                   after → 404
GET  /notes/{id}                   200 while it exists

[commands]
relay.py export                    writes notes.json; exit 0

[pages]
/                                  the form
#delete-button                     [data-state=armed|fired]
#notes li                          one item per saved note

[files]
notes.json                         the export

[notes]
deleting needs no ceremony — it only removes
and a second line
"""

EXPOSURE = """
scenario = "deletion_guarded"

[[step]]
name = "create"
method = "POST"
url = "{base_url}/notes"
save = { note_id = "$.id" }

[[step]]
name = "delete"
method = "DELETE"
url = "{base_url}/notes/{note_id}?force=1"
expect = { status = 204 }

[[step]]
name = "gone"
url = "{base_url}/notes/{note_id}"
expect = { status = 404 }

[[step]]
name = "home"
kind = "goto"
url = "{base_url}/"

[[step]]
name = "arm"
kind = "click"
selector = "#delete-button"
expect = { selector_visible = "#notes li" }

[[step]]
name = "export"
kind = "command"
cmd = "python3 relay.py export --out {dir}"
"""

RUBRIC = """
[[criterion]]
id = "gone"
points = 1
witnesses = ["delete"]
"""


class TestParse:
    def test_sections_parse_to_surfaces_with_descriptions(self):
        surfaces = parse_surfaces(SURFACES)
        assert [str(s) for s in surfaces.entries] == [
            "POST /notes", "DELETE /notes/*", "GET /notes/*", "relay.py export",
            "/", "#delete-button", "#notes li", "notes.json",
        ]
        kinds = {str(s): s.kind for s in surfaces.entries}
        assert kinds["/"] == "page" and kinds["#notes li"] == "selector"
        assert kinds["relay.py export"] == "command" and kinds["notes.json"] == "file"
        by_name = {str(s): s.description for s in surfaces.entries}
        assert by_name["DELETE /notes/*"] == "X-Note-Token; 204; wrong token → 403 after → 404"
        assert by_name["POST /notes"] == "→ 201 {id, token}"
        assert surfaces.notes == "deleting needs no ceremony — it only removes\nand a second line"

    def test_empty_text_publishes_nothing(self):
        assert parse_surfaces("").entries == [] and parse_surfaces("[routes]\n").entries == []

    @pytest.mark.parametrize(
        "text, message",
        [
            ("[widgets]\n", "unknown section"),
            ("POST /x\n[routes]\n", "before the first"),
            ("[routes]\n/notes  no method\n", "opens with an HTTP method"),
        ],
    )
    def test_malformed_is_refused_by_line(self, text, message):
        with pytest.raises(SurfacesError, match=message):
            parse_surfaces(text)

    def test_paths_normalize(self):
        assert normalize_path("{base_url}/notes/{note_id}?x=1") == "/notes/*"
        assert normalize_path("http://localhost:8000/home/") == "/home"
        assert normalize_path("/") == "/"
        assert normalize_path("{base_url}") == "/"

    def test_surfaces_sit_beside_the_spec(self, tmp_path):
        assert surfaces_path(tmp_path / "scenarios" / "notes_page.feature") == (
            tmp_path / "scenarios" / "notes_page.surfaces"
        )


class TestTouched:
    def test_steps_touch_routes_pages_selectors_and_commands(self):
        assert [str(s) for s in touched_surfaces(tomllib.loads(EXPOSURE))] == [
            "POST /notes", "DELETE /notes/*", "GET /notes/*", "/", "#delete-button",
            "#notes li", "python3 relay.py export --out *",
        ]
        kinds = [s.kind for s in touched_surfaces(tomllib.loads(EXPOSURE))]
        assert kinds == ["route", "route", "route", "page", "selector", "selector", "command"]


class TestCrossCheck:
    def test_matching_exposure_is_clean(self):
        assert cross_check(parse_surfaces(SURFACES), tomllib.loads(EXPOSURE)) == []

    def test_both_directions_are_reported(self):
        script = tomllib.loads(EXPOSURE.replace("/notes/{note_id}?force=1", "/notes/{note_id}/purge"))
        codes = cross_check(parse_surfaces(SURFACES), script)
        assert [c for c, _ in codes] == ["surface-unpublished", "surface-untouched"]
        assert "DELETE /notes/*/purge" in codes[0][1] and "DELETE /notes/*" in codes[1][1]

    def test_a_page_opened_and_a_page_fetched_are_one_surface(self):
        published = parse_surfaces("[pages]\n/me   the home page\n")
        assert cross_check(published, {"step": [{"kind": "http", "url": "{base_url}/me"}]}) == []
        published = parse_surfaces("[routes]\nGET /me   the home page\n")
        assert cross_check(published, {"step": [{"kind": "goto", "url": "{base_url}/me"}]}) == []

    def test_a_command_matches_by_its_words_in_order(self):
        published = parse_surfaces("[commands]\nrelay.py export   the export\n")
        assert cross_check(published, {"step": [{"kind": "command", "cmd": "python3 relay.py export"}]}) == []
        [(code, _)] = [
            f for f in cross_check(published, {"step": [{"kind": "command", "cmd": "relay.py import"}]})
            if f[0] == "surface-unpublished"
        ]
        assert code == "surface-unpublished"

    def test_the_judge_gets_addresses_and_never_the_builders_prose(self):
        from darkroom.surfaces import inventory

        listed = inventory(parse_surfaces(SURFACES))
        assert listed == (
            "[routes]\nPOST /notes\nDELETE /notes/*\nGET /notes/*\n\n"
            "[commands]\nrelay.py export\n\n"
            "[pages]\n/\n#delete-button\n#notes li\n\n"
            "[files]\nnotes.json"
        )
        for prose in ("wrong token", "one item per", "ceremony", "writes notes.json"):
            assert prose not in listed
        assert inventory(parse_surfaces("[notes]\nonly prose\n")) == ""

    def test_a_selector_narrowed_to_a_state_is_the_same_surface(self):
        published = parse_surfaces("[pages]\n#start-door   the one action\n")
        narrowed = {"step": [{"kind": "click", "selector": '#start-door[data-starts-from="home"]'}]}
        assert cross_check(published, narrowed) == []
        published = parse_surfaces('[pages]\n#notes li[data-note-id]   one per item\n')
        broader = {"step": [{"kind": "click", "selector": "#notes li"}]}
        assert cross_check(published, broader) == []
        other = {"step": [{"kind": "click", "selector": "#start-doorbell"}]}
        codes = [c for c, _ in cross_check(parse_surfaces("[pages]\n#start-door   x\n"), other)]
        assert codes == ["surface-unpublished", "surface-untouched"]

    def test_a_command_probing_the_app_is_not_a_command_surface(self):
        probe = {"step": [{"kind": "command", "cmd": "curl -s {base_url}/ | grep -c 'name=\"handle\"'"}]}
        assert touched_surfaces(probe) == []
        assert cross_check(parse_surfaces(""), probe) == []

    def test_a_shell_script_step_is_harness_not_a_surface(self):
        scripts = [
            "cat > /tmp/stub.py <<'PY'\nprint(1)\nPY\nnohup python /tmp/stub.py &",
            "pkill -f stub.py || true; echo tidy",
            "port=$(echo x); kill $port",
            "relay export | tee out.json",
        ]
        for cmd in scripts:
            assert touched_surfaces({"step": [{"kind": "command", "cmd": cmd}]}) == [], cmd
        plain = {"step": [{"kind": "command", "cmd": "relay export --out {dir}"}]}
        assert [str(s) for s in touched_surfaces(plain)] == ["relay export --out *"]

    def test_files_are_for_the_reader_never_checked(self):
        assert cross_check(parse_surfaces("[files]\nout.json   the export\n"), {"step": []}) == []


def _project(tmp_path, surfaces_text):
    proofs = tmp_path / "proofs" / "deletion_guarded"
    proofs.mkdir(parents=True)
    (proofs / EXPOSURE_FILE).write_text(EXPOSURE)
    (proofs / RUBRIC_FILE).write_text(RUBRIC)
    specs = tmp_path / "scenarios"
    specs.mkdir()
    spec = specs / "deletion_guarded.feature"
    spec.write_text("Feature: deletion\n  Scenario: guarded\n    Given a note\n")
    if surfaces_text is not None:
        (specs / "deletion_guarded.surfaces").write_text(textwrap.dedent(surfaces_text))
    return FilesystemVault(tmp_path / "vault"), proofs.parent, [spec]


class TestAuditIntegration:
    def test_findings_carry_codes_and_never_errors(self, tmp_path):
        vault, proofs, specs = _project(tmp_path, SURFACES.replace("#delete-button", "#other"))
        findings = audit(vault, proofs, specs=specs)
        assert not has_errors(findings)
        assert [(f.severity, f.code) for f in findings] == [
            ("warning", "surface-unpublished"), ("info", "surface-untouched"),
        ]
        assert findings[0].scenario == "deletion_guarded"

    def test_nothing_published_yields_nothing(self, tmp_path):
        vault, proofs, specs = _project(tmp_path, None)
        assert audit(vault, proofs, specs=specs) == []

    def test_malformed_surfaces_is_an_error(self, tmp_path):
        vault, proofs, specs = _project(tmp_path, "[routes]\n/no-method  x\n")
        [finding] = audit(vault, proofs, specs=specs)
        assert finding.severity == "error" and finding.code == "surfaces-malformed"
        assert "deletion_guarded.surfaces" in finding.message

    def test_scenario_without_spec_yields_nothing(self, tmp_path):
        vault, proofs, _ = _project(tmp_path, SURFACES)
        assert audit(vault, proofs, specs=[tmp_path / "scenarios" / "other.feature"]) == []


SPEC_WITH_BUILD = """\
Feature: a note marked "read once" is gone after the first read
  Scenario: gone once the reader has it
    A member posts a read-once note on the default clock.

  Build: `POST /workspaces/{slug}/notes/{id}/ack` (recipient session)
  is the device's confirmation; it answers `{state}`. The browser calls it
  right after rendering `#opened-note`. Any read of a gone note → 410
  `gone`. The author's `#sent-notes` entry shows `data-gone-reason="read"`;
  the home page is `/me`.

  Build: a second note, `GET /me/unread` lists them.
"""


class TestDraft:
    def test_build_notes_are_paragraphs(self):
        notes = build_notes(SPEC_WITH_BUILD)
        assert len(notes) == 2
        assert notes[0].startswith("`POST /workspaces/{slug}/notes/{id}/ack` (recipient session)")
        assert notes[1] == "a second note, `GET /me/unread` lists them."

    def test_draft_lifts_routes_and_pages_and_keeps_the_prose(self):
        draft = draft_surfaces(SPEC_WITH_BUILD)
        surfaces = parse_surfaces(draft)
        assert [str(s) for s in surfaces.of("route")] == [
            "POST /workspaces/*/notes/*/ack", "GET /me/unread",
        ]
        assert [str(s) for s in surfaces.of("page", "selector")] == [
            "#opened-note", "#sent-notes", "/me",
        ]
        assert "device's confirmation" in surfaces.notes and "second note" in surfaces.notes
        assert all(s.description == "" for s in surfaces.entries)  # engineering's to add

    def test_no_build_note_means_no_draft(self):
        assert draft_surfaces("Feature: x\n  Scenario: y\n    Given z\n") is None


class TestFirstSliceFindings:
    """Four precision defects the first backdrop-posed scenario surfaced."""

    def test_backdrop_steps_are_the_owning_scenarios_surfaces(self):
        from darkroom.backdrops import expand, loads_backdrops

        backdrops = loads_backdrops(
            '[[backdrop]]\nname = "founded"\n[[backdrop.step]]\nname = "found"\nkind = "goto"\n'
            'url = "{base_url}/setup"\n'
        )
        script = expand(
            {"scenario": "s", "backdrop": ["founded"], "step": [{"kind": "goto", "url": "{base_url}/me"}]},
            backdrops,
        )
        assert [str(s) for s in touched_surfaces(script)] == ["/me"]

    def test_a_runtime_path_is_not_addressable(self):
        steps = [
            {"kind": "goto", "url": "{base_url}{request_link}"},
            {"kind": "http", "url": "{base_url}{link}?x=1"},
            {"kind": "goto", "url": "{base_url}/agent-requests/{request_id}"},
        ]
        assert [str(s) for s in touched_surfaces({"step": steps})] == ["/agent-requests/*"]

    def test_attribute_values_never_decide_a_selector_match(self):
        published = parse_surfaces("[pages]\n#approve[data-partner]   the gesture\n")
        touched = {"step": [{"kind": "click", "selector": '#approve[data-partner="acme"]'}]}
        assert cross_check(published, touched) == []
        published = parse_surfaces('[pages]\nmain[data-agent-status="pending"]   x\n')
        touched = {"step": [{"kind": "click", "selector": 'main[data-agent-status="admitted"]', "expect": {}}]}
        assert cross_check(published, touched) == []

    def test_a_published_command_with_placeholders_matches_the_words_run(self):
        published = parse_surfaces("[commands]\nmake register-partner ID=… NAME=… KEY=…   operator-only\n")
        run = {"step": [{"kind": "command", "cmd": "make register-partner ID=acme NAME='Acme Bank' KEY='*' DATABASE_URL=postgresql://x"}]}
        assert cross_check(published, run) == []
        other = {"step": [{"kind": "command", "cmd": "make deploy ID=acme"}]}
        assert [c for c, _ in cross_check(published, other)] == ["surface-unpublished", "surface-untouched"]
