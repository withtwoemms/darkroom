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
    """Rubrics as files in a directory outside every builder-visible path.

    Two layouts: ``vault/<feature-id>.rubric.toml`` (the rubric alone,
    the drive in ``drives/``), or ``proofs/<scenario>/`` beside it
    (``exposure.toml`` and ``rubric.toml``, one sealed folder). When a
    ``proofs`` directory holds proofs it is the authority: ``list`` names
    them by scenario and ``read`` renders the rubric half, so the judge is
    given criteria and never the exposure.
    """

    def __init__(self, root: Path, proofs: Path | None = None, backdrops: Path | None = None):
        from darkroom.backdrops import BACKDROPS_FILE

        self.root = Path(root)
        self.proofs = Path(proofs) if proofs is not None else self.root.parent / "proofs"
        self.backdrops_path = (
            Path(backdrops) if backdrops is not None else self.root.parent / BACKDROPS_FILE
        )

    def initialize(self) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        self.root.chmod(0o700)

    def _path(self, feature_id: str) -> Path:
        return self.root / f"{feature_id}{RUBRIC_SUFFIX}"

    def _audit(self, line: str) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        with open(self.root / "audit.log", "a") as f:
            f.write(f"{datetime.now().isoformat()} {line}\n")

    def uses_proofs(self) -> bool:
        from darkroom.proof import proof_dirs

        return bool(proof_dirs(self.proofs))

    def _backdrops(self) -> dict[str, list[dict]]:
        from darkroom.backdrops import load_backdrops

        return load_backdrops(self.backdrops_path)

    def list(self) -> list[str]:
        if self.uses_proofs():
            from darkroom.proof import proof_dirs

            return [p.name for p in proof_dirs(self.proofs)]
        return sorted(
            p.name[: -len(RUBRIC_SUFFIX)]
            for p in self.root.glob(f"*{RUBRIC_SUFFIX}")
        )

    def read(self, feature_id: str, version: str | None = None) -> str:
        if self.uses_proofs():
            from darkroom.proof import ProofError, is_proof, load_proof, rubric_text

            folder = self.proofs / feature_id
            if not is_proof(folder):
                raise VaultError(f"no proof '{feature_id}' in {self.proofs}")
            try:
                text = rubric_text(load_proof(folder), self._backdrops())
            except ProofError as exc:
                raise VaultError(str(exc)) from None
            if version is not None:
                stored = str(tomllib.loads(text).get("version", ""))
                if stored != version:
                    raise VaultError(
                        f"proof '{feature_id}' is at version '{stored}', not '{version}'"
                    )
            self._audit(f"read proof {feature_id} version={version or 'current'}")
            return text
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


def seal_proofs(vault: FilesystemVault) -> list[str]:
    """Validate every proof in the home and record the sealing. Proofs are
    born operator-side, so there is nothing to move — sealing is the
    check that each parses, cites real witnesses, and is listed."""
    from darkroom.proof import ProofError, load_proof, proof_dirs, rubric

    if not vault.proofs.is_dir():
        raise VaultError(f"no proofs directory at {vault.proofs}; nothing to seal")
    backdrops = vault._backdrops()
    sealed = []
    for folder in proof_dirs(vault.proofs):
        try:
            rubric(load_proof(folder), backdrops)
        except ProofError as exc:
            raise VaultError(str(exc)) from None
        folder.chmod(0o700)
        sealed.append(folder.name)
    if not sealed:
        raise VaultError(f"no proofs in {vault.proofs}; nothing to seal")
    vault.proofs.chmod(0o700)
    vault._audit(f"sealed {len(sealed)} proof(s): {', '.join(sealed)}")
    return sealed


def seal(adapter: ProjectAdapter, vault: FilesystemVault) -> list[str]:
    """Move the tenant's rubrics into the vault. Returns sealed feature ids."""
    rubric_files = adapter.rubric_files()
    if not rubric_files:
        if vault.uses_proofs():
            return seal_proofs(vault)
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


def runtime_contract(
    adapter: ProjectAdapter, proofs_dir: Path | None = None
) -> EvidenceContract | None:
    """The contract a run is verified against: the tenant's declared file
    when it has one, else the one the proofs imply — the directory the run
    was given when it holds proofs, else the home's — derived on the spot,
    so a tenant on proofs commits no contract at all. None when none of
    these exist (verify is then structural only)."""
    from darkroom.contract import load_contract

    if adapter.contract_path is not None:
        declared = adapter.resolve(adapter.contract_path)
        if declared.exists():
            return load_contract(declared)
    from darkroom.backdrops import BackdropError, load_backdrops
    from darkroom.homedir import default_backdrops, default_proofs
    from darkroom.proof import ProofError, load_proofs, proof_dirs
    from darkroom.proof import derive_contract as derive_from_proofs

    if proofs_dir is None or not proof_dirs(proofs_dir):
        if not adapter.name:
            return None
        proofs_dir = default_proofs(adapter.name)
    if not Path(proofs_dir).is_dir():
        return None
    from darkroom.proof import has_rubric

    try:
        proofs = load_proofs(proofs_dir)
        if not any(has_rubric(p) for p in proofs.values()):
            return None  # exposures alone hold a run to nothing
        backdrops = load_backdrops(default_backdrops(adapter.name)) if adapter.name else {}
        return derive_from_proofs(list(proofs.values()), adapter.name, backdrops)
    except (ProofError, BackdropError, OSError, ValueError) as exc:
        raise VaultError(str(exc)) from None


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
