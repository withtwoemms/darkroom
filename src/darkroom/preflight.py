"""Preflight: is this project wired for evidence-based delivery?

The generalized descendant of the source framework's ``preflight.sh``,
minus its domain heuristics. Runs before any test executes and answers
mechanically: does the adapter parse, does a test command exist, do the
spec and rubric globs resolve, does each spec have a rubric, does the
declared contract load? The natural CI job *before* the run that
``darkroom verify`` gates *after*.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from darkroom.adapter import ProjectAdapter, load_adapter
from darkroom.contract import load_contract
from darkroom.verify import Finding


@dataclass
class PreflightResult:
    adapter_path: Path
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


def _stem_key(path: Path) -> str:
    """Normalized pairing key: 'staff_login.feature' ~ 'staff-login.rubric.toml'."""
    stem = path.name.split(".")[0]
    return re.sub(r"[-_]", "", stem).lower()


def _check_commands(adapter: ProjectAdapter, findings: list[Finding]) -> None:
    if "test" not in adapter.commands:
        findings.append(
            Finding(
                severity="error",
                code="missing-command",
                message="no 'test' command declared; nothing can produce evidence",
            )
        )


def _check_scenarios(adapter: ProjectAdapter, findings: list[Finding]) -> None:
    if not adapter.spec_glob:
        findings.append(
            Finding(
                severity="warning",
                code="no-spec-glob",
                message="no [scenarios] spec_glob declared; spec checks skipped",
            )
        )
        return

    specs = adapter.spec_files()
    if not specs:
        findings.append(
            Finding(
                severity="error",
                code="no-specs",
                message=f"spec_glob '{adapter.spec_glob}' matches no files",
            )
        )
        return

    if not adapter.rubric_glob:
        findings.append(
            Finding(
                severity="warning",
                code="no-rubric-glob",
                message="specs exist but no rubric_glob is declared",
            )
        )
        return

    rubric_keys = {_stem_key(p) for p in adapter.rubric_files()}
    for spec in specs:
        if _stem_key(spec) not in rubric_keys:
            findings.append(
                Finding(
                    severity="warning",
                    code="unpaired-spec",
                    message=f"spec '{spec.name}' has no matching rubric",
                )
            )


def _check_contract(adapter: ProjectAdapter, findings: list[Finding]) -> None:
    if adapter.contract_path is None:
        findings.append(
            Finding(
                severity="warning",
                code="no-contract",
                message="no evidence contract declared; verify will be structural only",
            )
        )
        return
    path = adapter.resolve(adapter.contract_path)
    if not path.exists():
        findings.append(
            Finding(
                severity="error",
                code="missing-contract",
                message=f"declared contract does not exist: {adapter.contract_path}",
            )
        )
        return
    try:
        load_contract(path)
    except (OSError, ValueError) as exc:
        findings.append(
            Finding(
                severity="error",
                code="contract-error",
                message=f"contract does not load: {exc}",
            )
        )


def preflight(adapter_path: Path) -> PreflightResult:
    """Validate a project's darkroom wiring from its adapter file."""
    adapter_path = Path(adapter_path)
    findings: list[Finding] = []
    try:
        adapter = load_adapter(adapter_path)
    except (OSError, ValueError) as exc:
        findings.append(
            Finding(
                severity="error",
                code="adapter-error",
                message=f"adapter does not load: {exc}",
            )
        )
        return PreflightResult(adapter_path=adapter_path, findings=findings)

    _check_commands(adapter, findings)
    _check_scenarios(adapter, findings)
    _check_contract(adapter, findings)
    return PreflightResult(adapter_path=adapter_path, findings=findings)
