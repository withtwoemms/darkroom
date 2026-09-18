"""Legacy compatibility helpers.

These reproduce the module-level constants and free functions
from the original evidence.py so that the target project's
conftest.py can import them with zero changes.

Legacy-only: new projects should use the pytest plugin
(``darkroom.pytest_plugin``, auto-loaded on install), which provides the
session hooks, the ``evidence`` fixture, and failure screenshots without
any conftest wiring. This module exists solely for the original pilot
caller and receives no new functionality.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING

from darkroom.run import get_evidence_dir

if TYPE_CHECKING:
    from playwright.sync_api import Page

EVIDENCE_DIR = get_evidence_dir()
SCREENSHOTS_DIR = EVIDENCE_DIR / "screenshots"
SCREENCASTS_DIR = EVIDENCE_DIR / "screencasts"
LOGS_DIR = EVIDENCE_DIR / "logs"


def ensure_dirs() -> None:
    """Ensure evidence directories exist."""
    SCREENSHOTS_DIR.mkdir(parents=True, exist_ok=True)
    SCREENCASTS_DIR.mkdir(parents=True, exist_ok=True)
    LOGS_DIR.mkdir(parents=True, exist_ok=True)


def timestamp() -> str:
    """Generate timestamp for evidence filenames."""
    return datetime.now().strftime("%Y%m%d-%H%M%S")


def screenshot(
    page: Page,
    scenario: str,
    step: str,
    full_page: bool = False,
) -> Path:
    """Capture screenshot (legacy free-function API)."""
    ensure_dirs()
    filename = f"{timestamp()}-{scenario}-{step}.png"
    path = SCREENSHOTS_DIR / filename
    page.screenshot(path=str(path), full_page=full_page)
    return path
