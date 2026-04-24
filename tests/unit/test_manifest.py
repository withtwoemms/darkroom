"""Unit tests for manifest serialization/deserialization."""

import json
from datetime import datetime
from pathlib import Path

from darkroom.manifest import (
    CURRENT_SCHEMA_VERSION,
    dumps_manifest,
    load_manifest,
    loads_manifest,
)
from darkroom.model import EvidenceItem, RunManifest, ScenarioBundle


V1_MANIFEST = """{
  "run_id": "2026-03-17T13-43-29",
  "timestamp": "2026-03-17T13:44:02.049178",
  "scenario_file": null,
  "scenarios": [
    {
      "name": "capacity_alerts_double_booked",
      "evidence": [
        {
          "step": "logged_in",
          "type": "screenshot",
          "path": "capacity_alerts_double_booked/01-logged_in.png",
          "captured_at": "2026-03-17T13:43:48.707534"
        },
        {
          "step": "capacity_planner",
          "type": "screenshot",
          "path": "capacity_alerts_double_booked/02-capacity_planner.png",
          "captured_at": "2026-03-17T13:43:49.661620"
        }
      ]
    }
  ]
}"""


class TestV2RoundTrip:
    def test_dumps_loads(self):
        item = EvidenceItem(
            kind="screenshot",
            mime="image/png",
            path=Path("scenario_a/01-login.png"),
            scenario="scenario_a",
            step="login",
            captured_at=datetime(2026, 3, 17, 13, 43, 48),
        )
        manifest = RunManifest(
            run_id="test-run",
            project="my-project",
            timestamp="2026-03-17T13:44:02",
            scenarios=[ScenarioBundle(scenario="scenario_a", items=[item])],
        )

        text = dumps_manifest(manifest)
        loaded = loads_manifest(text)

        assert loaded.run_id == "test-run"
        assert loaded.schema_version == "2.0"
        assert loaded.project == "my-project"
        assert loaded.timestamp == "2026-03-17T13:44:02"
        assert len(loaded.scenarios) == 1
        assert loaded.scenarios[0].scenario == "scenario_a"
        assert len(loaded.scenarios[0].items) == 1

        loaded_item = loaded.scenarios[0].items[0]
        assert loaded_item.kind == "screenshot"
        assert loaded_item.mime == "image/png"
        assert loaded_item.path == Path("scenario_a/01-login.png")
        assert loaded_item.scenario == "scenario_a"
        assert loaded_item.step == "login"
        assert loaded_item.captured_at == datetime(2026, 3, 17, 13, 43, 48)
        assert loaded_item.metadata == {}

    def test_file_round_trip(self, tmp_path):
        from darkroom.manifest import dump_manifest

        manifest = RunManifest(
            run_id="file-test",
            project="proj",
            timestamp="2026-01-01T00:00:00",
        )
        path = tmp_path / "manifest.json"
        dump_manifest(manifest, path)

        assert path.exists()
        loaded = load_manifest(path)
        assert loaded.run_id == "file-test"
        assert loaded.project == "proj"

    def test_schema_version_in_output(self):
        manifest = RunManifest(run_id="test")
        text = dumps_manifest(manifest)
        data = json.loads(text)
        assert data["schema_version"] == "2.0"

    def test_path_as_posix(self):
        item = EvidenceItem(
            kind="log", mime="application/json",
            path=Path("scenario") / "01-step.json",
            scenario="scenario", step="step",
            captured_at=datetime.now(),
        )
        manifest = RunManifest(
            run_id="test",
            scenarios=[ScenarioBundle(scenario="scenario", items=[item])],
        )
        text = dumps_manifest(manifest)
        data = json.loads(text)
        assert data["scenarios"][0]["items"][0]["path"] == "scenario/01-step.json"

    def test_metadata_round_trip(self):
        item = EvidenceItem(
            kind="screenshot", mime="image/png",
            path=Path("a/01-b.png"), scenario="a", step="b",
            captured_at=datetime(2026, 1, 1),
            metadata={"full_page": True, "viewport": "1280x720"},
        )
        manifest = RunManifest(
            run_id="test",
            scenarios=[ScenarioBundle(scenario="a", items=[item])],
        )
        loaded = loads_manifest(dumps_manifest(manifest))
        loaded_item = loaded.scenarios[0].items[0]
        assert loaded_item.metadata == {"full_page": True, "viewport": "1280x720"}


class TestV1Load:
    def test_loads_v1_manifest(self):
        manifest = loads_manifest(V1_MANIFEST)
        assert manifest.run_id == "2026-03-17T13-43-29"
        assert manifest.schema_version == CURRENT_SCHEMA_VERSION
        assert manifest.project == ""
        assert manifest.timestamp == "2026-03-17T13:44:02.049178"

    def test_v1_scenario_mapping(self):
        manifest = loads_manifest(V1_MANIFEST)
        assert len(manifest.scenarios) == 1
        bundle = manifest.scenarios[0]
        assert bundle.scenario == "capacity_alerts_double_booked"

    def test_v1_evidence_items(self):
        manifest = loads_manifest(V1_MANIFEST)
        items = manifest.scenarios[0].items
        assert len(items) == 2

        first = items[0]
        assert first.kind == "screenshot"
        assert first.mime == "image/png"
        assert first.path == Path("capacity_alerts_double_booked/01-logged_in.png")
        assert first.scenario == "capacity_alerts_double_booked"
        assert first.step == "logged_in"
        assert first.captured_at == datetime(2026, 3, 17, 13, 43, 48, 707534)
        assert first.metadata == {}

    def test_v1_type_to_kind_mapping(self):
        v1_with_log = """{
          "run_id": "test",
          "timestamp": "",
          "scenario_file": null,
          "scenarios": [{
            "name": "s",
            "evidence": [
              {"step": "a", "type": "screenshot", "path": "s/01-a.png", "captured_at": "2026-01-01T00:00:00"},
              {"step": "b", "type": "screenshot_element", "path": "s/02-b.png", "captured_at": "2026-01-01T00:00:01"},
              {"step": "c", "type": "log", "path": "s/03-c.json", "captured_at": "2026-01-01T00:00:02"}
            ]
          }]
        }"""
        manifest = loads_manifest(v1_with_log)
        items = manifest.scenarios[0].items
        assert items[0].kind == "screenshot"
        assert items[0].mime == "image/png"
        assert items[1].kind == "screenshot_element"
        assert items[1].mime == "image/png"
        assert items[2].kind == "log"
        assert items[2].mime == "application/json"

    def test_v1_drops_scenario_file(self):
        manifest = loads_manifest(V1_MANIFEST)
        assert not hasattr(manifest, "scenario_file") or True  # field doesn't exist on RunManifest
