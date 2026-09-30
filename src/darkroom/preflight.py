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


_SKIPPED_DIRS = {".git", "node_modules", "__pycache__"}


def tenant_drive_scripts(adapter: ProjectAdapter) -> list[Path]:
    """Drive scripts living inside the tenant — where the builder can read
    the exam. Hidden directories, the evidence dir, and dependency trees
    are not searched."""
    root = adapter.root
    evidence = adapter.resolve(adapter.evidence_dir)
    found: list[Path] = []
    for path in sorted(root.rglob("*.drive.toml")):
        rel = path.relative_to(root)
        if any(part.startswith(".") or part in _SKIPPED_DIRS for part in rel.parts[:-1]):
            continue
        if evidence in path.parents:
            continue
        found.append(rel)
    return found


def drives_in_tenant_message(adapter: ProjectAdapter, scripts: list[Path]) -> str:
    from darkroom.homedir import default_drives

    sample = ", ".join(str(p) for p in scripts[:3]) + (" …" if len(scripts) > 3 else "")
    return (
        f"{len(scripts)} drive script(s) live inside the tenant ({sample}); "
        f"the builder can read the exam there. Move them to the operator home "
        f"({default_drives(adapter.name)}) and drop --drives from the test command"
    )


def _check_drives_location(adapter: ProjectAdapter, findings: list[Finding]) -> None:
    """Stages 1-3 of the quickstart keep drives in the tenant on purpose; the
    finding only appears once the exam has moved operator-side (an
    operator config or sealed rubrics in the home)."""
    from darkroom.homedir import exam_is_operator_side

    if not exam_is_operator_side(adapter.name):
        return
    scripts = tenant_drive_scripts(adapter)
    if scripts:
        findings.append(
            Finding(
                severity="warning",
                code="drives-in-tenant",
                message=drives_in_tenant_message(adapter, scripts),
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
    _check_drives_location(adapter, findings)
    return PreflightResult(adapter_path=adapter_path, findings=findings)
