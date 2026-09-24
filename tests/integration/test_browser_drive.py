"""Browser drive steps against a real chromium (skipped without one).

The tenant is a stdlib HTTP server with a form page, so the tests
exercise the true path: goto with expectations over the live page,
fill + click driving a real submission, screenshot evidence through
the existing producer, and a failing selector expectation stopping
the scenario while keeping its evidence.
"""

import shutil
import textwrap
from pathlib import Path

import pytest

pytest.importorskip("playwright")

from darkroom.adapter import loads_adapter  # noqa: E402
from darkroom.cli import main  # noqa: E402
from darkroom.drive import drive  # noqa: E402
from darkroom.manifest import load_manifest  # noqa: E402

EXAMPLE = Path(__file__).parent.parent.parent / "examples" / "relay-service"


def _chromium_available() -> bool:
    from playwright.sync_api import sync_playwright

    try:
        with sync_playwright() as p:
            p.chromium.launch(headless=True).close()
        return True
    except Exception:
        return False


pytestmark = pytest.mark.skipif(
    not _chromium_available(), reason="no chromium for playwright"
)

APP_PY = """
import html, sys
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import parse_qs

NOTES = []

PAGE = '''<!doctype html>
<title>Notebook</title>
<h1>Notebook</h1>
<form id="note-form" method="post" action="/">
  <input type="text" name="text" id="note-text">
  <button type="submit" id="save">Save</button>
</form>
<ul id="notes">{items}</ul>
'''

class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a): pass
    def _page(self):
        items = "".join(f"<li>{html.escape(n)}</li>" for n in NOTES)
        body = PAGE.format(items=items).encode()
        self.send_response(200)
        self.send_header("Content-Type", "text/html")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)
    def do_GET(self):
        self._page()
    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        data = parse_qs(self.rfile.read(length).decode())
        NOTES.extend(data.get("text", []))
        self._page()

HTTPServer(("127.0.0.1", int(sys.argv[1])), Handler).serve_forever()
"""


@pytest.fixture()
def tenant(tmp_path):
    root = tmp_path / "tenant"
    root.mkdir()
    (root / "app.py").write_text(textwrap.dedent(APP_PY))
    import sys as _sys

    adapter = loads_adapter(
        textwrap.dedent(f"""
        [project]
        name = "notebook"

        [commands]
        serve = "{_sys.executable} app.py {{port}}"

        [evidence]
        dir = "evidence"
        """),
        root=root,
    )
    drives = tmp_path / "drives"
    drives.mkdir()
    return adapter, drives


class TestBrowserDrive:
    def test_goto_fill_click_screenshot(self, tenant, monkeypatch):
        adapter, drives = tenant
        monkeypatch.delenv("EVIDENCE_MODE", raising=False)
        monkeypatch.delenv("EVIDENCE_DIR", raising=False)
        (drives / "note_saved.drive.toml").write_text(textwrap.dedent("""
            scenario = "note_saved"

            [[step]]
            name = "open_notebook"
            kind = "goto"
            url = "{base_url}/"
            expect = { status = 200, title_contains = "Notebook", selector_visible = "#note-form" }

            [[step]]
            name = "write_note"
            kind = "fill"
            fields = { "#note-text" = "buy film" }

            [[step]]
            name = "save_note"
            kind = "click"
            selector = "#save"
            expect = { body_contains = "buy film", selector_visible = "#notes li" }

            [[step]]
            name = "saved_state"
            kind = "screenshot"
            full_page = true
        """))
        report = drive(adapter, drives, containers_mode="off")
        failures = [
            (s.name, s.detail) for r in report.results for s in r.steps if not s.ok
        ]
        assert report.ok, failures

        manifest_path = next(
            adapter.resolve(adapter.evidence_dir).glob("runs/*/manifest.json")
        )
        manifest = load_manifest(manifest_path)
        items = manifest.scenarios[0].items
        kinds = [i.kind for i in items]
        assert kinds == ["log", "log", "log", "screenshot"]
        shot = items[-1]
        assert (manifest_path.parent / shot.path).stat().st_size > 0

    def test_record_captures_screencast(self, tenant, monkeypatch):
        adapter, drives = tenant
        monkeypatch.delenv("EVIDENCE_MODE", raising=False)
        monkeypatch.delenv("EVIDENCE_DIR", raising=False)
        (drives / "recorded.drive.toml").write_text(textwrap.dedent("""
            scenario = "recorded"
            record = true

            [[step]]
            name = "open"
            kind = "goto"
            url = "{base_url}/"
            expect = { status = 200 }

            [[step]]
            name = "type_and_save"
            kind = "fill"
            fields = { "#note-text" = "on camera" }

            [[step]]
            name = "save"
            kind = "click"
            selector = "#save"
            expect = { body_contains = "on camera" }
        """))
        report = drive(adapter, drives, containers_mode="off")
        assert report.ok, [
            (s.name, s.detail) for r in report.results for s in r.steps if not s.ok
        ]
        manifest_path = next(
            adapter.resolve(adapter.evidence_dir).glob("runs/*/manifest.json")
        )
        manifest = load_manifest(manifest_path)
        videos = [
            i for i in manifest.scenarios[0].items if i.kind == "video"
        ]
        assert len(videos) == 1
        assert videos[0].step == "screencast"
        assert (manifest_path.parent / videos[0].path).stat().st_size > 0

    def test_shipped_ui_example_runs_green(self, tmp_path, capsys, monkeypatch):
        project = tmp_path / "relay-service"
        shutil.copytree(EXAMPLE, project)
        monkeypatch.chdir(project)
        monkeypatch.delenv("EVIDENCE_MODE", raising=False)
        monkeypatch.delenv("EVIDENCE_DIR", raising=False)

        code = main(
            ["drive", "--drives", "drives-ui", "--scenario", "notes_page"]
        )
        out = capsys.readouterr().out
        assert code == 0, out
        assert "notes_page:" in out

        manifest = next(project.glob("evidence/runs/*/manifest.json"))
        assert main(
            ["verify", str(manifest),
             "--contract", str(project / "evidence-contract-ui.toml")]
        ) == 0
        items = load_manifest(manifest).scenarios[0].items
        assert [i.step for i in items if i.kind == "screenshot"] == [
            "empty_state", "saved_state",
        ]

    def test_viewport_and_webauthn_session_options(self, tmp_path, monkeypatch):
        monkeypatch.delenv("EVIDENCE_MODE", raising=False)
        monkeypatch.delenv("EVIDENCE_DIR", raising=False)
        root = tmp_path / "tenant"
        root.mkdir()
        (root / "app.py").write_text(textwrap.dedent("""
            import sys
            from http.server import BaseHTTPRequestHandler, HTTPServer

            PAGE = '''<!doctype html>
            <title>Passkey Bench</title>
            <div id="width"></div>
            <button id="enroll">enroll</button>
            <button id="assert">assert</button>
            <div id="out"></div>
            <script>
            document.getElementById("width").textContent = "w=" + window.innerWidth;
            let credId = null;
            const doEnroll = async () => {
              const cred = await navigator.credentials.create({publicKey: {
                challenge: new Uint8Array(32), rp: {name: "bench"},
                user: {id: new Uint8Array(16), name: "u", displayName: "u"},
                pubKeyCredParams: [{type: "public-key", alg: -7}],
                authenticatorSelection: {authenticatorAttachment: "platform",
                                         userVerification: "required"}}});
              credId = cred.rawId;
              document.getElementById("out").textContent = "enrolled";
            };
            document.getElementById("enroll").onclick = async () => {
              try { await doEnroll(); }
              catch (e) { document.getElementById("out").textContent = "error:" + e; }
            };
            document.getElementById("assert").onclick = async () => {
              await navigator.credentials.get({publicKey: {
                challenge: new Uint8Array(32),
                allowCredentials: [{type: "public-key", id: credId}],
                userVerification: "required"}});
              document.getElementById("out").textContent = "asserted";
            };
            </script>'''

            class Handler(BaseHTTPRequestHandler):
                def log_message(self, *a): pass
                def do_GET(self):
                    body = PAGE.encode()
                    self.send_response(200)
                    self.send_header("Content-Type", "text/html")
                    self.send_header("Content-Length", str(len(body)))
                    self.end_headers()
                    self.wfile.write(body)

            HTTPServer(("127.0.0.1", int(sys.argv[1])), Handler).serve_forever()
        """))
        import sys as _sys

        adapter = loads_adapter(
            textwrap.dedent(f"""
            [project]
            name = "passkey-bench"
            [commands]
            serve = "{_sys.executable} app.py {{port}}"
            [evidence]
            dir = "evidence"
            """),
            root=root,
        )
        drives = tmp_path / "drives"
        drives.mkdir()
        (drives / "passkey.drive.toml").write_text(textwrap.dedent("""
            scenario = "passkey_flow"

            [browser]
            webauthn = true
            viewport = { width = 390, height = 844 }

            [[step]]
            name = "open"
            kind = "goto"
            url = "{base_url}/"
            expect = { status = 200, body_contains = "w=390" }

            [[step]]
            name = "enroll_passkey"
            kind = "click"
            selector = "#enroll"
            expect = { selector_visible = "text=enrolled" }

            [[step]]
            name = "assert_passkey"
            kind = "click"
            selector = "#assert"
            expect = { selector_visible = "text=asserted" }
        """))
        report = drive(adapter, drives, containers_mode="off")
        failures = [
            (s.name, s.detail) for r in report.results for s in r.steps if not s.ok
        ]
        assert report.ok, failures

    def test_failing_expectation_stops_scenario_keeps_evidence(
        self, tenant, monkeypatch
    ):
        adapter, drives = tenant
        monkeypatch.delenv("EVIDENCE_MODE", raising=False)
        monkeypatch.delenv("EVIDENCE_DIR", raising=False)
        (drives / "missing.drive.toml").write_text(textwrap.dedent("""
            scenario = "missing"

            [[step]]
            name = "open"
            kind = "goto"
            url = "{base_url}/"
            expect = { selector_visible = "#does-not-exist" }

            [[step]]
            name = "never_runs"
            kind = "screenshot"
        """))
        report = drive(adapter, drives, containers_mode="off")
        assert not report.ok
        steps = report.results[0].steps
        assert [s.name for s in steps] == ["open"]  # later steps skipped
        assert "not visible" in steps[0].detail
        manifest_path = next(
            adapter.resolve(adapter.evidence_dir).glob("runs/*/manifest.json")
        )
        manifest = load_manifest(manifest_path)
        # the goto's log evidence survived the failure — still judgeable
        assert [i.kind for i in manifest.scenarios[0].items] == ["log"]
