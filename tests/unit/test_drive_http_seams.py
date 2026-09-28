"""Drive-scripts 1.5: unfollowed redirects, Location witnesses, and http
steps that borrow the browser's session."""

import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

import darkroom.run as run_module
from darkroom.capture import EvidenceCapture
from darkroom.drive import Context, DriveError, _evaluate_expect, _run_http_step
from darkroom.producer import CaptureContext
from darkroom.producers.http import HTTPTranscriptProducer
from darkroom.run import EvidenceRun


class _Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def _respond(self, status, body: bytes, headers=None):
        self.send_response(status)
        for name, value in (headers or {}).items():
            self.send_header(name, value)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path == "/locked":
            self._respond(303, b"", {"Location": "/signin?next=/locked"})
        elif self.path.startswith("/signin"):
            self._respond(200, b"sign in here")
        elif self.path == "/whoami":
            cookie = self.headers.get("Cookie", "")
            self._respond(200, json.dumps({"cookie": cookie}).encode())
        else:
            self._respond(404, b"")


@pytest.fixture(scope="module")
def server_url():
    server = HTTPServer(("127.0.0.1", 0), _Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{server.server_port}"
    server.shutdown()


def _transcript(tmp_path, url, **kwargs):
    ctx = CaptureContext(scenario="s", step="step", run_dir=tmp_path, step_count=1)
    item = HTTPTranscriptProducer().capture(ctx, url=url, **kwargs)
    return json.loads((tmp_path / item.path).read_text())


class TestFollowRedirects:
    def test_followed_by_default(self, tmp_path, server_url):
        transcript = _transcript(tmp_path, f"{server_url}/locked")
        assert transcript["response"]["status"] == 200
        assert transcript["request"]["follow_redirects"] is True

    def test_unfollowed_records_the_3xx_and_location(self, tmp_path, server_url):
        transcript = _transcript(
            tmp_path, f"{server_url}/locked", follow_redirects=False
        )
        assert transcript["response"]["status"] == 303
        assert transcript["response"]["headers"]["Location"] == "/signin?next=/locked"
        assert transcript["request"]["follow_redirects"] is False


class TestLocationWitness:
    def test_location_is_found_and_matched(self):
        transcript = {"response": {"status": 303, "headers": {"location": "/signin"}}}
        detail, found = _evaluate_expect(
            {"status": 303, "location_contains": "/signin"}, transcript
        )
        assert detail is None
        assert found == {"status": 303, "location": "/signin"}

    def test_missing_location_fails_with_none_recorded(self):
        transcript = {"response": {"status": 200, "headers": {}}}
        detail, found = _evaluate_expect({"location_contains": "/signin"}, transcript)
        assert "got None" in detail
        assert found == {"location": None}


class _FakeContext:
    def __init__(self, cookies):
        self._cookies = cookies
        self.asked = []

    def cookies(self, urls):
        self.asked.append(urls)
        return self._cookies


class _FakeBrowser:
    def __init__(self, cookies):
        self.context = _FakeContext(cookies)


@pytest.fixture
def capture(monkeypatch, tmp_path):
    monkeypatch.setenv("EVIDENCE_MODE", "1")
    monkeypatch.setenv("EVIDENCE_DIR", str(tmp_path))
    run_module._current_run = EvidenceRun(run_id="seams")
    try:
        yield EvidenceCapture("seams")
    finally:
        run_module._current_run = None


class TestBrowserSession:
    def test_sends_the_browser_cookies(self, capture, server_url):
        browser = _FakeBrowser(
            [{"name": "session", "value": "abc"}, {"name": "theme", "value": "ember"}]
        )
        step = {"name": "whoami", "url": f"{server_url}/whoami", "session": "browser"}
        transcript, failure = _run_http_step(step, Context(), capture, browser)
        assert failure is None
        assert json.loads(transcript["response"]["body"])["cookie"] == (
            "session=abc; theme=ember"
        )
        assert browser.context.asked == [[f"{server_url}/whoami"]]

    def test_explicit_cookie_header_wins(self, capture, server_url):
        browser = _FakeBrowser([{"name": "session", "value": "abc"}])
        step = {
            "name": "whoami",
            "url": f"{server_url}/whoami",
            "session": "browser",
            "headers": {"Cookie": "session=mine"},
        }
        transcript, _ = _run_http_step(step, Context(), capture, browser)
        assert json.loads(transcript["response"]["body"])["cookie"] == "session=mine"

    def test_no_browser_is_an_authoring_error(self, capture, server_url):
        step = {"name": "whoami", "url": f"{server_url}/whoami", "session": "browser"}
        with pytest.raises(DriveError, match="no browser"):
            _run_http_step(step, Context(), capture, None)

    def test_unknown_session_is_refused(self, capture, server_url):
        step = {"name": "whoami", "url": f"{server_url}/whoami", "session": "other"}
        with pytest.raises(DriveError, match='must be "browser"'):
            _run_http_step(step, Context(), capture, _FakeBrowser([]))

    def test_unfollowed_redirect_through_the_step(self, capture, server_url):
        step = {
            "name": "locked",
            "url": f"{server_url}/locked",
            "follow_redirects": False,
            "expect": {"status": 303, "location_contains": "/signin"},
        }
        _, failure = _run_http_step(step, Context(), capture, None)
        assert failure is None
