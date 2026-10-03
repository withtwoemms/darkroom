"""The surfaces doc string: the spec's declared contract, cross-checked
against the exam's steps by the audit."""

import sys
import textwrap

from darkroom.audit import audit, has_errors

if sys.version_info >= (3, 11):
    import tomllib
else:  # pragma: no cover
    import tomli as tomllib
from darkroom.surfaces import (
    Surface,
    cross_check,
    normalize_path,
    parse_surfaces,
    touched_surfaces,
)
from darkroom.vault import FilesystemVault

SPEC = """\
Feature: deletion is token-guarded
  Scenario: only the holder of the note's token may delete it
    Given a note with a token
    When a wrong token tries to delete it
    Then the deletion is refused
    And the surfaces hold:
      \"\"\"surfaces
      POST /notes                        → 201 {id, token}
      DELETE /notes/{id}  X-Note-Token   -> 204; wrong token → 403; after → 404
      #delete-button                     [data-state=armed|fired]
      \"\"\"
    And the step's own doc string is not a contract:
      \"\"\"
      GET /never — a plain doc string, outside the surfaces
      \"\"\"
"""

PROOF = """\
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
name = "arm"
kind = "click"
selector = "#delete-button"

[[criterion]]
id = "gone"
points = 1
witnesses = ["delete"]
"""


class TestParse:
    def test_block_is_parsed_to_routes_and_selectors(self):
        surfaces = parse_surfaces(SPEC)
        assert surfaces == [
            Surface("route", "POST", "/notes", "POST /notes                        → 201 {id, token}"),
            Surface(
                "route", "DELETE", "/notes/*",
                "DELETE /notes/{id}  X-Note-Token   -> 204; wrong token → 403; after → 404",
            ),
            Surface(
                "selector", target="#delete-button",
                line="#delete-button                     [data-state=armed|fired]",
            ),
        ]

    def test_no_doc_string_means_nothing_declared(self):
        assert parse_surfaces("Feature: x\n  Scenario: y\n    Build: GET /x -> 200\n") is None
        assert parse_surfaces('Feature: x\n  Scenario: y\n    Given x:\n      """\n      GET /x\n      """\n') is None
        assert parse_surfaces('Feature: x\n  Scenario: y\n    Given x:\n      """surfaces\n      """\n') == []

    def test_compound_selector_keeps_its_descendant_parts(self):
        text = (
            "Feature: x\n  Scenario: a\n    Then a:\n      ```surfaces\n"
            "      #notes li                   one item per saved note\n"
            "      input[name=\"text\"]          the field\n"
            "      ```\n"
        )
        assert [s.target for s in parse_surfaces(text)] == ["#notes li", 'input[name="text"]']

    def test_markdown_fences_and_several_blocks_add_up(self):
        text = (
            "Feature: x\n"
            "  Scenario: a\n    Then a:\n      ```surfaces\n      GET /a → 200\n      ```\n"
            "  Scenario: b\n    Then b:\n      ```surfaces\n      #b\n      ```\n"
        )
        assert [str(s) for s in parse_surfaces(text)] == ["GET /a", "#b"]

    def test_paths_normalize(self):
        assert normalize_path("{base_url}/notes/{note_id}?x=1") == "/notes/*"
        assert normalize_path("http://localhost:8000/hearth/") == "/hearth"
        assert normalize_path("/") == "/"
        assert normalize_path("{base_url}") == "/"


class TestTouched:
    def test_steps_touch_routes_and_selectors(self):
        script = {
            "step": [
                {"kind": "http", "url": "{base_url}/notes"},
                {"kind": "goto", "url": "{base_url}/hearth"},
                {"kind": "click", "selector": "#send"},
                {"kind": "fill", "fields": {"#title": "x"}},
                {"kind": "screenshot", "expect": {"selector_visible": ".card"}},
                {"kind": "http", "url": "{base_url}/notes"},  # deduplicated
            ]
        }
        assert [str(s) for s in touched_surfaces(script)] == [
            "GET /notes", "GET /hearth", "#send", "#title", ".card",
        ]


class TestCrossCheck:
    def test_matching_exam_is_clean(self):
        assert cross_check(parse_surfaces(SPEC), tomllib.loads(PROOF)) == []

    def test_both_directions_are_reported(self):
        script = tomllib.loads(PROOF.replace("/notes/{note_id}?force=1", "/notes/{note_id}/purge"))
        codes = cross_check(parse_surfaces(SPEC), script)
        assert [c for c, _ in codes] == ["surface-undeclared", "surface-untouched"]
        assert "DELETE /notes/*/purge" in codes[0][1] and "DELETE /notes/*" in codes[1][1]


def _project(tmp_path, spec_text):
    proofs = tmp_path / "proofs"
    proofs.mkdir()
    (proofs / "deletion_guarded.proof.toml").write_text(PROOF)
    specs = tmp_path / "scenarios"
    specs.mkdir()
    spec = specs / "deletion_guarded.feature"
    spec.write_text(textwrap.dedent(spec_text))
    return FilesystemVault(tmp_path / "vault"), proofs, [spec]


class TestAuditIntegration:
    def test_findings_carry_codes_and_never_errors(self, tmp_path):
        vault, proofs, specs = _project(
            tmp_path, SPEC.replace("#delete-button                     [data-state=armed|fired]", "#other")
        )
        findings = audit(vault, proofs, specs=specs)
        assert not has_errors(findings)
        assert [(f.severity, f.code) for f in findings] == [
            ("warning", "surface-undeclared"), ("info", "surface-untouched"),
        ]
        assert findings[0].scenario == "deletion_guarded"

    def test_spec_without_doc_string_yields_nothing(self, tmp_path):
        vault, proofs, specs = _project(tmp_path, "Feature: x\n  Build: GET /anything -> 200\n")
        assert audit(vault, proofs, specs=specs) == []

    def test_scenario_without_spec_yields_nothing(self, tmp_path):
        vault, proofs, _ = _project(tmp_path, SPEC)
        assert audit(vault, proofs, specs=[tmp_path / "scenarios" / "other.feature"]) == []
