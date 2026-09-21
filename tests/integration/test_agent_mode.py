"""End-to-end agent-mode convergence: darkroom auto --operator.

The same miniature seeded-bug project as the hook-mode test, but driven
through the full agent pipeline with fake agents standing in for the
claude CLI: the judge fake reads the rendered evidence *from its
prompt* (as a real judge would) and honors the output contract parsed
from the prompt text; the builder fake applies a fix in its working
directory (the tenant, as AgentBuilder guarantees). Along the way the
vault is read (and audited), the contract is derived from the rubric,
and gates ratchet on convergence.
"""

import json
import subprocess
import sys
import textwrap
from pathlib import Path

from darkroom.cli import main


def _write(path: Path, content: str) -> None:
    path.write_text(textwrap.dedent(content))


def _make_project(root: Path, vault_dir: Path, operator_path: Path) -> None:
    root.mkdir()
    _write(root / "app.py", 'print("41")\n')  # seeded bug

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
        root / "darkroom.toml",
        f"""
        [project]
        name = "mini"

        [commands]
        test = "EVIDENCE_MODE=1 EVIDENCE_DIR=evidence {sys.executable} harness.py"

        [evidence]
        dir = "evidence"
        contract = "evidence-contract.toml"

        [scenarios]
        rubric_glob = "scenarios/*.rubric.toml"
        """,
    )

    (root / "scenarios").mkdir()
    _write(
        root / "scenarios" / "answer-flow.rubric.toml",
        """
        feature_id = "answer-flow"
        version = "1"
        scenario = "answer_flow"

        [[criterion]]
        id = "prints_the_answer"
        points = 100
        description = "the program prints exactly 42"
        evidence = ["command_transcript"]
        """,
    )

    # fake claude: judge — reads evidence from the prompt, honors the contract
    _write(
        root / "fake_judge_agent.py",
        """
        import json, re, sys
        prompt = open(sys.argv[1]).read()
        evaluation_out = re.search(r"JSON to: (\\S+)", prompt).group(1)
        feedback_out = re.search(r"markdown to: (\\S+)", prompt).group(1)
        correct = "42" in re.search(r"--- stdout ---\\n(\\S+)", prompt).group(1)
        json.dump({
            "run_id": "r", "rubric_version": "1",
            "scenarios": [{"scenario": "answer_flow", "criteria": [{
                "criterion": "prints_the_answer", "passed": correct,
                "points_earned": 100 if correct else 50, "points_possible": 100,
            }]}],
        }, open(evaluation_out, "w"))
        if not correct:
            open(feedback_out, "w").write(
                "The program's output does not match the expected answer of 42."
            )
        """,
    )

    # fake claude: builder — applies the fix in cwd (the tenant)
    _write(
        root / "fake_builder_agent.py",
        """
        import sys
        from pathlib import Path
        prompt = open(sys.argv[1]).read()
        if "expected answer of 42" in prompt:
            Path("app.py").write_text('print("42")\\n')
        """,
    )

    _write(
        operator_path,
        f"""
        [judge]
        model = "claude-opus-5"

        [judge.invoke]
        command = "{sys.executable} {root}/fake_judge_agent.py {{prompt}}"

        [builder]
        model = "claude-sonnet-5"

        [builder.invoke]
        command = "{sys.executable} {root}/fake_builder_agent.py {{prompt}}"

        [vault]
        backend = "filesystem"
        path = "{vault_dir}"

        [loop]
        max_iterations = 4
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


def test_agent_mode_convergence(tmp_path, capsys, monkeypatch):
    project = tmp_path / "mini"
    vault_dir = tmp_path / "vault"
    operator_path = tmp_path / "operator.toml"  # outside the tenant, as intended
    _make_project(project, vault_dir, operator_path)
    monkeypatch.chdir(project)
    monkeypatch.setenv("DARKROOM_HOME", str(tmp_path / "darkroom-home"))
    monkeypatch.delenv("EVIDENCE_MODE", raising=False)
    monkeypatch.delenv("EVIDENCE_DIR", raising=False)

    # seal rubrics out of the tenant, derive the contract from the vault
    assert main(["vault", "seal", "--vault", str(vault_dir)]) == 0
    assert main(["vault", "derive-contract", "--vault", str(vault_dir)]) == 0
    subprocess.run(["git", "add", "-A"], cwd=project, check=True)
    subprocess.run(
        ["git", "commit", "-q", "-m", "seal rubrics; derive contract"],
        cwd=project, check=True,
    )
    capsys.readouterr()

    code = main([
        "auto", "--scenario", "answer_flow", "--operator", str(operator_path),
    ])
    out = capsys.readouterr().out
    assert code == 0, out
    assert "iteration 1: 50.0" in out
    assert "iteration 2: 100.0" in out
    assert "CONVERGED after 2 iteration(s)" in out

    # the fix is real and the gates ratcheted with rubric provenance
    assert (project / "app.py").read_text() == 'print("42")\n'
    gates = json.loads((project / "evidence-gates.json").read_text())
    assert gates["peaks"][0]["score"] == 100.0
    assert gates["peaks"][0]["rubric_version"] == "1"

    # the vault was the judge's rubric source, and every read is audited
    audit = (vault_dir / "audit.log").read_text()
    assert audit.count("read answer-flow") >= 2  # derive-contract + judge reads

    # opacity held structurally: no rubric remains anywhere in the tenant
    assert not list(project.rglob("*.rubric.toml"))


def test_agent_mode_defaults_vault_to_home(tmp_path, capsys, monkeypatch):
    # an operator config without [vault] falls back to the project's home
    # vault — empty here, so the judge aborts on the missing rubric rather
    # than misconfiguring silently
    project = tmp_path / "mini"
    vault_dir = tmp_path / "vault"
    operator_path = tmp_path / "operator.toml"
    _make_project(project, vault_dir, operator_path)
    monkeypatch.chdir(project)
    monkeypatch.setenv("DARKROOM_HOME", str(tmp_path / "darkroom-home"))
    operator_path.write_text('[judge]\nmodel = "m"\n[loop]\nmax_iterations = 1')
    assert main(["auto", "--scenario", "answer_flow", "--operator", str(operator_path)]) == 2
    assert "no rubric" in capsys.readouterr().out
