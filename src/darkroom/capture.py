"""Per-scenario evidence capture helper -- the primary user-facing API."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING

from darkroom.producer import CaptureContext
from darkroom.producers.log import LogProducer
from darkroom.run import get_current_run, get_evidence_dir

if TYPE_CHECKING:
    from playwright.sync_api import Page


class EvidenceCapture:
    """Capture evidence during a single scenario test.

    This is the backward-compatible API matching the original evidence.py.
    Internally delegates to EvidenceProducer instances.
    """

    def __init__(self, scenario: str):
        self.scenario = scenario
        self.step_count = 0
        self.run = get_current_run()
        self._log_producer = LogProducer()
        self._screenshot_producer = None
        self._element_screenshot_producer = None

    def _get_screenshot_producer(self):
        if self._screenshot_producer is None:
            from darkroom.producers.screenshot import ScreenshotProducer

            self._screenshot_producer = ScreenshotProducer()
        return self._screenshot_producer

    def _get_element_screenshot_producer(self):
        if self._element_screenshot_producer is None:
            from darkroom.producers.screenshot import ElementScreenshotProducer

            self._element_screenshot_producer = ElementScreenshotProducer()
        return self._element_screenshot_producer

    def _make_context(self, step: str) -> CaptureContext:
        run_dir = self.run.run_dir if self.run else get_evidence_dir()
        return CaptureContext(
            scenario=self.scenario,
            step=step,
            run_dir=run_dir,
            step_count=self.step_count,
        )

    def _fallback_path(self, step: str, extension: str) -> Path:
        """Generate path when no run or non-evidence mode."""
        base = get_evidence_dir() / "screenshots"
        base.mkdir(parents=True, exist_ok=True)
        ts = datetime.now().strftime("%Y%m%d-%H%M%S")
        return base / f"{ts}-{self.scenario}-{step}.{extension}"

    def screenshot(self, page: Page, step: str, full_page: bool = False) -> Path:
        """Capture screenshot with scenario context. Returns absolute path."""
        self.step_count += 1

        if self.run and self.run.evidence_mode:
            ctx = self._make_context(step)
            producer = self._get_screenshot_producer()
            item = producer.capture(ctx, page=page, full_page=full_page)
            self.run.record_evidence(item)
            return self.run.run_dir / item.path
        else:
            path = self._fallback_path(step, "png")
            page.screenshot(path=str(path), full_page=full_page)
            return path

    def screenshot_element(
        self, page: Page, step: str, selector: str
    ) -> Path | None:
        """Capture screenshot of specific element."""
        element = page.query_selector(selector)
        if element is None:
            return None

        self.step_count += 1

        if self.run and self.run.evidence_mode:
            ctx = self._make_context(step)
            producer = self._get_element_screenshot_producer()
            item = producer.capture(ctx, page=page, selector=selector)
            if item is None:
                return None
            self.run.record_evidence(item)
            return self.run.run_dir / item.path
        else:
            path = self._fallback_path(f"{step}-element", "png")
            element.screenshot(path=str(path))
            return path

    def log(self, step: str, data: dict) -> Path:
        """Capture structured data as evidence."""
        self.step_count += 1

        if self.run and self.run.evidence_mode:
            ctx = self._make_context(step)
            item = self._log_producer.capture(ctx, data=data)
            self.run.record_evidence(item)
            return self.run.run_dir / item.path
        else:
            path = self._fallback_path(step, "json")
            with open(path, "w") as f:
                json.dump(
                    {
                        "captured_at": datetime.now().isoformat(),
                        "scenario": self.scenario,
                        "step": step,
                        "data": data,
                    },
                    f,
                    indent=2,
                    default=str,
                )
            return path
