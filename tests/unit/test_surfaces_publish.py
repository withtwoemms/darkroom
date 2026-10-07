"""darkroom surfaces: a baseline publication drafted from what an exposure
reaches, or merged into a file that lacks addresses — so the audit holds
every exposure to something real before engineering has written."""

import textwrap

from darkroom.cli import main
from darkroom.proof import EXPOSURE_FILE, RUBRIC_FILE
from darkroom.surfaces import (
    DRAFT_NOTE,
    cross_check,
    draft_from_exposure,
    merge_addresses,
    parse_surfaces,
)

SCRIPT = {
    "scenario": "notes_page",
    "step": [
        {"kind": "goto", "url": "{base_url}/", "expect": {"selector_visible": "#note-form"}},
        {"kind": "fill", "fields": {"#note-text": "x"}},
        {"kind": "click", "selector": "#save", "expect": {"selector_visible": "#notes li"}},
        {"kind": "http", "method": "POST", "url": "{base_url}/notes"},
        {"kind": "command", "cmd": "relay export --out {dir}"},
        {"kind": "command", "cmd": "curl -s {base_url}/"},  # a probe, not a surface
    ],
}


class TestDraft:
    def test_every_touched_address_is_published_without_descriptions(self):
        text = draft_from_exposure(SCRIPT)
        surfaces = parse_surfaces(text)
        assert [str(s) for s in surfaces.of("route")] == ["POST /notes"]
        assert [str(s) for s in surfaces.of("page", "selector")] == [
            "/", "#note-form", "#note-text", "#save", "#notes li",
        ]
        assert [str(s) for s in surfaces.of("command")] == ["relay export --out *"]
        assert all(s.description == "" for s in surfaces.entries)
        assert surfaces.notes == DRAFT_NOTE
        assert cross_check(surfaces, SCRIPT) == []  # the audit is clean against it


class TestMerge:
    def test_missing_addresses_join_their_sections_and_existing_lines_stay(self):
        existing = textwrap.dedent("""\
            [routes]
            POST /notes          → 201 {id, token}

            [commands]

            [pages]
            #note-form           the form

            [files]

            [notes]
            the form posts the whole page
            """)
        text, added = merge_addresses(existing, SCRIPT)
        assert sorted(added) == sorted(["/", "#note-text", "#save", "#notes li", "relay export --out *"])
        assert "POST /notes          → 201 {id, token}" in text  # verbatim
        assert "the form posts the whole page" in text
        merged = parse_surfaces(text)
        assert cross_check(merged, SCRIPT) == []
        again, added_again = merge_addresses(text, SCRIPT)
        assert again == text and added_again == []

    def test_a_section_the_file_lacks_is_created_before_notes(self):
        existing = "[routes]\nPOST /notes   x\n\n[notes]\nhello\n"
        text, added = merge_addresses(existing, {"step": [{"kind": "command", "cmd": "relay export"}]})
        assert added == ["relay export"]
        assert text.index("[commands]\nrelay export") < text.index("[notes]")
        assert parse_surfaces(text).of("command")[0].target == "relay export"


class TestCli:
    def _tenant(self, tmp_path, monkeypatch):
        monkeypatch.setenv("DARKROOM_HOME", str(tmp_path / "home"))
        root = tmp_path / "tenant"
        (root / "scenarios").mkdir(parents=True)
        (root / "darkroom.toml").write_text(
            '[project]\nname = "press"\n[scenarios]\nspec_glob = "scenarios/*.feature"\n'
        )
        (root / "scenarios" / "notes_page.feature").write_text("Feature: n\n  Scenario: p\n    Given x\n")
        (root / "scenarios" / "other.feature").write_text("Feature: o\n  Scenario: q\n    Given y\n")
        proofs = tmp_path / "home" / "projects" / "press" / "proofs" / "notes_page"
        proofs.mkdir(parents=True)
        (proofs / EXPOSURE_FILE).write_text(textwrap.dedent("""
            scenario = "notes_page"
            [[step]]
            name = "open"
            kind = "goto"
            url = "{base_url}/"
            expect = { selector_visible = "#note-form" }
            [[step]]
            name = "save"
            kind = "click"
            selector = "#save"
        """))
        (proofs / RUBRIC_FILE).write_text('[[criterion]]\nid = "a"\npoints = 1\nwitnesses = ["open"]\n')
        return root

    def test_drafts_only_scenarios_with_an_exposure_and_merges_on_request(self, tmp_path, monkeypatch, capsys):
        root = self._tenant(tmp_path, monkeypatch)
        assert main(["surfaces", "--check", "--project", str(root)]) == 0
        out = capsys.readouterr().out
        assert "notes_page.surfaces drafted" in out and "(check only)" in out
        assert not (root / "scenarios" / "notes_page.surfaces").exists()

        assert main(["surfaces", "--project", str(root)]) == 0
        drafted = (root / "scenarios" / "notes_page.surfaces").read_text()
        assert "#note-form" in drafted and "#save" in drafted and DRAFT_NOTE in drafted
        assert not (root / "scenarios" / "other.surfaces").exists()  # no exposure, no draft

        (root / "scenarios" / "notes_page.surfaces").write_text("[pages]\n#note-form   the form\n")
        assert main(["surfaces", "--project", str(root)]) == 0
        assert "0 drafted, 0 merged, 1 left as published" in capsys.readouterr().out
        assert main(["surfaces", "--merge", "--project", str(root)]) == 0
        out = capsys.readouterr().out
        assert "+2: /, #save" in out and "1 merged" in out
        assert "#note-form   the form" in (root / "scenarios" / "notes_page.surfaces").read_text()
