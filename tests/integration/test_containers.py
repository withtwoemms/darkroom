"""Container-environment tests against real docker (skipped without it).

The app image is built from a tiny Dockerfile in the test tenant — a
stdlib HTTP server — so the tests exercise the true path: build command,
private network, service container, digest evidence, and the container
step kind for failure injection.
"""

import shutil
import subprocess
import textwrap

import pytest

pytest.importorskip("testcontainers")

from darkroom.adapter import loads_adapter  # noqa: E402
from darkroom.drive import (  # noqa: E402
    DriveError,
    drive,
    resolve_container_mode,
)
from darkroom.manifest import load_manifest  # noqa: E402


def _docker_available() -> bool:
    if shutil.which("docker") is None:
        return False
    return subprocess.run(
        ["docker", "info"], capture_output=True
    ).returncode == 0


pytestmark = pytest.mark.skipif(
    not _docker_available(), reason="docker unavailable"
)

APP_PY = """
import json, os
from http.server import BaseHTTPRequestHandler, HTTPServer

class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a): pass
    def do_GET(self):
        body = json.dumps({
            "ok": True,
            "greeting": os.environ.get("GREETING", "none"),
            "db_host": os.environ.get("DB_HOST", "none"),
        }).encode()
        self.send_response(200)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

HTTPServer(("0.0.0.0", 8000), Handler).serve_forever()
"""

DOCKERFILE = """
FROM python:3.12-alpine
COPY app.py /app.py
CMD ["python", "/app.py"]
"""


@pytest.fixture()
def tenant(tmp_path):
    root = tmp_path / "tenant"
    root.mkdir()
    (root / "app.py").write_text(textwrap.dedent(APP_PY))
    (root / "Dockerfile").write_text(textwrap.dedent(DOCKERFILE))
    adapter = loads_adapter(
        textwrap.dedent("""
        [project]
        name = "boxed"

        [environment]
        app_image = "darkroom-test-boxed:latest"
        app_port = 8000
        build = "docker build -q -t darkroom-test-boxed:latest ."
        app_env = { GREETING = "{greeting}", DB_HOST = "{db.host}" }

        [[environment.services]]
        name = "db"
        image = "python:3.12-alpine"
        port = 9999
        env = { X = "1" }
        """),
        root=root,
    )
    drives = tmp_path / "drives"
    drives.mkdir()
    return adapter, drives


class TestModeResolution:
    def test_off_never(self, tenant):
        adapter, _ = tenant
        assert resolve_container_mode("off", adapter) is False

    def test_auto_with_image(self, tenant):
        adapter, _ = tenant
        assert resolve_container_mode("auto", adapter) is True

    def test_auto_without_image(self, tmp_path):
        adapter = loads_adapter('[project]\nname = "p"', root=tmp_path)
        assert resolve_container_mode("auto", adapter) is False

    def test_required_without_image_refused(self, tmp_path):
        adapter = loads_adapter('[project]\nname = "p"', root=tmp_path)
        with pytest.raises(DriveError, match="declares no"):
            resolve_container_mode("required", adapter)


class TestContainerDrive:
    def test_containerized_scenario_with_digests_and_env(self, tenant, monkeypatch):
        adapter, drives = tenant
        monkeypatch.delenv("EVIDENCE_MODE", raising=False)
        monkeypatch.delenv("EVIDENCE_DIR", raising=False)
        (drives / "boxed.drive.toml").write_text(textwrap.dedent("""
            scenario = "boxed"

            [serve]
            greeting = "safelight"

            [[step]]
            name = "hit"
            kind = "http"
            url = "{base_url}/"
            expect = { status = 200, body_contains = "safelight" }

            [[step]]
            name = "service_alias_injected"
            kind = "http"
            url = "{base_url}/"
            expect = { status = 200, body_contains = "db" }
        """))
        report = drive(adapter, drives, containers_mode="required")
        failures = [
            (s.name, s.detail) for r in report.results for s in r.steps if not s.ok
        ]
        assert report.ok, failures

        import json as json_module

        manifest_path = next(
            adapter.resolve(adapter.evidence_dir).glob("runs/*/manifest.json")
        )
        manifest = load_manifest(manifest_path)
        items = manifest.scenarios[0].items
        assert items[0].step == "environment"  # digests recorded first
        digests = json_module.loads(
            (manifest_path.parent / items[0].path).read_text()
        )
        assert "app" in digests["data"]["images"]
        assert "db" in digests["data"]["images"]

    def test_container_step_failure_injection(self, tenant, monkeypatch):
        adapter, drives = tenant
        monkeypatch.delenv("EVIDENCE_MODE", raising=False)
        monkeypatch.delenv("EVIDENCE_DIR", raising=False)
        (drives / "chaos.drive.toml").write_text(textwrap.dedent("""
            scenario = "chaos"

            [serve]
            greeting = "x"

            [[step]]
            name = "alive"
            kind = "http"
            url = "{base_url}/"
            expect = { status = 200 }

            [[step]]
            name = "pause_app"
            kind = "container"
            action = "pause"
            service = "app"

            [[step]]
            name = "unpause_app"
            kind = "container"
            action = "unpause"
            service = "app"

            [[step]]
            name = "alive_again"
            kind = "http"
            url = "{base_url}/"
            expect = { status = 200 }
        """))
        report = drive(adapter, drives, containers_mode="required")
        failures = [
            (s.name, s.detail) for r in report.results for s in r.steps if not s.ok
        ]
        assert report.ok, failures
        kinds = [s.kind for s in report.results[0].steps]
        assert kinds == ["http", "container", "container", "http"]
