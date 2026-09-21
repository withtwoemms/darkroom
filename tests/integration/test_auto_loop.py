"""End-to-end automated convergence: darkroom auto with scripted hooks.

A miniature project with a seeded bug converges over two iterations with
no human between them: the harness captures command-transcript evidence,
a scripted judge scores the manifest and writes feedback, a scripted
builder applies the fix, git checkpoints every step, and gates ratchet
on convergence.
"""

import json
import subprocess
import sys
import textwrap
from pathlib import Path

from darkroom.cli import main


def _write(path: Path, content: str) -> None:
    path.write_text(textwrap.dedent(content))


def _make_project(root: Path) -> None:
    root.mkdir()
    _write(root / "app.py", 'print("41")\n')  # seeded bug: should be 42

    _write(
        root / "harness.py",
        f"""
        import json, sys
        from darkroom.capture import EvidenceCapture
        from darkroom.run import start_run, end_run

        start_run(project="mini")
        evidence = EvidenceCapture("answer_flow")
        path = evidence.command("compute", [{sys.executable!r}, "app.py"])
        transcript = json.loads(path.read_text())
        end_run()
        sys.exit(0 if transcript["stdout"].strip() == "42" else 1)
        """,
    )

    _write(
        root / "judge.py",
        """
        import json, sys
        manifest_path, evaluation_out, feedback_out = sys.argv[1:4]
        manifest = json.loads(open(manifest_path).read())
        item = manifest["scenarios"][0]["items"][0]
        transcript_path = f"{manifest_path.rsplit('/', 1)[0]}/{item['path']}"
        transcript = json.loads(open(transcript_path).read())
        correct = transcript["stdout"].strip() == "42"
        evaluation = {
            "run_id": manifest["run_id"],
            "evaluated_at": "2026-09-20T12:00:00",
            "rubric_version": "1",
            "scenarios": [{"scenario": "answer_flow", "criteria": [{
                "criterion": "prints_the_answer",
                "passed": correct,
                "points_earned": 100 if correct else 50,
                "points_possible": 100,
                "evidence": [item["path"]],
            }]}],
        }
        open(evaluation_out, "w").write(json.dumps(evaluation))
        if not correct:
            open(feedback_out, "w").write(
                "The computed answer is wrong. Expected output: 42, "
                f"observed: {transcript['stdout'].strip()}."
            )
        """,
    )

    _write(
        root / "fixer.py",
        """
        from pathlib import Path
        feedback = Path(__import__("sys").argv[1]).read_text()
        if "Expected output: 42" in feedback:
            Path("app.py").write_text('print("42")\\n')
        """,
    )

    _write(
        root / "darkroom.toml",
        f"""
        [project]
        name = "mini"

        [commands]
        test = "EVIDENCE_MODE=1 EVIDENCE_DIR=evidence {sys.executable} harness.py"
        """,
    )
    _write(root / ".gitignore", "evidence/\n.darkroom/\n__pycache__/\n")

    subprocess.run(["git", "init", "-q"], cwd=root, check=True)
    for key, value in (
        ("user.email", "loop@example.com"),
        ("user.name", "loop"),
        ("commit.gpgsign", "false"),
        ("tag.gpgsign", "false"),
    ):
        subprocess.run(["git", "config", key, value], cwd=root, check=True)
    subprocess.run(["git", "add", "-A"], cwd=root, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "init"], cwd=root, check=True)


def test_full_automated_convergence(tmp_path, capsys, monkeypatch):
    project = tmp_path / "mini"
    _make_project(project)
    monkeypatch.chdir(project)
    monkeypatch.setenv("DARKROOM_HOME", str(tmp_path / "darkroom-home"))
    monkeypatch.delenv("EVIDENCE_MODE", raising=False)
    monkeypatch.delenv("EVIDENCE_DIR", raising=False)

    code = main([
        "auto",
        "--scenario", "answer_flow",
        "--judge-cmd", f"{sys.executable} judge.py {{manifest}} {{evaluation_out}} {{feedback_out}}",
        "--build-cmd", f"{sys.executable} fixer.py {{feedback}}",
        "--max-iter", "4",
    ])
    out = capsys.readouterr().out
    assert code == 0, out

    assert "iteration 1: 50.0" in out
    assert "iteration 2: 100.0" in out
    assert "CONVERGED after 2 iteration(s)" in out

    # gates ratcheted on convergence, citing rubric provenance
    gates = json.loads((project / "evidence-gates.json").read_text())
    assert gates["peaks"][0]["scenario"] == "answer_flow"
    assert gates["peaks"][0]["score"] == 100.0
    assert gates["peaks"][0]["rubric_version"] == "1"

    # git carries the iteration trail
    log = subprocess.run(
        ["git", "log", "--oneline"], cwd=project, capture_output=True, text=True
    ).stdout
    assert "auto: iteration 1 (50.0%)" in log

    # iteration memory exists — in the darkroom home, not the tenant
    log = tmp_path / "darkroom-home" / "projects" / "mini" / "state" / "builder-log.md"
    assert "## iteration 1" in log.read_text()
    assert not (project / ".darkroom").exists()

    # and the fix is real
    assert (project / "app.py").read_text() == 'print("42")\n'


def test_judge_hook_writing_nothing_aborts(tmp_path, capsys, monkeypatch):
    project = tmp_path / "mini"
    _make_project(project)
    monkeypatch.chdir(project)
    monkeypatch.setenv("DARKROOM_HOME", str(tmp_path / "darkroom-home"))
    code = main([
        "auto",
        "--scenario", "answer_flow",
        "--judge-cmd", "true",  # writes no evaluation
        "--build-cmd", "true",
        "--max-iter", "2",
    ])
    out = capsys.readouterr().out
    assert code == 2
    assert "missing score is not a zero" in out
