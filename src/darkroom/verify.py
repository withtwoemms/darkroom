"""Manifest verification: structural checks plus contract satisfaction.

Structural checks (the manifest parses; every item path resolves to a
real, non-empty file) run on any manifest. With a contract, each
scenario's declared requirements are checked as well — per run for the
deterministic case, across the supplied run series for requirements
declaring ``trials`` > 1.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from darkroom.contract import EvidenceContract, EvidenceRequirement
from darkroom.manifest import load_manifest
from darkroom.model import RunManifest


@dataclass(frozen=True)
class Finding:
    severity: str  # "error" | "warning"
    code: str
    message: str
    scenario: str | None = None
    manifest: Path | None = None


@dataclass
class VerificationResult:
    manifests: list[Path]
    findings: list[Finding] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.errors

    @property
    def errors(self) -> list[Finding]:
        return [f for f in self.findings if f.severity == "error"]

    @property
    def warnings(self) -> list[Finding]:
        return [f for f in self.findings if f.severity == "warning"]


def _item_path(manifest_path: Path, item_path: Path) -> Path:
    if item_path.is_absolute():
        return item_path
    return manifest_path.parent / item_path


def _check_structure(
    manifest_path: Path, manifest: RunManifest, findings: list[Finding]
) -> None:
    for bundle in manifest.scenarios:
        for item in bundle.items:
            resolved = _item_path(manifest_path, item.path)
            if not resolved.exists():
                findings.append(
                    Finding(
                        severity="error",
                        code="unresolved-path",
                        message=f"item path does not resolve: {item.path}",
                        scenario=bundle.scenario,
                        manifest=manifest_path,
                    )
                )
            elif resolved.stat().st_size == 0:
                findings.append(
                    Finding(
                        severity="error",
                        code="empty-file",
                        message=f"item file is empty: {item.path}",
                        scenario=bundle.scenario,
                        manifest=manifest_path,
                    )
                )


def _requirement_gaps(
    requirement: EvidenceRequirement, manifest: RunManifest, scenario: str
) -> list[str]:
    """Reasons this requirement is unsatisfied in this run (empty = satisfied)."""
    bundle = next(
        (b for b in manifest.scenarios if b.scenario == scenario), None
    )
    if bundle is None:
        return ["scenario not present in run"]
    items = [i for i in bundle.items if i.kind == requirement.kind]
    gaps = []
    if len(items) < requirement.min_count:
        gaps.append(
            f"wanted >= {requirement.min_count} of kind "
            f"'{requirement.kind}', found {len(items)}"
        )
    present_steps = {i.step for i in items}
    for step in requirement.steps:
        if step not in present_steps:
            gaps.append(f"missing step '{step}' of kind '{requirement.kind}'")
    return gaps


def _check_contract(
    contract: EvidenceContract,
    loaded: list[tuple[Path, RunManifest]],
    findings: list[Finding],
) -> None:
    manifests = [manifest for _, manifest in loaded]

    for scenario_contract in contract.scenarios:
        name = scenario_contract.scenario
        present_anywhere = any(
            any(b.scenario == name for b in m.scenarios) for m in manifests
        )
        if not present_anywhere:
            findings.append(
                Finding(
                    severity="error",
                    code="missing-scenario",
                    message=f"scenario '{name}' not present in any supplied run",
                    scenario=name,
                )
            )
            continue

        for requirement in scenario_contract.requirements:
            per_run_gaps = [
                _requirement_gaps(requirement, manifest, name)
                for manifest in manifests
            ]
            satisfied = sum(1 for gaps in per_run_gaps if not gaps)
            if satisfied >= requirement.trials:
                continue
            if requirement.trials == 1 and len(manifests) == 1:
                for gap in per_run_gaps[0]:
                    findings.append(
                        Finding(
                            severity="error",
                            code="unsatisfied-requirement",
                            message=gap,
                            scenario=name,
                            manifest=loaded[0][0],
                        )
                    )
            else:
                findings.append(
                    Finding(
                        severity="error",
                        code="insufficient-trials",
                        message=(
                            f"kind '{requirement.kind}' satisfied in "
                            f"{satisfied}/{len(manifests)} runs, "
                            f"needs {requirement.trials}"
                        ),
                        scenario=name,
                    )
                )

    contracted = {s.scenario for s in contract.scenarios}
    seen: set[str] = set()
    for manifest in manifests:
        for bundle in manifest.scenarios:
            if bundle.scenario not in contracted and bundle.scenario not in seen:
                seen.add(bundle.scenario)
                findings.append(
                    Finding(
                        severity="warning",
                        code="uncontracted-scenario",
                        message=(
                            f"scenario '{bundle.scenario}' captured but not "
                            "declared in the contract"
                        ),
                        scenario=bundle.scenario,
                    )
                )


def verify(
    manifest_paths: list[Path],
    contract: EvidenceContract | None = None,
) -> VerificationResult:
    """Verify manifests structurally and, if given, against a contract."""
    manifest_paths = [Path(p) for p in manifest_paths]
    findings: list[Finding] = []
    loaded: list[tuple[Path, RunManifest]] = []

    for path in manifest_paths:
        try:
            manifest = load_manifest(path)
        except (OSError, ValueError, KeyError) as exc:
            findings.append(
                Finding(
                    severity="error",
                    code="parse-error",
                    message=f"could not load manifest: {exc}",
                    manifest=path,
                )
            )
            continue
        loaded.append((path, manifest))
        _check_structure(path, manifest, findings)

    if contract is not None and loaded:
        _check_contract(contract, loaded, findings)

    return VerificationResult(manifests=manifest_paths, findings=findings)
