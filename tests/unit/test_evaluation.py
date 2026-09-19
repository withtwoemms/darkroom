"""Unit tests for the evaluation score model."""

import json
from datetime import datetime

import pytest

from darkroom.evaluation import (
    CriterionResult,
    Evaluation,
    ScenarioEvaluation,
    coerce_evaluation,
    dump_evaluation,
    dumps_evaluation,
    load_evaluation,
    loads_evaluation,
    normalize_percentage,
)


def _evaluation() -> Evaluation:
    return Evaluation(
        run_id="2026-09-18T10-00-00",
        evaluated_at=datetime(2026, 9, 18, 10, 5),
        project="bookbinder",
        rubric_version="3",
        scenarios=[
            ScenarioEvaluation(
                scenario="approve_flow",
                criteria=[
                    CriterionResult(
                        criterion="approval_persists",
                        passed=True,
                        points_earned=20,
                        points_possible=20,
                        evidence=("approve_flow/01-before.png",),
                    ),
                    CriterionResult(
                        criterion="press_notified",
                        passed=False,
                        points_earned=5,
                        points_possible=15,
                        notes="outbox empty at 5s",
                    ),
                ],
            ),
            ScenarioEvaluation(
                scenario="listing",
                criteria=[
                    CriterionResult(
                        criterion="renders",
                        passed=True,
                        points_earned=10,
                        points_possible=10,
                    )
                ],
            ),
        ],
    )


class TestDerivedProperties:
    def test_totals_and_percentage(self):
        evaluation = _evaluation()
        assert evaluation.total_earned == 35
        assert evaluation.total_possible == 45
        assert evaluation.percentage == pytest.approx(77.777, rel=1e-3)

    def test_all_passed(self):
        evaluation = _evaluation()
        assert not evaluation.all_passed
        assert not evaluation.for_scenario("approve_flow").passed
        assert evaluation.for_scenario("listing").passed

    def test_empty_evaluation_scores_zero(self):
        empty = Evaluation(run_id="r", evaluated_at=datetime(2026, 1, 1))
        assert empty.percentage == 0.0
        assert not empty.all_passed


class TestStrictRoundTrip:
    def test_dumps_loads(self):
        evaluation = _evaluation()
        loaded = loads_evaluation(dumps_evaluation(evaluation))
        assert loaded.run_id == evaluation.run_id
        assert loaded.rubric_version == "3"
        assert loaded.percentage == pytest.approx(evaluation.percentage)
        criterion = loaded.for_scenario("approve_flow").criteria[0]
        assert criterion.evidence == ("approve_flow/01-before.png",)

    def test_summary_in_output(self):
        data = json.loads(dumps_evaluation(_evaluation()))
        assert data["summary"]["percentage"] == pytest.approx(77.777, rel=1e-3)
        assert data["summary"]["all_passed"] is False

    def test_file_round_trip(self, tmp_path):
        path = tmp_path / "evaluation.json"
        dump_evaluation(_evaluation(), path)
        assert load_evaluation(path).total_earned == 35


class TestCoercion:
    FRAMEWORK_SHAPE = {
        "run_id": "2026-03-17T13-43-29",
        "evaluated_at": "2026-03-17T13:50:00",
        "feature": "capacity-alerts",
        "summary": {
            "total_earned_score": 23,
            "total_max_score": 30,
            "percentage": 76.7,
            "all_criteria_passed": False,
            "notes": "banner missing",
        },
        "scenarios": {
            "double_booked": {
                "criteria": {
                    "alert_shown": {
                        "passed": True,
                        "points_earned": 10,
                        "points_possible": 10,
                        "evidence": "double_booked/01-alert.png",
                    },
                    "banner_color": {
                        "points_earned": "3",
                        "points_possible": "10",
                    },
                }
            }
        },
    }

    def test_framework_shape(self):
        evaluation = coerce_evaluation(self.FRAMEWORK_SHAPE)
        assert evaluation.run_id == "2026-03-17T13-43-29"
        assert evaluation.notes == "banner missing"
        scenario = evaluation.for_scenario("double_booked")
        alert = next(c for c in scenario.criteria if c.criterion == "alert_shown")
        assert alert.passed and alert.evidence == ("double_booked/01-alert.png",)
        banner = next(c for c in scenario.criteria if c.criterion == "banner_color")
        assert banner.passed is False  # derived: 3 < 10
        assert banner.points_earned == 3.0  # string number coerced

    def test_scenario_list_shape(self):
        evaluation = coerce_evaluation(
            {
                "run_id": "r",
                "scenarios": [
                    {
                        "name": "s1",
                        "criteria": [
                            {"id": "c1", "points_earned": 5, "points_possible": 5}
                        ],
                    }
                ],
            }
        )
        assert evaluation.for_scenario("s1").criteria[0].criterion == "c1"

    def test_bad_timestamp_defaults(self):
        evaluation = coerce_evaluation({"run_id": "r", "evaluated_at": "whenever"})
        assert isinstance(evaluation.evaluated_at, datetime)


class TestNormalizePercentage:
    def test_summary_percentage_passthrough(self):
        assert normalize_percentage({"summary": {"percentage": 76.7}}) == 76.7

    def test_zero_to_one_scale_lifted(self):
        assert normalize_percentage({"summary": {"percentage": 0.85}}) == 85.0
        assert normalize_percentage({"overall_score": 0.5}) == 50.0

    def test_pass_rate_synonym(self):
        assert normalize_percentage({"pass_rate": 0.9}) == 90.0

    def test_earned_over_max(self):
        score = normalize_percentage(
            {"summary": {"total_earned_score": 23, "total_max_score": 30}}
        )
        assert score == pytest.approx(76.667, rel=1e-3)

    def test_computed_from_criteria(self):
        score = normalize_percentage(TestCoercion.FRAMEWORK_SHAPE | {"summary": {}})
        assert score == pytest.approx(65.0)  # (10+3)/(10+10)

    def test_unrecognizable_raises(self):
        with pytest.raises(ValueError, match="no recognizable score"):
            normalize_percentage({"vibes": "good"})

    def test_boundary_one_is_lifted(self):
        # 1 reads as a ratio (100%), matching judge drift in the wild
        assert normalize_percentage({"summary": {"percentage": 1}}) == 100.0
