"""Unit tests for the convergence loop state machine, with scripted roles."""

from datetime import datetime
from pathlib import Path

import pytest

from darkroom.adapter import ProjectAdapter
from darkroom.evaluation import CriterionResult, Evaluation, ScenarioEvaluation
from darkroom.loop import (
    Assessment,
    ConvergenceLoop,
    Escalation,
    JudgeReport,
    LoopContext,
    LoopError,
    LoopPolicy,
)


def _evaluation(score: float, scenario="flow") -> Evaluation:
    return Evaluation(
        run_id="r",
        evaluated_at=datetime(2026, 9, 20),
        scenarios=[
            ScenarioEvaluation(
                scenario=scenario,
                criteria=[
                    CriterionResult(
                        criterion="c",
                        passed=score >= 100,
                        points_earned=score,
                        points_possible=100,
                    )
                ],
            )
        ],
    )


class ScriptedAssessor:
    def __init__(self, results=None):
        self.results = results

    def assess(self, ctx):
        if self.results:
            return self.results.pop(0)
        return Assessment(manifest_path=Path("m.json"), tests_passed=True, verify_ok=True)


class ScriptedJudge:
    def __init__(self, scores):
        self.scores = list(scores)
        self.escalations: list[Escalation] = []

    def judge(self, ctx, assessment, escalation):
        self.escalations.append(escalation)
        return JudgeReport(
            evaluation=_evaluation(self.scores.pop(0)), feedback="try harder"
        )


class RecordingBuilder:
    def __init__(self):
        self.calls: list[tuple[str, Escalation]] = []

    def build(self, ctx, feedback, escalation):
        self.calls.append((feedback, escalation))


class FakeCheckpointer:
    def __init__(self, clean=True):
        self.clean = clean
        self.refs = ["ref-0"]
        self.rollbacks: list[str] = []

    def is_clean(self, ctx):
        return self.clean

    def current(self, ctx):
        return self.refs[-1]

    def checkpoint(self, ctx, label):
        self.refs.append(f"ref-{len(self.refs)}")
        return self.refs[-1]

    def rollback(self, ctx, ref):
        self.rollbacks.append(ref)

    def changed_files(self, ctx, ref):
        return ["app.py"]


def _ctx(tmp_path, scenario="flow"):
    return LoopContext(
        adapter=ProjectAdapter(root=tmp_path, name="p"),
        scenario=scenario,
        state_dir=tmp_path / "state",
    )


def _loop(judge, policy=None, checkpointer=None, builder=None):
    return ConvergenceLoop(
        policy=policy or LoopPolicy(),
        assessor=ScriptedAssessor(),
        judge=judge,
        builder=builder or RecordingBuilder(),
        checkpointer=checkpointer or FakeCheckpointer(),
    )


class TestConvergence:
    def test_converges_when_target_met(self, tmp_path):
        judge = ScriptedJudge([60, 80, 100])
        result = _loop(judge).run(_ctx(tmp_path))
        assert result.converged and result.reason == "converged"
        assert len(result.iterations) == 3
        assert result.final_score == 100.0
        assert result.iterations[-1].action == "converged"

    def test_exhausts_at_max_iterations(self, tmp_path):
        judge = ScriptedJudge([50] * 3)
        result = _loop(judge, policy=LoopPolicy(max_iterations=3)).run(_ctx(tmp_path))
        assert not result.converged and result.reason == "exhausted"
        assert len(result.iterations) == 3

    def test_convergence_requires_green_tests(self, tmp_path):
        judge = ScriptedJudge([100, 100])
        loop = ConvergenceLoop(
            policy=LoopPolicy(max_iterations=2),
            assessor=ScriptedAssessor([
                Assessment(Path("m"), tests_passed=False, verify_ok=True),
                Assessment(Path("m"), tests_passed=True, verify_ok=True),
            ]),
            judge=judge,
            builder=RecordingBuilder(),
            checkpointer=FakeCheckpointer(),
        )
        result = loop.run(_ctx(tmp_path))
        assert result.converged
        assert len(result.iterations) == 2  # first 100 didn't count


class TestEscalation:
    def test_dials_trip_in_order(self, tmp_path):
        judge = ScriptedJudge([50, 50, 50, 50])
        builder = RecordingBuilder()
        result = _loop(
            judge, policy=LoopPolicy(max_iterations=4), builder=builder
        ).run(_ctx(tmp_path))
        assert not result.converged
        stagnations = [r.stagnation for r in result.iterations]
        assert stagnations == [0, 1, 2, 3]
        escalations = [esc for _, esc in builder.calls]
        assert [e.diagnostic for e in escalations] == [False, False, True, True]
        assert [e.escalate_model for e in escalations] == [False, False, False, True]

    def test_judge_sees_prior_stagnation(self, tmp_path):
        # the judge sees the counter as it stood entering the iteration:
        # iteration 1 sets the baseline, so three flat scores read 0, 0, 1
        judge = ScriptedJudge([50, 50, 50])
        _loop(judge, policy=LoopPolicy(max_iterations=3)).run(_ctx(tmp_path))
        assert [e.stagnation for e in judge.escalations] == [0, 0, 1]
        assert [e.feedback_level for e in judge.escalations] == [0, 0, 1]

    def test_improvement_resets_stagnation(self, tmp_path):
        judge = ScriptedJudge([50, 50, 70, 50])
        result = _loop(judge, policy=LoopPolicy(max_iterations=4)).run(_ctx(tmp_path))
        assert [r.stagnation for r in result.iterations] == [0, 1, 0, 1]


class TestRollback:
    def test_regression_rolls_back_to_best_ref(self, tmp_path):
        checkpointer = FakeCheckpointer()
        judge = ScriptedJudge([80, 40, 60])
        result = _loop(
            judge, policy=LoopPolicy(max_iterations=3), checkpointer=checkpointer
        ).run(_ctx(tmp_path))
        # iteration 2 scored 40 < best 80 → rollback to the ref current at best
        assert checkpointer.rollbacks == ["ref-0", "ref-0"]
        assert result.iterations[1].action == "rolled-back-and-built"

    def test_rollback_disabled(self, tmp_path):
        checkpointer = FakeCheckpointer()
        judge = ScriptedJudge([80, 40])
        _loop(
            judge,
            policy=LoopPolicy(max_iterations=2, rollback_on_regression=False),
            checkpointer=checkpointer,
        ).run(_ctx(tmp_path))
        assert checkpointer.rollbacks == []


class TestPreconditionsAndMemory:
    def test_dirty_tree_refused(self, tmp_path):
        judge = ScriptedJudge([100])
        with pytest.raises(LoopError, match="not clean"):
            _loop(judge, checkpointer=FakeCheckpointer(clean=False)).run(
                _ctx(tmp_path)
            )

    def test_builder_log_written(self, tmp_path):
        judge = ScriptedJudge([50, 100])
        ctx = _ctx(tmp_path)
        _loop(judge).run(ctx)
        log = (ctx.state_dir / "builder-log.md").read_text()
        assert "## iteration 1" in log
        assert "score: 50.0" in log
        assert "changed: app.py" in log
        assert "## iteration 2" in log

    def test_whole_evaluation_scoring_when_no_scenario(self, tmp_path):
        judge = ScriptedJudge([100])
        ctx = _ctx(tmp_path, scenario=None)
        result = _loop(judge).run(ctx)
        assert result.converged
