"""The darkroom home: one protected place for all operator-side material.

``~/.darkroom`` (override: ``DARKROOM_HOME``), mode 700 — the ``~/.ssh``
precedent — partitioned per project by the adapter's declared name:

    ~/.darkroom/projects/<name>/
    ├── operator.toml     auto-discovered by agent mode
    ├── backdrops.toml    shared step sequences exposures are posed against
    ├── proofs/           one folder per scenario: exposure.toml + rubric.toml
    ├── vault/            the audit log
    └── state/            loop state: evaluations, feedback, builder-log,
                          tickets, gates — outside every builder-addressable path

Relocating loop state here closes a real leak: it previously defaulted
inside the tenant, leaving judge evaluations (scores) readable by the
builder between iterations. The home is a *default*, not a cage —
explicit flags always override — but it is a default that is
structurally guaranteed to live outside every tenant.

The usual ceiling applies: mode 700 protects against other users, not a
same-UID escaped builder; secret-manager vault backends remain the
graduation path for adversarial infrastructure.
"""

from __future__ import annotations

import os
from pathlib import Path


def darkroom_home() -> Path:
    override = os.environ.get("DARKROOM_HOME")
    return Path(override).expanduser() if override else Path.home() / ".darkroom"


def project_home(project_name: str) -> Path:
    if not project_name:
        raise ValueError("a project name is required to resolve its home")
    return darkroom_home() / "projects" / project_name


def ensure_project_home(project_name: str) -> Path:
    home = darkroom_home()
    home.mkdir(parents=True, exist_ok=True)
    home.chmod(0o700)
    project = project_home(project_name)
    for sub in ("vault", "proofs", "state"):
        (project / sub).mkdir(parents=True, exist_ok=True)
    project.chmod(0o700)
    return project


def find_operator_config(project_name: str) -> Path | None:
    candidate = project_home(project_name) / "operator.toml"
    return candidate if candidate.is_file() else None


def default_vault(project_name: str) -> Path:
    return project_home(project_name) / "vault"


def exam_is_operator_side(project_name: str) -> bool:
    """Has this project's exam moved out of the tenant — an operator config,
    proofs, or sealed rubrics in the home? The home directory itself is no
    signal: ``auto`` creates it for loop state even in the quickstart's free
    stage."""
    if not project_name:
        return False
    home = project_home(project_name)
    if (home / "operator.toml").is_file():
        return True
    return _holds_proofs(home / "proofs")


def _holds_proofs(proofs: Path) -> bool:
    from darkroom.proof import proof_dirs

    return bool(proof_dirs(proofs))


def default_proofs(project_name: str) -> Path:
    return project_home(project_name) / "proofs"


def default_backdrops(project_name: str) -> Path:
    from darkroom.backdrops import BACKDROPS_FILE

    return project_home(project_name) / BACKDROPS_FILE


OLD_LAYOUT_HINT = (
    "the home holds the pre-0.20 pair (drives/*.drive.toml and vault/*.rubric.toml) "
    "and no proofs; run `darkroom migrate` to carry it into proofs/"
)


def old_layout_present(project_name: str) -> bool:
    """A home still on the pre-0.20 pair — drive scripts or vaulted rubrics
    and no proofs. Every command but ``migrate`` refuses it by name."""
    if not project_name:
        return False
    home = project_home(project_name)
    if _holds_proofs(home / "proofs"):
        return False
    return any((home / "drives").glob("*.drive.toml")) or any(
        (home / "vault").glob("*.rubric.toml")
    )


def old_layout_message(project_name: str) -> str | None:
    return OLD_LAYOUT_HINT if old_layout_present(project_name) else None


def default_state(project_name: str) -> Path:
    return project_home(project_name) / "state"


def gates_file(adapter) -> Path:
    """Where the score ratchet lives: the tenant's declared [evidence] gates
    path, else the operator home's state — loop output beside the loop's
    other state, not beside the code the builder edits."""
    if adapter.gates_declared:
        return adapter.resolve(adapter.gates_path)
    return default_state(adapter.name) / "gates.json"
