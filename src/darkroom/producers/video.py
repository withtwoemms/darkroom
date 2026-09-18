"""Video evidence producer.

Registers an already-recorded video file (e.g. a Playwright context
recording, finalized on context close) as evidence, moving it into the
run's scenario directory. Recording itself is the harness's job; this
producer owns the handoff into the manifest.
"""

from __future__ import annotations

import shutil
from datetime import datetime
from pathlib import Path

from darkroom.model import EvidenceItem
from darkroom.producer import CaptureContext


class VideoProducer:
    """Files a finalized recording under the run and manifests it."""

    kind = "video"
    mime = "video/webm"

    def capture(
        self,
        ctx: CaptureContext,
        *,
        source: Path,
        keep_source: bool = False,
        **kwargs,
    ) -> EvidenceItem:
        """Move (or copy, with ``keep_source``) the recording into the run."""
        source = Path(source)
        extension = source.suffix.lstrip(".") or "webm"
        rel_path = ctx.make_path(ctx.step, extension)
        abs_path = ctx.run_dir / rel_path
        abs_path.parent.mkdir(parents=True, exist_ok=True)
        if keep_source:
            shutil.copy2(source, abs_path)
        else:
            shutil.move(str(source), str(abs_path))
        return EvidenceItem(
            kind=self.kind,
            mime=self.mime,
            path=rel_path,
            scenario=ctx.scenario,
            step=ctx.step,
            captured_at=datetime.now(),
            metadata={"size_bytes": abs_path.stat().st_size},
        )
