"""Screenshot producers using Playwright."""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from darkroom.model import EvidenceItem
from darkroom.producer import CaptureContext

if TYPE_CHECKING:
    from playwright.sync_api import Page


class ScreenshotProducer:
    """Captures full-page or viewport screenshots via Playwright."""

    kind = "screenshot"
    mime = "image/png"

    def capture(
        self,
        ctx: CaptureContext,
        *,
        page: Page,
        full_page: bool = False,
        **kwargs,
    ) -> EvidenceItem:
        rel_path = ctx.make_path(ctx.step, "png")
        abs_path = ctx.run_dir / rel_path
        abs_path.parent.mkdir(parents=True, exist_ok=True)
        page.screenshot(path=str(abs_path), full_page=full_page)
        metadata: dict = {"full_page": full_page}
        viewport = getattr(page, "viewport_size", None)
        if isinstance(viewport, dict):
            metadata["viewport"] = f"{viewport['width']}x{viewport['height']}"
        return EvidenceItem(
            kind=self.kind,
            mime=self.mime,
            path=rel_path,
            scenario=ctx.scenario,
            step=ctx.step,
            captured_at=datetime.now(),
            metadata=metadata,
        )


class ElementScreenshotProducer:
    """Captures screenshots of a specific element via Playwright."""

    kind = "screenshot_element"
    mime = "image/png"

    def capture(
        self,
        ctx: CaptureContext,
        *,
        page: Page,
        selector: str,
        **kwargs,
    ) -> EvidenceItem | None:
        """Screenshot a specific element. Returns None if element not found."""
        element = page.query_selector(selector)
        if element is None:
            return None
        rel_path = ctx.make_path(f"{ctx.step}-element", "png")
        abs_path = ctx.run_dir / rel_path
        abs_path.parent.mkdir(parents=True, exist_ok=True)
        element.screenshot(path=str(abs_path))
        return EvidenceItem(
            kind=self.kind,
            mime=self.mime,
            path=rel_path,
            scenario=ctx.scenario,
            step=ctx.step,
            captured_at=datetime.now(),
            metadata={"selector": selector},
        )
