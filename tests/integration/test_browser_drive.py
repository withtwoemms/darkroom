"""Browser drive steps against a real chromium (skipped without one).

The tenant is a stdlib HTTP server with a form page, so the tests
exercise the true path: goto with expectations over the live page,
fill + click driving a real submission, screenshot evidence through
the existing producer, and a failing selector expectation stopping
the scenario while keeping its evidence.
"""

import json
import shutil
import textwrap
from pathlib import Path

import pytest


def _exposure(proofs, scenario):
    """A proof folder holding only its exposure — the fixture shape."""
    folder = proofs / scenario
    folder.mkdir(parents=True, exist_ok=True)
    return folder / "exposure.toml"


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
        _exposure(drives, "note_saved").write_text(textwrap.dedent("""
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
        # goto (+ its expectation witness), fill, click (+ witness), screenshot
        assert kinds == ["log", "log", "log", "log", "log", "screenshot"]
        shot = items[-1]
        assert (manifest_path.parent / shot.path).stat().st_size > 0

    def test_record_captures_screencast(self, tenant, monkeypatch):
        adapter, drives = tenant
        monkeypatch.delenv("EVIDENCE_MODE", raising=False)
        monkeypatch.delenv("EVIDENCE_DIR", raising=False)
        _exposure(drives, "recorded").write_text(textwrap.dedent("""
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

    def test_touching_a_selector_selects_the_pages_that_reach_it(self, tmp_path, capsys, monkeypatch):
        project = tmp_path / "relay-service"
        shutil.copytree(EXAMPLE, project, ignore=shutil.ignore_patterns("evidence"))
        monkeypatch.chdir(project)
        monkeypatch.delenv("EVIDENCE_MODE", raising=False)
        monkeypatch.delenv("EVIDENCE_DIR", raising=False)

        code = main(["expose", "--drives", "proofs-ui", "--touching", "#notes li"])
        out = capsys.readouterr().out
        assert code == 0, out
        assert "selection: --touching '#notes li'" in out
        assert "notes_page:" in out and "archived_note_shows_its_state:" in out
        assert "2/2 scenario(s) green" in out

    def test_shipped_ui_example_runs_green(self, tmp_path, capsys, monkeypatch):
        project = tmp_path / "relay-service"
        shutil.copytree(EXAMPLE, project, ignore=shutil.ignore_patterns("evidence"))
        monkeypatch.chdir(project)
        monkeypatch.delenv("EVIDENCE_MODE", raising=False)
        monkeypatch.delenv("EVIDENCE_DIR", raising=False)

        code = main(
            ["expose", "--drives", "proofs-ui", "--scenario", "notes_page"]
        )
        out = capsys.readouterr().out
        assert code == 0, out
        assert "notes_page:" in out
        assert "verify: ok (contract)" in out  # derived from the proof's rubric

        manifest = next(project.glob("evidence/runs/*/manifest.json"))
        bundle = load_manifest(manifest).scenarios[0]
        assert bundle.provenance["rubric_version"] == "2"
        items = bundle.items
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
            <button id="later">later</button>
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
            document.getElementById("later").onclick = () => {
              setTimeout(() => { location.href = "/?went=1"; }, 800);
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
        _exposure(drives, "passkey_flow").write_text(textwrap.dedent("""
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

            [[step]]
            name = "delayed_navigation_waits"
            kind = "click"
            selector = "#later"
            expect = { url_contains = "went=1" }
        """))
        report = drive(adapter, drives, containers_mode="off")
        failures = [
            (s.name, s.detail) for r in report.results for s in r.steps if not s.ok
        ]
        assert report.ok, failures

    def test_prf_extension_on_by_default_and_switchable(self, tmp_path, monkeypatch):
        monkeypatch.delenv("EVIDENCE_MODE", raising=False)
        monkeypatch.delenv("EVIDENCE_DIR", raising=False)
        root = tmp_path / "tenant"
        root.mkdir()
        (root / "app.py").write_text(textwrap.dedent("""
            import sys
            from http.server import BaseHTTPRequestHandler, HTTPServer

            PAGE = '''<!doctype html>
            <title>PRF Bench</title>
            <button id="enroll">enroll</button>
            <button id="derive">derive</button>
            <div id="out"></div>
            <script>
            let credId = null, first = null;
            const b64 = b => btoa(String.fromCharCode(...new Uint8Array(b)));
            const salt = new TextEncoder().encode("bench-salt");
            document.getElementById("enroll").onclick = async () => {
              const cred = await navigator.credentials.create({publicKey: {
                challenge: new Uint8Array(32), rp: {name: "bench"},
                user: {id: new Uint8Array(16), name: "u", displayName: "u"},
                pubKeyCredParams: [{type: "public-key", alg: -7}],
                authenticatorSelection: {authenticatorAttachment: "platform",
                                         residentKey: "required",
                                         userVerification: "required"},
                extensions: {prf: {}}}});
              credId = cred.rawId;
              const ext = cred.getClientExtensionResults();
              document.getElementById("out").textContent =
                "prf=" + (ext.prf ? ext.prf.enabled : "absent");
            };
            document.getElementById("derive").onclick = async () => {
              const a = await navigator.credentials.get({publicKey: {
                challenge: new Uint8Array(32),
                allowCredentials: [{type: "public-key", id: credId}],
                userVerification: "required",
                extensions: {prf: {eval: {first: salt}}}}});
              const ext = a.getClientExtensionResults();
              const got = ext.prf && ext.prf.results ? b64(ext.prf.results.first) : "none";
              if (first === null) { first = got; document.getElementById("out").textContent = "derived"; }
              else { document.getElementById("out").textContent = "same=" + (got === first && got !== "none"); }
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
            name = "prf-bench"
            [commands]
            serve = "{_sys.executable} app.py {{port}}"
            [evidence]
            dir = "evidence"
            """),
            root=root,
        )
        drives = tmp_path / "drives"
        drives.mkdir()
        _exposure(drives, "prf_on").write_text(textwrap.dedent("""
            scenario = "prf_on"

            [browser]
            webauthn = true

            [[step]]
            name = "open"
            kind = "goto"
            url = "{base_url}/"
            expect = { status = 200 }

            [[step]]
            name = "enroll"
            kind = "click"
            selector = "#enroll"
            expect = { selector_visible = "text=prf=true" }

            [[step]]
            name = "derive_once"
            kind = "click"
            selector = "#derive"
            expect = { selector_visible = "text=derived" }

            [[step]]
            name = "derive_again"
            kind = "click"
            selector = "#derive"
            expect = { selector_visible = "text=same=true" }
        """))
        _exposure(drives, "prf_off").write_text(textwrap.dedent("""
            scenario = "prf_off"

            [browser]
            webauthn = true
            prf = false

            [[step]]
            name = "open"
            kind = "goto"
            url = "{base_url}/"
            expect = { status = 200 }

            [[step]]
            name = "enroll"
            kind = "click"
            selector = "#enroll"
            expect = { selector_visible = "text=prf=false" }
        """))
        report = drive(adapter, drives, containers_mode="off")
        failures = [
            (r.scenario, s.name, s.detail)
            for r in report.results
            for s in r.steps
            if not s.ok
        ]
        assert report.ok, failures

    def test_failing_expectation_stops_scenario_keeps_evidence(
        self, tenant, monkeypatch
    ):
        adapter, drives = tenant
        monkeypatch.delenv("EVIDENCE_MODE", raising=False)
        monkeypatch.delenv("EVIDENCE_DIR", raising=False)
        _exposure(drives, "missing").write_text(textwrap.dedent("""
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
        # the goto's log evidence survived the failure — and so did its
        # expectation witness, recording what it found — still judgeable
        assert [i.kind for i in manifest.scenarios[0].items] == ["log", "log"]


class TestPushOption:
    """The Push API the exam supplies, driven against the relay example.

    The relay has no push service, no exam flag, and no route behind
    its control — the page talks to the Push API as any page would.
    What makes it driveable is ``[browser] push``, the same bargain as
    the virtual authenticator: the exam provides the platform piece,
    and the tenant stays clean.
    """

    def _relay(self, tmp_path, monkeypatch):
        project = tmp_path / "relay-service"
        shutil.copytree(EXAMPLE, project, ignore=shutil.ignore_patterns("evidence"))
        monkeypatch.chdir(project)
        monkeypatch.delenv("EVIDENCE_MODE", raising=False)
        monkeypatch.delenv("EVIDENCE_DIR", raising=False)
        return project

    def _adapter(self):
        return loads_adapter(Path("darkroom.toml").read_text(), root=Path.cwd())

    def test_the_shipped_telling_proofs_run_green(self, tmp_path, capsys, monkeypatch):
        pytest.importorskip("cryptography")
        project = self._relay(tmp_path, monkeypatch)

        code = main(["expose", "--drives", "proofs-ui", "--tag", "telling"])
        out = capsys.readouterr().out
        assert code == 0, out
        assert "2/2 scenario(s) green" in out

        manifest_path = next(project.glob("evidence/runs/*/manifest.json"))
        bundles = {b.scenario: b for b in load_manifest(manifest_path).scenarios}
        turned_on = bundles["telling_can_be_turned_on"]
        witnesses = {i.step: i for i in turned_on.items if i.step.endswith(".expect")}

        def witness(step):
            path = manifest_path.parent / witnesses[step + ".expect"].path
            return json.loads(path.read_text())["data"]

        # the address the page showed is the endpoint the exam configured
        agreed = witness("agree_to_be_told")
        assert agreed["ok"] is True
        assert "/push/relay-device" in agreed["expect"]["body_contains"]
        # and opening it again found the same address, unasked
        again = witness("open_it_again")
        assert again["found"] == {"selector_visible": True, "body_contains": True}
        # stopping left nothing for a reload to find
        assert witness("forgotten_after_a_reload")["ok"] is True

    def test_a_dismissed_prompt_is_its_own_state(self, tmp_path, monkeypatch):
        """``permission = "default"`` — asked, and never answered.

        subscribe() rejects as a browser's does, so a tenant can tell
        "never answered" from "refused" without the product keeping a
        flag for either.
        """
        pytest.importorskip("cryptography")
        self._relay(tmp_path, monkeypatch)
        drives = Path("drives")
        drives.mkdir()
        _exposure(drives, "the_prompt_went_unanswered").write_text(textwrap.dedent("""
            scenario = "the_prompt_went_unanswered"

            [browser]
            push = { permission = "default" }

            [[step]]
            name = "open"
            kind = "goto"
            url = "{base_url}/telling"
            expect = { status = 200, selector_visible = 'main[data-telling-state="unasked"]' }

            [[step]]
            name = "ask_and_say_nothing"
            kind = "click"
            selector = "#ask"
            expect = { selector_visible = 'main[data-telling-state="unanswered"]', body_contains = "NotAllowedError" }
        """))
        report = drive(self._adapter(), drives, containers_mode="off")
        assert report.ok, [
            (s.name, s.detail) for r in report.results for s in r.steps if not s.ok
        ]

    def test_an_application_server_key_given_as_bytes_is_carried_back(
        self, tmp_path, monkeypatch
    ):
        """Pages pass the sender key either way, so both must survive.

        The relay passes its VAPID key as a base64url string; plenty of
        pages convert it to a `Uint8Array` first. Either way
        `subscription.options.applicationServerKey` must read back as
        the ArrayBuffer a browser hands over.
        """
        pytest.importorskip("cryptography")
        root = tmp_path / "tenant"
        root.mkdir()
        (root / "app.py").write_text(textwrap.dedent("""
            import sys
            from http.server import BaseHTTPRequestHandler, HTTPServer

            PAGE = '''<!doctype html><title>Bytes Bench</title>
            <div id="out">waiting</div>
            <script>
            (async () => {
              const reg = await navigator.serviceWorker.register("/w.js");
              const key = new Uint8Array(65); key[0] = 4;
              const sub = await reg.pushManager.subscribe(
                {userVisibleOnly: true, applicationServerKey: key});
              const back = new Uint8Array(sub.options.applicationServerKey);
              document.getElementById("out").textContent =
                "bytes=" + back.byteLength + " head=" + back[0];
            })();
            </script>'''

            class Handler(BaseHTTPRequestHandler):
                def log_message(self, *a): pass
                def do_GET(self):
                    js = self.path == "/w.js"
                    body = (b"// worker" if js else PAGE.encode())
                    self.send_response(200)
                    self.send_header(
                        "Content-Type",
                        "text/javascript" if js else "text/html")
                    self.send_header("Content-Length", str(len(body)))
                    self.end_headers()
                    self.wfile.write(body)

            HTTPServer(("127.0.0.1", int(sys.argv[1])), Handler).serve_forever()
        """))
        import sys as _sys

        adapter = loads_adapter(
            textwrap.dedent(f"""
            [project]
            name = "bytes-bench"
            [commands]
            serve = "{_sys.executable} app.py {{port}}"
            [evidence]
            dir = "evidence"
            """),
            root=root,
        )
        drives = tmp_path / "drives"
        drives.mkdir()
        _exposure(drives, "the_sender_key_comes_back").write_text(textwrap.dedent("""
            scenario = "the_sender_key_comes_back"

            [browser]
            push = true

            [[step]]
            name = "subscribe_with_bytes"
            kind = "goto"
            url = "{base_url}/"
            expect = { status = 200, body_contains = "bytes=65 head=4" }
        """))
        report = drive(adapter, drives, containers_mode="off")
        assert report.ok, [
            (s.name, s.detail) for r in report.results for s in r.steps if not s.ok
        ]

    def test_the_generated_keys_reach_the_drive_context(self, tmp_path, monkeypatch):
        """``{push.private}`` is the drive's own ear.

        A tenant that sends opens the collector's body in a ``command``
        step. This proves the values are there, that the endpoint
        resolved against a drive value, and that both halves and the
        secret are the sizes RFC 8291 encryption needs; the unit tests
        prove they open a real payload.
        """
        pytest.importorskip("cryptography")
        self._relay(tmp_path, monkeypatch)
        drives = Path("drives")
        drives.mkdir()
        import sys as _sys

        sizes = (
            "import base64; d = lambda s: base64.urlsafe_b64decode("
            "s + '=' * (-len(s) % 4)); "
            "print(len(d('{push.p256dh}')), len(d('{push.auth}')), "
            "len(d('{push.private}')))"
        )
        _exposure(drives, "the_keys_are_in_hand").write_text(
            'scenario = "the_keys_are_in_hand"\n\n'
            "[browser]\n"
            'push = { endpoint = "{base_url}/push/one-device" }\n\n'
            "[[step]]\n"
            'name = "open"\n'
            'kind = "goto"\n'
            'url = "{base_url}/telling"\n'
            "expect = { status = 200 }\n\n"
            "[[step]]\n"
            'name = "the_endpoint_addressed_the_served_app"\n'
            'kind = "assert"\n'
            "that = '''{push.endpoint} == {base_url}/push/one-device'''\n\n"
            "[[step]]\n"
            'name = "both_halves_and_the_secret"\n'
            'kind = "command"\n'
            f"cmd = '''{_sys.executable} -c \"{sizes}\"'''\n"
            'expect = { exit_code = 0, body_contains = "65 16 32" }\n'
        )
        report = drive(self._adapter(), drives, containers_mode="off")
        assert report.ok, [
            (s.name, s.detail) for r in report.results for s in r.steps if not s.ok
        ]
