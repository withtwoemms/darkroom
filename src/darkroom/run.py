"""Evidence run lifecycle management."""

from __future__ import annotations

import os
from datetime import datetime
from pathlib import Path

from darkroom.manifest import dump_manifest
from darkroom.model import EvidenceItem, RunManifest


def is_evidence_mode() -> bool:
    """Check if running in evidence mode (for judge evaluation)."""
    return os.environ.get("EVIDENCE_MODE", "").lower() in ("1", "true", "yes")


def get_evidence_dir() -> Path:
    """Get evidence directory from environment or default.

    The EVIDENCE_DIR environment variable is the primary mechanism.
    Falls back to cwd/evidence for development convenience.
    """
    env_dir = os.environ.get("EVIDENCE_DIR")
    if env_dir:
        return Path(env_dir)
    return Path.cwd() / "evidence"


# Module-level run manager (initialized per session)
_current_run: EvidenceRun | None = None


def get_current_run() -> EvidenceRun | None:
    """Get the current evidence run, if any."""
    return _current_run


def start_run(
    run_id: str | None = None,
    project: str = "",
) -> EvidenceRun:
    """Start a new evidence run. Called at pytest session start."""
    global _current_run
    _current_run = EvidenceRun(run_id=run_id, project=project)
    return _current_run


def end_run() -> Path | None:
    """End the current run and write manifest. Called at pytest session end."""
    global _current_run
    if _current_run is None:
        return None
    manifest_path = _current_run.write_manifest()
    _current_run = None
    return manifest_path


class EvidenceRun:
    """Manages evidence collection for a single test run.

    In evidence mode, creates a timestamped run directory::

        evidence/runs/2026-03-12T14-30-00/
            manifest.json
            admin_sees_job_board/
                01-login_page.png
                02-after_login.png
    """

    def __init__(
        self,
        run_id: str | None = None,
        project: str = "",
    ):
        self.run_id = run_id or datetime.now().strftime("%Y-%m-%dT%H-%M-%S")
        self.evidence_mode = is_evidence_mode()
        self.base_dir = get_evidence_dir()
        self.project = project
        self._manifest = RunManifest(
            run_id=self.run_id,
            project=project,
        )

        if self.evidence_mode:
            self.run_dir = self.base_dir / "runs" / self.run_id
            self.run_dir.mkdir(parents=True, exist_ok=True)
        else:
            self.run_dir = self.base_dir
            (self.base_dir / "screenshots").mkdir(parents=True, exist_ok=True)
            (self.base_dir / "screencasts").mkdir(parents=True, exist_ok=True)

    def get_scenario_dir(self, scenario: str) -> Path:
        """Get or create directory for a scenario's evidence."""
        if self.evidence_mode:
            scenario_dir = self.run_dir / scenario
            scenario_dir.mkdir(exist_ok=True)
            return scenario_dir
        else:
            return self.base_dir / "screenshots"

    def record_evidence(self, item: EvidenceItem) -> None:
        """Record an EvidenceItem into the manifest."""
        bundle = self._manifest.get_or_create_bundle(item.scenario)
        bundle.add(item)

    def write_manifest(self) -> Path | None:
        """Write manifest.json summarizing the run. Only in evidence mode."""
        if not self.evidence_mode:
            return None

        self._manifest.timestamp = datetime.now().isoformat()
        manifest_path = self.run_dir / "manifest.json"
        dump_manifest(self._manifest, manifest_path)
        return manifest_path
