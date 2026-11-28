"""Unit tests for peak gates and run diffing."""

from datetime import datetime
from pathlib import Path

from darkroom.evaluation import CriterionResult, Evaluation, ScenarioEvaluation
from darkroom.gates import (
    GateFile,
    PeakRecord,
    check_gates,
    dumps_gates,
    has_regressions,
    loads_gates,
    provenance_findings,
    update_gates,
)
from darkroom.model import EvidenceItem, RunManifest, ScenarioBundle
from darkroom.rundiff import diff_runs


def _evaluation(score_pairs, rubric_version="1", run_id="r2") -> Evaluation:
    """score_pairs: list of (scenario, earned, possible)."""
    return Evaluation(
        run_id=run_id,
        evaluated_at=datetime(2026, 9, 19),
        rubric_version=rubric_version,
        scenarios=[
            ScenarioEvaluation(
                scenario=name,
                criteria=[
                    CriterionResult(
                        criterion="c",
                        passed=earned >= possible,
                        points_earned=earned,
                        points_possible=possible,
                    )
                ]
                if possible
                else [],
            )
            for name, earned, possible in score_pairs
        ],
    )


def _peak(scenario, score, rubric_version="1") -> PeakRecord:
    return PeakRecord(
        scenario=scenario,
        score=score,
        run_id="r1",
        recorded_at=datetime(2026, 9, 18),
        rubric_version=rubric_version,
        commit="abc1234",
    )


class TestCheckGates:
    def test_held_at_or_above_peak(self):
        gates = GateFile(peaks=[_peak("flow", 80.0)])
        findings = check_gates(gates, _evaluation([("flow", 9, 10)]))
        assert findings[0].kind == "held"
        assert not has_regressions(findings)

    def test_regression_below_peak(self):
        gates = GateFile(peaks=[_peak("flow", 95.0)])
        findings = check_gates(gates, _evaluation([("flow", 8, 10)]))
        assert findings[0].kind == "regression"
        assert "below peak 95.0" in findings[0].message
        assert "run r1" in findings[0].message
        assert "commit abc1234" in findings[0].message
        assert has_regressions(findings)

    def test_rubric_mismatch_is_stale_not_regression(self):
        gates = GateFile(peaks=[_peak("flow", 95.0, rubric_version="1")])
        findings = check_gates(
            gates, _evaluation([("flow", 5, 10)], rubric_version="2")
        )
        assert findings[0].kind == "stale-peak"
        assert not has_regressions(findings)

    def test_ungated_and_unscored(self):
        gates = GateFile()
        findings = check_gates(
            gates, _evaluation([("new_flow", 5, 10), ("empty", 0, 0)])
        )
        kinds = {f.scenario: f.kind for f in findings}
        assert kinds == {"new_flow": "ungated", "empty": "ungated"}


class TestUpdateGates:
    def test_first_evaluation_sets_peaks(self):
        new_gates, _ = update_gates(GateFile(), _evaluation([("flow", 9, 10)]), commit="def5678")
        peak = new_gates.peak_for("flow")
        assert peak.score == 90.0
        assert peak.run_id == "r2"
        assert peak.commit == "def5678"

    def test_ratchets_upward(self):
        gates = GateFile(peaks=[_peak("flow", 80.0)])
        new_gates, _ = update_gates(gates, _evaluation([("flow", 9, 10)]))
        assert new_gates.peak_for("flow").score == 90.0

    def test_regression_keeps_old_peak(self):
        gates = GateFile(peaks=[_peak("flow", 95.0)])
        new_gates, findings = update_gates(gates, _evaluation([("flow", 8, 10)]))
        assert new_gates.peak_for("flow").score == 95.0
        assert has_regressions(findings)

    def test_rubric_mismatch_rebaselines(self):
        gates = GateFile(peaks=[_peak("flow", 95.0, rubric_version="1")])
        new_gates, _ = update_gates(
            gates, _evaluation([("flow", 5, 10)], rubric_version="2")
        )
        peak = new_gates.peak_for("flow")
        assert peak.score == 50.0
        assert peak.rubric_version == "2"

    def test_absent_scenarios_keep_peaks(self):
        gates = GateFile(peaks=[_peak("other", 70.0)])
        new_gates, _ = update_gates(gates, _evaluation([("flow", 9, 10)]))
        assert new_gates.peak_for("other").score == 70.0


class TestProvenanceFindings:
    """A peak is a claim about a commit. These are the ways an evaluation
    can say, in its own provenance, that the claim would be false — the
    likeliest of them by accident rather than by cheating: scoring an old
    manifest and ratcheting it against today's code."""

    def _stamped(self, **provenance) -> Evaluation:
        evaluation = _evaluation([("flow", 10, 10)])
        evaluation.provenance = provenance
        return evaluation

    def test_clean_provenance_has_nothing_to_report(self):
        stamped = self._stamped(tenant_commit="abc", tenant_dirty=False)
        assert provenance_findings(stamped, commit="abc") == []

    def test_a_commit_the_evidence_was_not_judged_against(self):
        stamped = self._stamped(tenant_commit="aaaaaaaaaaaa")
        findings = provenance_findings(stamped, commit="bbbbbbbbbbbb")
        assert [f.kind for f in findings] == ["commit-mismatch"]
        assert "aaaaaaaaaaaa" in findings[0].message

    def test_a_dirty_tree_is_reported_without_a_commit_to_compare(self):
        stamped = self._stamped(tenant_dirty=True)
        assert [f.kind for f in provenance_findings(stamped)] == ["dirty-tree"]

    def test_a_rubric_version_the_judge_was_not_handed(self):
        stamped = self._stamped(rubric_versions={"flow": "3"})
        findings = provenance_findings(stamped)
        assert [f.kind for f in findings] == ["rubric-version-mismatch"]
        assert "'3'" in findings[0].message

    def test_an_unstamped_evaluation_claims_nothing(self):
        """Evaluations written before schema 1.1 carry no provenance. That
        is reportable only when a commit is being recorded from them —
        otherwise there is no claim to contradict."""
        plain = _evaluation([("flow", 10, 10)])
        assert provenance_findings(plain) == []
        assert [f.kind for f in provenance_findings(plain, commit="abc")] == [
            "no-provenance"
        ]


class TestGatesRoundTrip:
    def test_dumps_loads(self):
        gates = GateFile(project="bookbinder", peaks=[_peak("flow", 88.5)])
        loaded = loads_gates(dumps_gates(gates))
        assert loaded.project == "bookbinder"
        peak = loaded.peak_for("flow")
        assert peak.score == 88.5
        assert peak.rubric_version == "1"
        assert peak.commit == "abc1234"


class TestRunDiff:
    def _manifest(self, spec) -> RunManifest:
        return RunManifest(
            run_id="r",
            scenarios=[
                ScenarioBundle(
                    scenario=name,
                    items=[
                        EvidenceItem(
                            kind=kind,
                            mime="application/octet-stream",
                            path=Path(f"{name}/{step}.bin"),
                            scenario=name,
                            step=step,
                            captured_at=datetime(2026, 1, 1),
                        )
                        for kind, step in items
                    ],
                )
                for name, items in spec.items()
            ],
        )

    def test_identical_runs(self):
        spec = {"flow": [("log", "state")]}
        assert diff_runs(self._manifest(spec), self._manifest(spec)).unchanged

    def test_scenario_and_item_changes(self):
        old = self._manifest({"flow": [("log", "a")], "gone": [("log", "x")]})
        new = self._manifest(
            {"flow": [("log", "a"), ("screenshot", "b")], "fresh": []}
        )
        diff = diff_runs(old, new)
        assert diff.scenarios_added == ["fresh"]
        assert diff.scenarios_removed == ["gone"]
        assert diff.items_added == {"flow": ["screenshot:b"]}
        assert diff.items_removed == {}
