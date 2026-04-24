"""Manifest serialization: dump RunManifest to JSON, load from JSON (v1 and v2)."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from darkroom.model import EvidenceItem, RunManifest, ScenarioBundle

CURRENT_SCHEMA_VERSION = "2.0"

# v1 type -> (kind, mime) mapping
_V1_TYPE_MAP: dict[str, tuple[str, str]] = {
    "screenshot": ("screenshot", "image/png"),
    "screenshot_element": ("screenshot_element", "image/png"),
    "log": ("log", "application/json"),
}


def dump_manifest(manifest: RunManifest, path: Path) -> Path:
    """Serialize a RunManifest to a JSON file. Always writes v2 format."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w") as f:
        f.write(dumps_manifest(manifest))
    return path


def dumps_manifest(manifest: RunManifest) -> str:
    """Serialize a RunManifest to a JSON string. Always writes v2 format."""
    data = {
        "schema_version": manifest.schema_version,
        "run_id": manifest.run_id,
        "project": manifest.project,
        "timestamp": manifest.timestamp,
        "scenarios": [
            {
                "scenario": bundle.scenario,
                "items": [
                    {
                        "kind": item.kind,
                        "mime": item.mime,
                        "path": item.path.as_posix(),
                        "scenario": item.scenario,
                        "step": item.step,
                        "captured_at": item.captured_at.isoformat(),
                        "metadata": item.metadata,
                    }
                    for item in bundle.items
                ],
            }
            for bundle in manifest.scenarios
        ],
    }
    return json.dumps(data, indent=2)


def load_manifest(path: Path) -> RunManifest:
    """Load a manifest from a JSON file, handling both v1 and v2 schemas."""
    with open(path) as f:
        return loads_manifest(f.read())


def loads_manifest(text: str) -> RunManifest:
    """Load a manifest from a JSON string, handling both v1 and v2 schemas."""
    data = json.loads(text)
    if "schema_version" in data:
        return _load_v2(data)
    return _load_v1(data)


def _load_v1(data: dict) -> RunManifest:
    """Convert a v1 manifest (no schema_version) to a RunManifest."""
    scenarios = []
    for scenario_data in data.get("scenarios", []):
        items = []
        scenario_name = scenario_data["name"]
        for evidence in scenario_data.get("evidence", []):
            v1_type = evidence.get("type", "screenshot")
            kind, mime = _V1_TYPE_MAP.get(v1_type, (v1_type, "application/octet-stream"))
            items.append(
                EvidenceItem(
                    kind=kind,
                    mime=mime,
                    path=Path(evidence["path"]),
                    scenario=scenario_name,
                    step=evidence["step"],
                    captured_at=datetime.fromisoformat(evidence["captured_at"]),
                    metadata={},
                )
            )
        scenarios.append(ScenarioBundle(scenario=scenario_name, items=items))

    return RunManifest(
        run_id=data["run_id"],
        schema_version=CURRENT_SCHEMA_VERSION,
        project="",
        timestamp=data.get("timestamp", ""),
        scenarios=scenarios,
    )


def _load_v2(data: dict) -> RunManifest:
    """Load a v2 manifest into a RunManifest."""
    scenarios = []
    for scenario_data in data.get("scenarios", []):
        items = []
        for item_data in scenario_data.get("items", []):
            items.append(
                EvidenceItem(
                    kind=item_data["kind"],
                    mime=item_data["mime"],
                    path=Path(item_data["path"]),
                    scenario=item_data["scenario"],
                    step=item_data["step"],
                    captured_at=datetime.fromisoformat(item_data["captured_at"]),
                    metadata=item_data.get("metadata", {}),
                )
            )
        scenarios.append(
            ScenarioBundle(
                scenario=scenario_data["scenario"],
                items=items,
            )
        )

    return RunManifest(
        run_id=data["run_id"],
        schema_version=data.get("schema_version", CURRENT_SCHEMA_VERSION),
        project=data.get("project", ""),
        timestamp=data.get("timestamp", ""),
        scenarios=scenarios,
    )
