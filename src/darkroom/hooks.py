"""Shell-hook judge and builder roles.

The operator supplies commands; darkroom supplies the file contract.
This makes the convergence loop runnable before the built-in agent
roles exist — a hook can be a script, a ``claude -p`` one-liner, or
anything else that honors the contract:

Judge hook placeholders:
    {manifest}        path to the run manifest to judge (read)
    {evaluation_out}  path where the hook must write evaluation JSON
                      (strict or judge-drift shapes both accepted)
    {feedback_out}    path where the hook should write builder-safe
                      feedback markdown (may be omitted/empty)
    {scenario} {stagnation} {feedback_level}

Builder hook placeholders:
    {feedback}        path to the judge's feedback file (read)
    {scenario} {stagnation} {diagnostic} {escalate_model}

Hooks run via ``sh -c`` in the project root. A judge hook that fails or
writes no evaluation aborts the loop — a missing score is not a zero.
This file contract is a public interface: the built-in agent roles of
the orchestration releases will honor the same shapes.
"""

from __future__ import annotations

import subprocess
import tempfile
from pathlib import Path

from darkroom.evaluation import Evaluation
from darkroom.gallery import load_evaluation_lenient
from darkroom.loop import Assessment, Escalation, JudgeReport, LoopContext, LoopError


def _work_dir(ctx: LoopContext) -> Path:
    if ctx.state_dir is not None:
        path = ctx.state_dir / "loop"
    else:
        path = Path(tempfile.mkdtemp(prefix="darkroom-loop-"))
    path.mkdir(parents=True, exist_ok=True)
    return path


def _run_hook(ctx: LoopContext, command: str, timeout: float) -> None:
    subprocess.run(
        ["/bin/sh", "-c", command],
        cwd=ctx.adapter.root,
        capture_output=True,
        timeout=timeout,
        check=False,
    )


class CommandJudge:
    """Judges by invoking an operator-supplied command per iteration."""

    def __init__(self, command_template: str, timeout: float = 1800):
        self.command_template = command_template
        self.timeout = timeout
        self.iteration = 0
        self.last_evaluation: Evaluation | None = None

    def judge(
        self, ctx: LoopContext, assessment: Assessment, escalation: Escalation
    ) -> JudgeReport:
        if assessment.manifest_path is None:
            raise LoopError("nothing to judge: assessment produced no manifest")
        self.iteration += 1
        work = _work_dir(ctx)
        evaluation_out = work / f"evaluation-{self.iteration}.json"
        feedback_out = work / f"feedback-{self.iteration}.md"

        command = self.command_template.format(
            manifest=assessment.manifest_path,
            evaluation_out=evaluation_out,
            feedback_out=feedback_out,
            scenario=ctx.scenario or "",
            stagnation=escalation.stagnation,
            feedback_level=escalation.feedback_level,
        )
        _run_hook(ctx, command, self.timeout)

        if not evaluation_out.exists():
            raise LoopError(
                f"judge hook wrote no evaluation at {evaluation_out}; "
                "a missing score is not a zero"
            )
        try:
            evaluation = load_evaluation_lenient(evaluation_out)
        except (OSError, ValueError, KeyError) as exc:
            raise LoopError(f"judge hook evaluation unreadable: {exc}") from None
        self.last_evaluation = evaluation

        feedback = ""
        if feedback_out.exists():
            feedback = feedback_out.read_text()
        return JudgeReport(evaluation=evaluation, feedback=feedback)


class CommandBuilder:
    """Builds by invoking an operator-supplied command per iteration."""

    def __init__(self, command_template: str, timeout: float = 3600):
        self.command_template = command_template
        self.timeout = timeout
        self.iteration = 0

    def build(
        self, ctx: LoopContext, feedback: str, escalation: Escalation
    ) -> None:
        self.iteration += 1
        work = _work_dir(ctx)
        feedback_path = work / f"feedback-for-builder-{self.iteration}.md"
        feedback_path.write_text(feedback)

        command = self.command_template.format(
            feedback=feedback_path,
            scenario=ctx.scenario or "",
            stagnation=escalation.stagnation,
            diagnostic=int(escalation.diagnostic),
            escalate_model=int(escalation.escalate_model),
        )
        _run_hook(ctx, command, self.timeout)
