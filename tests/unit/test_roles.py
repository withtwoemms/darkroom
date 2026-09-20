"""Unit tests for AdapterAssessor and GitCheckpointer."""

import subprocess

from darkroom.adapter import loads_adapter
from darkroom.loop import LoopContext
from darkroom.roles import AdapterAssessor, GitCheckpointer

ADAPTER = """
[project]
name = "p"
[commands]
test = "{cmd}"
[evidence]
dir = "evidence"
"""


def _ctx_with_test_command(tmp_path, cmd: str) -> LoopContext:
    adapter = loads_adapter(ADAPTER.replace("{cmd}", cmd), root=tmp_path)
    return LoopContext(adapter=adapter, scenario=None)


def _write_run(tmp_path, name="r1"):
    run = tmp_path / "evidence" / "runs" / name
    scenario_dir = run / "flow"
    scenario_dir.mkdir(parents=True)
    (scenario_dir / "01-x.json").write_text("{}")
    (run / "manifest.json").write_text(
        '{"schema_version": "2.0", "run_id": "' + name + '", "project": "", '
        '"timestamp": "", "scenarios": [{"scenario": "flow", "items": ['
        '{"kind": "log", "mime": "application/json", "path": "flow/01-x.json",'
        ' "scenario": "flow", "step": "x", "captured_at": "2026-01-01T00:00:00",'
        ' "metadata": {}}]}]}'
    )
    return run


class TestAdapterAssessor:
    def test_green_run_with_manifest(self, tmp_path):
        _write_run(tmp_path)
        ctx = _ctx_with_test_command(tmp_path, "true")
        assessment = AdapterAssessor().assess(ctx)
        assert assessment.tests_passed and assessment.verify_ok
        assert assessment.manifest_path is not None

    def test_failing_tests_still_assessed(self, tmp_path):
        _write_run(tmp_path)
        ctx = _ctx_with_test_command(tmp_path, "false")
        assessment = AdapterAssessor().assess(ctx)
        assert not assessment.tests_passed
        assert assessment.verify_ok  # evidence still verifiable

    def test_no_manifest_found(self, tmp_path):
        ctx = _ctx_with_test_command(tmp_path, "true")
        assessment = AdapterAssessor().assess(ctx)
        assert assessment.manifest_path is None
        assert not assessment.verify_ok

    def test_newest_run_selected(self, tmp_path):
        import os
        import time

        old = _write_run(tmp_path, "r1")
        new = _write_run(tmp_path, "r2")
        past = time.time() - 100
        os.utime(old / "manifest.json", (past, past))
        ctx = _ctx_with_test_command(tmp_path, "true")
        assessment = AdapterAssessor().assess(ctx)
        assert assessment.manifest_path == new / "manifest.json"

    def test_missing_test_command(self, tmp_path):
        adapter = loads_adapter('[project]\nname = "p"', root=tmp_path)
        assessment = AdapterAssessor().assess(LoopContext(adapter=adapter))
        assert not assessment.tests_passed
        assert "test" in assessment.notes


class TestGitCheckpointer:
    def _repo(self, tmp_path) -> LoopContext:
        subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
        for key, value in (
            ("user.email", "t@example.com"),
            ("user.name", "t"),
            ("commit.gpgsign", "false"),
            ("tag.gpgsign", "false"),
        ):
            subprocess.run(["git", "config", key, value], cwd=tmp_path, check=True)
        (tmp_path / "app.py").write_text("v1\n")
        subprocess.run(["git", "add", "-A"], cwd=tmp_path, check=True)
        subprocess.run(["git", "commit", "-q", "-m", "init"], cwd=tmp_path, check=True)
        adapter = loads_adapter('[project]\nname = "p"', root=tmp_path)
        return LoopContext(adapter=adapter)

    def test_clean_and_current(self, tmp_path):
        ctx = self._repo(tmp_path)
        checkpointer = GitCheckpointer()
        assert checkpointer.is_clean(ctx)
        (tmp_path / "app.py").write_text("v2\n")
        assert not checkpointer.is_clean(ctx)

    def test_checkpoint_and_changed_files(self, tmp_path):
        ctx = self._repo(tmp_path)
        checkpointer = GitCheckpointer()
        (tmp_path / "app.py").write_text("v2\n")
        ref = checkpointer.checkpoint(ctx, "auto: iteration 1 (50.0%)")
        assert checkpointer.is_clean(ctx)
        assert checkpointer.changed_files(ctx, ref) == ["app.py"]
        assert ref == checkpointer.current(ctx)

    def test_rollback_restores_best(self, tmp_path):
        ctx = self._repo(tmp_path)
        checkpointer = GitCheckpointer()
        best = checkpointer.current(ctx)
        (tmp_path / "app.py").write_text("regressed\n")
        checkpointer.checkpoint(ctx, "auto: iteration 1 (40.0%)")
        checkpointer.rollback(ctx, best)
        assert (tmp_path / "app.py").read_text() == "v1\n"

    def test_empty_iteration_still_checkpoints(self, tmp_path):
        ctx = self._repo(tmp_path)
        checkpointer = GitCheckpointer()
        before = checkpointer.current(ctx)
        after = checkpointer.checkpoint(ctx, "auto: iteration 1 (50.0%)")
        assert before != after  # --allow-empty keeps the iteration trail
