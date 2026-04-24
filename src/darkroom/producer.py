"""EvidenceProducer protocol and CaptureContext."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Protocol, runtime_checkable

from darkroom.model import EvidenceItem


@dataclass
class CaptureContext:
    """Context passed to every producer capture call."""

    scenario: str
    step: str
    run_dir: Path
    step_count: int = 0

    def make_path(self, name: str, extension: str) -> Path:
        """Generate a scenario-relative evidence file path.

        Returns a path relative to run_dir: {scenario}/{step_count:02d}-{name}.{ext}
        """
        filename = f"{self.step_count:02d}-{name}.{extension}"
        return Path(self.scenario) / filename


@runtime_checkable
class EvidenceProducer(Protocol):
    """Protocol that all evidence producers must satisfy."""

    kind: str
    mime: str

    def capture(self, ctx: CaptureContext, **kwargs) -> EvidenceItem: ...
