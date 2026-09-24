"""The witnessability audit: catch unproducible evidence at authoring time.

The costliest exam-authoring defect observed in the field is a rubric
criterion declaring an evidence kind its scenario's drive script can
never produce — discovered, expensively, at run six of a convergence
campaign instead of at writing time. This audit makes that class a
static check: for every sealed rubric, compare each criterion's
declared kinds against what the scenario's drive script can capture.

Operator-side by nature (it reads the vault and the drives); the
step-kind → evidence-kind map is the drive engine's own vocabulary.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path

if sys.version_info >= (3, 11):
    import tomllib
else:  # pragma: no cover - exercised only on 3.10
    import tomli as tomllib

from darkroom.drive import DRIVE_SUFFIX, DriveError, load_drive
from darkroom.vault import RubricVault

# what each drive step kind can register in the manifest
STEP_EVIDENCE: dict[str, frozenset[str]] = {
    "http": frozenset({"http_transcript"}),
    "command": frozenset({"command_transcript"}),
    "assert": frozenset({"log"}),
    "container": frozenset({"log"}),
    "goto": frozenset({"log"}),
    "click": frozenset({"log"}),
    "fill": frozenset({"log"}),
    "screenshot": frozenset({"screenshot"}),
    "keygen": frozenset(),
    "wait": frozenset(),
}


@dataclass(frozen=True)
class AuditFinding:
    severity: str  # "error" | "warning"
    scenario: str
    message: str


def producible_kinds(script: dict) -> set[str]:
    """Evidence kinds a drive script can put in the manifest."""
    kinds: set[str] = set()
    for step in script.get("step", []):
        kind = step.get("kind", "http")
        kinds |= STEP_EVIDENCE.get(kind, frozenset())
    if script.get("record"):
        kinds.add("video")
    return kinds


def _drive_scripts(drives_dir: Path) -> dict[str, dict]:
    scripts: dict[str, dict] = {}
    for path in sorted(Path(drives_dir).glob(f"*{DRIVE_SUFFIX}")):
        try:
            script = load_drive(path)
        except (DriveError, OSError, ValueError):
            continue
        scripts[script["scenario"]] = script
    return scripts


def audit(vault: RubricVault, drives_dir: Path) -> list[AuditFinding]:
    """Cross-check every rubric criterion against its drive's capabilities."""
    findings: list[AuditFinding] = []
    scripts = _drive_scripts(drives_dir)

    for feature_id in vault.list():
        rubric = tomllib.loads(vault.read(feature_id))
        scenario = rubric.get("scenario", feature_id.replace("-", "_"))
        script = scripts.get(scenario)
        if script is None:
            findings.append(
                AuditFinding(
                    "warning",
                    scenario,
                    f"rubric '{feature_id}' has no drive script — its "
                    "criteria cannot be exercised by the exam",
                )
            )
            continue
        can = producible_kinds(script)
        for criterion in rubric.get("criterion", []):
            declared = set(criterion.get("evidence", []))
            missing = declared - can
            if missing:
                findings.append(
                    AuditFinding(
                        "error",
                        scenario,
                        f"criterion '{criterion.get('id', '?')}' declares "
                        f"{sorted(missing)} but no step in the drive can "
                        f"produce it (drive can produce: {sorted(can) or 'nothing'})",
                    )
                )
    return findings


def has_errors(findings: list[AuditFinding]) -> bool:
    return any(f.severity == "error" for f in findings)
