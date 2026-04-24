"""Evidence capture and manifest management for autonomous software delivery.

darkroom is the evidence subsystem of the Judge-Builder framework.
It provides typed records for evidence items, a producer protocol
for capturing diverse evidence kinds, and manifest serialization
for the handoff between Builder and Judge.
"""

from importlib.metadata import version as _pkg_version

from darkroom.capture import EvidenceCapture
from darkroom.manifest import dump_manifest, load_manifest
from darkroom.model import EvidenceItem, RunManifest, ScenarioBundle
from darkroom.producer import CaptureContext, EvidenceProducer
from darkroom.run import EvidenceRun

__all__ = [
    "CaptureContext",
    "EvidenceCapture",
    "EvidenceItem",
    "EvidenceProducer",
    "EvidenceRun",
    "RunManifest",
    "ScenarioBundle",
    "dump_manifest",
    "load_manifest",
]

__version__ = _pkg_version("darkroom")
