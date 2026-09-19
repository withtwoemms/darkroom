"""Unit tests for judge renderers."""

import json
from datetime import datetime
from pathlib import Path

from darkroom.model import EvidenceItem, ScenarioBundle
from darkroom.render import (
    JudgeRenderer,
    RendererRegistry,
    default_registry,
    render_scenario,
)


def _item(kind, step, rel_path, mime="application/json", metadata=None) -> EvidenceItem:
    return EvidenceItem(
        kind=kind,
        mime=mime,
        path=Path(rel_path),
        scenario="s",
        step=step,
        captured_at=datetime(2026, 1, 1),
        metadata=metadata or {},
    )


class TestImageRenderer:
    def test_attaches_image(self, tmp_path):
        (tmp_path / "01-shot.png").write_bytes(b"png")
        item = _item(
            "screenshot", "shot", "01-shot.png", "image/png",
            {"full_page": True, "viewport": "1024x640"},
        )
        rendered = default_registry().render(item, tmp_path)
        assert rendered.attachments == (tmp_path / "01-shot.png",)
        assert "full_page=True" in rendered.text
        assert "viewport=1024x640" in rendered.text

    def test_missing_file_noted_not_raised(self, tmp_path):
        item = _item("screenshot", "shot", "gone.png", "image/png")
        rendered = default_registry().render(item, tmp_path)
        assert "missing" in rendered.text
        assert rendered.attachments == ()


class TestTranscriptRenderer:
    def test_command_transcript(self, tmp_path):
        (tmp_path / "01-build.json").write_text(json.dumps({
            "argv": ["make", "build"], "exit_code": 2, "duration_ms": 810,
            "timed_out": False, "stdout": "compiling...",
            "stderr": "error: missing header",
            "stdout_truncated": False, "stderr_truncated": True,
        }))
        item = _item("command_transcript", "build", "01-build.json")
        text = default_registry().render(item, tmp_path).text
        assert "$ make build" in text
        assert "exit_code=2" in text
        assert "error: missing header" in text
        assert "[truncated at capture]" in text

    def test_http_transcript(self, tmp_path):
        (tmp_path / "01-api.json").write_text(json.dumps({
            "request": {"method": "POST", "url": "http://x/create", "body": "{}"},
            "response": {"status": 201, "body": '{"id": 1}', "body_truncated": False},
            "duration_ms": 45, "error": None,
        }))
        item = _item("http_transcript", "api", "01-api.json")
        text = default_registry().render(item, tmp_path).text
        assert "POST http://x/create -> 201 (45ms)" in text
        assert '{"id": 1}' in text

    def test_unreadable_transcript_noted(self, tmp_path):
        (tmp_path / "01-bad.json").write_text("{broken")
        item = _item("command_transcript", "bad", "01-bad.json")
        assert "unreadable" in default_registry().render(item, tmp_path).text


class TestStructuredRenderer:
    def test_pretty_prints(self, tmp_path):
        (tmp_path / "01-state.json").write_text('{"data": {"items": 2}}')
        item = _item("log", "state", "01-state.json")
        text = default_registry().render(item, tmp_path).text
        assert '"items": 2' in text


class TestFileRenderer:
    def test_diff_inlined(self, tmp_path):
        (tmp_path / "01-change.diff").write_text("--- a\n+++ b\n-x\n+y\n")
        item = _item("diff", "change", "01-change.diff", "text/x-diff")
        text = default_registry().render(item, tmp_path).text
        assert "+y" in text

    def test_empty_diff_stated(self, tmp_path):
        (tmp_path / "01-none.diff").write_text("")
        item = _item("diff", "none", "01-none.diff", "text/x-diff")
        assert "no differences" in default_registry().render(item, tmp_path).text

    def test_small_text_snapshot_inlined(self, tmp_path):
        (tmp_path / "01-cfg.json").write_text('{"a": 1}')
        item = _item("file_snapshot", "cfg", "01-cfg.json")
        assert '"a": 1' in default_registry().render(item, tmp_path).text

    def test_binary_snapshot_not_inlined(self, tmp_path):
        (tmp_path / "01-blob.bin").write_bytes(b"\x00\x01")
        item = _item(
            "file_snapshot", "blob", "01-blob.bin", "application/octet-stream"
        )
        assert "not inlined" in default_registry().render(item, tmp_path).text


class TestVideoRenderer:
    def test_video_described_and_attached(self, tmp_path):
        (tmp_path / "01-walk.webm").write_bytes(b"webm")
        item = _item("video", "walk", "01-walk.webm", "video/webm")
        rendered = default_registry().render(item, tmp_path)
        assert "not viewable inline" in rendered.text
        assert rendered.attachments == (tmp_path / "01-walk.webm",)


class TestRegistry:
    def test_unknown_kind_falls_back(self, tmp_path):
        item = _item("thermal_image", "scan", "01-scan.tiff", "image/tiff")
        rendered = RendererRegistry().render(item, tmp_path)
        assert "no renderer for this kind" in rendered.text

    def test_custom_renderer_registration(self, tmp_path):
        class ThermalRenderer:
            kinds = ("thermal_image",)

            def render(self, item, base_dir):
                from darkroom.render import RenderedEvidence
                return RenderedEvidence(item, "thermal ok")

        assert isinstance(ThermalRenderer(), JudgeRenderer)
        registry = default_registry()
        registry.register(ThermalRenderer())
        item = _item("thermal_image", "scan", "01-scan.tiff")
        assert registry.render(item, tmp_path).text == "thermal ok"

    def test_render_scenario_orders_items(self, tmp_path):
        (tmp_path / "01-a.json").write_text('{"x": 1}')
        (tmp_path / "02-b.png").write_bytes(b"png")
        bundle = ScenarioBundle(
            scenario="s",
            items=[
                _item("log", "a", "01-a.json"),
                _item("screenshot", "b", "02-b.png", "image/png"),
            ],
        )
        rendered = render_scenario(bundle, tmp_path)
        assert [r.item.step for r in rendered] == ["a", "b"]

    def test_clipping(self, tmp_path):
        (tmp_path / "01-big.json").write_text(json.dumps({"data": "x" * 10000}))
        item = _item("log", "big", "01-big.json")
        text = default_registry().render(item, tmp_path).text
        assert "... [truncated]" in text
        assert len(text) < 6000
