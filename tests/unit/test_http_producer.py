"""Unit tests for the HTTP transcript producer, against a local stdlib server."""

import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from darkroom.producer import CaptureContext
from darkroom.producers.http import HTTPTranscriptProducer


class _Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def _respond(self, status, body: bytes, headers=None):
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        for name, value in (headers or {}).items():
            self.send_header(name, value)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path == "/ok":
            self._respond(200, b'{"proofs": 3}', {"Set-Cookie": "session=s3cret"})
        elif self.path == "/missing":
            self._respond(404, b'{"error": "not found"}')
        else:
            self._respond(500, b"{}")

    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        received = self.rfile.read(length)
        self._respond(201, json.dumps({"echo": received.decode()}).encode())


@pytest.fixture(scope="module")
def server_url():
    server = HTTPServer(("127.0.0.1", 0), _Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{server.server_port}"
    server.shutdown()


def _ctx(tmp_path, step="request"):
    return CaptureContext(
        scenario="api_flow", step=step, run_dir=tmp_path, step_count=1
    )


class TestHTTPTranscriptProducer:
    def test_get_success(self, tmp_path, server_url):
        item = HTTPTranscriptProducer().capture(_ctx(tmp_path), url=f"{server_url}/ok")
        assert item.kind == "http_transcript"
        assert item.metadata["status"] == 200
        assert item.metadata["method"] == "GET"
        transcript = json.loads((tmp_path / item.path).read_text())
        assert json.loads(transcript["response"]["body"]) == {"proofs": 3}
        assert transcript["error"] is None

    def test_non_2xx_still_captured(self, tmp_path, server_url):
        item = HTTPTranscriptProducer().capture(
            _ctx(tmp_path), url=f"{server_url}/missing"
        )
        assert item.metadata["status"] == 404
        transcript = json.loads((tmp_path / item.path).read_text())
        assert "not found" in transcript["response"]["body"]

    def test_post_body_recorded(self, tmp_path, server_url):
        item = HTTPTranscriptProducer().capture(
            _ctx(tmp_path),
            url=f"{server_url}/create",
            method="POST",
            body='{"proof": "A-114"}',
            headers={"Content-Type": "application/json"},
        )
        assert item.metadata["status"] == 201
        transcript = json.loads((tmp_path / item.path).read_text())
        assert transcript["request"]["body"] == '{"proof": "A-114"}'
        assert "A-114" in transcript["response"]["body"]

    def test_sensitive_headers_redacted_both_ways(self, tmp_path, server_url):
        item = HTTPTranscriptProducer().capture(
            _ctx(tmp_path),
            url=f"{server_url}/ok",
            headers={"Authorization": "Bearer sk-live-secret", "X-Trace": "t1"},
        )
        transcript = json.loads((tmp_path / item.path).read_text())
        assert transcript["request"]["headers"]["Authorization"] == "[REDACTED]"
        assert transcript["request"]["headers"]["X-Trace"] == "t1"
        assert transcript["response"]["headers"]["Set-Cookie"] == "[REDACTED]"
        assert "s3cret" not in (tmp_path / item.path).read_text()

    def test_connection_error_captured(self, tmp_path):
        item = HTTPTranscriptProducer().capture(
            _ctx(tmp_path), url="http://127.0.0.1:9", timeout=2
        )
        assert item.metadata["status"] is None
        assert "error" in item.metadata
        transcript = json.loads((tmp_path / item.path).read_text())
        assert transcript["response"]["status"] is None
        assert transcript["error"]

    def test_body_truncation(self, tmp_path, server_url):
        item = HTTPTranscriptProducer().capture(
            _ctx(tmp_path), url=f"{server_url}/ok", max_body_bytes=5
        )
        transcript = json.loads((tmp_path / item.path).read_text())
        assert transcript["response"]["body"] == '{"pro'
        assert transcript["response"]["body_truncated"] is True
        assert item.metadata["status"] == 200
