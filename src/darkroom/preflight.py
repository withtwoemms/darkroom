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
    """Normalized pairing key: 'staff-login.feature' ~ the 'staff_login' proof."""
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

    # a spec pairs with its proof folder in the home
    from darkroom.homedir import default_proofs
    from darkroom.proof import proof_dirs

    proofs = proof_dirs(default_proofs(adapter.name)) if adapter.name else []
    if proofs:
        paired_with, keys = "proof", {_stem_key(p) for p in proofs}
    else:
        findings.append(
            Finding(
                severity="warning",
                code="no-proofs",
                message="specs exist but no proofs are in the home",
            )
        )
        return

    for spec in specs:
        if _stem_key(spec) not in keys:
            findings.append(
                Finding(
                    severity="warning",
                    code="unpaired-spec",
                    message=f"spec '{spec.name}' has no matching {paired_with}",
                )
            )


def _check_contract(adapter: ProjectAdapter, findings: list[Finding]) -> None:
    if adapter.contract_path is None:
        from darkroom.homedir import default_proofs
        from darkroom.proof import proof_dirs

        if adapter.name and proof_dirs(default_proofs(adapter.name)):
            return  # derived from the proofs every run; nothing to declare
        findings.append(
            Finding(
                severity="warning",
                code="no-contract",
                message=(
                    "no evidence contract declared and no proofs in the home to "
                    "derive one from; verify will be structural only"
                ),
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


def _check_layout(adapter: ProjectAdapter, findings: list[Finding]) -> None:
    """A home still on the pre-0.20 pair is refused by name: every command
    but ``migrate`` reads proofs only."""
    from darkroom.homedir import old_layout_message

    message = old_layout_message(adapter.name)
    if message:
        findings.append(Finding(severity="error", code="old-layout", message=message))


def _check_container_runtime(adapter: ProjectAdapter, findings: list[Finding]) -> None:
    """A tenant that boots services or an app image runs through
    testcontainers; under colima the Ryuk reaper needs the socket named as
    the VM sees it, or every service boot fails in seconds. The engine sets
    it when it can; preflight says so when it will have to."""
    if not (adapter.services or adapter.app_image):
        return
    from darkroom.drive import (
        RYUK_SOCKET_OVERRIDE,
        VM_DOCKER_SOCKET,
        colima_socket_override_needed,
        docker_host_setting,
    )

    if colima_socket_override_needed():
        findings.append(
            Finding(
                severity="info",
                code="container-runtime",
                message=(
                    f"docker host is colima ({docker_host_setting()}); the engine will set "
                    f"{RYUK_SOCKET_OVERRIDE}={VM_DOCKER_SOCKET} for Ryuk — export it yourself "
                    "for anything else that starts containers in this shell"
                ),
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
    _check_layout(adapter, findings)
    _check_container_runtime(adapter, findings)
    return PreflightResult(adapter_path=adapter_path, findings=findings)
