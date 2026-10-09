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
An http step with ``session = "browser"`` sends that session's cookies,
acting as whoever the browser signed in; ``follow_redirects = false``
records a 3xx itself (status, Location) instead of what it led to.

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
import signal
import socket
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from types import SimpleNamespace

if sys.version_info >= (3, 11):
    pass
else:  # pragma: no cover - exercised only on 3.10
    pass

from darkroom.adapter import ProjectAdapter
from darkroom.capture import EvidenceCapture


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


_PATH_SEGMENT = re.compile(r"^([^\[\]]*)((?:\[-?\d+\])*)$")


def _dot_path(payload, path: str):
    """Walk ``$.field.sub`` into a JSON body; a segment may carry array
    indexes, ``$.items[0].id`` or ``$.receipts[-1].who`` (drive-scripts 1.7)."""
    if not path.startswith("$."):
        raise DriveError(f"save paths use '$.field.sub' form, got '{path}'")
    current = payload
    for segment in path[2:].split("."):
        match = _PATH_SEGMENT.match(segment)
        if match is None:
            raise DriveError(f"path '{path}' has a malformed segment '{segment}'")
        key, indexes = match.group(1), match.group(2)
        if key:
            if not isinstance(current, dict) or key not in current:
                raise DriveError(f"path '{path}' not found in response body")
            current = current[key]
        for index in re.findall(r"\[(-?\d+)\]", indexes):
            position = int(index)
            if not isinstance(current, list) or not -len(current) <= position < len(current):
                raise DriveError(f"path '{path}' not found in response body")
            current = current[position]
    return current


# --- step execution -------------------------------------------------------

def _evaluate_expect(expect: dict, transcript: dict) -> tuple[str | None, dict]:
    """Evaluate expectations over a transcript: (failure detail or None,
    what was found for each checked key). The found table is the witness —
    an enforced check the judge cannot see is not evidence."""
    response = transcript.get("response", transcript)
    status = response.get("status", transcript.get("exit_code"))
    found: dict = {}
    if "status" in expect or "status_in" in expect:
        found["status"] = status
    if "status" in expect and status != expect["status"]:
        return f"expected status {expect['status']}, got {status}", found
    if "status_in" in expect and status not in expect["status_in"]:
        return f"expected status in {expect['status_in']}, got {status}", found
    if "exit_code" in expect:
        found["exit_code"] = transcript.get("exit_code")
        if transcript.get("exit_code") != expect["exit_code"]:
            return (
                f"expected exit_code {expect['exit_code']}, got {transcript.get('exit_code')}",
                found,
            )
    if "body_contains" in expect:
        body = response.get("body", transcript.get("stdout", ""))
        found["body_contains"] = expect["body_contains"] in body
        if not found["body_contains"]:
            return f"body does not contain '{expect['body_contains']}'", found
    if "location_contains" in expect:
        location = _header(response.get("headers", {}), "location")
        found["location"] = location
        if location is None or expect["location_contains"] not in location:
            return (
                f"expected Location containing '{expect['location_contains']}', "
                f"got {location!r}",
                found,
            )
    return None, found


def _header(headers: dict, name: str) -> str | None:
    for key, value in headers.items():
        if key.lower() == name:
            return value
    return None


def _check_expect(expect: dict, transcript: dict) -> str | None:
    """Return a failure detail, or None if all expectations hold."""
    return _evaluate_expect(expect, transcript)[0]


def _log_expect_witness(
    capture: EvidenceCapture, name: str, expect: dict, found: dict, detail: str | None
) -> None:
    """Record what an expectation checked and found (drive-scripts 1.4)."""
    if not expect:
        return
    capture.log(f"{name}.expect", {"expect": expect, "found": found, "ok": detail is None})


def _http_request_body(step: dict, ctx: Context, headers: dict) -> str | None:
    """`json` is serialized (and typed); `body` is sent verbatim, untyped —
    the raw-bytes seam that exact-payload scenarios (webhook HMACs) need."""
    if "json" in step and "body" in step:
        raise DriveError(f"step '{step.get('name')}': give json or body, not both")
    if "json" in step:
        headers.setdefault("Content-Type", "application/json")
        return json.dumps(ctx.interpolate_json(step["json"]))
    if "body" in step:
        return ctx.interpolate(str(step["body"]))
    return None


def _browser_cookie_header(session, url: str) -> str | None:
    """The browser's cookies for ``url``, as one Cookie header — how an http
    step acts as whoever the browser signed in (drive-scripts 1.5)."""
    cookies = session.context.cookies([url])
    if not cookies:
        return None
    return "; ".join(f"{c['name']}={c['value']}" for c in cookies)


def _run_http_step(
    step: dict, ctx: Context, capture: EvidenceCapture, browser=None
) -> tuple[dict, str | None]:
    url = ctx.interpolate(step["url"])
    method = step.get("method", "GET")
    headers = ctx.interpolate_json(step.get("headers", {}))
    body = _http_request_body(step, ctx, headers)
    if step.get("session") == "browser":
        if browser is None:
            raise DriveError(
                f"http step '{step['name']}' asks for the browser session, "
                "but the scenario has no browser"
            )
        if not any(name.lower() == "cookie" for name in headers):
            cookie = _browser_cookie_header(browser, url)
            if cookie is not None:
                headers["Cookie"] = cookie
    elif "session" in step:
        raise DriveError(
            f"http step '{step['name']}': session must be \"browser\" if given"
        )
    path = capture.http(
        step["name"],
        url,
        method=method,
        headers=headers,
        body=body,
        follow_redirects=bool(step.get("follow_redirects", True)),
    )
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
    detail, found = _evaluate_expect(expect, transcript)
    _log_expect_witness(capture, step["name"], expect, found, detail)
    return transcript, detail


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
    detail, found = _evaluate_expect(expect, transcript)
    _log_expect_witness(capture, step["name"], expect, found, detail)
    return transcript, detail


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
    presence auto-simulated) so passkey flows run headlessly; ``prf``
    (default on) gives it the PRF extension, so a passkey can also
    yield per-salt secrets — off, it models an authenticator without
    it, for exams of the fallback road.
    """

    def __init__(
        self,
        record_dir: Path | None = None,
        viewport: dict | None = None,
        webauthn: bool = False,
        prf: bool = True,
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
            options = {
                "protocol": "ctap2",
                "transport": "internal",
                "hasResidentKey": True,
                "hasUserVerification": True,
                "isUserVerified": True,
                "automaticPresenceSimulation": True,
            }
            if prf:
                # the PRF extension rides CTAP 2.1's hmac-secret
                options["ctap2Version"] = "ctap2_1"
                options["hasPrf"] = True
            cdp.send("WebAuthn.addVirtualAuthenticator", {"options": options})

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


def _wait_until(page, probe) -> bool:
    """Poll a zero-arg probe until true or the shared deadline passes. A
    probe that raises — ``page.content()`` or ``page.title()`` while a
    navigation is between start and commit — counts as not yet, never as
    failure: the redirect a click triggers is what the expectation is
    waiting for."""
    deadline = time.monotonic() + _EXPECT_WAIT_MS / 1000
    while True:
        try:
            if probe():
                return True
        except Exception:
            pass
        if time.monotonic() >= deadline:
            return False
        page.wait_for_timeout(200)


def _settled(read, fallback=""):
    """Read a page property for the witness; mid-navigation, the fallback."""
    try:
        return read()
    except Exception:
        return fallback


def _evaluate_browser_expect(
    expect: dict, page, status: int | None
) -> tuple[str | None, dict]:
    """Browser expectations wait (bounded) — pages settle asynchronously,
    and navigations triggered by page script land after the click returns.
    Returns (failure detail or None, what was found): the found table is
    the witness, so a settled check is evidence and not merely a gate."""
    found: dict = {}
    if "status" in expect:
        found["status"] = status
        if status != expect["status"]:
            return f"expected status {expect['status']}, got {status}", found
    if "title_contains" in expect:
        needle = expect["title_contains"]
        ok = _wait_until(page, lambda: needle in page.title())
        found["title"] = _settled(page.title)
        if not ok:
            return f"title '{found['title']}' does not contain '{needle}'", found
    if "url_contains" in expect:
        needle = expect["url_contains"]
        ok = _wait_until(page, lambda: needle in page.url)
        found["url"] = page.url
        if not ok:
            return f"url '{page.url}' does not contain '{needle}'", found
    if "body_contains" in expect:
        needle = expect["body_contains"]
        found["body_contains"] = _wait_until(page, lambda: needle in page.content())
        if not found["body_contains"]:
            return f"page body does not contain '{needle}'", found
    if "selector_visible" in expect:
        selector = expect["selector_visible"]
        try:
            page.locator(selector).first.wait_for(
                state="visible", timeout=_EXPECT_WAIT_MS
            )
            found["selector_visible"] = True
        except Exception:
            found["selector_visible"] = False
            return f"selector '{selector}' is not visible", found
    return None, found


def _check_browser_expect(expect: dict, page, status: int | None) -> str | None:
    return _evaluate_browser_expect(expect, page, status)[0]


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
        detail, found = _evaluate_browser_expect(expect, page, status)
        _log_expect_witness(capture, step.get("name", kind), expect, found, detail)
        return detail
    except DriveError:
        raise
    except Exception as exc:  # a browser failure is a step failure, judgeable
        return f"{kind} failed: {str(exc).splitlines()[0]}"


# --- server lifecycle -----------------------------------------------------

def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _wait_healthy(base_url: str, timeout: float = 30.0) -> None:
    # an app that runs migrations at import against a service the engine
    # only TCP-probed can take longer than the old 15s to answer its first
    # request on a loaded machine; the bound stays, the budget doubles
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


def _wait_tcp(host: str, port: int, timeout: float = 30.0) -> None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with socket.create_connection((host, port), timeout=1):
                return
        except OSError:
            time.sleep(0.25)
    raise DriveError(f"service on {host}:{port} never accepted a connection")


def _wait_http(url: str, timeout: float = 90.0) -> None:
    """Poll until the URL answers any HTTP response — a service that has
    opened its port but is still starting closes the connection instead.
    The bound is generous because it only ever costs time on failure: a
    JVM store on a loaded machine has taken a minute to serve its first
    request."""
    import urllib.error
    import urllib.request

    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            urllib.request.urlopen(url, timeout=2)
            return
        except urllib.error.HTTPError:
            return
        except (urllib.error.URLError, OSError):
            time.sleep(0.25)
    raise DriveError(f"service at {url} never answered an HTTP request")


def _listeners(port: int) -> list[int]:
    """PIDs listening on a TCP port (lsof; an absent lsof lists nothing)."""
    try:
        result = subprocess.run(
            ["lsof", "-ti", f"tcp:{port}", "-sTCP:LISTEN"],
            capture_output=True, text=True, timeout=10,
        )
    except (OSError, subprocess.TimeoutExpired):
        return []
    pids = []
    for line in result.stdout.split():
        try:
            pid = int(line)
        except ValueError:
            continue
        if pid != os.getpid():
            pids.append(pid)
    return pids


def _sweep_port(port: int) -> list[int]:
    """Kill whatever still listens on a scenario's port after its server
    tree was signalled, and return the PIDs swept. The port was handed
    out by the engine for this scenario alone, so a listener on it is
    this scenario's leftover — typically an app an exposure restarted
    outside the engine's process group."""
    # the common case — the group stop freed the port — must cost nothing;
    # lsof scans every process on the host and takes seconds on macOS
    with socket.socket() as probe:
        probe.settimeout(0.5)
        if probe.connect_ex(("127.0.0.1", port)) != 0:
            return []
    swept = []
    for pid in _listeners(port):
        try:
            os.kill(pid, signal.SIGKILL)
            swept.append(pid)
        except (ProcessLookupError, PermissionError):
            pass
    return swept


COLIMA_SOCKET_MARK = "/.colima/"
RYUK_SOCKET_OVERRIDE = "TESTCONTAINERS_DOCKER_SOCKET_OVERRIDE"
VM_DOCKER_SOCKET = "/var/run/docker.sock"


def docker_host_setting() -> str:
    """The docker host testcontainers will use: ``DOCKER_HOST``, else
    ``docker.host`` from ``~/.testcontainers.properties``, else empty."""
    host = os.environ.get("DOCKER_HOST", "")
    if host:
        return host
    properties = Path.home() / ".testcontainers.properties"
    try:
        for line in properties.read_text().splitlines():
            key, sep, value = line.partition("=")
            if sep and key.strip() == "docker.host":
                return value.strip()
    except OSError:
        pass
    return ""


def colima_socket_override_needed() -> bool:
    """Under colima the host's docker socket lives at ``~/.colima/…``, a
    path that does not exist inside the VM — so Ryuk, which mounts the
    socket by that path, fails to start (``mkdir …/docker.sock: operation
    not supported``) and takes every service boot down with it. The fix
    is one environment variable naming the socket as the VM sees it."""
    if os.environ.get(RYUK_SOCKET_OVERRIDE):
        return False
    if os.environ.get("TESTCONTAINERS_RYUK_DISABLED", "").lower() in ("1", "true", "yes"):
        return False
    return COLIMA_SOCKET_MARK in docker_host_setting()


def prepare_container_runtime() -> bool:
    """Set the colima socket override when it is needed and unset. Called
    before the first container of a run; returns whether it acted."""
    if not colima_socket_override_needed():
        return False
    os.environ[RYUK_SOCKET_OVERRIDE] = VM_DOCKER_SOCKET
    return True


class _Services:
    """The adapter's declared services beside a process-mode app: a fresh
    Postgres per scenario while ``make serve`` still boots the app itself.
    Each service's mapped host address reaches the serve command as
    ``{name.host}`` / ``{name.port}``, and its image digest is logged with
    the evidence — the same record container mode keeps.
    """

    def __init__(
        self, adapter: ProjectAdapter, container_cls=None, wait=_wait_tcp, ready=_wait_http
    ):
        if container_cls is None:
            try:
                from testcontainers.core.container import DockerContainer as container_cls
            except ImportError:
                raise DriveError(
                    "declared [[environment.services]] need the containers "
                    "extra: pip install 'darkroom-ai[containers]'"
                ) from None
            prepare_container_runtime()
        self.adapter = adapter
        self.containers: dict[str, object] = {}
        self.namespaces: dict[str, SimpleNamespace] = {}
        try:
            for svc in adapter.services:
                container = container_cls(svc.image)
                for key, value in svc.env:
                    container.with_env(key, value)
                if svc.command:
                    container.with_command(list(svc.command))
                if svc.port is not None:
                    container.with_exposed_ports(svc.port)
                container.start()
                self.containers[svc.name] = container
                host = container.get_container_host_ip()
                port = None
                if svc.port is not None:
                    port = int(container.get_exposed_port(svc.port))
                    wait(host, port)
                    if svc.ready_path:
                        ready(f"http://{host}:{port}{svc.ready_path}")
                self.namespaces[svc.name] = SimpleNamespace(host=host, port=port)
        except Exception:
            self.stop()
            raise

    def digests(self) -> dict[str, str]:
        return {svc.name: _image_digest(svc.image) for svc in self.adapter.services}

    def stop(self) -> None:
        for container in self.containers.values():
            try:
                container.stop()
            except Exception:
                pass
        self.containers = {}


def _serve_env(adapter: ProjectAdapter, port: int, substitutions: dict) -> dict[str, str]:
    """[serve.env] templates resolved the way the serve command is:
    {port}, the serve vars, and declared services' {name.host}/{name.port}."""
    # service namespaces stay objects: format() reads {postgres.host} as
    # an attribute, exactly as the serve command's template does
    values: dict = {"port": str(port)}
    for key, value in substitutions.items():
        if isinstance(value, SimpleNamespace):
            values[str(key)] = SimpleNamespace(
                host=str(value.host), port="" if value.port is None else str(value.port)
            )
        else:
            values[str(key)] = str(value)
    resolved: dict[str, str] = {}
    for name, template in adapter.serve_env:
        try:
            resolved[name] = template.format(**values)
        except (KeyError, AttributeError) as exc:
            missing = exc.args[0] if isinstance(exc, KeyError) else template
            raise DriveError(
                f"[serve.env] {name} needs a value for {{{missing}}}"
            ) from None
    return resolved


class _Server:
    def __init__(
        self, adapter: ProjectAdapter, extra_vars: dict, services: _Services | None = None
    ):
        self.port = _free_port()
        self.base_url = f"http://127.0.0.1:{self.port}"
        self.services = services
        substitutions = dict(extra_vars)
        if services is not None:
            substitutions.update(services.namespaces)
        self.command = adapter.command("serve", port=self.port, **substitutions)
        # [serve.env]: the engine sets the served process's environment
        # directly, so a tenant needs no Makefile hop per knob
        self.env = dict(os.environ)
        self.env.update(_serve_env(adapter, self.port, substitutions))
        # its own session, so stop() can signal the whole tree: a serve
        # command is usually `make serve` -> `uv run` -> the server, and
        # terminating the shell alone orphaned the server every scenario
        self.process = subprocess.Popen(
            ["/bin/sh", "-c", self.command],
            cwd=adapter.root,
            env=self.env,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )

    def _signal_tree(self, sig: int) -> None:
        # only while the leader shell lives: once it has exited (a restart
        # scenario kills its own server tree) the pgid may be gone or, on
        # macOS, recycled by a process we may not signal — neither is ours
        if self.process.poll() is not None:
            return
        try:
            os.killpg(self.process.pid, sig)
        except (ProcessLookupError, PermissionError):
            pass

    def stop(self) -> None:
        self._signal_tree(signal.SIGTERM)
        try:
            self.process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            self._signal_tree(signal.SIGKILL)
            try:
                self.process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                pass
        # whatever still listens on the scenario's port is this scenario's
        # — a server an exposure restarted itself (a restart scenario's
        # `nohup uvicorn …`) lives outside the group the engine signalled
        _sweep_port(self.port)
        if self.services is not None:
            self.services.stop()


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

        prepare_container_runtime()
        self.adapter = adapter
        self.network = Network().create()
        self.containers: dict[str, object] = {}

        substitutions = {str(k): str(v) for k, v in serve_vars.items()}
        for svc in adapter.services:
            container = DockerContainer(svc.image).with_network(self.network)
            container.with_network_aliases(svc.name)
            for key, value in svc.env:
                container.with_env(key, value)
            if svc.command:
                container.with_command(list(svc.command))
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

def drive_scenario(
    adapter: ProjectAdapter,
    script: dict,
    containers: bool = False,
    provenance: dict | None = None,
) -> ScenarioResult:
    scenario = script["scenario"]
    result = ScenarioResult(scenario=scenario)
    steps = script.get("step", [])
    needs_browser = any(
        s.get("kind") in BROWSER_STEP_KINDS or s.get("session") == "browser"
        for s in steps
    )
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
                environment = _ContainerEnvironment(
                    adapter, adapter.serve_vars(script.get("serve"))
                )
                ctx.values["base_url"] = environment.base_url
                _wait_healthy(environment.base_url)
            else:
                services = _Services(adapter) if adapter.services else None
                server = _Server(
                    adapter, adapter.serve_vars(script.get("serve")), services=services
                )
                ctx.values["base_url"] = server.base_url
                if services is not None:
                    # a drive that re-boots the app in place (a restart
                    # scenario) must address the same services the engine
                    # started, so their mapped addresses are drive values too
                    for svc_name, ns in services.namespaces.items():
                        ctx.values[f"{svc_name}.host"] = ns.host
                        ctx.values[f"{svc_name}.port"] = "" if ns.port is None else str(ns.port)
                if adapter.browser_options(script.get("browser")).get("webauthn"):
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
            browser_options = adapter.browser_options(script.get("browser"))
            browser = _BrowserSession(
                record_dir=record_dir,
                viewport=browser_options.get("viewport"),
                webauthn=bool(browser_options.get("webauthn")),
                prf=bool(browser_options.get("prf", True)),
            )

        capture = EvidenceCapture(scenario)
        if provenance and capture.run is not None:
            capture.run.record_provenance(scenario, provenance)
        if environment is not None:
            capture.log("environment", {"images": environment.digests()})
        elif server is not None and server.services is not None:
            capture.log("environment", {"images": server.services.digests()})
        for step in script.get("step", []):
            kind = step.get("kind", "http")
            name = step.get("name", kind)
            try:
                if kind == "http":
                    _, failure = _run_http_step(step, ctx, capture, browser)
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


def backdrops_file(adapter: ProjectAdapter, drives_dir: Path) -> Path | None:
    from darkroom.backdrops import backdrops_for

    return backdrops_for(adapter.name, drives_dir)


def drive(
    adapter: ProjectAdapter,
    drives_dir: Path,
    scenario: str | None = None,
    containers_mode: str = "auto",
) -> DriveReport:
    """Run every proof's exposure under an evidence run; returns the report.

    The caller owns run lifecycle policy; this function sets evidence
    mode, starts a run, executes each exposure (fresh server per
    scenario), and ends the run so the manifest is written.
    """
    from darkroom.backdrops import BackdropError, load_backdrops
    from darkroom.proof import ProofError, exposure, load_proof, proof_dirs
    from darkroom.proof import provenance as proof_provenance
    from darkroom.run import end_run, start_run

    try:
        backdrops = load_backdrops(backdrops_file(adapter, Path(drives_dir)))
    except BackdropError as exc:
        raise DriveError(str(exc)) from None

    def _load(path: Path) -> tuple[dict, dict]:
        """The runnable script and what the manifest records about it."""
        try:
            proof = load_proof(path)
            return exposure(proof, backdrops), proof_provenance(path, proof)
        except ProofError as exc:
            raise DriveError(str(exc)) from None

    scripts = proof_dirs(drives_dir)
    if not scripts and any(Path(drives_dir).glob("*.drive.toml")):
        raise DriveError(
            f"{drives_dir} holds pre-0.20 drive scripts and no proofs; "
            "run `darkroom migrate` to carry them into proofs/"
        )
    if scenario is not None:
        scripts = [p for p in scripts if p.name == scenario]
    if not scripts:
        raise DriveError(
            f"no proofs{f' for scenario {scenario!r}' if scenario else ''} in {drives_dir}"
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
            name = path.name
            try:
                script, provenance = _load(path)
                report.results.append(
                    drive_scenario(
                        adapter, script, containers=containers, provenance=provenance
                    )
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
        prune_runs(adapter)
        for key, value in saved_env.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
    return report


def prune_runs(adapter: ProjectAdapter) -> list[Path]:
    """Keep the newest ``[evidence] keep_runs`` run directories plus every
    run a gate cites; remove the rest. Nothing is pruned unless the
    adapter sets ``keep_runs``. Returns the directories removed."""
    keep = adapter.keep_runs
    if keep is None:
        return []
    runs_dir = adapter.resolve(adapter.evidence_dir) / "runs"
    if not runs_dir.is_dir():
        return []
    cited: set[str] = set()
    from darkroom.homedir import gates_file

    gates = gates_file(adapter)
    try:
        data = json.loads(gates.read_text())
        cited = {str(p.get("run_id")) for p in data.get("peaks", []) if p.get("run_id")}
    except (OSError, ValueError):
        pass
    runs = sorted((p for p in runs_dir.iterdir() if p.is_dir()), key=lambda p: p.name)
    removed = []
    for path in runs[: max(0, len(runs) - keep)]:
        if path.name in cited:
            continue
        import shutil

        shutil.rmtree(path, ignore_errors=True)
        removed.append(path)
    return removed


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
