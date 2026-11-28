"""On-demand judging: a score for evidence already captured.

Everything downstream of an evaluation is a standalone command — ``gate
check`` and ``gate update`` both take one by path — but until now nothing
produced one except ``auto``, a convergence loop that also edits the
tenant and commits. So the only route to a score was a command that
writes code. Recording a gate for a scenario that already passes is
conceptually read-only, and it required reasoning about branches, open
pull requests, and builder commits to answer a question that changes
nothing.

This module is the missing producer. It runs the loop's own judge
(:class:`darkroom.agents.AgentJudge`) over a run that already exists:
same prompt assembly, same vault access, same provenance stamp, same
audit line. There is deliberately no second judge — a judge that could
be reached two ways and score differently is worse than no second route
at all.

What it does *not* do is the loop's other half. Nothing is built,
nothing is committed, and the gates are not touched: the evaluation is
written and its path printed, and ratcheting stays an explicit ``gate
update``. Judging is also the cheap half — a judge call costs a fraction
of a builder call — so measuring judge variance over one fixed set of
evidence is simply this command run more than once.

The rubric half only: the judge is handed what the vault renders
(criteria, with the exposure's steps absent) exactly as in the loop. A
judge that can see the exposure would be scoring the exam.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from darkroom.adapter import ProjectAdapter
from darkroom.evaluation import ORIGIN_ON_DEMAND, Evaluation
from darkroom.loop import Escalation, LoopContext, LoopError, score_for
from darkroom.operator import OperatorConfig
from darkroom.roles import verified_assessment

_SCENARIO_LINE = re.compile(r"^scenario (\S+): (ok|FAILED)$")


class JudgingError(Exception):
    pass


@dataclass(frozen=True)
class Judging:
    evaluation: Evaluation
    evaluation_path: Path
    feedback_path: Path | None
    run_id: str
    score: float
    tests_passed: bool
    verify_ok: bool


def runs_dir(adapter: ProjectAdapter) -> Path:
    return adapter.resolve(adapter.evidence_dir) / "runs"


def resolve_manifest(adapter: ProjectAdapter, run_id: str | None) -> Path:
    """The manifest of the run to judge: the named one, else the newest.

    Naming a run is the normal case — the point of on-demand judging is
    scoring evidence that already exists, and which evidence is the whole
    question. The newest is a convenience for "score what just ran".
    """
    runs = runs_dir(adapter)
    if run_id:
        manifest = runs / run_id / "manifest.json"
        if not manifest.is_file():
            raise JudgingError(
                f"no run '{run_id}' under {runs} (expected {manifest})"
            )
        return manifest
    manifests = sorted(runs.glob("*/manifest.json"), key=lambda p: p.stat().st_mtime)
    if not manifests:
        raise JudgingError(
            f"no runs under {runs}; capture evidence first with darkroom expose"
        )
    return manifests[-1]


def harness_outcome(run_dir: Path, scenario: str | None) -> tuple[bool, str]:
    """Whether the run's steps passed, read off the harness log beside
    the manifest.

    The loop learns this from the test command it just ran; an on-demand
    judging runs nothing, so it reads what the harness recorded. An
    absent log is reported as unknown rather than as failure: a judging
    told the steps failed when nobody knows is a lie in the direction
    that costs points.
    """
    log = Path(run_dir) / "harness.log"
    if not log.is_file():
        return False, "no harness log beside the manifest; step outcomes unknown"
    outcomes = {}
    for line in log.read_text().splitlines():
        match = _SCENARIO_LINE.match(line.strip())
        if match:
            outcomes[match.group(1)] = match.group(2) == "ok"
    if scenario is not None:
        outcomes = {k: v for k, v in outcomes.items() if k == scenario}
    if not outcomes:
        return False, "the harness log records no outcome for this scenario"
    failed = sorted(name for name, ok in outcomes.items() if not ok)
    if failed:
        return False, "steps failed in: " + ", ".join(failed)
    return True, ""


def judge_run(
    adapter: ProjectAdapter,
    operator: OperatorConfig,
    vault,
    *,
    manifest_path: Path,
    scenario: str | None = None,
    state_dir: Path | None = None,
) -> Judging:
    """Score a captured run with the loop's judge. Builds nothing."""
    from darkroom.agents import AgentJudge

    tests_passed, note = harness_outcome(manifest_path.parent, scenario)
    assessment = verified_assessment(
        adapter, manifest_path, scenario, tests_passed=tests_passed, notes=note
    )
    ctx = LoopContext(
        adapter=adapter,
        scenario=scenario,
        state_dir=state_dir,
        space="judge",
    )
    judge = AgentJudge(operator.judge, vault, origin=ORIGIN_ON_DEMAND)
    try:
        report = judge.judge(ctx, assessment, Escalation())
    except LoopError as exc:
        raise JudgingError(str(exc)) from None

    evaluation = report.evaluation
    return Judging(
        evaluation=evaluation,
        evaluation_path=judge.last_evaluation_path,
        feedback_path=judge.last_feedback_path,
        run_id=evaluation.provenance.get("evidence_run", ""),
        score=score_for(evaluation, scenario),
        tests_passed=assessment.tests_passed,
        verify_ok=assessment.verify_ok,
    )


def scorecard(judging: Judging, scenario: str | None) -> list[str]:
    """The printed verdict: per-criterion points, then the scenario total.

    Criterion notes are included. This output is operator-facing — it
    carries scores, so it must never be piped anywhere a builder reads.
    """
    lines = []
    for scenario_eval in judging.evaluation.scenarios:
        if scenario is not None and scenario_eval.scenario != scenario:
            continue
        possible = scenario_eval.points_possible
        percentage = 100.0 * scenario_eval.points_earned / possible if possible else 0.0
        lines.append(
            f"{scenario_eval.scenario}: {percentage:.1f} "
            f"({scenario_eval.points_earned:g}/{possible:g})"
        )
        for criterion in scenario_eval.criteria:
            mark = "pass" if criterion.passed else "FAIL"
            lines.append(
                f"  {mark} {criterion.criterion} "
                f"{criterion.points_earned:g}/{criterion.points_possible:g}"
            )
            if criterion.notes:
                lines.append(f"       {criterion.notes}")
    return lines
