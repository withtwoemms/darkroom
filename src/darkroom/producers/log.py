"""Structured log evidence producer."""

from __future__ import annotations

import json
from datetime import datetime

from darkroom.model import EvidenceItem
from darkroom.producer import CaptureContext


class LogProducer:
    """Captures structured data as JSON evidence."""

    kind = "log"
    mime = "application/json"

    def capture(
        self,
        ctx: CaptureContext,
        *,
        data: dict,
        **kwargs,
    ) -> EvidenceItem:
        """Write structured data to a JSON file and return an EvidenceItem."""
        rel_path = ctx.make_path(ctx.step, "json")
        abs_path = ctx.run_dir / rel_path
        abs_path.parent.mkdir(parents=True, exist_ok=True)

        captured_at = datetime.now()
        with open(abs_path, "w") as f:
            json.dump(
                {
                    "captured_at": captured_at.isoformat(),
                    "scenario": ctx.scenario,
                    "step": ctx.step,
                    "data": data,
                },
                f,
                indent=2,
                default=str,
            )

        return EvidenceItem(
            kind=self.kind,
            mime=self.mime,
            path=rel_path,
            scenario=ctx.scenario,
            step=ctx.step,
            captured_at=captured_at,
        )
