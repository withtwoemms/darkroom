"""Backdrops: named step sequences expanded ahead of an exposure's own
steps, names intact so witnesses resolve, collisions refused."""

import pytest

from darkroom.backdrops import BackdropError, expand, load_backdrops, loads_backdrops

BACKDROPS = """
[[backdrop]]
name = "founded"
[[backdrop.step]]
name = "found_circle"
kind = "goto"
url = "{base_url}/setup"
[[backdrop.step]]
name = "create"
kind = "click"
selector = "#create-circle"

[[backdrop]]
name = "mom_joins"
[[backdrop.step]]
name = "invite_mom"
method = "POST"
url = "{base_url}/invites"
"""


class TestLoad:
    def test_loads_named_sequences(self):
        backdrops = loads_backdrops(BACKDROPS)
        assert list(backdrops) == ["founded", "mom_joins"]
        assert [s["name"] for s in backdrops["founded"]] == ["found_circle", "create"]

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
            "backdrop": ["founded", "mom_joins"],
            "step": [{"name": "seal", "kind": "http", "url": "x"}],
        }
        expanded = expand(script, loads_backdrops(BACKDROPS))
        assert [s["name"] for s in expanded["step"]] == [
            "found_circle", "create", "invite_mom", "seal",
        ]
        assert "backdrop" not in expanded
        assert script["step"] == [{"name": "seal", "kind": "http", "url": "x"}]  # untouched

    def test_no_backdrop_is_the_identity(self):
        script = {"scenario": "s", "step": [{"name": "a"}]}
        assert expand(script, {}) is script

    def test_unknown_backdrop_is_named(self):
        with pytest.raises(BackdropError, match="unknown backdrop 'nope'"):
            expand({"scenario": "s", "backdrop": ["nope"]}, loads_backdrops(BACKDROPS))

    def test_colliding_step_names_are_refused(self):
        script = {
            "scenario": "s",
            "backdrop": ["founded"],
            "step": [{"name": "create", "kind": "click", "selector": "#x"}],
        }
        with pytest.raises(BackdropError, match="step 'create' from the exposure itself collides"):
            expand(script, loads_backdrops(BACKDROPS))

    def test_backdrop_must_be_a_list_of_names(self):
        with pytest.raises(BackdropError, match="list of names"):
            expand({"scenario": "s", "backdrop": "founded"}, loads_backdrops(BACKDROPS))
