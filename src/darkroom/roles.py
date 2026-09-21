"""Concrete loop roles darkroom can own itself.

:class:`AdapterAssessor` runs the project's declared test command and
verifies the resulting run against the contract. :class:`GitCheckpointer`
implements checkpoints, best-ref rollback, and change listing over git.
Judge and builder roles are supplied by the operator (shell hooks now,
agent implementations in the orchestration releases).
"""

from __future__ import annotations

import subprocess
from pathlib import Path

from darkroom.contract import load_contract
from darkroom.loop import Assessment, LoopContext
from darkroom.verify import verify


class AdapterAssessor:
    """Runs the adapter's ``test`` command and verifies the newest run."""

    def __init__(self, timeout: float = 1800):
        self.timeout = timeout

    def assess(self, ctx: LoopContext) -> Assessment:
        adapter = ctx.adapter
        substitutions = {"scenario": ctx.scenario} if ctx.scenario else {}
        try:
            command = adapter.command("test", **substitutions)
        except (KeyError, ValueError) as exc:
            return Assessment(
                manifest_path=None,
                tests_passed=False,
                verify_ok=False,
                notes=str(exc),
            )

        completed = subprocess.run(
            ["/bin/sh", "-c", command],
            cwd=adapter.root,
            capture_output=True,
            timeout=self.timeout,
        )
        tests_passed = completed.returncode == 0
        output_tail = (
            (completed.stdout + completed.stderr)
            .decode("utf-8", errors="replace")
            .strip()[-1500:]
        )

        manifest_path = self._newest_manifest(adapter)
        if manifest_path is None:
            return Assessment(
                manifest_path=None,
                tests_passed=tests_passed,
                verify_ok=False,
                notes="no run manifest found after test command"
                + (f"; test output: {output_tail}" if output_tail else ""),
            )

        contract = None
        if adapter.contract_path is not None:
            contract_file = adapter.resolve(adapter.contract_path)
            if contract_file.exists():
                contract = load_contract(contract_file)
        result = verify([manifest_path], contract)
        notes = "; ".join(f.message for f in result.errors[:5])
        if not tests_passed and output_tail:
            notes = (notes + " | " if notes else "") + f"test output: {output_tail}"
        return Assessment(
            manifest_path=manifest_path,
            tests_passed=tests_passed,
            verify_ok=result.ok,
            notes=notes,
        )

    @staticmethod
    def _newest_manifest(adapter) -> Path | None:
        runs = adapter.resolve(adapter.evidence_dir) / "runs"
        manifests = sorted(
            runs.glob("*/manifest.json"),
            key=lambda p: p.stat().st_mtime,
        )
        return manifests[-1] if manifests else None


class GitCheckpointer:
    """Checkpoints, best-ref rollback, and change listing over git."""

    def _git(self, ctx: LoopContext, *args: str) -> str:
        completed = subprocess.run(
            ["git", *args],
            cwd=ctx.adapter.root,
            capture_output=True,
            text=True,
            check=True,
        )
        return completed.stdout.strip()

    def is_clean(self, ctx: LoopContext) -> bool:
        return self._git(ctx, "status", "--porcelain") == ""

    def current(self, ctx: LoopContext) -> str:
        return self._git(ctx, "rev-parse", "HEAD")

    def checkpoint(self, ctx: LoopContext, label: str) -> str:
        self._git(ctx, "add", "-A")
        self._git(ctx, "commit", "--allow-empty", "-m", label)
        return self.current(ctx)

    def rollback(self, ctx: LoopContext, ref: str) -> None:
        """Restore the working tree to ``ref`` without rewriting history."""
        self._git(ctx, "checkout", ref, "--", ".")

    def changed_files(self, ctx: LoopContext, ref: str) -> list[str]:
        output = self._git(ctx, "show", "--name-only", "--format=", ref)
        return [line for line in output.splitlines() if line]
