"""The status bundle: campaign detection, conservative states, blocker
attribution, the queue, spend, and the fixed report shape."""

import json
from datetime import datetime

import pytest

from darkroom.adapter import loads_adapter
from darkroom.cli import main
from darkroom.status import (
    _campaigns,
    assemble_status,
    dumps_status_markdown,
)

NOW = datetime(2026, 9, 28, 16, 30, 0)

BUILDER_LOG = """\
## iteration 1 — 2026-09-28T15:00:00

scenario: gate_closes
score: 0.0 (best 0.0) · stagnation: 0 · action: built
changed: app.py

## iteration 2 — 2026-09-28T15:05:00

scenario: gate_closes
score: 100.0 (best 100.0) · stagnation: 0 · action: converged

## iteration 1 — 2026-09-28T15:10:00

scenario: pending_page
score: 40.0 (best 40.0) · stagnation: 0 · action: built
changed: app.py

## iteration 2 — 2026-09-28T15:12:00

scenario: pending_page
score: 40.0 (best 40.0) · stagnation: 1 · action: built
escalation: diagnostic
changed: app.py

## iteration 1 — 2026-09-28T16:28:00

scenario: badge
score: 66.7 (best 66.7) · stagnation: 0 · action: built
changed: app.py
"""

EVALUATION = {
    "run_id": "r1",
    "evaluated_at": "2026-09-28T15:12:30",
    "rubric_version": "1",
    "scenarios": [
        {
            "scenario": "pending_page",
            "criteria": [
                {"criterion": "briefing", "passed": True,
                 "points_earned": 10, "points_possible": 10},
                {"criterion": "clock_is_real", "passed": False,
                 "points_earned": 0, "points_possible": 10},
            ],
        }
    ],
}

GATES = {
    "schema_version": "1.0",
    "project": "press",
    "peaks": [
        {"scenario": "gate_closes", "score": 100.0, "run_id": "r0",
         "recorded_at": "2026-09-28T15:05:30", "rubric_version": "2", "commit": "abc"}
    ],
}


def _usage_line(role, scenario, cost, at):
    return json.dumps({
        "role": role, "iteration": 1, "model": "m", "duration_seconds": 1.0,
        "recorded_at": at, "input_tokens": 1, "output_tokens": 1,
        "cost_usd": cost, "partial": False, "scenario": scenario,
    })


@pytest.fixture()
def project(tmp_path):
    root = tmp_path / "tenant"
    root.mkdir()
    adapter = loads_adapter(
        '[project]\nname = "press"\n[evidence]\ndir = "evidence"\n'
        'gates = "evidence-gates.json"',
        root=root,
    )
    (root / "evidence-gates.json").write_text(json.dumps(GATES))
    home = tmp_path / "home"
    state = home / "state"
    run = state / "loop" / "20260928T151000-aaaa"
    run.mkdir(parents=True)
    earlier = state / "loop" / "20260927T090000-zzzz"
    earlier.mkdir(parents=True)
    (earlier / "usage.jsonl").write_text(
        _usage_line("judge", "pending_page", 9.0, "2026-09-27T09:00:00") + "\n"
    )
    (root / "darkroom.toml").write_text(
        '[project]\nname = "press"\n[evidence]\ndir = "evidence"\n'
        'gates = "evidence-gates.json"\n'
    )
    (home / "operator.toml").write_text("[loop]\nmax_iterations = 2\n")
    (state / "builder-log.md").write_text(BUILDER_LOG)
    (run / "evaluation-1.json").write_text(json.dumps(EVALUATION))
    (run / "usage.jsonl").write_text(
        _usage_line("builder", "gate_closes", 1.0, "2026-09-28T15:01:00") + "\n"
        + _usage_line("judge", "pending_page", 0.5, "2026-09-28T15:11:00") + "\n"
        + _usage_line("builder", "pending_page", 0.25, "2026-09-28T15:12:00") + "\n"
    )
    (state / "queue" / "interview").mkdir(parents=True)
    (state / "queue" / "interview" / "t2.md").write_text(
        "---\nid: t2\nrole: interview\ntitle: Second thing\npriority: 5\n---\nbody\n"
    )
    (state / "queue" / "interview" / "t1.md").write_text(
        "---\nid: t1\nrole: interview\ntitle: First thing\npriority: 4.6\n---\nbody\n"
    )
    return adapter, state


class TestCampaigns:
    def test_iteration_one_opens_a_fresh_campaign(self):
        iterations = [
            {"number": 1, "scenario": "a", "at": "t1"},
            {"number": 2, "scenario": "a", "at": "t2"},
            {"number": 1, "scenario": "a", "at": "t3"},
        ]
        assert [e["at"] for e in _campaigns(iterations)["a"]] == ["t3"]


class TestStates:
    def test_states_are_conservative(self, project):
        adapter, state = project
        bundle = assemble_status(adapter, state, now=NOW)
        by = {s["scenario"]: s for s in bundle["scenarios"]}
        assert by["gate_closes"]["state"] == "converged"
        assert by["gate_closes"]["gate"]["score"] == 100.0
        # two iterations against a cap of two, 78 minutes quiet: exhausted
        assert by["pending_page"]["state"] == "exhausted"
        assert by["pending_page"]["trajectory"] == [40.0, 40.0]
        assert by["pending_page"]["escalation"] == ["diagnostic"]
        assert by["pending_page"]["failing"] == ["clock_is_real"]
        # one iteration two minutes ago: running, with its last score
        assert by["badge"]["state"] == "running"
        assert by["badge"]["seconds_since_activity"] == 120
        assert bundle["counts"] == {
            "converged": 1, "running": 1, "blocked": 0, "exhausted": 1, "stopped": 0
        }

    def test_quiet_run_under_the_cap_is_stopped_not_exhausted(self, project):
        adapter, state = project
        (state.parent / "operator.toml").write_text("[loop]\nmax_iterations = 6\n")
        bundle = assemble_status(adapter, state, now=NOW)
        by = {s["scenario"]: s for s in bundle["scenarios"]}
        assert by["pending_page"]["state"] == "stopped"

    def test_blocker_attaches_to_the_last_moving_unconverged_campaign(self, project):
        adapter, state = project
        adapter.resolve("HARNESS-BLOCKER.md").write_text("# blocker\nthe drive cites a bare goto\n")
        bundle = assemble_status(adapter, state, now=NOW)
        assert bundle["blocker"]["scenario"] == "badge"
        by = {s["scenario"]: s for s in bundle["scenarios"]}
        assert by["badge"]["state"] == "blocked"
        assert by["gate_closes"]["state"] == "converged"

    def test_campaign_spend_excludes_earlier_campaigns(self, project):
        adapter, state = project
        bundle = assemble_status(adapter, state, now=NOW)
        by = {s["scenario"]: s for s in bundle["scenarios"]}
        # the $9 judge call in the earlier run directory is not this campaign's
        assert by["pending_page"]["campaign_spend_usd"] == 0.75
        assert bundle["spend"]["cost_usd"] == 10.75

    def test_queue_in_priority_order(self, project):
        adapter, state = project
        bundle = assemble_status(adapter, state, now=NOW)
        assert [t["id"] for t in bundle["queue"]] == ["t1", "t2"]

    def test_scenario_filter(self, project):
        adapter, state = project
        bundle = assemble_status(adapter, state, scenario="badge", now=NOW)
        assert [s["scenario"] for s in bundle["scenarios"]] == ["badge"]


class TestReport:
    def test_shape_is_fixed(self, project):
        adapter, state = project
        text = dumps_status_markdown(assemble_status(adapter, state, now=NOW))
        headings = [line for line in text.splitlines() if line.startswith("## ")]
        assert headings == [
            "## convergence", "## last run", "## blocker", "## queue", "## metered equivalent",
        ]
        assert "3 campaign(s): 1 converged · 1 running · 1 exhausted" in text
        assert "| gate_closes | converged | 2 | 0 → 100 | 100 | 100 | $1.00 |" in text
        assert "failing: clock_is_real" in text
        assert "- interview/t1 — First thing (4.6)" in text

    def test_last_run_names_its_selection(self, project):
        adapter, state = project
        runs = adapter.root / "evidence" / "runs"
        (runs / "2026-10-09T10-00-00").mkdir(parents=True)
        (runs / "2026-10-09T10-00-00" / "harness.log").write_text(
            "selection: all\nscenario gate_closes: ok\nscenario badge: FAILED\n"
        )
        (runs / "2026-10-09T11-00-00").mkdir()
        (runs / "2026-10-09T11-00-00" / "harness.log").write_text(
            "selection: --touching '#save'\nscenario gate_closes: ok\n"
        )
        bundle = assemble_status(adapter, state, now=NOW)
        assert bundle["last_run"] == {
            "run": "2026-10-09T11-00-00", "selection": "--touching '#save'",
            "scenarios": 1, "green": 1, "partial": True,
        }
        text = dumps_status_markdown(bundle)
        assert "2026-10-09T11-00-00: 1/1 green · selection --touching '#save' (a partial run" in text

    def test_last_run_without_a_selection_line_is_unknown(self, project):
        adapter, state = project
        run = adapter.root / "evidence" / "runs" / "2026-10-01T00-00-00"
        run.mkdir(parents=True)
        (run / "harness.log").write_text("scenario gate_closes: ok\n")
        last = assemble_status(adapter, state, now=NOW)["last_run"]
        assert last["selection"] == "unknown" and last["partial"] is False
        assert "selection unknown" in dumps_status_markdown(
            assemble_status(adapter, state, now=NOW)
        )

    def test_no_run_is_no_run(self, project):
        adapter, state = project
        bundle = assemble_status(adapter, state, now=NOW)
        assert bundle["last_run"] is None
        assert "no run on record" in dumps_status_markdown(bundle)

    def test_empty_state_reports_nothing_ran(self, tmp_path):
        root = tmp_path / "t"
        root.mkdir()
        adapter = loads_adapter('[project]\nname = "p"', root=root)
        text = dumps_status_markdown(assemble_status(adapter, tmp_path / "s", now=NOW))
        assert "no campaigns in loop state yet" in text


class TestCli:
    def test_status_json(self, project, capsys):
        adapter, state = project
        code = main(
            ["status", "--project", str(adapter.root), "--state", str(state), "--format", "json"]
        )
        assert code == 0
        bundle = json.loads(capsys.readouterr().out)
        assert bundle["project"] == "press"
        assert {s["scenario"] for s in bundle["scenarios"]} == {
            "gate_closes", "pending_page", "badge"
        }
