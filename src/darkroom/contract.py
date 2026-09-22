"""Evidence contracts: the declared capture requirements for scenarios.

A contract answers, before any judging happens, "did this run capture
enough to be judged?" It is deliberately a pure projection of what a
rubric's evidence declarations could generate — kinds, counts, named
steps, trial counts, nothing more — so that when rubric-derived
contracts arrive, existing contract files are exactly what derivation
would have emitted.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass, field
from pathlib import Path

if sys.version_info >= (3, 11):
    import tomllib
else:  # pragma: no cover - exercised only on 3.10
    import tomli as tomllib

CURRENT_CONTRACT_SCHEMA_VERSION = "1.0"


@dataclass(frozen=True)
class EvidenceRequirement:
    """One capture requirement within a scenario.

    ``trials`` is the statistical dimension: the number of supplied runs
    in which this requirement must be satisfied (1 for deterministic
    scenarios; higher for nondeterministic domains judged over a series).
    """

    kind: str
    min_count: int = 1
    steps: tuple[str, ...] = ()
    trials: int = 1

    def __post_init__(self):
        if not self.kind:
            raise ValueError("requirement is missing a kind")
        if self.min_count < 1:
            raise ValueError(f"min_count must be >= 1, got {self.min_count}")
        if self.trials < 1:
            raise ValueError(f"trials must be >= 1, got {self.trials}")


@dataclass
class ScenarioContract:
    scenario: str
    requirements: list[EvidenceRequirement] = field(default_factory=list)


@dataclass
class EvidenceContract:
    schema_version: str = CURRENT_CONTRACT_SCHEMA_VERSION
    project: str = ""
    scenarios: list[ScenarioContract] = field(default_factory=list)

    def for_scenario(self, name: str) -> ScenarioContract | None:
        for scenario in self.scenarios:
            if scenario.scenario == name:
                return scenario
        return None


def scoped_contract(
    contract: EvidenceContract | None, scenario: str | None
) -> EvidenceContract | None:
    """The contract narrowed to one scenario, for scenario-scoped runs.

    A run that deliberately exercised one scenario must not fail
    verification for the scenarios it never attempted. A scenario absent
    from the contract scopes to an empty contract (structural checks
    plus an uncontracted-scenario warning), never to the full one.
    """
    if contract is None or scenario is None:
        return contract
    selected = contract.for_scenario(scenario)
    return EvidenceContract(
        schema_version=contract.schema_version,
        project=contract.project,
        scenarios=[selected] if selected else [],
    )


def loads_contract(text: str) -> EvidenceContract:
    """Parse a TOML contract document."""
    data = tomllib.loads(text)

    scenarios = []
    for entry in data.get("scenario", []):
        name = entry.get("name", "")
        if not name:
            raise ValueError("contract scenario is missing a name")
        requirements = [
            EvidenceRequirement(
                kind=req.get("kind", ""),
                min_count=req.get("min_count", 1),
                steps=tuple(req.get("steps", ())),
                trials=req.get("trials", 1),
            )
            for req in entry.get("requires", [])
        ]
        scenarios.append(ScenarioContract(scenario=name, requirements=requirements))

    return EvidenceContract(
        schema_version=str(data.get("schema_version", CURRENT_CONTRACT_SCHEMA_VERSION)),
        project=data.get("project", ""),
        scenarios=scenarios,
    )


def load_contract(path: Path) -> EvidenceContract:
    """Load a TOML contract file."""
    return loads_contract(Path(path).read_text())
