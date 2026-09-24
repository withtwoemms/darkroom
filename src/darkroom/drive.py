"""The drive engine: the exam as data, executed against a black box.

A drive script is a declarative step sequence per scenario. The engine
boots the system under test via the adapter's ``serve`` command (fresh
process per scenario — hermetic state), executes the steps, and captures
every exchange through the existing producers, so a drive run yields an
ordinary evidence manifest. The tenant contains no harness: the engine
is this package, the scripts are operator-side data.

Step kinds:
    http     request via the HTTP transcript producer; ``expect`` checks
             (status / status_in / body_contains), ``save`` extracts
             dot-path values from the JSON response body
    command  run an argv/string via the command transcript producer
    keygen   Ed25519 pairs (requires the ``crypto`` extra)
    assert   a simple equality/inequality over interpolated values,
             captured as log evidence
    wait     sleep
    container  stop/start/pause/unpause a declared service (container
             mode only) — failure injection, captured as log evidence
    goto     navigate a real browser page (requires the ``playwright``
             extra + an installed browser); action captured as log
             evidence, ``expect`` adds title_contains / body_contains /
             url_contains / selector_visible over the live page
    click    click a selector on the current page
    fill     fill form fields ({selector = value} table)
    screenshot  capture the current page via the screenshot producer

A scenario containing browser steps gets one browser session (fresh
per scenario, like the server): pages navigate against ``{base_url}``.

Interpolation: ``{name}`` from saved values, ``{base_url}``,
``{keys.<n>.public}``, and the call form ``{sign(keys.<n>, <var>)}``.
A step whose ``expect`` fails stops its scenario (later steps skipped);
evidence captured before the check is kept — a failing scenario is still
judgeable, which is the point.
"""

from __future__ import annotations

import json
import os
import re
import socket
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

if sys.version_info >= (3, 11):
    import tomllib
else:  # pragma: no cover - exercised only on 3.10
    import tomli as tomllib

from darkroom.adapter import ProjectAdapter
from darkroom.capture import EvidenceCapture

DRIVE_SUFFIX = ".drive.toml"


class DriveError(Exception):
    pass


@dataclass
class StepResult:
    name: str
    kind: str
    ok: bool
    detail: str = ""


@dataclass
class ScenarioResult:
    scenario: str
    steps: list[StepResult] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return all(s.ok for s in self.steps)


@dataclass
class DriveReport:
    results: list[ScenarioResult] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return bool(self.results) and all(r.ok for r in self.results)


# --- interpolation --------------------------------------------------------

_SIGN_CALL = re.compile(r"\{sign\(\s*([A-Za-z0-9_.]+)\s*,\s*([A-Za-z0-9_.]+)\s*\)\}")
_PLACEHOLDER = re.compile(r"\{([A-Za-z0-9_.]+)\}")


class Context:
    def __init__(self, values: dict[str, str] | None = None):
        self.values: dict[str, str] = dict(values or {})
        self.private_keys: dict[str, object] = {}

    def interpolate(self, text: str) -> str:
        # {{ and }} are literal-brace escapes, so shell fragments like
        # curl's %{http_code} can be written %{{http_code}} — resolved
        # after placeholder substitution
        text = text.replace("{{", "\x00").replace("}}", "\x01")

        def _sign(match: re.Match) -> str:
            key_ref, var = match.group(1), match.group(2)
            private = self.private_keys.get(key_ref)
            if private is None:
                raise DriveError(f"no key '{key_ref}' generated before sign()")
            payload = self.lookup(var).encode()
            import base64

            return base64.b64encode(private.sign(payload)).decode()

        text = _SIGN_CALL.sub(_sign, text)

        def _value(match: re.Match) -> str:
            return self.lookup(match.group(1))

        text = _PLACEHOLDER.sub(_value, text)
        return text.replace("\x00", "{").replace("\x01", "}")

    def lookup(self, name: str) -> str:
        if name not in self.values:
            raise DriveError(f"unknown placeholder '{{{name}}}'")
        return self.values[name]

    def interpolate_json(self, value):
        if isinstance(value, str):
            return self.interpolate(value)
        if isinstance(value, dict):
            return {k: self.interpolate_json(v) for k, v in value.items()}
        if isinstance(value, list):
            return [self.interpolate_json(v) for v in value]
        return value


def _dot_path(payload, path: str):
    if not path.startswith("$."):
        raise DriveError(f"save paths use '$.field.sub' form, got '{path}'")
    current = payload
    for part in path[2:].split("."):
        if not isinstance(current, dict) or part not in current:
            raise DriveError(f"path '{path}' not found in response body")
        current = current[part]
    return current


# --- step execution -------------------------------------------------------

def _check_expect(expect: dict, transcript: dict) -> str | None:
    """Return a failure detail, or None if all expectations hold."""
    response = transcript.get("response", transcript)
    status = response.get("status", transcript.get("exit_code"))
    if "status" in expect and status != expect["status"]:
        return f"expected status {expect['status']}, got {status}"
    if "status_in" in expect and status not in expect["status_in"]:
        return f"expected status in {expect['status_in']}, got {status}"
    if "exit_code" in expect and transcript.get("exit_code") != expect["exit_code"]:
        return f"expected exit_code {expect['exit_code']}, got {transcript.get('exit_code')}"
    if "body_contains" in expect:
        body = response.get("body", transcript.get("stdout", ""))
        if expect["body_contains"] not in body:
            return f"body does not contain '{expect['body_contains']}'"
    return None


def _run_http_step(
    step: dict, ctx: Context, capture: EvidenceCapture
) -> tuple[dict, str | None]:
    url = ctx.interpolate(step["url"])
    method = step.get("method", "GET")
    headers = ctx.interpolate_json(step.get("headers", {}))
    body = None
    if "json" in step:
        body = json.dumps(ctx.interpolate_json(step["json"]))
        headers.setdefault("Content-Type", "application/json")
    path = capture.http(step["name"], url, method=method, headers=headers, body=body)
    transcript = json.loads(Path(path).read_text())

    for var, save_path in step.get("save", {}).items():
        try:
            payload = json.loads(transcript["response"]["body"])
        except (ValueError, KeyError):
            raise DriveError(
                f"step '{step['name']}': cannot save from a non-JSON response"
            ) from None
        ctx.values[var] = str(_dot_path(payload, save_path))
    expect = ctx.interpolate_json(step.get("expect", {}))
    return transcript, _check_expect(expect, transcript)


def _run_command_step(
    step: dict, ctx: Context, capture: EvidenceCapture
) -> tuple[dict, str | None]:
    raw = step.get("argv", step.get("cmd"))
    if raw is None:
        raise DriveError(f"command step '{step['name']}' needs argv or cmd")
    if isinstance(raw, list):
        argv = [ctx.interpolate(a) for a in raw]
    else:
        argv = ["/bin/sh", "-c", ctx.interpolate(raw)]
    path = capture.command(step["name"], argv)
    transcript = json.loads(Path(path).read_text())
    expect = ctx.interpolate_json(step.get("expect", {}))
    return transcript, _check_expect(expect, transcript)


def _run_keygen_step(step: dict, ctx: Context) -> None:
    try:
        import base64

        from cryptography.hazmat.primitives.asymmetric.ed25519 import (
            Ed25519PrivateKey,
        )
        from cryptography.hazmat.primitives.serialization import (
            Encoding,
            PublicFormat,
        )
    except ImportError:
        raise DriveError(
            "keygen steps need the crypto extra: pip install 'darkroom-ai[crypto]'"
        ) from None
    for name in step.get("names", []):
        private = Ed25519PrivateKey.generate()
        public = private.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)
        ctx.private_keys[f"keys.{name}"] = private
        ctx.values[f"keys.{name}.public"] = base64.b64encode(public).decode()


def _run_assert_step(step: dict, ctx: Context, capture: EvidenceCapture) -> str | None:
    expression = step["that"]
    resolved = ctx.interpolate(expression)
    if "!=" in resolved:
        left, _, right = resolved.partition("!=")
        ok = left.strip() != right.strip()
    elif "==" in resolved:
        left, _, right = resolved.partition("==")
        ok = left.strip() == right.strip()
    else:
        raise DriveError(f"assert step '{step['name']}' needs == or !=")
    capture.log(step["name"], {"assert": expression, "resolved": resolved, "ok": ok})
    return None if ok else f"assertion failed: {resolved}"


# --- browser steps --------------------------------------------------------

BROWSER_STEP_KINDS = ("goto", "click", "fill", "screenshot")


class _BrowserSession:
    """One live browser per scenario — the visual counterpart of _Server.

    With ``record_dir`` set, the context records a screencast; ``stop``
    then returns the finalized video path for evidence registration.
    ``viewport`` sizes the page (phone-width criteria); ``webauthn``
    attaches a CDP virtual authenticator (platform, user-verifying,
    presence auto-simulated) so passkey flows run headlessly.
    """

    def __init__(
        self,
        record_dir: Path | None = None,
        viewport: dict | None = None,
        webauthn: bool = False,
        timeout_ms: float = 10_000,
    ):
        try:
            from playwright.sync_api import sync_playwright
        except ImportError:
            raise DriveError(
                "browser steps need the playwright extra: "
                "pip install 'darkroom-ai[playwright]' "
                "(then: playwright install chromium)"
            ) from None
        self._playwright = sync_playwright().start()
        try:
            self.browser = self._playwright.chromium.launch(headless=True)
        except Exception as exc:
            self._playwright.stop()
            raise DriveError(
                f"could not launch chromium ({str(exc).splitlines()[0]}); "
                "run: playwright install chromium"
            ) from None
        options: dict = {"record_video_dir": str(record_dir)} if record_dir else {}
        if viewport:
            options["viewport"] = {
                "width": int(viewport.get("width", 1280)),
                "height": int(viewport.get("height", 720)),
            }
        self.context = self.browser.new_context(**options)
        self.page = self.context.new_page()
        self.page.set_default_timeout(timeout_ms)
        if webauthn:
            cdp = self.context.new_cdp_session(self.page)
            cdp.send("WebAuthn.enable")
            cdp.send(
                "WebAuthn.addVirtualAuthenticator",
                {
                    "options": {
                        "protocol": "ctap2",
                        "transport": "internal",
                        "hasResidentKey": True,
                        "hasUserVerification": True,
                        "isUserVerified": True,
                        "automaticPresenceSimulation": True,
                    }
                },
            )

    def stop(self) -> Path | None:
        """Tear down; returns the screencast path when recording."""
        video = None
        try:
            video = self.page.video
        except Exception:
            pass
        path: Path | None = None
        try:
            self.context.close()  # finalizes any recording
            if video is not None:
                path = Path(video.path())
        except Exception:
            path = None
        for closing in (self.browser.close, self._playwright.stop):
            try:
                closing()
            except Exception:
                pass
        return path


_EXPECT_WAIT_MS = 5_000


def _check_browser_expect(expect: dict, page, status: int | None) -> str | None:
    """Browser expectations wait (bounded) — pages settle asynchronously."""
    if "status" in expect and status != expect["status"]:
        return f"expected status {expect['status']}, got {status}"
    if "title_contains" in expect:
        title = page.title()
        if expect["title_contains"] not in title:
            return f"title '{title}' does not contain '{expect['title_contains']}'"
    if "url_contains" in expect and expect["url_contains"] not in page.url:
        return f"url '{page.url}' does not contain '{expect['url_contains']}'"
    if "body_contains" in expect:
        needle = expect["body_contains"]
        deadline = time.monotonic() + _EXPECT_WAIT_MS / 1000
        while needle not in page.content():
            if time.monotonic() >= deadline:
                return f"page body does not contain '{needle}'"
            page.wait_for_timeout(200)
    if "selector_visible" in expect:
        selector = expect["selector_visible"]
        try:
            page.locator(selector).first.wait_for(
                state="visible", timeout=_EXPECT_WAIT_MS
            )
        except Exception:
            return f"selector '{selector}' is not visible"
    return None


def _run_browser_step(
    step: dict, kind: str, ctx: Context, capture: EvidenceCapture, session
) -> str | None:
    if session is None:
        raise DriveError(f"browser step '{step.get('name')}' has no browser session")
    page = session.page
    status: int | None = None
    try:
        if kind == "goto":
            url = ctx.interpolate(step["url"])
            response = page.goto(url)
            status = response.status if response is not None else None
            capture.log(
                step.get("name", "goto"),
                {"action": "goto", "url": url, "status": status},
            )
        elif kind == "click":
            selector = ctx.interpolate(step["selector"])
            page.click(selector)
            capture.log(
                step.get("name", "click"),
                {"action": "click", "selector": selector},
            )
        elif kind == "fill":
            fields = {
                ctx.interpolate(sel): ctx.interpolate(str(value))
                for sel, value in step.get("fields", {}).items()
            }
            if not fields:
                raise DriveError(
                    f"fill step '{step.get('name')}' needs a fields table"
                )
            for selector, value in fields.items():
                page.fill(selector, value)
            capture.log(
                step.get("name", "fill"),
                {"action": "fill", "fields": fields},
            )
        elif kind == "screenshot":
            capture.screenshot(
                page,
                step.get("name", "screenshot"),
                full_page=bool(step.get("full_page", False)),
            )
        expect = ctx.interpolate_json(step.get("expect", {}))
        return _check_browser_expect(expect, page, status)
    except DriveError:
        raise
    except Exception as exc:  # a browser failure is a step failure, judgeable
        return f"{kind} failed: {str(exc).splitlines()[0]}"


# --- server lifecycle -----------------------------------------------------

def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _wait_healthy(base_url: str, timeout: float = 15.0) -> None:
    import urllib.error
    import urllib.request

    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            urllib.request.urlopen(base_url + "/", timeout=1)
            return
        except urllib.error.HTTPError:
            return  # any HTTP response means the server is up
        except (urllib.error.URLError, OSError):
            time.sleep(0.15)
    raise DriveError(f"server never became healthy at {base_url}")


class _Server:
    def __init__(self, adapter: ProjectAdapter, extra_vars: dict):
        self.port = _free_port()
        self.base_url = f"http://127.0.0.1:{self.port}"
        command = adapter.command("serve", port=self.port, **extra_vars)
        self.process = subprocess.Popen(
            ["/bin/sh", "-c", command],
            cwd=adapter.root,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )

    def stop(self) -> None:
        self.process.terminate()
        try:
            self.process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            self.process.kill()


def resolve_container_mode(mode: str, adapter: ProjectAdapter) -> bool:
    """Whether this drive runs the app in containers.

    ``off``: never. ``required``: containers or refuse — the hardened
    posture (a builder editing the adapter to drop the image cannot
    disable containment). ``auto``: containers when an app image is
    declared and the runtime is available.
    """
    if mode == "off":
        return False
    have_lib = True
    try:
        import testcontainers  # noqa: F401
    except ImportError:
        have_lib = False
    if mode == "required":
        if not adapter.app_image:
            raise DriveError(
                "containers mode is 'required' but the adapter declares no "
                "[environment] app_image"
            )
        if not have_lib:
            raise DriveError(
                "containers mode is 'required' but the containers extra is "
                "missing: pip install 'darkroom-ai[containers]'"
            )
        return True
    return bool(adapter.app_image) and have_lib


def _image_digest(image: str) -> str:
    result = subprocess.run(
        ["docker", "image", "inspect", "--format",
         "{{if .RepoDigests}}{{index .RepoDigests 0}}{{else}}{{.Id}}{{end}}",
         image],
        capture_output=True, text=True,
    )
    return result.stdout.strip() if result.returncode == 0 else "unknown"


class _ContainerEnvironment:
    """App + declared services in fresh containers on a private network."""

    def __init__(self, adapter: ProjectAdapter, serve_vars: dict):
        from testcontainers.core.container import DockerContainer
        from testcontainers.core.network import Network

        self.adapter = adapter
        self.network = Network().create()
        self.containers: dict[str, object] = {}

        substitutions = {str(k): str(v) for k, v in serve_vars.items()}
        for svc in adapter.services:
            container = DockerContainer(svc.image).with_network(self.network)
            container.with_network_aliases(svc.name)
            for key, value in svc.env:
                container.with_env(key, value)
            container.start()
            self.containers[svc.name] = container
            substitutions[f"{svc.name}.host"] = svc.name
            if svc.port is not None:
                substitutions[f"{svc.name}.port"] = str(svc.port)

        app = DockerContainer(adapter.app_image).with_network(self.network)
        app.with_network_aliases("app")
        app.with_exposed_ports(adapter.app_port)
        for key, template in adapter.app_env:
            value = template
            for name, sub in substitutions.items():
                value = value.replace("{" + name + "}", sub)
            app.with_env(key, value)
        app.start()
        self.containers["app"] = app
        host = app.get_container_host_ip()
        port = app.get_exposed_port(adapter.app_port)
        self.base_url = f"http://{host}:{port}"

    def digests(self) -> dict[str, str]:
        images = {"app": self.adapter.app_image}
        images.update({svc.name: svc.image for svc in self.adapter.services})
        return {name: _image_digest(image) for name, image in images.items()}

    def container_id(self, name: str) -> str | None:
        container = self.containers.get(name)
        wrapped = getattr(container, "_container", None)
        return getattr(wrapped, "id", None)

    def stop(self) -> None:
        for container in self.containers.values():
            try:
                container.stop()
            except Exception:
                pass
        try:
            self.network.remove()
        except Exception:
            pass


def _run_container_step(
    step: dict, environment, capture: EvidenceCapture
) -> str | None:
    if environment is None:
        raise DriveError(
            f"container step '{step.get('name')}' needs container mode"
        )
    action = step.get("action", "")
    service = step.get("service", "")
    if action not in ("stop", "start", "pause", "unpause"):
        raise DriveError(f"unknown container action '{action}'")
    container_id = environment.container_id(service)
    if container_id is None:
        raise DriveError(f"no container named '{service}' in this scenario")
    result = subprocess.run(
        ["docker", action, container_id], capture_output=True, text=True
    )
    capture.log(
        step.get("name", f"{action}_{service}"),
        {"action": action, "service": service, "ok": result.returncode == 0,
         "stderr": result.stderr.strip()},
    )
    return None if result.returncode == 0 else (
        f"docker {action} {service} failed: {result.stderr.strip()}"
    )


# --- the engine -----------------------------------------------------------

def load_drive(path: Path) -> dict:
    script = tomllib.loads(Path(path).read_text())
    if not script.get("scenario"):
        raise DriveError(f"{path.name}: drive script is missing 'scenario'")
    return script


def drive_scenario(
    adapter: ProjectAdapter, script: dict, containers: bool = False
) -> ScenarioResult:
    scenario = script["scenario"]
    result = ScenarioResult(scenario=scenario)
    steps = script.get("step", [])
    needs_browser = any(s.get("kind") in BROWSER_STEP_KINDS for s in steps)
    needs_server = (
        any(s.get("kind") == "http" for s in steps)
        or needs_browser
        or (containers and any(s.get("kind") == "container" for s in steps))
    )
    server = None
    environment = None
    browser = None
    capture = None
    ctx = Context()
    try:
        if needs_server:
            if containers:
                environment = _ContainerEnvironment(adapter, script.get("serve", {}))
                ctx.values["base_url"] = environment.base_url
                _wait_healthy(environment.base_url)
            else:
                server = _Server(adapter, script.get("serve", {}))
                ctx.values["base_url"] = server.base_url
                if script.get("browser", {}).get("webauthn"):
                    # WebAuthn RP IDs must be valid domains — an IP
                    # origin is rejected, so passkey scenarios address
                    # the same server as localhost
                    ctx.values["base_url"] = f"http://localhost:{server.port}"
                _wait_healthy(server.base_url)

        if needs_browser:
            record_dir = None
            if script.get("record"):
                import tempfile

                record_dir = Path(tempfile.mkdtemp(prefix="darkroom-screencast-"))
            browser_options = script.get("browser", {})
            browser = _BrowserSession(
                record_dir=record_dir,
                viewport=browser_options.get("viewport"),
                webauthn=bool(browser_options.get("webauthn")),
            )

        capture = EvidenceCapture(scenario)
        if environment is not None:
            capture.log("environment", {"images": environment.digests()})
        for step in script.get("step", []):
            kind = step.get("kind", "http")
            name = step.get("name", kind)
            try:
                if kind == "http":
                    _, failure = _run_http_step(step, ctx, capture)
                elif kind == "command":
                    _, failure = _run_command_step(step, ctx, capture)
                elif kind == "keygen":
                    _run_keygen_step(step, ctx)
                    failure = None
                elif kind == "assert":
                    failure = _run_assert_step(step, ctx, capture)
                elif kind == "container":
                    failure = _run_container_step(step, environment, capture)
                elif kind in BROWSER_STEP_KINDS:
                    failure = _run_browser_step(step, kind, ctx, capture, browser)
                elif kind == "wait":
                    time.sleep(float(step.get("seconds", 1)))
                    failure = None
                else:
                    raise DriveError(f"unknown step kind '{kind}'")
            except DriveError as exc:
                result.steps.append(StepResult(name, kind, ok=False, detail=str(exc)))
                break
            result.steps.append(
                StepResult(name, kind, ok=failure is None, detail=failure or "")
            )
            if failure is not None:
                break
    finally:
        if browser is not None:
            screencast = browser.stop()
            if (
                screencast is not None
                and screencast.exists()
                and capture is not None
            ):
                capture.video("screencast", screencast)
        if server is not None:
            server.stop()
        if environment is not None:
            environment.stop()
    return result


def drive(
    adapter: ProjectAdapter,
    drives_dir: Path,
    scenario: str | None = None,
    containers_mode: str = "auto",
) -> DriveReport:
    """Run drive scripts under an evidence run; returns the report.

    The caller owns run lifecycle policy; this function sets evidence
    mode, starts a run, executes each script (fresh server per
    scenario), and ends the run so the manifest is written.
    """
    from darkroom.run import end_run, start_run

    scripts = sorted(Path(drives_dir).glob(f"*{DRIVE_SUFFIX}"))
    if scenario is not None:
        scripts = [
            p for p in scripts if load_drive(p)["scenario"] == scenario
        ]
    if not scripts:
        raise DriveError(
            f"no drive scripts{f' for scenario {scenario!r}' if scenario else ''} "
            f"in {drives_dir}"
        )

    containers = resolve_container_mode(containers_mode, adapter)
    if containers and adapter.environment_build:
        built = subprocess.run(
            ["/bin/sh", "-c", adapter.environment_build],
            cwd=adapter.root, capture_output=True, text=True,
        )
        if built.returncode != 0:
            raise DriveError(
                "environment build failed: "
                + (built.stdout + built.stderr).strip()[-800:]
            )

    saved_env = {
        key: os.environ.get(key) for key in ("EVIDENCE_MODE", "EVIDENCE_DIR")
    }
    os.environ["EVIDENCE_MODE"] = "1"
    os.environ.setdefault(
        "EVIDENCE_DIR", str(adapter.resolve(adapter.evidence_dir))
    )
    run = start_run(project=adapter.name)
    report = DriveReport()
    try:
        for path in scripts:
            name = path.name[: -len(DRIVE_SUFFIX)]
            try:
                script = load_drive(path)
                report.results.append(
                    drive_scenario(adapter, script, containers=containers)
                )
            except DriveError as exc:
                # a scenario that cannot even boot is a failed scenario,
                # not a failed drive — later scenarios still run, and the
                # failure detail lands in the harness log for the builder
                report.results.append(
                    ScenarioResult(
                        scenario=name,
                        steps=[StepResult("boot", "serve", ok=False, detail=str(exc))],
                    )
                )
    finally:
        _write_harness_log(run, report)
        end_run()
        for key, value in saved_env.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
    return report


def _write_harness_log(run, report: DriveReport) -> None:
    """Harness diagnostics beside the manifest — builder-visible by design.

    Step names and failure details are spec-level information (the
    sanitized scenarios already state them); criteria and scores never
    appear here.
    """
    if run is None or not getattr(run, "evidence_mode", False):
        return
    lines = []
    for result in report.results:
        lines.append(f"scenario {result.scenario}: {'ok' if result.ok else 'FAILED'}")
        for step in result.steps:
            status = "ok" if step.ok else f"FAIL {step.detail}"
            lines.append(f"  {step.name} [{step.kind}] {status}")
    run.run_dir.mkdir(parents=True, exist_ok=True)
    (run.run_dir / "harness.log").write_text("\n".join(lines) + "\n")
