"""Unit tests for the producer protocol and CaptureContext."""

import json
from pathlib import Path

from darkroom.producer import CaptureContext, EvidenceProducer
from darkroom.producers.log import LogProducer


class TestCaptureContext:
    def test_make_path(self):
        ctx = CaptureContext(
            scenario="login_flow",
            step="login_page",
            run_dir=Path("/tmp/runs/test"),
            step_count=1,
        )
        path = ctx.make_path("login_page", "png")
        assert path == Path("login_flow/01-login_page.png")

    def test_make_path_zero_padded(self):
        ctx = CaptureContext(
            scenario="s", step="step",
            run_dir=Path("/tmp"), step_count=3,
        )
        path = ctx.make_path("step", "json")
        assert path == Path("s/03-step.json")

    def test_make_path_default_step_count(self):
        ctx = CaptureContext(
            scenario="s", step="step", run_dir=Path("/tmp"),
        )
        path = ctx.make_path("step", "png")
        assert path == Path("s/00-step.png")


class TestEvidenceProducerProtocol:
    def test_log_producer_satisfies_protocol(self):
        producer = LogProducer()
        assert isinstance(producer, EvidenceProducer)

    def test_log_producer_attributes(self):
        producer = LogProducer()
        assert producer.kind == "log"
        assert producer.mime == "application/json"


class TestLogProducerCapture:
    def test_writes_json_file(self, tmp_path):
        producer = LogProducer()
        ctx = CaptureContext(
            scenario="my_scenario",
            step="api_response",
            run_dir=tmp_path,
            step_count=1,
        )
        item = producer.capture(ctx, data={"status": 200, "body": "ok"})

        abs_path = tmp_path / item.path
        assert abs_path.exists()

        with open(abs_path) as f:
            content = json.load(f)
        assert content["scenario"] == "my_scenario"
        assert content["step"] == "api_response"
        assert content["data"] == {"status": 200, "body": "ok"}
        assert "captured_at" in content

    def test_returns_correct_evidence_item(self, tmp_path):
        producer = LogProducer()
        ctx = CaptureContext(
            scenario="s", step="step",
            run_dir=tmp_path, step_count=2,
        )
        item = producer.capture(ctx, data={"key": "value"})

        assert item.kind == "log"
        assert item.mime == "application/json"
        assert item.scenario == "s"
        assert item.step == "step"
        assert item.path == Path("s/02-step.json")
