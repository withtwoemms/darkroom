"""Unit tests for the core data model."""

from datetime import datetime
from pathlib import Path

import pytest

from darkroom.model import EvidenceItem, RunManifest, ScenarioBundle


class TestEvidenceItem:
    def test_creation(self):
        item = EvidenceItem(
            kind="screenshot",
            mime="image/png",
            path=Path("scenario_a/01-login.png"),
            scenario="scenario_a",
            step="login",
            captured_at=datetime(2026, 3, 17, 13, 43, 48),
        )
        assert item.kind == "screenshot"
        assert item.mime == "image/png"
        assert item.path == Path("scenario_a/01-login.png")
        assert item.scenario == "scenario_a"
        assert item.step == "login"
        assert item.metadata == {}

    def test_frozen(self):
        item = EvidenceItem(
            kind="screenshot",
            mime="image/png",
            path=Path("a/b.png"),
            scenario="a",
            step="b",
            captured_at=datetime.now(),
        )
        with pytest.raises(AttributeError):
            item.kind = "log"

    def test_metadata_default(self):
        item = EvidenceItem(
            kind="log",
            mime="application/json",
            path=Path("a/01-step.json"),
            scenario="a",
            step="step",
            captured_at=datetime.now(),
        )
        assert item.metadata == {}

    def test_metadata_provided(self):
        item = EvidenceItem(
            kind="screenshot",
            mime="image/png",
            path=Path("a/01-step.png"),
            scenario="a",
            step="step",
            captured_at=datetime.now(),
            metadata={"full_page": True},
        )
        assert item.metadata == {"full_page": True}

    def test_equality(self):
        ts = datetime(2026, 1, 1, 0, 0, 0)
        a = EvidenceItem(
            kind="log", mime="application/json",
            path=Path("x/01-y.json"), scenario="x", step="y",
            captured_at=ts,
        )
        b = EvidenceItem(
            kind="log", mime="application/json",
            path=Path("x/01-y.json"), scenario="x", step="y",
            captured_at=ts,
        )
        assert a == b


class TestScenarioBundle:
    def test_creation(self):
        bundle = ScenarioBundle(scenario="login_flow")
        assert bundle.scenario == "login_flow"
        assert bundle.items == []

    def test_add(self):
        bundle = ScenarioBundle(scenario="login_flow")
        item = EvidenceItem(
            kind="screenshot", mime="image/png",
            path=Path("login_flow/01-page.png"),
            scenario="login_flow", step="page",
            captured_at=datetime.now(),
        )
        bundle.add(item)
        assert len(bundle.items) == 1
        assert bundle.items[0] is item


class TestRunManifest:
    def test_defaults(self):
        manifest = RunManifest(run_id="test-run")
        assert manifest.schema_version == "2.0"
        assert manifest.project == ""
        assert manifest.timestamp == ""
        assert manifest.scenarios == []

    def test_get_or_create_bundle_creates(self):
        manifest = RunManifest(run_id="test-run")
        bundle = manifest.get_or_create_bundle("scenario_a")
        assert bundle.scenario == "scenario_a"
        assert len(manifest.scenarios) == 1

    def test_get_or_create_bundle_returns_existing(self):
        manifest = RunManifest(run_id="test-run")
        bundle1 = manifest.get_or_create_bundle("scenario_a")
        bundle2 = manifest.get_or_create_bundle("scenario_a")
        assert bundle1 is bundle2
        assert len(manifest.scenarios) == 1

    def test_get_or_create_bundle_multiple_scenarios(self):
        manifest = RunManifest(run_id="test-run")
        manifest.get_or_create_bundle("a")
        manifest.get_or_create_bundle("b")
        assert len(manifest.scenarios) == 2
        assert manifest.scenarios[0].scenario == "a"
        assert manifest.scenarios[1].scenario == "b"
