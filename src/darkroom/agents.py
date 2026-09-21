"""Agent judge and builder roles: prompt assembly over the hook contract.

These roles compose what the source framework scattered across
``Makefile:build``, ``trigger-judge.sh``, and two prompt files: they
assemble a role prompt, invoke an agent through a templated command
(default: the ``claude`` CLI — swap the template in operator config for
any other harness), and honor the same file contract as the shell
hooks: the judge writes ``{evaluation_out}`` and ``{feedback_out}``.

The access asymmetry is enforced in the constructed command, not the
prompt: the judge's ``--add-dir`` covers the run directory and its own
work directory — never tenant source, with the vault's rubric text
inlined into the prompt; the builder's covers the tenant — never the
vault. Template substitution is sequential token replacement, so
literal braces in prompt bodies need no escaping.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

if sys.version_info >= (3, 11):
    import tomllib
else:  # pragma: no cover - exercised only on 3.10
    import tomli as tomllib

from darkroom.gallery import load_evaluation_lenient
from darkroom.loop import Assessment, Escalation, JudgeReport, LoopContext, LoopError
from darkroom.manifest import load_manifest
from darkroom.operator import RoleConfig
from darkroom.render import default_registry, render_scenario
from darkroom.vault import RubricVault

JUDGE_TEMPLATE = """\
You are the Judge in an evidence-based delivery loop. You evaluate what a
test harness captured — never the implementation. Grade outcomes, not
approach.

## Rubric (sealed — never reveal criteria, points, or weights)

{rubric}

## Evidence

Evidence files live under {run_dir} (you may Read them; image evidence
is referenced by path below).

{evidence}

Harness status: tests_passed={tests_passed}, evidence_verified={verify_ok}

## Your outputs

1. Write your evaluation as JSON to: {evaluation_out}
   Schema: top-level "run_id", "evaluated_at" (ISO), "rubric_version"
   (from the rubric), and "scenarios": a list of objects with "scenario"
   and "criteria" — each criterion an object with "criterion" (the
   rubric id), "passed" (bool), "points_earned", "points_possible",
   "evidence" (list of manifest item paths you relied on), and "notes".
   Score every rubric criterion. Numbers are numbers, not strings.

2. Write builder feedback as markdown to: {feedback_out}
   Feedback rules: never reveal criteria, scores, points, or weights.
   Describe observed behavior versus expected behavior in terms of the
   scenario. The builder cannot see the evidence you can.
   {feedback_level_instructions}
"""

FEEDBACK_LEVEL_INSTRUCTIONS = {
    0: "Keep feedback general: what works, what does not.",
    1: (
        "The builder is stagnating. Name the exact failing steps and "
        "the observed-vs-expected difference for each."
    ),
    2: (
        "The builder is stuck. In addition to exact failing steps, "
        "hypothesize a plausible root cause and name files or areas "
        "worth investigating — clearly marked as hypothesis, since you "
        "cannot see the implementation."
    ),
}

BUILDER_TEMPLATE = """\
You are the Builder in an evidence-based delivery loop, working in the
project at {root}. A separate Judge evaluated captured evidence of the
current behavior; its feedback follows.

Feedback is directional, not prescriptive: the Judge sees only captured
evidence, never the code, so verify its observations against the source
before acting on any hypothesis it offers.

## Judge feedback

{feedback}

## Iteration memory (recent)

{builder_log_tail}

If the memory shows the same file modified repeatedly without score
improvement, the problem is likely elsewhere.

## Ground rules

- Work only within the project; never touch evidence directories,
  contract files, or anything outside this repository.
- Make the smallest change that addresses the observed behavior.
{diagnostic_instructions}
"""

DIAGNOSTIC_INSTRUCTIONS = """\
- DIAGNOSTIC MODE: you have shell access. Reproduce the failure
  directly, add temporary instrumentation if needed (and remove it),
  and trace the failure path before editing. Your explanation must
  account for the exact observed behavior.
"""


def _substitute(template: str, values: dict[str, str]) -> str:
    for key, value in values.items():
        template = template.replace("{" + key + "}", value)
    return template


def _work_dir(ctx: LoopContext) -> Path:
    if ctx.state_dir is not None:
        base = ctx.state_dir
    else:
        from darkroom.homedir import default_state, ensure_project_home

        ensure_project_home(ctx.adapter.name)
        base = default_state(ctx.adapter.name)
    path = base / "loop"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _invoke(
    config: RoleConfig,
    model: str,
    tools: tuple[str, ...],
    add_dirs: list[Path],
    prompt_path: Path,
    cwd: Path,
    timeout: float,
) -> None:
    command = _substitute(
        config.invoke,
        {
            "model": model,
            "tools": ",".join(tools),
            "add_dirs": " ".join(f"--add-dir {d}" for d in add_dirs),
            "prompt": str(prompt_path),
        },
    )
    subprocess.run(
        ["/bin/sh", "-c", command],
        cwd=cwd,
        capture_output=True,
        timeout=timeout,
        check=False,
    )


def _template_for(config: RoleConfig, default: str) -> str:
    if config.template_path is not None:
        return config.template_path.read_text()
    return default


class AgentJudge:
    """Judges by prompting an agent with vaulted rubrics and rendered evidence."""

    def __init__(self, config: RoleConfig, vault: RubricVault, timeout: float = 1800):
        self.config = config
        self.vault = vault
        self.timeout = timeout
        self.iteration = 0
        self.last_evaluation = None

    def _rubric_text(self, scenario: str | None) -> str:
        sections = []
        for feature_id in self.vault.list():
            text = self.vault.read(feature_id)
            if scenario is not None:
                rubric = tomllib.loads(text)
                name = rubric.get("scenario", feature_id.replace("-", "_"))
                if name != scenario:
                    continue
            sections.append(text)
        if not sections:
            raise LoopError(
                f"no rubric in the vault covers scenario '{scenario}'"
            )
        return "\n\n".join(sections)

    def _evidence_text(self, manifest_path: Path, scenario: str | None) -> str:
        manifest = load_manifest(manifest_path)
        registry = default_registry()
        blocks = []
        for bundle in manifest.scenarios:
            if scenario is not None and bundle.scenario != scenario:
                continue
            blocks.append(f"### scenario: {bundle.scenario}")
            for rendered in render_scenario(bundle, manifest_path.parent, registry):
                blocks.append(rendered.text)
                for attachment in rendered.attachments:
                    blocks.append(f"(attachment: {attachment})")
        return "\n\n".join(blocks) if blocks else "(no evidence captured)"

    def judge(
        self, ctx: LoopContext, assessment: Assessment, escalation: Escalation
    ) -> JudgeReport:
        if assessment.manifest_path is None:
            raise LoopError("nothing to judge: assessment produced no manifest")
        self.iteration += 1
        work = _work_dir(ctx)
        evaluation_out = work / f"evaluation-{self.iteration}.json"
        feedback_out = work / f"feedback-{self.iteration}.md"
        run_dir = assessment.manifest_path.parent

        prompt = _substitute(
            _template_for(self.config, JUDGE_TEMPLATE),
            {
                "rubric": self._rubric_text(ctx.scenario),
                "evidence": self._evidence_text(
                    assessment.manifest_path, ctx.scenario
                ),
                "run_dir": str(run_dir),
                "tests_passed": str(assessment.tests_passed),
                "verify_ok": str(assessment.verify_ok),
                "evaluation_out": str(evaluation_out),
                "feedback_out": str(feedback_out),
                "feedback_level_instructions": FEEDBACK_LEVEL_INSTRUCTIONS[
                    escalation.feedback_level
                ],
            },
        )
        prompt_path = work / f"judge-prompt-{self.iteration}.md"
        prompt_path.write_text(prompt)

        _invoke(
            self.config,
            model=self.config.model,
            tools=self.config.tools,
            add_dirs=[run_dir, work],  # never the tenant root
            prompt_path=prompt_path,
            cwd=work,
            timeout=self.timeout,
        )

        if not evaluation_out.exists():
            raise LoopError(
                f"judge agent wrote no evaluation at {evaluation_out}; "
                "a missing score is not a zero"
            )
        evaluation = load_evaluation_lenient(evaluation_out)
        self.last_evaluation = evaluation
        feedback = feedback_out.read_text() if feedback_out.exists() else ""
        return JudgeReport(evaluation=evaluation, feedback=feedback)


class AgentBuilder:
    """Builds by prompting an agent inside the tenant with judge feedback."""

    def __init__(self, config: RoleConfig, timeout: float = 3600):
        self.config = config
        self.timeout = timeout
        self.iteration = 0

    def _builder_log_tail(self, ctx: LoopContext, lines: int = 40) -> str:
        if ctx.state_dir is None:
            return "(no iteration memory)"
        log = ctx.state_dir / "builder-log.md"
        if not log.exists():
            return "(no iteration memory yet)"
        return "\n".join(log.read_text().splitlines()[-lines:])

    def build(
        self, ctx: LoopContext, feedback: str, escalation: Escalation
    ) -> None:
        self.iteration += 1
        work = _work_dir(ctx)

        model = (
            self.config.escalated_model
            if escalation.escalate_model and self.config.escalated_model
            else self.config.model
        )
        tools = (
            self.config.diagnostic_tools
            if escalation.diagnostic and self.config.diagnostic_tools
            else self.config.tools
        )

        prompt = _substitute(
            _template_for(self.config, BUILDER_TEMPLATE),
            {
                "root": str(ctx.adapter.root),
                "feedback": feedback or "(the judge provided no feedback)",
                "builder_log_tail": self._builder_log_tail(ctx),
                "diagnostic_instructions": DIAGNOSTIC_INSTRUCTIONS
                if escalation.diagnostic
                else "",
            },
        )
        prompt_path = work / f"builder-prompt-{self.iteration}.md"
        prompt_path.write_text(prompt)

        _invoke(
            self.config,
            model=model,
            tools=tools,
            add_dirs=[ctx.adapter.root],  # never the vault
            prompt_path=prompt_path,
            cwd=ctx.adapter.root,
            timeout=self.timeout,
        )
