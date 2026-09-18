"""Command transcript evidence producer.

The first non-browser evidence kind: the producer runs the command
itself, so the transcript is harness-captured ground truth rather than a
reported claim. This is the evidence backbone for judging CLIs, build
steps, seeds, and anything else that speaks through a process.
"""

from __future__ import annotations

import json
import shlex
import subprocess
from datetime import datetime
from pathlib import Path

from darkroom.model import EvidenceItem
from darkroom.producer import CaptureContext


class CommandTranscriptProducer:
    """Runs a command and captures its full transcript as JSON evidence."""

    kind = "command_transcript"
    mime = "application/json"

    def capture(
        self,
        ctx: CaptureContext,
        *,
        argv: list[str] | str,
        cwd: Path | None = None,
        timeout: float = 120,
        max_output_bytes: int = 1_000_000,
        **kwargs,
    ) -> EvidenceItem:
        argv_list = argv if isinstance(argv, list) else shlex.split(argv)

        started = datetime.now()
        timed_out = False
        try:
            proc = subprocess.run(
                argv_list, cwd=cwd, capture_output=True, timeout=timeout
            )
            exit_code: int | None = proc.returncode
            stdout_bytes, stderr_bytes = proc.stdout, proc.stderr
        except subprocess.TimeoutExpired as exc:
            exit_code = None
            timed_out = True
            stdout_bytes = exc.stdout or b""
            stderr_bytes = exc.stderr or b""
        captured_at = datetime.now()
        duration_ms = int((captured_at - started).total_seconds() * 1000)

        def _decode(raw: bytes) -> tuple[str, bool]:
            truncated = len(raw) > max_output_bytes
            return raw[:max_output_bytes].decode("utf-8", errors="replace"), truncated

        stdout, stdout_truncated = _decode(stdout_bytes)
        stderr, stderr_truncated = _decode(stderr_bytes)

        transcript = {
            "captured_at": captured_at.isoformat(),
            "argv": argv_list,
            "cwd": str(cwd) if cwd else None,
            "exit_code": exit_code,
            "timed_out": timed_out,
            "duration_ms": duration_ms,
            "stdout": stdout,
            "stderr": stderr,
            "stdout_truncated": stdout_truncated,
            "stderr_truncated": stderr_truncated,
        }

        rel_path = ctx.make_path(ctx.step, "json")
        abs_path = ctx.run_dir / rel_path
        abs_path.parent.mkdir(parents=True, exist_ok=True)
        abs_path.write_text(json.dumps(transcript, indent=2, default=str))

        metadata: dict = {"exit_code": exit_code, "duration_ms": duration_ms}
        if timed_out:
            metadata["timed_out"] = True
        return EvidenceItem(
            kind=self.kind,
            mime=self.mime,
            path=rel_path,
            scenario=ctx.scenario,
            step=ctx.step,
            captured_at=captured_at,
            metadata=metadata,
        )
