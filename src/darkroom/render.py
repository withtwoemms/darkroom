"""Judge renderers: the consuming mirror of the producer protocol.

A renderer turns an :class:`EvidenceItem` into judge-consumable form —
readable text plus any media files the invoking harness should attach.
Renderers are deliberately API-agnostic: no model-provider types here,
just text and paths. Dispatch is by ``item.kind`` through a registry, so
third-party evidence kinds plug in the same way third-party producers
do. Rendering never raises on missing or malformed evidence files — the
defect is stated in the rendered text (and `darkroom verify` exists to
catch it mechanically); a judge should see that evidence is broken, not
crash the harness.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol, runtime_checkable

from darkroom.model import EvidenceItem, ScenarioBundle

DEFAULT_MAX_CHARS = 4000


@dataclass(frozen=True)
class RenderedEvidence:
    item: EvidenceItem
    text: str
    attachments: tuple[Path, ...] = ()


@runtime_checkable
class JudgeRenderer(Protocol):
    kinds: tuple[str, ...]

    def render(self, item: EvidenceItem, base_dir: Path) -> RenderedEvidence: ...


def _resolve(item: EvidenceItem, base_dir: Path) -> Path:
    return item.path if item.path.is_absolute() else base_dir / item.path


def _clip(text: str, max_chars: int) -> str:
    if len(text) <= max_chars:
        return text
    return text[:max_chars] + "\n... [truncated]"


def _meta_line(item: EvidenceItem) -> str:
    if not item.metadata:
        return ""
    pairs = ", ".join(f"{k}={v}" for k, v in item.metadata.items())
    return f" ({pairs})"


class ImageRenderer:
    kinds = ("screenshot", "screenshot_element")

    def render(self, item: EvidenceItem, base_dir: Path) -> RenderedEvidence:
        path = _resolve(item, base_dir)
        if not path.exists():
            return RenderedEvidence(
                item, f"[{item.kind}] step '{item.step}': image file missing"
            )
        text = f"[{item.kind}] step '{item.step}'{_meta_line(item)} — image attached"
        return RenderedEvidence(item, text, attachments=(path,))


class TranscriptRenderer:
    kinds = ("command_transcript", "http_transcript")

    def __init__(self, max_chars: int = DEFAULT_MAX_CHARS):
        self.max_chars = max_chars

    def render(self, item: EvidenceItem, base_dir: Path) -> RenderedEvidence:
        path = _resolve(item, base_dir)
        try:
            transcript = json.loads(path.read_text())
        except (OSError, ValueError):
            return RenderedEvidence(
                item, f"[{item.kind}] step '{item.step}': transcript unreadable"
            )
        if item.kind == "command_transcript":
            text = self._command_text(item, transcript)
        else:
            text = self._http_text(item, transcript)
        return RenderedEvidence(item, text)

    def _command_text(self, item: EvidenceItem, t: dict) -> str:
        argv = " ".join(t.get("argv", []))
        lines = [
            f"[command] step '{item.step}': $ {argv}",
            f"exit_code={t.get('exit_code')} duration_ms={t.get('duration_ms')}"
            + (" TIMED OUT" if t.get("timed_out") else ""),
        ]
        for stream in ("stdout", "stderr"):
            content = t.get(stream, "")
            if content:
                flag = " [truncated at capture]" if t.get(f"{stream}_truncated") else ""
                lines.append(f"--- {stream}{flag} ---")
                lines.append(_clip(content, self.max_chars))
        return "\n".join(lines)

    def _http_text(self, item: EvidenceItem, t: dict) -> str:
        request = t.get("request", {})
        response = t.get("response", {})
        lines = [
            f"[http] step '{item.step}': {request.get('method')} {request.get('url')}"
            f" -> {response.get('status')} ({t.get('duration_ms')}ms)"
        ]
        if t.get("error"):
            lines.append(f"error: {t['error']}")
        if request.get("body"):
            lines.append("--- request body ---")
            lines.append(_clip(str(request["body"]), self.max_chars))
        body = response.get("body", "")
        if body:
            flag = " [truncated at capture]" if response.get("body_truncated") else ""
            lines.append(f"--- response body{flag} ---")
            lines.append(_clip(body, self.max_chars))
        return "\n".join(lines)


class StructuredRenderer:
    kinds = ("log",)

    def __init__(self, max_chars: int = DEFAULT_MAX_CHARS):
        self.max_chars = max_chars

    def render(self, item: EvidenceItem, base_dir: Path) -> RenderedEvidence:
        path = _resolve(item, base_dir)
        try:
            content = json.dumps(json.loads(path.read_text()), indent=2)
        except (OSError, ValueError):
            return RenderedEvidence(
                item, f"[log] step '{item.step}': log unreadable"
            )
        text = f"[log] step '{item.step}':\n{_clip(content, self.max_chars)}"
        return RenderedEvidence(item, text)


class FileRenderer:
    kinds = ("file_snapshot", "diff")

    def __init__(self, max_chars: int = DEFAULT_MAX_CHARS, max_inline_bytes: int = 8192):
        self.max_chars = max_chars
        self.max_inline_bytes = max_inline_bytes

    def render(self, item: EvidenceItem, base_dir: Path) -> RenderedEvidence:
        path = _resolve(item, base_dir)
        if not path.exists():
            return RenderedEvidence(
                item, f"[{item.kind}] step '{item.step}': file missing"
            )
        if item.kind == "diff":
            content = path.read_text(errors="replace")
            header = (
                f"[diff] step '{item.step}'{_meta_line(item)}:"
                if content
                else f"[diff] step '{item.step}': no differences"
            )
            text = f"{header}\n{_clip(content, self.max_chars)}" if content else header
            return RenderedEvidence(item, text)

        summary = f"[file_snapshot] step '{item.step}'{_meta_line(item)}"
        texty = item.mime.startswith("text/") or item.mime == "application/json"
        if texty and path.stat().st_size <= self.max_inline_bytes:
            content = path.read_text(errors="replace")
            return RenderedEvidence(
                item, f"{summary}\n{_clip(content, self.max_chars)}"
            )
        return RenderedEvidence(item, f"{summary} — content not inlined")


class VideoRenderer:
    kinds = ("video",)

    def render(self, item: EvidenceItem, base_dir: Path) -> RenderedEvidence:
        path = _resolve(item, base_dir)
        if not path.exists():
            return RenderedEvidence(
                item, f"[video] step '{item.step}': video file missing"
            )
        text = (
            f"[video] step '{item.step}'{_meta_line(item)} — recording at "
            f"{item.path.as_posix()} (not viewable inline)"
        )
        return RenderedEvidence(item, text, attachments=(path,))


class RendererRegistry:
    def __init__(self):
        self._by_kind: dict[str, JudgeRenderer] = {}

    def register(self, renderer: JudgeRenderer) -> None:
        for kind in renderer.kinds:
            self._by_kind[kind] = renderer

    def renderer_for(self, kind: str) -> JudgeRenderer | None:
        return self._by_kind.get(kind)

    def render(self, item: EvidenceItem, base_dir: Path) -> RenderedEvidence:
        renderer = self.renderer_for(item.kind)
        if renderer is None:
            return RenderedEvidence(
                item,
                f"[{item.kind}] step '{item.step}'{_meta_line(item)} — "
                f"no renderer for this kind; file at {item.path.as_posix()}",
            )
        return renderer.render(item, base_dir)


def default_registry() -> RendererRegistry:
    registry = RendererRegistry()
    for renderer in (
        ImageRenderer(),
        TranscriptRenderer(),
        StructuredRenderer(),
        FileRenderer(),
        VideoRenderer(),
    ):
        registry.register(renderer)
    return registry


def render_scenario(
    bundle: ScenarioBundle,
    base_dir: Path,
    registry: RendererRegistry | None = None,
) -> list[RenderedEvidence]:
    """Render every item in a scenario, in capture order."""
    registry = registry or default_registry()
    return [registry.render(item, base_dir) for item in bundle.items]
