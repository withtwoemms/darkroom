"""Preludes: named step sequences included ahead of an exam's own steps,
names intact so witnesses resolve, collisions refused."""

import pytest

from darkroom.preludes import PreludeError, expand, load_preludes, loads_preludes

PRELUDES = """
[[prelude]]
name = "founded"
[[prelude.step]]
name = "found_circle"
kind = "goto"
url = "{base_url}/setup"
[[prelude.step]]
name = "create"
kind = "click"
selector = "#create-circle"

[[prelude]]
name = "mom_joins"
[[prelude.step]]
name = "invite_mom"
method = "POST"
url = "{base_url}/invites"
"""


class TestLoad:
    def test_loads_named_sequences(self):
        preludes = loads_preludes(PRELUDES)
        assert list(preludes) == ["founded", "mom_joins"]
        assert [s["name"] for s in preludes["founded"]] == ["found_circle", "create"]

    def test_absent_file_means_no_preludes(self, tmp_path):
        assert load_preludes(tmp_path / "preludes.toml") == {}
        assert load_preludes(None) == {}

    def test_refuses_duplicates_and_empties(self):
        with pytest.raises(PreludeError, match="defined twice"):
            loads_preludes(PRELUDES + PRELUDES)
        with pytest.raises(PreludeError, match="no steps"):
            loads_preludes('[[prelude]]\nname = "empty"\n')


class TestExpand:
    def test_includes_lead_the_exams_own_steps_in_order(self):
        script = {
            "scenario": "s",
            "include": ["founded", "mom_joins"],
            "step": [{"name": "seal", "kind": "http", "url": "x"}],
        }
        expanded = expand(script, loads_preludes(PRELUDES))
        assert [s["name"] for s in expanded["step"]] == [
            "found_circle", "create", "invite_mom", "seal",
        ]
        assert "include" not in expanded
        assert script["step"] == [{"name": "seal", "kind": "http", "url": "x"}]  # untouched

    def test_no_include_is_the_identity(self):
        script = {"scenario": "s", "step": [{"name": "a"}]}
        assert expand(script, {}) is script

    def test_unknown_prelude_is_named(self):
        with pytest.raises(PreludeError, match="unknown prelude 'nope'"):
            expand({"scenario": "s", "include": ["nope"]}, loads_preludes(PRELUDES))

    def test_colliding_step_names_are_refused(self):
        script = {
            "scenario": "s",
            "include": ["founded"],
            "step": [{"name": "create", "kind": "click", "selector": "#x"}],
        }
        with pytest.raises(PreludeError, match="step 'create' from the exam itself collides"):
            expand(script, loads_preludes(PRELUDES))

    def test_include_must_be_a_list_of_names(self):
        with pytest.raises(PreludeError, match="list of names"):
            expand({"scenario": "s", "include": "founded"}, loads_preludes(PRELUDES))
