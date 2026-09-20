"""The rubric vault: sealed storage for the definition of good.

Rubrics are the load-bearing secret of the opacity model — builders must
not read the criteria they are optimized against. The vault holds them
outside every builder-visible path, behind a four-verb surface:

- ``seal``: move rubrics out of the tenant tree (move, not copy — two
  authorities is how leaks come back)
- ``list`` / ``read``: the judge's access, every read audited
- ``derive_contract``: rubric-as-root — the evidence contract is
  regenerated from the rubrics' evidence declarations, demoting the
  tenant's contract file to a derived cache

:class:`RubricVault` is a protocol so backends can graduate: the
filesystem implementation here suits a single operator (isolation by
addressability: the builder's process is never pointed at the vault);
secret-manager backends (OpenBao / HashiCorp Vault) add token-gated
access, server-side audit a compromised builder cannot edit, and native
version history. The ``version`` parameter on ``read`` exists for those
backends; the filesystem honors it by checking the stored rubric's own
version field.
"""

from __future__ import annotations

import shutil
import sys
from datetime import datetime
from pathlib import Path
from typing import Protocol, runtime_checkable

if sys.version_info >= (3, 11):
    import tomllib
else:  # pragma: no cover - exercised only on 3.10
    import tomli as tomllib

from darkroom.adapter import ProjectAdapter
from darkroom.contract import (
    EvidenceContract,
    EvidenceRequirement,
    ScenarioContract,
)

RUBRIC_SUFFIX = ".rubric.toml"


class VaultError(Exception):
    pass


@runtime_checkable
class RubricVault(Protocol):
    def list(self) -> list[str]: ...

    def read(self, feature_id: str, version: str | None = None) -> str: ...


class FilesystemVault:
    """Rubrics as files in a directory outside every builder-visible path."""

    def __init__(self, root: Path):
        self.root = Path(root)

    def initialize(self) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        self.root.chmod(0o700)

    def _path(self, feature_id: str) -> Path:
        return self.root / f"{feature_id}{RUBRIC_SUFFIX}"

    def _audit(self, line: str) -> None:
        with open(self.root / "audit.log", "a") as f:
            f.write(f"{datetime.now().isoformat()} {line}\n")

    def list(self) -> list[str]:
        return sorted(
            p.name[: -len(RUBRIC_SUFFIX)]
            for p in self.root.glob(f"*{RUBRIC_SUFFIX}")
        )

    def read(self, feature_id: str, version: str | None = None) -> str:
        path = self._path(feature_id)
        if not path.exists():
            raise VaultError(f"no rubric '{feature_id}' in the vault")
        text = path.read_text()
        if version is not None:
            stored = str(tomllib.loads(text).get("version", ""))
            if stored != version:
                raise VaultError(
                    f"rubric '{feature_id}' is at version '{stored}', "
                    f"not '{version}' (the filesystem backend keeps no "
                    "history; versioned reads need a secret-manager backend)"
                )
        self._audit(f"read {feature_id} version={version or 'current'}")
        return text


def seal(adapter: ProjectAdapter, vault: FilesystemVault) -> list[str]:
    """Move the tenant's rubrics into the vault. Returns sealed feature ids."""
    rubric_files = adapter.rubric_files()
    if not rubric_files:
        raise VaultError(
            f"no rubrics match '{adapter.rubric_glob}' in the tenant; "
            "nothing to seal"
        )
    vault.initialize()
    sealed = []
    for source in rubric_files:
        feature_id = source.name[: -len(RUBRIC_SUFFIX)] \
            if source.name.endswith(RUBRIC_SUFFIX) else source.stem
        shutil.move(str(source), vault._path(feature_id))
        sealed.append(feature_id)
    vault._audit(f"sealed {len(sealed)} rubric(s): {', '.join(sealed)}")
    return sealed


def _scenario_name(rubric: dict, feature_id: str) -> str:
    return rubric.get("scenario", feature_id.replace("-", "_"))


def derive_contract(vault: RubricVault, project: str = "") -> EvidenceContract:
    """Rubric-as-root: build the evidence contract from vaulted rubrics."""
    scenarios = []
    for feature_id in vault.list():
        rubric = tomllib.loads(vault.read(feature_id))
        trials = int(rubric.get("trials", 1))
        kinds: list[str] = []
        for criterion in rubric.get("criterion", []):
            for kind in criterion.get("evidence", []):
                if isinstance(kind, str) and kind not in kinds:
                    kinds.append(kind)
        requirements = [
            EvidenceRequirement(kind=kind, trials=trials) for kind in kinds
        ]
        scenarios.append(
            ScenarioContract(
                scenario=_scenario_name(rubric, feature_id),
                requirements=requirements,
            )
        )
    return EvidenceContract(project=project, scenarios=scenarios)


def dumps_contract(contract: EvidenceContract) -> str:
    """Serialize a contract to TOML (stdlib tomllib has no writer)."""
    lines = [
        f'schema_version = "{contract.schema_version}"',
        f'project = "{contract.project}"',
    ]
    for scenario in contract.scenarios:
        lines += ["", "[[scenario]]", f'name = "{scenario.scenario}"']
        for requirement in scenario.requirements:
            lines += ["", "  [[scenario.requires]]", f'  kind = "{requirement.kind}"']
            if requirement.min_count != 1:
                lines.append(f"  min_count = {requirement.min_count}")
            if requirement.steps:
                steps = ", ".join(f'"{s}"' for s in requirement.steps)
                lines.append(f"  steps = [{steps}]")
            if requirement.trials != 1:
                lines.append(f"  trials = {requirement.trials}")
    return "\n".join(lines) + "\n"
