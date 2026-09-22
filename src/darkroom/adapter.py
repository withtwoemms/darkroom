"""The project adapter: ``darkroom.toml`` at a tenant project's root.

The adapter holds a project's *run-me facts* — commands, evidence paths,
spec/rubric globs — so the machinery asks the project where things live
instead of reaching in by convention (the source framework's
symlinks-as-API, retired).

**Trust rule** (load-bearing; do not relax): the tenant file lives in
the repo a builder agent edits, so everything in it is builder-writable.
It may therefore contain only configuration whose manipulation is either
futile (the builder already controls the Makefile its commands invoke)
or mechanically caught (lying globs and paths fail preflight/verify).
Judging, gating, and loop *authority* — judge models, tool allowlists,
vault locations, iteration budgets — must never be read from this file;
they belong to the operator-side configuration (arriving with the
orchestration releases). The ``[defaults]`` table is advisory only and
is overridden by operator config once an orchestrator exists.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass, field
from pathlib import Path

if sys.version_info >= (3, 11):
    import tomllib
else:  # pragma: no cover - exercised only on 3.10
    import tomli as tomllib

CURRENT_ADAPTER_SCHEMA_VERSION = "1.0"
ADAPTER_FILENAME = "darkroom.toml"


@dataclass(frozen=True)
class ServiceSpec:
    """A dependency container the app needs (declared fact, not policy)."""

    name: str
    image: str
    port: int | None = None
    env: tuple[tuple[str, str], ...] = ()


@dataclass(frozen=True)
class ProjectAdapter:
    root: Path
    name: str
    schema_version: str = CURRENT_ADAPTER_SCHEMA_VERSION
    commands: dict[str, str] = field(default_factory=dict)
    evidence_dir: Path = Path("evidence")
    contract_path: Path | None = None
    gates_path: Path = Path("evidence-gates.json")
    spec_glob: str = ""
    rubric_glob: str = ""
    defaults: dict = field(default_factory=dict)
    app_image: str = ""
    app_port: int = 8000
    environment_build: str = ""
    app_env: tuple[tuple[str, str], ...] = ()
    services: tuple[ServiceSpec, ...] = ()

    def resolve(self, relative: Path) -> Path:
        relative = Path(relative)
        return relative if relative.is_absolute() else self.root / relative

    def command(self, name: str, **substitutions) -> str:
        """The named command with its ``{placeholders}`` substituted."""
        if name not in self.commands:
            raise KeyError(f"command '{name}' is not declared in {ADAPTER_FILENAME}")
        template = self.commands[name]
        try:
            return template.format(**substitutions)
        except KeyError as exc:
            raise ValueError(
                f"command '{name}' needs a value for {{{exc.args[0]}}}"
            ) from None

    def spec_files(self) -> list[Path]:
        return sorted(self.root.glob(self.spec_glob)) if self.spec_glob else []

    def rubric_files(self) -> list[Path]:
        return sorted(self.root.glob(self.rubric_glob)) if self.rubric_glob else []


def loads_adapter(text: str, root: Path) -> ProjectAdapter:
    data = tomllib.loads(text)
    project = data.get("project", {})
    name = project.get("name", "")
    if not name:
        raise ValueError("adapter is missing [project] name")

    evidence = data.get("evidence", {})
    scenarios = data.get("scenarios", {})
    contract = evidence.get("contract")

    commands = data.get("commands", {})
    for cmd_name, cmd in commands.items():
        if not isinstance(cmd, str) or not cmd.strip():
            raise ValueError(f"command '{cmd_name}' must be a non-empty string")

    environment = data.get("environment", {})
    services = tuple(
        ServiceSpec(
            name=svc.get("name", ""),
            image=svc.get("image", ""),
            port=svc.get("port"),
            env=tuple(sorted((svc.get("env") or {}).items())),
        )
        for svc in environment.get("services", [])
    )
    for svc in services:
        if not svc.name or not svc.image:
            raise ValueError("[[environment.services]] entries need name and image")

    return ProjectAdapter(
        root=Path(root),
        name=name,
        app_image=environment.get("app_image", ""),
        app_port=int(environment.get("app_port", 8000)),
        environment_build=environment.get("build", ""),
        app_env=tuple(sorted((environment.get("app_env") or {}).items())),
        services=services,
        schema_version=str(
            data.get("schema_version", CURRENT_ADAPTER_SCHEMA_VERSION)
        ),
        commands=dict(commands),
        evidence_dir=Path(evidence.get("dir", "evidence")),
        contract_path=Path(contract) if contract else None,
        gates_path=Path(evidence.get("gates", "evidence-gates.json")),
        spec_glob=scenarios.get("spec_glob", ""),
        rubric_glob=scenarios.get("rubric_glob", ""),
        defaults=dict(data.get("defaults", {})),
    )


def load_adapter(path: Path) -> ProjectAdapter:
    path = Path(path)
    return loads_adapter(path.read_text(), root=path.parent)


def find_adapter(start: Path | None = None) -> Path | None:
    """Locate ``darkroom.toml`` in ``start`` or its parents (pyproject-style)."""
    current = Path(start) if start else Path.cwd()
    for candidate in [current, *current.parents]:
        adapter = candidate / ADAPTER_FILENAME
        if adapter.is_file():
            return adapter
    return None
