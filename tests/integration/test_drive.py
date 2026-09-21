"""End-to-end tests of the drive engine against a real stdlib SUT.

The system under test is a tiny JSON HTTP server (subprocess, fresh per
scenario) with an Ed25519 /verify endpoint, so the full step vocabulary
— keygen, sign() interpolation, save, expect, assert, command — is
exercised over a real socket with real crypto.
"""

import textwrap
from pathlib import Path

import pytest

from darkroom.adapter import loads_adapter
from darkroom.drive import DriveError, drive
from darkroom.manifest import load_manifest

SUT = """
    import base64, json, sys, uuid
    from http.server import BaseHTTPRequestHandler, HTTPServer
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
    from cryptography.exceptions import InvalidSignature

    ITEMS = {}

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *a): pass

        def _json(self, status, payload):
            body = json.dumps(payload).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _body(self):
            length = int(self.headers.get("Content-Length", 0))
            return json.loads(self.rfile.read(length) or b"{}")

        def do_POST(self):
            data = self._body()
            if self.path == "/items":
                item_id = str(len(ITEMS) + 1)
                ITEMS[item_id] = {"id": item_id, "name": data["name"],
                                  "nonce": uuid.uuid4().hex}
                return self._json(201, ITEMS[item_id])
            if self.path == "/verify":
                try:
                    key = Ed25519PublicKey.from_public_bytes(
                        base64.b64decode(data["pub"]))
                    key.verify(base64.b64decode(data["sig"]),
                               data["msg"].encode())
                    return self._json(200, {"verified": True})
                except (InvalidSignature, ValueError, KeyError):
                    return self._json(400, {"verified": False})
            self._json(404, {})

        def do_GET(self):
            item = ITEMS.get(self.path.rsplit("/", 1)[-1])
            self._json(200 if item else 404, item or {})

    HTTPServer(("127.0.0.1", int(sys.argv[1])), Handler).serve_forever()
"""


@pytest.fixture()
def project(tmp_path):
    import sys

    root = tmp_path / "tenant"
    root.mkdir()
    (root / "app.py").write_text(textwrap.dedent(SUT))
    adapter = loads_adapter(
        f'[project]\nname = "sut"\n[commands]\n'
        f'serve = "{sys.executable} app.py {{port}}"',
        root=root,
    )
    drives = tmp_path / "drives"
    drives.mkdir()
    return adapter, drives


def _script(drives: Path, name: str, content: str) -> Path:
    path = drives / f"{name}.drive.toml"
    path.write_text(textwrap.dedent(content))
    return path


class TestDriveEngine:
    def test_full_vocabulary_green_scenario(self, project, tmp_path, monkeypatch):
        adapter, drives = project
        monkeypatch.delenv("EVIDENCE_MODE", raising=False)
        monkeypatch.delenv("EVIDENCE_DIR", raising=False)
        _script(drives, "roundtrip", """
            scenario = "roundtrip"

            [[step]]
            name = "keys"
            kind = "keygen"
            names = ["mom", "impostor"]

            [[step]]
            name = "create"
            kind = "http"
            method = "POST"
            url = "{base_url}/items"
            json = { name = "{keys.mom.public}" }
            expect = { status = 201 }
            save = { item_id = "$.id", nonce_a = "$.nonce" }

            [[step]]
            name = "second"
            kind = "http"
            method = "POST"
            url = "{base_url}/items"
            json = { name = "other" }
            save = { nonce_b = "$.nonce" }

            [[step]]
            name = "nonces_differ"
            kind = "assert"
            that = "{nonce_a} != {nonce_b}"

            [[step]]
            name = "fetch"
            kind = "http"
            url = "{base_url}/items/{item_id}"
            expect = { status = 200, body_contains = "{nonce_a}" }

            [[step]]
            name = "verify_good"
            kind = "http"
            method = "POST"
            url = "{base_url}/verify"
            json = { pub = "{keys.mom.public}", msg = "{nonce_a}", sig = "{sign(keys.mom, nonce_a)}" }
            expect = { status = 200, body_contains = "true" }

            [[step]]
            name = "verify_forged"
            kind = "http"
            method = "POST"
            url = "{base_url}/verify"
            json = { pub = "{keys.mom.public}", msg = "{nonce_a}", sig = "{sign(keys.impostor, nonce_a)}" }
            expect = { status_in = [400] }

            [[step]]
            name = "shell"
            kind = "command"
            cmd = "echo done-{item_id}"
            expect = { exit_code = 0, body_contains = "done-1" }
        """)
        report = drive(adapter, drives)
        failures = [
            (s.name, s.detail) for r in report.results for s in r.steps if not s.ok
        ]
        assert report.ok, failures
        assert [s.kind for s in report.results[0].steps] == [
            "keygen", "http", "http", "assert", "http", "http", "http", "command"
        ]

        # the run is ordinary darkroom evidence
        manifests = list(
            adapter.resolve(adapter.evidence_dir).glob("runs/*/manifest.json")
        )
        assert len(manifests) == 1
        manifest = load_manifest(manifests[0])
        bundle = manifest.scenarios[0]
        assert bundle.scenario == "roundtrip"
        kinds = {i.kind for i in bundle.items}
        assert kinds == {"http_transcript", "log", "command_transcript"}

    def test_failed_expect_stops_scenario_but_keeps_evidence(
        self, project, monkeypatch
    ):
        adapter, drives = project
        monkeypatch.delenv("EVIDENCE_MODE", raising=False)
        monkeypatch.delenv("EVIDENCE_DIR", raising=False)
        _script(drives, "failing", """
            scenario = "failing"

            [[step]]
            name = "missing"
            kind = "http"
            url = "{base_url}/items/999"
            expect = { status = 200 }

            [[step]]
            name = "never_runs"
            kind = "http"
            url = "{base_url}/items/999"
        """)
        report = drive(adapter, drives)
        assert not report.ok
        result = report.results[0]
        assert len(result.steps) == 1  # second step skipped
        assert "expected status 200, got 404" in result.steps[0].detail

        manifest = load_manifest(
            next(adapter.resolve(adapter.evidence_dir).glob("runs/*/manifest.json"))
        )
        assert manifest.scenarios[0].items  # evidence captured before the check

    def test_scenario_filter_and_missing(self, project, monkeypatch):
        adapter, drives = project
        monkeypatch.delenv("EVIDENCE_MODE", raising=False)
        _script(drives, "one", 'scenario = "one"\n[[step]]\nname = "x"\nkind = "wait"\nseconds = 0\n')
        report = drive(adapter, drives, scenario="one")
        assert report.ok and report.results[0].scenario == "one"
        with pytest.raises(DriveError, match="no drive scripts"):
            drive(adapter, drives, scenario="ghost")

    def test_unknown_placeholder_named(self, project, monkeypatch):
        adapter, drives = project
        monkeypatch.delenv("EVIDENCE_MODE", raising=False)
        _script(drives, "bad", """
            scenario = "bad"
            [[step]]
            name = "x"
            kind = "http"
            url = "{base_url}/items/{nope}"
        """)
        report = drive(adapter, drives)
        assert not report.ok
        assert "unknown placeholder '{nope}'" in report.results[0].steps[0].detail
