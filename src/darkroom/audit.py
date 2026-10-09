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

from darkroom.vault import RubricVault, VaultError

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

# step kinds whose own record is something the judge can read: a resolved
# value (assert), a transcript (http, command), or the picture itself
WITNESS_KINDS: frozenset[str] = frozenset({"assert", "http", "command", "screenshot"})


def _witness_capable(step: dict) -> bool:
    """A cited witness must leave a record: an assert, an http/command
    transcript, a screenshot, or any step whose `expect` is logged
    (drive-scripts 1.4). A bare goto/click/fill gates a run but leaves
    nothing to score."""
    return step.get("kind", "http") in WITNESS_KINDS or bool(step.get("expect"))


@dataclass(frozen=True)
class AuditFinding:
    severity: str  # "error" | "warning" | "info"
    scenario: str
    message: str
    code: str = ""  # a stable name for the class of finding, where one exists


SURFACE_SEVERITY = {"surface-unpublished": "warning", "surface-untouched": "info"}


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
    drives_dir: Path, backdrops: dict[str, list[dict]] | None = None
) -> dict[str, dict]:
    """Every exam in the directory, backdrops expanded so the audit sees
    the steps the engine will run."""
    from darkroom.proof import ProofError, exposure, load_proof, proof_dirs

    scripts: dict[str, dict] = {}
    for folder in proof_dirs(drives_dir):
        try:
            script = exposure(load_proof(folder), backdrops)
        except (ProofError, OSError, ValueError):
            continue
        scripts[script["scenario"]] = script
    return scripts


def _surface_findings(scenario: str, script: dict, spec: Path | None) -> list[AuditFinding]:
    """The build's published surfaces (the ``.surfaces`` beside the spec)
    against the exposure's steps; nothing when the scenario has no spec or
    engineering has published nothing yet."""
    from darkroom.surfaces import SurfacesError, cross_check, load_surfaces, surfaces_path

    if spec is None:
        return []
    path = surfaces_path(spec)
    if not path.is_file():
        return []
    try:
        published = load_surfaces(path)
    except SurfacesError as exc:
        return [
            AuditFinding("error", scenario, f"{path.name}: {exc}", "surfaces-malformed")
        ]
    except OSError:
        return []
    return [
        AuditFinding(SURFACE_SEVERITY[code], scenario, message, code)
        for code, message in cross_check(published, script)
    ]


@dataclass(frozen=True)
class Redundancy:
    """One scenario's standing in the redundancy report."""

    scenario: str
    criteria: int
    points: int
    touched: tuple[str, ...]  # published surfaces its own steps reach
    unique: tuple[str, ...]   # the ones no other scenario reaches
    covered_by: tuple[str, ...]  # scenarios whose touched sets contain this one's

    @property
    def candidate(self) -> bool:
        return bool(self.touched) and not self.unique


def _touched_published(script: dict, spec: Path | None) -> list[str]:
    """The surfaces an exposure's own steps reach, named the way the
    build publishes them: a selector narrowed to a state collapses onto
    the element published, a concrete path onto its route. A scenario
    without a publication is named by what it reaches as written."""
    from darkroom.surfaces import (
        SurfacesError,
        load_surfaces,
        matches,
        surfaces_path,
        touched_surfaces,
    )

    published = []
    if spec is not None:
        path = surfaces_path(spec)
        if path.is_file():
            try:
                published = load_surfaces(path).of("route", "page", "selector", "command")
            except (SurfacesError, OSError):
                published = []
    names: list[str] = []
    for touched in touched_surfaces(script):
        name = next((str(p) for p in published if matches(p, touched)), str(touched))
        if name not in names:
            names.append(name)
    return names


def redundancy(
    vault: RubricVault,
    drives_dir: Path,
    backdrops: dict[str, list[dict]] | None = None,
    specs: list[Path] | None = None,
    only: set[str] | None = None,
) -> list[Redundancy]:
    """Which scenarios reach no surface another does not. A report, never
    a verdict: a scenario can be the only one proving a *refusal* on a
    shared surface, which is why each entry carries its rubric's
    criterion count and points."""
    scripts = _drive_scripts(drives_dir, backdrops)
    spec_by_scenario = {Path(p).name.split(".", 1)[0]: Path(p) for p in specs or []}
    reach: dict[str, list[str]] = {}
    weight: dict[str, tuple[int, int]] = {}
    for feature_id in vault.list():
        if only is not None and feature_id not in only:
            continue
        try:
            rubric = tomllib.loads(vault.read(feature_id))
        except VaultError:
            continue
        scenario = rubric.get("scenario", feature_id.replace("-", "_"))
        script = scripts.get(scenario)
        if script is None:
            continue
        criteria = rubric.get("criterion", [])
        weight[scenario] = (len(criteria), sum(int(c.get("points", 0)) for c in criteria))
        reach[scenario] = _touched_published(script, spec_by_scenario.get(scenario))

    report: list[Redundancy] = []
    for scenario, touched in reach.items():
        others = {name: set(t) for name, t in reach.items() if name != scenario}
        unique = [s for s in touched if not any(s in t for t in others.values())]
        covered_by = (
            sorted(name for name, t in others.items() if set(touched) <= t)
            if touched and not unique
            else []
        )
        criteria, points = weight[scenario]
        report.append(
            Redundancy(
                scenario, criteria, points, tuple(touched), tuple(unique), tuple(covered_by)
            )
        )
    # candidates first; among them, one a single scenario covers outright
    # before one only covered jointly, which a reader weighs differently
    report.sort(key=lambda r: (not r.candidate, not r.covered_by, r.scenario))
    return report


def dumps_redundancy(report: list[Redundancy]) -> str:
    """The report as text: candidates first, each with who covers it, then
    every scenario with what it alone reaches."""
    lines: list[str] = []
    candidates = [r for r in report if r.candidate]
    lines.append(
        f"candidates: {len(candidates)} of {len(report)} scenario(s) reach no surface "
        "another does not"
    )
    for r in candidates:
        who = ", ".join(r.covered_by) if r.covered_by else "no single scenario; covered jointly"
        lines.append(
            f"  {r.scenario}  [{r.criteria} criteria, {r.points} points]  covered by: {who}"
        )
        for s in r.touched:
            lines.append(f"      reaches {s}")
    lines.append("")
    lines.append("alone:")
    for r in report:
        if r.candidate:
            continue
        head = f"  {r.scenario}  [{r.criteria} criteria, {r.points} points]"
        if not r.touched:
            lines.append(
                head + "  reaches no published surface (command/assert-only, or no publication)"
            )
            continue
        lines.append(head)
        for s in r.unique:
            lines.append(f"      alone on {s}")
    lines.append("")
    lines.append(
        "a candidate is not a duplicate until a reader has checked it does not alone "
        "prove a refusal on a shared surface; nothing here retires anything"
    )
    return "\n".join(lines) + "\n"


def audit(
    vault: RubricVault,
    drives_dir: Path,
    backdrops: dict[str, list[dict]] | None = None,
    specs: list[Path] | None = None,
    only: set[str] | None = None,
) -> list[AuditFinding]:
    """Cross-check every rubric criterion against its exposure's
    capabilities, and the exposure's steps against the surfaces the build
    publishes beside the spec (specs are matched to scenarios by file
    stem)."""
    findings: list[AuditFinding] = []
    scripts = _drive_scripts(drives_dir, backdrops)
    spec_by_scenario = {Path(p).name.split(".", 1)[0]: Path(p) for p in specs or []}

    for feature_id in vault.list():
        if only is not None and feature_id not in only:
            continue
        try:
            rubric = tomllib.loads(vault.read(feature_id))
        except VaultError as exc:
            findings.append(AuditFinding("error", feature_id, str(exc), "no-rubric"))
            continue
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
                            "step leaves no record — cite an assert, an http/command "
                            "step, a screenshot, or give it an expect table "
                            "(expectation outcomes are logged since drive-scripts 1.4)",
                        )
                    )
        findings.extend(_surface_findings(scenario, script, spec_by_scenario.get(scenario)))
    return findings


def has_errors(findings: list[AuditFinding]) -> bool:
    return any(f.severity == "error" for f in findings)
