"""The worker pool: longest-first scheduling, and bundles that cross a
process boundary and come back in the original order."""

from datetime import datetime
from pathlib import Path

from darkroom.drive import (
    DriveReport,
    ScenarioResult,
    StepResult,
    _bundle_from_dict,
    _bundle_to_dict,
    _previous_durations,
    schedule,
)
from darkroom.model import EvidenceItem, ScenarioBundle


class TestSchedule:
    def test_longest_first_then_unknown_then_name(self):
        paths = [Path(p) for p in ("c_quick", "a_slow", "b_unknown", "d_mid")]
        order = schedule(paths, {"a_slow": 40.0, "d_mid": 9.0, "c_quick": 2.0})
        assert [p.name for p in order] == ["a_slow", "d_mid", "c_quick", "b_unknown"]

    def test_no_durations_is_alphabetical(self):
        paths = [Path(p) for p in ("b", "a", "c")]
        assert [p.name for p in schedule(paths, {})] == ["a", "b", "c"]

    def test_durations_come_from_the_newest_earlier_run(self, tmp_path):
        runs = tmp_path / "runs"
        for run_id, seconds in (("2026-01-01T00-00-00", 5), ("2026-01-02T00-00-00", 30)):
            (runs / run_id).mkdir(parents=True)
            (runs / run_id / "manifest.json").write_text(
                '{"scenarios": [{"scenario": "s", "items": ['
                '{"captured_at": "2026-01-01T00:00:00"}, '
                f'{{"captured_at": "2026-01-01T00:00:{seconds:02d}"}}]}}]}}'
            )
        (runs / "2026-01-03T00-00-00").mkdir()  # the current run: no manifest yet
        assert _previous_durations(tmp_path, "2026-01-03T00-00-00") == {"s": 30.0}

    def test_no_runs_means_no_durations(self, tmp_path):
        assert _previous_durations(tmp_path, "x") == {}


class TestBundleTransfer:
    def test_roundtrip_keeps_items_order_and_provenance(self):
        bundle = ScenarioBundle(scenario="note_lifecycle", provenance={"rubric_version": "2"})
        for n, step in enumerate(("create", "fetch")):
            bundle.add(
                EvidenceItem(
                    kind="http_transcript", mime="application/json",
                    path=Path(f"note_lifecycle/0{n}-{step}.json"), scenario="note_lifecycle",
                    step=step, captured_at=datetime(2026, 1, 1, 0, 0, n), metadata={"status": 200},
                )
            )
        back = _bundle_from_dict(_bundle_to_dict(bundle))
        assert back.scenario == "note_lifecycle"
        assert back.provenance == {"rubric_version": "2"}
        assert [i.step for i in back.items] == ["create", "fetch"]
        assert back.items[1].captured_at == datetime(2026, 1, 1, 0, 0, 1)
        assert back.items[0].metadata == {"status": 200}
        assert back.items[0].path == Path("note_lifecycle/00-create.json")

    def test_a_report_reads_the_same_whatever_the_pool_did(self):
        # the parent assembles results in proof order, not completion order
        done = {"b": ScenarioResult("b", [StepResult("x", "http", True)]), "a": ScenarioResult("a", [])}
        report = DriveReport(results=[done[name] for name in ("a", "b")])
        assert [r.scenario for r in report.results] == ["a", "b"]
