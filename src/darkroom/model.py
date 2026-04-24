"""Core data model for evidence items, scenario bundles, and run manifests."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path


@dataclass(frozen=True)
class EvidenceItem:
    """A single piece of captured evidence.

    Paths are relative to the manifest file's parent directory.
    Absolute paths (starting with '/') are also accepted.
    """

    kind: str
    mime: str
    path: Path
    scenario: str
    step: str
    captured_at: datetime
    metadata: dict = field(default_factory=dict)


@dataclass
class ScenarioBundle:
    """All evidence items for a single scenario within a run."""

    scenario: str
    items: list[EvidenceItem] = field(default_factory=list)

    def add(self, item: EvidenceItem) -> None:
        self.items.append(item)


@dataclass
class RunManifest:
    """Top-level manifest describing an entire evidence run."""

    run_id: str
    schema_version: str = "2.0"
    project: str = ""
    timestamp: str = ""
    scenarios: list[ScenarioBundle] = field(default_factory=list)

    def get_or_create_bundle(self, scenario: str) -> ScenarioBundle:
        for bundle in self.scenarios:
            if bundle.scenario == scenario:
                return bundle
        bundle = ScenarioBundle(scenario=scenario)
        self.scenarios.append(bundle)
        return bundle
