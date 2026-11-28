"""Unit tests for on-demand judging: a score without a build.

``darkroom judge`` is the standalone producer of an evaluation — the
piece that was missing while ``auto`` was the only thing that could
score a run. These tests hold it to four things, in the order they
matter:

- the judge sees the rubric half only. The exposure's steps must not
  reach the prompt: a judge that can read the exam is scoring the exam,
  and that defect would be invisible in the output.
- it builds nothing and commits nothing. The whole point is that
  recording a score is read-only.
- every judging lands in the vault's audit log, so scoring the same
  evidence repeatedly is visible rather than silent.
- the evaluation carries its provenance — origin, evidence, rubric,
  tenant commit — because a gate ratcheted from it is a claim about a
  commit, and the claim has to be checkable.

The model is always a fake script honoring the judge's file contract,
as in ``test_agents.py``: no test here may spend a judge call.
"""

import json
import sys
import textwrap
from datetime import datetime
from pathlib import Path

import pytest

from darkroom.adapter import ProjectAdapter, load_adapter
from darkroom.cli import main
from darkroom.judging import (
    JudgingError,
    harness_outcome,
    judge_run,
    resolve_manifest,
    scorecard,
)
from darkroom.manifest import dump_manifest
from darkroom.model import EvidenceItem, RunManifest, ScenarioBundle
from darkroom.operator import load_operator
from darkroom.vault import FilesystemVault

RUBRIC = """
feature_id = "answer-flow"
version = "2"
scenario = "answer_flow"

[[criterion]]
id = "prints_answer"
points = 10
description = "prints 42"
evidence = ["command_transcript"]
"""

EXPOSURE = """
scenario = "answer_flow"

[[step]]
name = "compute"
kind = "command"
cmd = "app compute"
"""

# The fake judge reads the two output paths out of its prompt, exactly
# as a real judge agent does, and records the prompt for inspection.
FAKE_JUDGE = """
    import re, sys
    prompt = open(sys.argv[1]).read()
    record = sys.argv[2] if len(sys.argv) > 2 else None
    evaluation_out = re.search(r"JSON to: (\\S+)", prompt).group(1)
    feedback_out = re.search(r"markdown to: (\\S+)", prompt).group(1)
    open(evaluation_out, "w").write(
        '{"run_id": "r", "rubric_version": "2", "provenance": '
        '{"origin": "loop", "tenant_commit": "deadbeef"}, "scenarios": '
        '[{"scenario": "answer_flow", "criteria": [{"criterion": '
        '"prints_answer", "passed": true, "points_earned": 10, '
        '"points_possible": 10, "notes": "transcript shows 42"}]}]}'
    )
    open(feedback_out, "w").write("nothing to fix")
    if record:
        open(record, "w").write(prompt)
"""


def _script(tmp_path, body) -> Path:
    path = tmp_path / "fake_judge.py"
    path.write_text(textwrap.dedent(body))
    return path


def _tenant(tmp_path, evidence="evidence") -> Path:
    root = tmp_path / "tenant"
    root.mkdir(exist_ok=True)
    (root / "darkroom.toml").write_text(
        f'[project]\nname = "p"\n[evidence]\ndir = "{evidence}"\n'
    )
    return root


def _run(root: Path, run_id: str, *, ok: bool = True, log: bool = True) -> Path:
    """One captured run under the tenant's evidence directory."""
    run_dir = root / "evidence" / "runs" / run_id
    (run_dir / "answer_flow").mkdir(parents=True)
    (run_dir / "answer_flow" / "01-compute.json").write_text(
        json.dumps(
            {
                "argv": ["app", "compute"], "exit_code": 0, "stdout": "42",
                "stderr": "", "timed_out": False, "duration_ms": 3,
                "stdout_truncated": False, "stderr_truncated": False,
            }
        )
    )
    if log:
        (run_dir / "harness.log").write_text(
            "selection: all\n"
            f"scenario answer_flow: {'ok' if ok else 'FAILED'}\n"
            "  compute [command] ok\n"
        )
    manifest_path = run_dir / "manifest.json"
    dump_manifest(
        RunManifest(
            run_id=run_id,
            project="p",
            scenarios=[
                ScenarioBundle(
                    scenario="answer_flow",
                    items=[
                        EvidenceItem(
                            kind="command_transcript",
                            mime="application/json",
                            path=Path("answer_flow/01-compute.json"),
                            scenario="answer_flow",
                            step="compute",
                            captured_at=datetime(2026, 1, 1),
                        )
                    ],
                    provenance={"exposure_sha256": "abc", "rubric_version": "2"},
                )
            ],
        ),
        manifest_path,
    )
    return manifest_path


def _home(tmp_path, invoke: str) -> Path:
    """A darkroom home with the proof sealed and a fake judge configured."""
    home = tmp_path / "home" / "projects" / "p"
    proof = home / "proofs" / "answer_flow"
    proof.mkdir(parents=True)
    (proof / "exposure.toml").write_text(EXPOSURE)
    (proof / "rubric.toml").write_text(RUBRIC)
    (home / "vault").mkdir(parents=True)
    (home / "operator.toml").write_text(
        f'[judge]\nmodel = "m"\ninvoke = "{invoke}"\n'
    )
    return home


def _vault(home: Path) -> FilesystemVault:
    vault = FilesystemVault(
        home / "vault", proofs=home / "proofs", backdrops=home / "backdrops.toml"
    )
    vault.initialize()
    return vault


class TestRunSelection:
    def test_named_run_is_resolved(self, tmp_path):
        root = _tenant(tmp_path)
        _run(root, "2026-01-01T00-00-00")
        expected = _run(root, "2026-01-02T00-00-00")
        adapter = load_adapter(root / "darkroom.toml")
        assert resolve_manifest(adapter, "2026-01-02T00-00-00") == expected

    def test_newest_run_when_none_named(self, tmp_path):
        root = _tenant(tmp_path)
        first = _run(root, "2026-01-01T00-00-00")
        second = _run(root, "2026-01-02T00-00-00")
        import os

        os.utime(first, (1, 1))
        os.utime(second, (2, 2))
        adapter = load_adapter(root / "darkroom.toml")
        assert resolve_manifest(adapter, None) == second

    def test_unknown_run_names_where_it_looked(self, tmp_path):
        root = _tenant(tmp_path)
        _run(root, "2026-01-01T00-00-00")
        adapter = load_adapter(root / "darkroom.toml")
        with pytest.raises(JudgingError, match="no run 'nope'"):
            resolve_manifest(adapter, "nope")

    def test_no_runs_at_all_points_at_capture(self, tmp_path):
        root = _tenant(tmp_path)
        adapter = load_adapter(root / "darkroom.toml")
        with pytest.raises(JudgingError, match="darkroom expose"):
            resolve_manifest(adapter, None)


class TestHarnessOutcome:
    def test_green_log_reads_as_passed(self, tmp_path):
        root = _tenant(tmp_path)
        manifest = _run(root, "r1", ok=True)
        assert harness_outcome(manifest.parent, "answer_flow") == (True, "")

    def test_red_log_names_the_scenario(self, tmp_path):
        root = _tenant(tmp_path)
        manifest = _run(root, "r1", ok=False)
        passed, note = harness_outcome(manifest.parent, None)
        assert passed is False and "answer_flow" in note

    def test_missing_log_is_unknown_not_failed(self, tmp_path):
        """An absent log must not be reported to the judge as a failure:
        unknown and failed are different facts, and only one is true."""
        root = _tenant(tmp_path)
        manifest = _run(root, "r1", log=False)
        passed, note = harness_outcome(manifest.parent, None)
        assert passed is False and "unknown" in note

    def test_a_scenario_the_log_does_not_mention(self, tmp_path):
        root = _tenant(tmp_path)
        manifest = _run(root, "r1")
        passed, note = harness_outcome(manifest.parent, "other_flow")
        assert passed is False and "no outcome" in note


class TestJudgeRun:
    def _judging(self, tmp_path, record: Path | None = None):
        root = _tenant(tmp_path)
        manifest = _run(root, "2026-01-02T00-00-00")
        fake = _script(tmp_path, FAKE_JUDGE)
        tail = f" {record}" if record else ""
        home = _home(tmp_path, f"{sys.executable} {fake} {{prompt}}{tail}")
        adapter = load_adapter(root / "darkroom.toml")
        operator = load_operator(home / "operator.toml")
        judging = judge_run(
            adapter,
            operator,
            _vault(home),
            manifest_path=manifest,
            scenario="answer_flow",
            state_dir=home / "state",
        )
        return judging, home, root

    def test_the_judge_is_handed_the_rubric_and_never_the_exposure(self, tmp_path):
        record = tmp_path / "prompt.md"
        self._judging(tmp_path, record)
        prompt = record.read_text()
        assert "prints_answer" in prompt          # criteria inlined
        assert "[command]" in prompt and "42" in prompt   # evidence rendered
        # the exposure itself is absent. A transcript naturally names the
        # command it captured; what must never appear is the script — the
        # steps, their order, and the expectations each was posed with.
        assert "[[step]]" not in prompt
        assert 'kind = "command"' not in prompt
        assert 'cmd = ' not in prompt

    def test_the_score_is_produced_and_written(self, tmp_path):
        judging, home, _ = self._judging(tmp_path)
        assert judging.score == 100.0
        assert judging.run_id == "2026-01-02T00-00-00"
        assert judging.evaluation_path.is_file()
        assert judging.feedback_path is not None

    def test_the_evaluation_lands_outside_the_campaign_record(self, tmp_path):
        """An on-demand judging is not a loop campaign, so it must not
        appear in state/loop/, which the dossier and status read as
        iteration history."""
        judging, home, _ = self._judging(tmp_path)
        assert judging.evaluation_path.parent.parent == home / "state" / "judge"
        assert not (home / "state" / "loop").exists()
        assert not (home / "state" / "builder-log.md").exists()

    def test_nothing_is_built_in_the_tenant(self, tmp_path):
        judging, _, root = self._judging(tmp_path)
        assert sorted(p.name for p in root.iterdir()) == [
            "darkroom.toml", "evidence",
        ]

    def test_provenance_is_stamped_over_whatever_the_judge_claimed(self, tmp_path):
        """The fake judge writes a provenance of its own, claiming the loop
        and a commit. darkroom's stamp replaces it: a scorer's account of
        who asked and what it was shown is not evidence of either."""
        judging, _, _ = self._judging(tmp_path)
        written = json.loads(judging.evaluation_path.read_text())
        provenance = written["provenance"]
        assert provenance == judging.evaluation.provenance
        assert provenance["origin"] == "on-demand"
        assert provenance["tenant_commit"] != "deadbeef"
        assert provenance["evidence_run"] == "2026-01-02T00-00-00"
        assert provenance["rubric_versions"] == {"answer_flow": "2"}
        assert len(provenance["evidence_manifest_sha256"]) == 64
        assert len(provenance["rubric_sha256"]) == 64
        # and the judge's own verdict survives the stamping
        assert written["scenarios"][0]["criteria"][0]["points_earned"] == 10

    def test_the_judging_is_audited(self, tmp_path):
        judging, home, _ = self._judging(tmp_path)
        audit = (home / "vault" / "audit.log").read_text()
        assert "judged answer_flow origin=on-demand" in audit
        assert "score=100.0" in audit
        assert str(judging.evaluation_path) in audit

    def test_scorecard_reports_each_criterion(self, tmp_path):
        judging, _, _ = self._judging(tmp_path)
        lines = scorecard(judging, "answer_flow")
        assert lines[0] == "answer_flow: 100.0 (10/10)"
        assert "pass prints_answer 10/10" in lines[1]
        assert "transcript shows 42" in lines[2]

    def test_a_scenario_with_no_rubric_is_refused_before_spending(self, tmp_path):
        root = _tenant(tmp_path)
        manifest = _run(root, "r1")
        home = _home(tmp_path, "false")
        adapter = load_adapter(root / "darkroom.toml")
        operator = load_operator(home / "operator.toml")
        with pytest.raises(JudgingError, match="no rubric"):
            judge_run(
                adapter, operator, _vault(home),
                manifest_path=manifest, scenario="other_flow",
                state_dir=home / "state",
            )


class TestJudgeCommand:
    def _project(self, tmp_path, monkeypatch, invoke=None):
        root = _tenant(tmp_path)
        _run(root, "2026-01-02T00-00-00")
        fake = _script(tmp_path, FAKE_JUDGE)
        home = _home(
            tmp_path, invoke or f"{sys.executable} {fake} {{prompt}}"
        )
        monkeypatch.setenv("DARKROOM_HOME", str(tmp_path / "home"))
        monkeypatch.chdir(root)
        return root, home

    def test_judging_prints_the_scorecard_and_the_next_step(
        self, tmp_path, monkeypatch, capsys
    ):
        root, home = self._project(tmp_path, monkeypatch)
        assert main(["judge", "--scenario", "answer_flow"]) == 0
        out = capsys.readouterr().out
        assert "judged run 2026-01-02T00-00-00" in out
        assert "answer_flow: 100.0 (10/10)" in out
        assert "score: 100.0" in out
        assert "darkroom gate check" in out

    def test_the_evaluation_composes_with_gate_update(
        self, tmp_path, monkeypatch, capsys
    ):
        """The point of the command: what it writes is what the gate
        commands already take."""
        root, home = self._project(tmp_path, monkeypatch)
        assert main(["judge", "--scenario", "answer_flow"]) == 0
        written = [
            line.split(": ", 1)[1]
            for line in capsys.readouterr().out.splitlines()
            if line.startswith("evaluation written: ")
        ]
        gates = tmp_path / "gates.json"
        assert main(["gate", "update", written[0], "--gates", str(gates)]) == 0
        recorded = json.loads(gates.read_text())
        assert recorded["peaks"][0]["scenario"] == "answer_flow"
        assert recorded["peaks"][0]["score"] == 100.0

    def test_a_named_run_that_does_not_exist_is_an_error(
        self, tmp_path, monkeypatch, capsys
    ):
        self._project(tmp_path, monkeypatch)
        assert main(["judge", "--run", "nope"]) == 2
        assert "no run 'nope'" in capsys.readouterr().out

    def test_judging_needs_operator_authority(self, tmp_path, monkeypatch, capsys):
        """The judge's model and the vault are operator-side; without that
        config there is nothing to judge with, and guessing would put
        authority in the tenant's file."""
        root = _tenant(tmp_path)
        _run(root, "r1")
        monkeypatch.setenv("DARKROOM_HOME", str(tmp_path / "empty-home"))
        monkeypatch.chdir(root)
        assert main(["judge"]) == 2
        assert "needs an operator config" in capsys.readouterr().out

    def test_it_refuses_to_write_the_evaluation_into_the_tenant(
        self, tmp_path, monkeypatch, capsys
    ):
        """An evaluation carries scores, so writing one where the builder
        can read it reopens the Goodhart channel the home exists to
        close — the same refusal the dossier makes."""
        root, _ = self._project(tmp_path, monkeypatch)
        assert main(["judge", "--state", str(root / "state")]) == 2
        assert "refusing to write an evaluation inside the tenant" in (
            capsys.readouterr().out
        )

    def test_no_adapter_is_an_error(self, tmp_path, monkeypatch, capsys):
        monkeypatch.chdir(tmp_path)
        assert main(["judge"]) == 2
        assert "no darkroom.toml" in capsys.readouterr().out


class TestLoopJudgingIsStampedToo:
    def test_a_loop_judging_records_its_origin_and_is_audited(self, tmp_path):
        """The same machinery serves both producers, so the loop's own
        evaluations gain the stamp and the audit line as well — otherwise
        'which of these did a human ask for?' stays unanswerable."""
        from darkroom.agents import AgentJudge
        from darkroom.loop import Assessment, Escalation, LoopContext

        root = _tenant(tmp_path)
        manifest = _run(root, "r1")
        fake = _script(tmp_path, FAKE_JUDGE)
        home = _home(tmp_path, f"{sys.executable} {fake} {{prompt}}")
        ctx = LoopContext(
            adapter=ProjectAdapter(root=root, name="p"),
            scenario="answer_flow",
            state_dir=home / "state",
        )
        assessment = Assessment(
            manifest_path=manifest, tests_passed=True, verify_ok=True
        )
        judge = AgentJudge(load_operator(home / "operator.toml").judge, _vault(home))
        report = judge.judge(ctx, assessment, Escalation())

        assert report.evaluation.provenance["origin"] == "loop"
        assert judge.last_evaluation_path.parent.parent == home / "state" / "loop"
        assert "origin=loop" in (home / "vault" / "audit.log").read_text()
