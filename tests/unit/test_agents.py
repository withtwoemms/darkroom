"""Unit tests for agent roles, driven by fake agents honoring the contract."""

import json
import sys
import textwrap
from datetime import datetime
from pathlib import Path

import pytest

from darkroom.adapter import ProjectAdapter
from darkroom.agents import AgentBuilder, AgentJudge
from darkroom.loop import Assessment, Escalation, LoopContext, LoopError
from darkroom.manifest import dump_manifest
from darkroom.model import EvidenceItem, RunManifest, ScenarioBundle
from darkroom.operator import RoleConfig
from darkroom.vault import FilesystemVault

RUBRIC = """
feature_id = "answer-flow"
version = "1"
scenario = "answer_flow"

[[criterion]]
id = "prints_answer"
points = 10
description = "prints 42"
evidence = ["command_transcript"]
"""

FAKE_JUDGE = """
    import re, sys
    prompt = open(sys.argv[1]).read()
    record = sys.argv[2] if len(sys.argv) > 2 else None
    evaluation_out = re.search(r"JSON to: (\\S+)", prompt).group(1)
    feedback_out = re.search(r"markdown to: (\\S+)", prompt).group(1)
    open(evaluation_out, "w").write(
        '{"run_id": "r", "rubric_version": "1", "scenarios": [{"scenario": '
        '"answer_flow", "criteria": [{"criterion": "prints_answer", "passed": '
        'false, "points_earned": 5, "points_possible": 10}]}]}'
    )
    open(feedback_out, "w").write("observed 41, expected different output")
    if record:
        open(record, "w").write(prompt)
"""

FAKE_BUILDER = """
    import sys
    record = sys.argv[2]
    open(record, "w").write(
        "PROMPT_FILE=" + sys.argv[1] + "\\n"
        + "MODEL=" + sys.argv[3] + "\\n"
        + "TOOLS=" + sys.argv[4] + "\\n"
        + "ADD_DIRS=" + " ".join(sys.argv[5:]) + "\\n"
        + open(sys.argv[1]).read()
    )
"""


def _script(tmp_path, name, body) -> Path:
    path = tmp_path / name
    path.write_text(textwrap.dedent(body))
    return path


def _ctx(tmp_path) -> LoopContext:
    root = tmp_path / "tenant"
    root.mkdir(exist_ok=True)
    return LoopContext(
        adapter=ProjectAdapter(root=root, name="p"),
        scenario="answer_flow",
        state_dir=tmp_path / "state",
    )


def _vault(tmp_path) -> FilesystemVault:
    vault = FilesystemVault(tmp_path / "vault")
    vault.initialize()
    (vault.root / "answer-flow.rubric.toml").write_text(RUBRIC)
    return vault


def _assessment(tmp_path) -> Assessment:
    run = tmp_path / "run"
    (run / "answer_flow").mkdir(parents=True)
    transcript = {"argv": ["app"], "exit_code": 0, "stdout": "41", "stderr": "",
                  "timed_out": False, "duration_ms": 3,
                  "stdout_truncated": False, "stderr_truncated": False}
    (run / "answer_flow" / "01-compute.json").write_text(json.dumps(transcript))
    manifest_path = run / "manifest.json"
    dump_manifest(
        RunManifest(
            run_id="r",
            scenarios=[ScenarioBundle(
                scenario="answer_flow",
                items=[EvidenceItem(
                    kind="command_transcript", mime="application/json",
                    path=Path("answer_flow/01-compute.json"),
                    scenario="answer_flow", step="compute",
                    captured_at=datetime(2026, 1, 1),
                )],
            )],
        ),
        manifest_path,
    )
    return Assessment(manifest_path=manifest_path, tests_passed=True, verify_ok=True)


class TestAgentJudge:
    def test_contract_honored_and_prompt_assembled(self, tmp_path):
        fake = _script(tmp_path, "fake_judge.py", FAKE_JUDGE)
        record = tmp_path / "prompt-record.txt"
        config = RoleConfig(
            model="claude-opus-5",
            tools=("Read", "Write"),
            invoke=f"{sys.executable} {fake} {{prompt}} {record}",
        )
        judge = AgentJudge(config, _vault(tmp_path))
        report = judge.judge(_ctx(tmp_path), _assessment(tmp_path), Escalation())

        assert report.evaluation.for_scenario("answer_flow") is not None
        assert judge.last_evaluation is report.evaluation
        assert "observed 41" in report.feedback

        prompt = record.read_text()
        assert "prints_answer" in prompt                     # rubric inlined
        assert "[command]" in prompt and "41" in prompt      # evidence rendered
        assert "never reveal criteria" in prompt
        assert "Harness notes: (none)" in prompt
        assert "Keep feedback general" in prompt             # level 0

    def test_feedback_level_escalates_prompt(self, tmp_path):
        fake = _script(tmp_path, "fake_judge.py", FAKE_JUDGE)
        record = tmp_path / "prompt-record.txt"
        config = RoleConfig(
            model="m", tools=("Read",),
            invoke=f"{sys.executable} {fake} {{prompt}} {record}",
        )
        judge = AgentJudge(config, _vault(tmp_path))
        judge.judge(
            _ctx(tmp_path), _assessment(tmp_path),
            Escalation(stagnation=2, feedback_level=2),
        )
        assert "hypothesize a plausible root cause" in record.read_text()

    def test_no_rubric_for_scenario_aborts(self, tmp_path):
        vault = FilesystemVault(tmp_path / "vault")
        vault.initialize()
        config = RoleConfig(model="m", tools=(), invoke="true")
        with pytest.raises(LoopError, match="no rubric"):
            AgentJudge(config, vault).judge(
                _ctx(tmp_path), _assessment(tmp_path), Escalation()
            )

    def test_silent_agent_aborts(self, tmp_path):
        config = RoleConfig(model="m", tools=(), invoke="true")
        with pytest.raises(LoopError, match="missing score is not a zero"):
            AgentJudge(config, _vault(tmp_path)).judge(
                _ctx(tmp_path), _assessment(tmp_path), Escalation()
            )


class TestAgentBuilder:
    def _config(self, tmp_path, record) -> RoleConfig:
        fake = _script(tmp_path, "fake_builder.py", FAKE_BUILDER)
        return RoleConfig(
            model="claude-sonnet-5",
            tools=("Read", "Edit"),
            escalated_model="claude-opus-5",
            diagnostic_tools=("Read", "Edit", "Bash"),
            invoke=f"{sys.executable} {fake} {{prompt}} {record} {{model}} {{tools}} {{add_dirs}}",
        )

    def test_normal_build(self, tmp_path):
        record = tmp_path / "record.txt"
        builder = AgentBuilder(self._config(tmp_path, record))
        ctx = _ctx(tmp_path)
        builder.build(ctx, "fix the output", Escalation())
        content = record.read_text()
        assert "MODEL=claude-sonnet-5" in content
        assert "TOOLS=Read,Edit" in content
        assert "fix the output" in content
        assert "DIAGNOSTIC MODE" not in content
        assert "Harness diagnostics" in content
        assert "(no run yet" in content
        assert str(ctx.adapter.root) in content  # add-dir covers tenant

    def test_escalation_switches_model_and_tools(self, tmp_path):
        record = tmp_path / "record.txt"
        builder = AgentBuilder(self._config(tmp_path, record))
        builder.build(
            _ctx(tmp_path), "still broken",
            Escalation(stagnation=3, diagnostic=True, escalate_model=True),
        )
        content = record.read_text()
        assert "MODEL=claude-opus-5" in content
        assert "TOOLS=Read,Edit,Bash" in content
        assert "DIAGNOSTIC MODE" in content

    def test_iteration_memory_inlined(self, tmp_path):
        record = tmp_path / "record.txt"
        ctx = _ctx(tmp_path)
        ctx.state_dir.mkdir(parents=True, exist_ok=True)
        (ctx.state_dir / "builder-log.md").write_text(
            "## iteration 1\nscore: 50.0 changed: app.py\n"
        )
        AgentBuilder(self._config(tmp_path, record)).build(
            ctx, "feedback", Escalation()
        )
        assert "changed: app.py" in record.read_text()
