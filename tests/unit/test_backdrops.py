"""Backdrops: named step sequences expanded ahead of an exposure's own
steps, names intact so witnesses resolve, collisions refused."""

import pytest

from darkroom.backdrops import BackdropError, expand, load_backdrops, loads_backdrops

BACKDROPS = """
[[backdrop]]
name = "note_saved"
[[backdrop.step]]
name = "save_note"
kind = "goto"
url = "{base_url}/"
[[backdrop.step]]
name = "create"
kind = "click"
selector = "#save"

[[backdrop]]
name = "note_archived"
[[backdrop.step]]
name = "archive_note"
method = "POST"
url = "{base_url}/notes/1/archive"
"""


class TestLoad:
    def test_loads_named_sequences(self):
        backdrops = loads_backdrops(BACKDROPS)
        assert list(backdrops) == ["note_saved", "note_archived"]
        assert [s["name"] for s in backdrops["note_saved"]] == ["save_note", "create"]

    def test_absent_file_means_no_backdrops(self, tmp_path):
        assert load_backdrops(tmp_path / "backdrops.toml") == {}
        assert load_backdrops(None) == {}

    def test_refuses_duplicates_and_empties(self):
        with pytest.raises(BackdropError, match="defined twice"):
            loads_backdrops(BACKDROPS + BACKDROPS)
        with pytest.raises(BackdropError, match="no steps"):
            loads_backdrops('[[backdrop]]\nname = "empty"\n')


class TestExpand:
    def test_backdrops_lead_the_exposures_own_steps_in_order(self):
        script = {
            "scenario": "s",
            "backdrop": ["note_saved", "note_archived"],
            "step": [{"name": "fetch", "kind": "http", "url": "x"}],
        }
        expanded = expand(script, loads_backdrops(BACKDROPS))
        assert [s["name"] for s in expanded["step"]] == [
            "save_note", "create", "archive_note", "fetch",
        ]
        assert "backdrop" not in expanded
        assert script["step"] == [{"name": "fetch", "kind": "http", "url": "x"}]  # untouched

    def test_no_backdrop_is_the_identity(self):
        script = {"scenario": "s", "step": [{"name": "a"}]}
        assert expand(script, {}) is script

    def test_unknown_backdrop_is_named(self):
        with pytest.raises(BackdropError, match="unknown backdrop 'nope'"):
            expand({"scenario": "s", "backdrop": ["nope"]}, loads_backdrops(BACKDROPS))

    def test_colliding_step_names_are_refused(self):
        script = {
            "scenario": "s",
            "backdrop": ["note_saved"],
            "step": [{"name": "create", "kind": "click", "selector": "#x"}],
        }
        with pytest.raises(BackdropError, match="step 'create' from the exposure itself collides"):
            expand(script, loads_backdrops(BACKDROPS))

    def test_backdrop_must_be_a_list_of_names(self):
        with pytest.raises(BackdropError, match="list of names"):
            expand({"scenario": "s", "backdrop": "note_saved"}, loads_backdrops(BACKDROPS))
