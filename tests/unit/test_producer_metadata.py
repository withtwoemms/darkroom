"""Unit tests for producer metadata population and the video producer."""

import json
from pathlib import Path
from unittest.mock import MagicMock

from darkroom.manifest import dumps_manifest, loads_manifest
from darkroom.model import RunManifest, ScenarioBundle
from darkroom.producer import CaptureContext
from darkroom.producers.screenshot import ElementScreenshotProducer, ScreenshotProducer
from darkroom.producers.video import VideoProducer


def _ctx(tmp_path, step="step", step_count=1):
    return CaptureContext(
        scenario="scenario_a",
        step=step,
        run_dir=tmp_path,
        step_count=step_count,
    )


class TestScreenshotMetadata:
    def test_records_full_page_and_viewport(self, tmp_path):
        page = MagicMock()
        page.viewport_size = {"width": 1024, "height": 640}
        item = ScreenshotProducer().capture(
            _ctx(tmp_path), page=page, full_page=True
        )
        assert item.metadata == {"full_page": True, "viewport": "1024x640"}

    def test_viewport_omitted_when_unavailable(self, tmp_path):
        page = MagicMock()
        page.viewport_size = None
        item = ScreenshotProducer().capture(_ctx(tmp_path), page=page)
        assert item.metadata == {"full_page": False}

    def test_viewport_omitted_when_not_a_dict(self, tmp_path):
        page = MagicMock()  # viewport_size is a MagicMock attribute
        item = ScreenshotProducer().capture(_ctx(tmp_path), page=page)
        assert item.metadata == {"full_page": False}

    def test_element_selector_recorded(self, tmp_path):
        page = MagicMock()
        page.query_selector.return_value = MagicMock()
        item = ElementScreenshotProducer().capture(
            _ctx(tmp_path), page=page, selector="#approve"
        )
        assert item.metadata == {"selector": "#approve"}

    def test_metadata_survives_manifest_round_trip(self, tmp_path):
        page = MagicMock()
        page.viewport_size = {"width": 800, "height": 600}
        item = ScreenshotProducer().capture(_ctx(tmp_path), page=page)
        manifest = RunManifest(
            run_id="t",
            scenarios=[ScenarioBundle(scenario="scenario_a", items=[item])],
        )
        loaded = loads_manifest(dumps_manifest(manifest))
        assert loaded.scenarios[0].items[0].metadata == {
            "full_page": False,
            "viewport": "800x600",
        }


class TestVideoProducer:
    def _source(self, tmp_path, name="raw.webm") -> Path:
        source = tmp_path / "recordings" / name
        source.parent.mkdir()
        source.write_bytes(b"webm-bytes")
        return source

    def test_moves_recording_into_run(self, tmp_path):
        source = self._source(tmp_path)
        item = VideoProducer().capture(
            _ctx(tmp_path, step="walkthrough"), source=source
        )
        assert item.kind == "video"
        assert item.mime == "video/webm"
        assert item.path == Path("scenario_a/01-walkthrough.webm")
        assert (tmp_path / item.path).read_bytes() == b"webm-bytes"
        assert not source.exists()
        assert item.metadata == {"size_bytes": 10}

    def test_keep_source_copies(self, tmp_path):
        source = self._source(tmp_path)
        item = VideoProducer().capture(
            _ctx(tmp_path, step="walkthrough"), source=source, keep_source=True
        )
        assert source.exists()
        assert (tmp_path / item.path).exists()

    def test_preserves_source_extension(self, tmp_path):
        source = self._source(tmp_path, name="raw.mp4")
        item = VideoProducer().capture(_ctx(tmp_path, step="clip"), source=source)
        assert item.path == Path("scenario_a/01-clip.mp4")

    def test_serializes_cleanly(self, tmp_path):
        source = self._source(tmp_path)
        item = VideoProducer().capture(_ctx(tmp_path, step="clip"), source=source)
        manifest = RunManifest(
            run_id="t",
            scenarios=[ScenarioBundle(scenario="scenario_a", items=[item])],
        )
        data = json.loads(dumps_manifest(manifest))
        assert data["scenarios"][0]["items"][0]["metadata"] == {"size_bytes": 10}
