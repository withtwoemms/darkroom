"""HTTP transcript evidence producer.

Performs the request itself (stdlib urllib, keeping the core
dependency-free), so the transcript is harness-captured ground truth —
the evidence backbone for judging APIs. Sensitive headers are redacted
by default: transcripts are read by judges, galleries, and humans, and
credentials must never develop into evidence.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from datetime import datetime

from darkroom.model import EvidenceItem
from darkroom.producer import CaptureContext

REDACTED_HEADERS = frozenset(
    {"authorization", "cookie", "set-cookie", "proxy-authorization", "x-api-key"}
)


def _redact(headers: dict, redacted: frozenset) -> dict:
    return {
        name: ("[REDACTED]" if name.lower() in redacted else value)
        for name, value in headers.items()
    }


class HTTPTranscriptProducer:
    """Makes an HTTP request and captures the full exchange as JSON evidence."""

    kind = "http_transcript"
    mime = "application/json"

    def capture(
        self,
        ctx: CaptureContext,
        *,
        url: str,
        method: str = "GET",
        headers: dict | None = None,
        body: bytes | str | None = None,
        timeout: float = 30,
        max_body_bytes: int = 1_000_000,
        redact_headers: frozenset = REDACTED_HEADERS,
        **kwargs,
    ) -> EvidenceItem:
        request_headers = dict(headers or {})
        data = body.encode() if isinstance(body, str) else body
        request = urllib.request.Request(
            url, data=data, headers=request_headers, method=method
        )

        started = datetime.now()
        status: int | None = None
        response_headers: dict = {}
        raw = b""
        error: str | None = None
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                status = response.status
                response_headers = dict(response.headers)
                raw = response.read(max_body_bytes + 1)
        except urllib.error.HTTPError as exc:
            # non-2xx is still a response worth capturing
            status = exc.code
            response_headers = dict(exc.headers or {})
            raw = exc.read(max_body_bytes + 1)
        except (urllib.error.URLError, OSError) as exc:
            error = str(getattr(exc, "reason", exc))
        captured_at = datetime.now()
        duration_ms = int((captured_at - started).total_seconds() * 1000)

        body_truncated = len(raw) > max_body_bytes
        request_body = data.decode("utf-8", errors="replace") if data else None

        transcript = {
            "captured_at": captured_at.isoformat(),
            "request": {
                "method": method,
                "url": url,
                "headers": _redact(request_headers, redact_headers),
                "body": request_body,
            },
            "response": {
                "status": status,
                "headers": _redact(response_headers, redact_headers),
                "body": raw[:max_body_bytes].decode("utf-8", errors="replace"),
                "body_truncated": body_truncated,
            },
            "duration_ms": duration_ms,
            "error": error,
        }

        rel_path = ctx.make_path(ctx.step, "json")
        abs_path = ctx.run_dir / rel_path
        abs_path.parent.mkdir(parents=True, exist_ok=True)
        abs_path.write_text(json.dumps(transcript, indent=2, default=str))

        metadata: dict = {
            "method": method,
            "url": url,
            "status": status,
            "duration_ms": duration_ms,
        }
        if error is not None:
            metadata["error"] = error
        return EvidenceItem(
            kind=self.kind,
            mime=self.mime,
            path=rel_path,
            scenario=ctx.scenario,
            step=ctx.step,
            captured_at=captured_at,
            metadata=metadata,
        )
