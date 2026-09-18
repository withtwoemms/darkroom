"""File snapshot and diff evidence producers.

Snapshots freeze a file's content into the run with a checksum, so later
judging (or auditing) can trust the bytes; diffs make a change itself
the evidence.
"""

from __future__ import annotations

import difflib
import hashlib
import mimetypes
from datetime import datetime
from pathlib import Path

from darkroom.model import EvidenceItem
from darkroom.producer import CaptureContext


class FileSnapshotProducer:
    """Copies a file into the run, recording size and a sha256 checksum."""

    kind = "file_snapshot"
    mime = "application/octet-stream"

    def capture(
        self,
        ctx: CaptureContext,
        *,
        source: Path,
        **kwargs,
    ) -> EvidenceItem:
        source = Path(source)
        content = source.read_bytes()

        extension = source.suffix.lstrip(".") or "snapshot"
        rel_path = ctx.make_path(ctx.step, extension)
        abs_path = ctx.run_dir / rel_path
        abs_path.parent.mkdir(parents=True, exist_ok=True)
        abs_path.write_bytes(content)

        return EvidenceItem(
            kind=self.kind,
            mime=mimetypes.guess_type(source.name)[0] or self.mime,
            path=rel_path,
            scenario=ctx.scenario,
            step=ctx.step,
            captured_at=datetime.now(),
            metadata={
                "source": str(source),
                "size_bytes": len(content),
                "sha256": hashlib.sha256(content).hexdigest(),
            },
        )


class DiffProducer:
    """Captures a unified diff between two files as evidence."""

    kind = "diff"
    mime = "text/x-diff"

    def capture(
        self,
        ctx: CaptureContext,
        *,
        before: Path,
        after: Path,
        **kwargs,
    ) -> EvidenceItem:
        before, after = Path(before), Path(after)
        before_lines = before.read_text(errors="replace").splitlines()
        after_lines = after.read_text(errors="replace").splitlines()

        diff_lines = list(
            difflib.unified_diff(
                before_lines,
                after_lines,
                fromfile=str(before),
                tofile=str(after),
                lineterm="",
            )
        )

        rel_path = ctx.make_path(ctx.step, "diff")
        abs_path = ctx.run_dir / rel_path
        abs_path.parent.mkdir(parents=True, exist_ok=True)
        abs_path.write_text("\n".join(diff_lines) + ("\n" if diff_lines else ""))

        added = sum(
            1 for line in diff_lines
            if line.startswith("+") and not line.startswith("+++")
        )
        removed = sum(
            1 for line in diff_lines
            if line.startswith("-") and not line.startswith("---")
        )
        return EvidenceItem(
            kind=self.kind,
            mime=self.mime,
            path=rel_path,
            scenario=ctx.scenario,
            step=ctx.step,
            captured_at=datetime.now(),
            metadata={
                "before": str(before),
                "after": str(after),
                "lines_added": added,
                "lines_removed": removed,
            },
        )
