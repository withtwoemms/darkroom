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

from darkroom.drive import DRIVE_SUFFIX, DriveError, load_exam
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

# step kinds whose own record resolves a value the judge can read
WITNESS_KINDS: frozenset[str] = frozenset({"assert", "http", "command"})


def _witness_capable(step: dict) -> bool:
    """A cited witness must resolve a value: an assert, an http/command
    transcript, or any step whose `expect` is logged (drive-scripts 1.4)."""
    return step.get("kind", "http") in WITNESS_KINDS or bool(step.get("expect"))


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
        if step.get("expect"):
            kinds.add("log")  # expectation witnesses (drive-scripts 1.4)
    if script.get("record"):
        kinds.add("video")
    return kinds


def _drive_scripts(
    drives_dir: Path, preludes: dict[str, list[dict]] | None = None
) -> dict[str, dict]:
    """Every exam in the directory, includes expanded so the audit sees
    the steps the engine will run."""
    scripts: dict[str, dict] = {}
    for path in sorted(Path(drives_dir).glob(f"*{DRIVE_SUFFIX}")):
        try:
            script = load_exam(path, preludes)
        except (DriveError, OSError, ValueError):
            continue
        scripts[script["scenario"]] = script
    return scripts


def audit(
    vault: RubricVault,
    drives_dir: Path,
    preludes: dict[str, list[dict]] | None = None,
) -> list[AuditFinding]:
    """Cross-check every rubric criterion against its drive's capabilities."""
    findings: list[AuditFinding] = []
    scripts = _drive_scripts(drives_dir, preludes)

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
        steps = {s.get("name"): s for s in script.get("step", []) if s.get("name")}
        for criterion in rubric.get("criterion", []):
            cid = criterion.get("id", "?")
            declared = set(criterion.get("evidence", []))
            missing = declared - can
            if missing:
                findings.append(
                    AuditFinding(
                        "error",
                        scenario,
                        f"criterion '{cid}' declares "
                        f"{sorted(missing)} but no step in the drive can "
                        f"produce it (drive can produce: {sorted(can) or 'nothing'})",
                    )
                )
            for cited in criterion.get("witnesses", []):
                step = steps.get(cited)
                if step is None:
                    findings.append(
                        AuditFinding(
                            "error",
                            scenario,
                            f"criterion '{cid}' cites witness '{cited}' but the "
                            f"drive has no step named '{cited}'",
                        )
                    )
                elif not _witness_capable(step):
                    findings.append(
                        AuditFinding(
                            "error",
                            scenario,
                            f"criterion '{cid}' cites '{cited}' "
                            f"({step.get('kind', 'http')}) as a witness, but that "
                            "step produces no resolved value — cite an assert, an "
                            "http/command step, or give it an expect table "
                            "(expectation outcomes are logged since drive-scripts 1.4)",
                        )
                    )
    return findings


def has_errors(findings: list[AuditFinding]) -> bool:
    return any(f.severity == "error" for f in findings)
