"""The convergence loop: assess → judge → escalate → build → checkpoint.

The source framework's ``make auto`` rebuilt as a testable state
machine. The loop owns *policy* — stagnation accounting, the three
escalation dials, rollback-to-best, iteration memory — and never the
*hands*: assessment, judging, building, and checkpointing are injected
roles. v0.7 ships real implementations for the two darkroom can own
(:class:`AdapterAssessor`, :class:`GitCheckpointer`); judge and builder
arrive as shell hooks first and agent implementations later.

Opacity is preserved by construction: a :class:`JudgeReport` carries the
evaluation (scores — read by the loop, never shown to the builder) and
the feedback (builder-safe prose, authored by the judge — carried by the
loop, never derived from scores). The loop is a courier that may read
one envelope and must not open the other.

Loop policy is operator authority. Per the adapter's trust rule it is
never read from the tenant's ``darkroom.toml``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Protocol

from darkroom.adapter import ProjectAdapter
from darkroom.evaluation import Evaluation


class LoopError(Exception):
    pass


@dataclass(frozen=True)
class LoopPolicy:
    max_iterations: int = 8
    target_score: float = 100.0
    diagnostic_after: int = 2
    escalate_model_after: int = 3
    rollback_on_regression: bool = True


@dataclass(frozen=True)
class Escalation:
    stagnation: int = 0
    diagnostic: bool = False
    escalate_model: bool = False
    feedback_level: int = 0

    @classmethod
    def for_stagnation(cls, stagnation: int, policy: LoopPolicy) -> Escalation:
        return cls(
            stagnation=stagnation,
            diagnostic=stagnation >= policy.diagnostic_after,
            escalate_model=stagnation >= policy.escalate_model_after,
            feedback_level=min(stagnation, 2),
        )


@dataclass
class LoopContext:
    adapter: ProjectAdapter
    scenario: str | None = None
    state_dir: Path | None = None


@dataclass
class Assessment:
    manifest_path: Path | None
    tests_passed: bool
    verify_ok: bool
    notes: str = ""


@dataclass
class JudgeReport:
    evaluation: Evaluation
    feedback: str


@dataclass
class IterationRecord:
    number: int
    score: float
    best_score: float
    stagnation: int
    escalation: Escalation
    action: str  # "converged" | "built" | "rolled-back-and-built"
    checkpoint: str = ""
    changed_files: list[str] = field(default_factory=list)


@dataclass
class ConvergenceResult:
    converged: bool
    reason: str  # "converged" | "exhausted"
    iterations: list[IterationRecord] = field(default_factory=list)

    @property
    def final_score(self) -> float | None:
        return self.iterations[-1].score if self.iterations else None


class Assessor(Protocol):
    def assess(self, ctx: LoopContext) -> Assessment: ...


class Judge(Protocol):
    def judge(
        self, ctx: LoopContext, assessment: Assessment, escalation: Escalation
    ) -> JudgeReport: ...


class Builder(Protocol):
    def build(
        self, ctx: LoopContext, feedback: str, escalation: Escalation
    ) -> None: ...


class Checkpointer(Protocol):
    def is_clean(self, ctx: LoopContext) -> bool: ...

    def current(self, ctx: LoopContext) -> str: ...

    def checkpoint(self, ctx: LoopContext, label: str) -> str: ...

    def rollback(self, ctx: LoopContext, ref: str) -> None: ...

    def changed_files(self, ctx: LoopContext, ref: str) -> list[str]: ...


def _score_for(evaluation: Evaluation, scenario: str | None) -> float:
    if scenario is None:
        return evaluation.percentage
    scenario_eval = evaluation.for_scenario(scenario)
    if scenario_eval is None or not scenario_eval.points_possible:
        return 0.0
    return 100.0 * scenario_eval.points_earned / scenario_eval.points_possible


class ConvergenceLoop:
    def __init__(
        self,
        policy: LoopPolicy,
        assessor: Assessor,
        judge: Judge,
        builder: Builder,
        checkpointer: Checkpointer,
        on_iteration=None,
    ):
        self.policy = policy
        self.assessor = assessor
        self.judge = judge
        self.builder = builder
        self.checkpointer = checkpointer
        self.on_iteration = on_iteration

    def run(self, ctx: LoopContext) -> ConvergenceResult:
        if not self.checkpointer.is_clean(ctx):
            raise LoopError(
                "working tree is not clean; the loop makes checkpoints and "
                "will not mix them with uncommitted work"
            )

        records: list[IterationRecord] = []
        best_score: float | None = None
        best_ref = self.checkpointer.current(ctx)
        stagnation = 0

        for number in range(1, self.policy.max_iterations + 1):
            escalation_in = Escalation.for_stagnation(stagnation, self.policy)
            assessment = self.assessor.assess(ctx)
            report = self.judge.judge(ctx, assessment, escalation_in)
            score = _score_for(report.evaluation, ctx.scenario)

            if (
                score >= self.policy.target_score
                and assessment.tests_passed
                and assessment.verify_ok
            ):
                records.append(
                    IterationRecord(
                        number=number,
                        score=score,
                        best_score=score,
                        stagnation=stagnation,
                        escalation=escalation_in,
                        action="converged",
                        checkpoint=self.checkpointer.current(ctx),
                    )
                )
                self._remember(ctx, records[-1])
                if self.on_iteration:
                    self.on_iteration(records[-1])
                return ConvergenceResult(
                    converged=True, reason="converged", iterations=records
                )

            action = "built"
            if best_score is None or score > best_score:
                best_score = score
                best_ref = self.checkpointer.current(ctx)
                stagnation = 0
            else:
                if score < best_score and self.policy.rollback_on_regression:
                    self.checkpointer.rollback(ctx, best_ref)
                    action = "rolled-back-and-built"
                stagnation += 1

            escalation_out = Escalation.for_stagnation(stagnation, self.policy)
            self.builder.build(ctx, report.feedback, escalation_out)
            ref = self.checkpointer.checkpoint(
                ctx, f"auto: iteration {number} ({score:.1f}%)"
            )
            record = IterationRecord(
                number=number,
                score=score,
                best_score=best_score,
                stagnation=stagnation,
                escalation=escalation_out,
                action=action,
                checkpoint=ref,
                changed_files=self.checkpointer.changed_files(ctx, ref),
            )
            records.append(record)
            self._remember(ctx, record)
            if self.on_iteration:
                self.on_iteration(record)

        return ConvergenceResult(
            converged=False, reason="exhausted", iterations=records
        )

    def _remember(self, ctx: LoopContext, record: IterationRecord) -> None:
        """Append the iteration to builder-log.md — the builder's memory."""
        if ctx.state_dir is None:
            return
        ctx.state_dir.mkdir(parents=True, exist_ok=True)
        log = ctx.state_dir / "builder-log.md"
        lines = [
            f"## iteration {record.number} — {datetime.now().isoformat()}",
            "",
        ]
        if ctx.scenario:
            lines.append(f"scenario: {ctx.scenario}")
        lines.append(
            f"score: {record.score:.1f} (best {record.best_score:.1f}) · "
            f"stagnation: {record.stagnation} · action: {record.action}"
        )
        if record.escalation.diagnostic or record.escalation.escalate_model:
            dials = []
            if record.escalation.diagnostic:
                dials.append("diagnostic")
            if record.escalation.escalate_model:
                dials.append("model-escalation")
            lines.append(f"escalation: {', '.join(dials)}")
        if record.changed_files:
            lines.append("changed: " + ", ".join(record.changed_files))
        lines.append("")
        with open(log, "a") as f:
            f.write("\n".join(lines) + "\n")
