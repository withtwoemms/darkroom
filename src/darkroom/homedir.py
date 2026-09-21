"""The darkroom home: one protected place for all operator-side material.

``~/.darkroom`` (override: ``DARKROOM_HOME``), mode 700 — the ``~/.ssh``
precedent — partitioned per project by the adapter's declared name:

    ~/.darkroom/projects/<name>/
    ├── operator.toml     auto-discovered by agent mode
    ├── vault/            default vault location
    ├── drives/           default drive-script location
    └── state/            loop state: evaluations, feedback, builder-log,
                          tickets — outside every builder-addressable path

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
    for sub in ("vault", "drives", "state"):
        (project / sub).mkdir(parents=True, exist_ok=True)
    project.chmod(0o700)
    return project


def find_operator_config(project_name: str) -> Path | None:
    candidate = project_home(project_name) / "operator.toml"
    return candidate if candidate.is_file() else None


def default_vault(project_name: str) -> Path:
    return project_home(project_name) / "vault"


def default_drives(project_name: str) -> Path:
    return project_home(project_name) / "drives"


def default_state(project_name: str) -> Path:
    return project_home(project_name) / "state"
