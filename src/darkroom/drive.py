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

        return _PLACEHOLDER.sub(_value, text)

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


# --- the engine -----------------------------------------------------------

def load_drive(path: Path) -> dict:
    script = tomllib.loads(Path(path).read_text())
    if not script.get("scenario"):
        raise DriveError(f"{path.name}: drive script is missing 'scenario'")
    return script


def drive_scenario(adapter: ProjectAdapter, script: dict) -> ScenarioResult:
    scenario = script["scenario"]
    result = ScenarioResult(scenario=scenario)
    needs_server = any(s.get("kind") == "http" for s in script.get("step", []))
    server = None
    ctx = Context()
    try:
        if needs_server:
            server = _Server(adapter, script.get("serve", {}))
            ctx.values["base_url"] = server.base_url
            _wait_healthy(server.base_url)

        capture = EvidenceCapture(scenario)
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
        if server is not None:
            server.stop()
    return result


def drive(
    adapter: ProjectAdapter,
    drives_dir: Path,
    scenario: str | None = None,
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

    saved_env = {
        key: os.environ.get(key) for key in ("EVIDENCE_MODE", "EVIDENCE_DIR")
    }
    os.environ["EVIDENCE_MODE"] = "1"
    os.environ.setdefault(
        "EVIDENCE_DIR", str(adapter.resolve(adapter.evidence_dir))
    )
    start_run(project=adapter.name)
    report = DriveReport()
    try:
        for path in scripts:
            report.results.append(drive_scenario(adapter, load_drive(path)))
    finally:
        end_run()
        for key, value in saved_env.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
    return report
