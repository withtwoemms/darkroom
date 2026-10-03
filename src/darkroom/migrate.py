"""``darkroom migrate``: drive + rubric pairs become proofs, mechanically.

Each ``drives/<scenario>.drive.toml`` is paired with the vault rubric
whose ``scenario`` names it; the pair becomes one
``proofs/<scenario>.proof.toml``. Along the way the restatements go:
``kind = "http"`` (the default), ``feature_id`` (derived from the
scenario), and a criterion's ``evidence`` when the steps it cites imply
exactly that list. The rubric's ``version`` and ``trials`` are carried.
Serve keys that are identical across nearly every drive are reported as
a ``[serve.defaults]`` block for darkroom.toml — a suggestion, since a
stripped key only means what the adapter says it means.

The tenant is never touched: inputs are the operator home's drives and
vault, the output is its ``proofs/`` directory.
"""

from __future__ import annotations

import sys
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

if sys.version_info >= (3, 11):
    import tomllib
else:  # pragma: no cover - exercised only on 3.10
    import tomli as tomllib

from darkroom.drive import DRIVE_SUFFIX
from darkroom.proof import PROOF_SUFFIX, ProofError, loads_proof, rubric
from darkroom.tomlout import dumps_toml
from darkroom.vault import RUBRIC_SUFFIX


class MigrateError(Exception):
    pass


@dataclass
class MigrationPlan:
    proofs: dict[str, dict] = field(default_factory=dict)  # scenario -> proof
    unpaired_drives: list[str] = field(default_factory=list)
    unpaired_rubrics: list[str] = field(default_factory=list)
    problems: dict[str, str] = field(default_factory=dict)  # scenario -> why
    serve_defaults: dict[str, object] = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return not (self.unpaired_drives or self.unpaired_rubrics or self.problems)

    def text(self, scenario: str) -> str:
        return dumps_toml(self.proofs[scenario])


def _load_toml(path: Path) -> dict:
    return tomllib.loads(path.read_text())


def _strip_default_kinds(steps: list[dict]) -> list[dict]:
    return [
        {k: v for k, v in step.items() if not (k == "kind" and v == "http")} for step in steps
    ]


def _merge(
    drive: dict, rubric_data: dict, preludes: dict[str, list[dict]] | None = None
) -> dict:
    """One proof from a drive and the rubric scoring it, restatements gone."""
    proof: dict = {"scenario": drive["scenario"]}
    version = str(rubric_data.get("version", "1"))
    proof["version"] = version
    if int(rubric_data.get("trials", 1)) != 1:
        proof["trials"] = int(rubric_data["trials"])
    for key, value in drive.items():
        if key in ("scenario", "step"):
            continue
        proof[key] = value  # include, serve, browser, record, ...
    proof["step"] = _strip_default_kinds(drive.get("step", []))
    proof["criterion"] = [dict(c) for c in rubric_data.get("criterion", [])]

    # a criterion whose cited steps imply exactly its declared evidence
    # need not restate it; one that cites nothing keeps its declaration.
    # the probe drops the declarations so the derivation is from witnesses
    probe = dict(proof)
    probe["criterion"] = [
        {k: v for k, v in c.items() if k != "evidence"} if c.get("witnesses") else c
        for c in proof["criterion"]
    ]
    derived = rubric(loads_proof(dumps_toml(probe)), preludes)
    for criterion, scored in zip(proof["criterion"], derived["criterion"], strict=True):
        if criterion.get("witnesses") and set(criterion.get("evidence", [])) == set(
            scored["evidence"]
        ):
            criterion.pop("evidence", None)
    return proof


def suggest_serve_defaults(drives: list[dict], threshold: float = 0.9) -> dict[str, object]:
    """Serve keys carrying the same value in at least ``threshold`` of the
    drives that set them — and set in at least that share of all drives."""
    if not drives:
        return {}
    counts: dict[str, Counter] = {}
    for drive in drives:
        for key, value in (drive.get("serve") or {}).items():
            counts.setdefault(key, Counter())[repr(value)] = (
                counts.setdefault(key, Counter()).get(repr(value), 0) + 1
            )
    suggested: dict[str, object] = {}
    for key, tally in counts.items():
        (common, n), = tally.most_common(1)
        if n / len(drives) >= threshold:
            for drive in drives:
                value = (drive.get("serve") or {}).get(key)
                if repr(value) == common:
                    suggested[key] = value
                    break
    return suggested


def plan_migration(
    drives_dir: Path,
    vault_dir: Path,
    threshold: float = 0.9,
    preludes: dict[str, list[dict]] | None = None,
) -> MigrationPlan:
    plan = MigrationPlan()
    drives: dict[str, dict] = {}
    for path in sorted(Path(drives_dir).glob(f"*{DRIVE_SUFFIX}")):
        data = _load_toml(path)
        scenario = data.get("scenario") or path.name[: -len(DRIVE_SUFFIX)]
        drives[scenario] = data
    rubrics: dict[str, tuple[str, dict]] = {}
    for path in sorted(Path(vault_dir).glob(f"*{RUBRIC_SUFFIX}")):
        data = _load_toml(path)
        feature_id = path.name[: -len(RUBRIC_SUFFIX)]
        rubrics[data.get("scenario", feature_id.replace("-", "_"))] = (feature_id, data)

    for scenario, drive in drives.items():
        if scenario not in rubrics:
            plan.unpaired_drives.append(scenario)
            continue
        try:
            plan.proofs[scenario] = _merge(drive, rubrics[scenario][1], preludes)
            rubric(loads_proof(plan.text(scenario), f"{scenario}{PROOF_SUFFIX}"), preludes)
        except (ProofError, TypeError, ValueError) as exc:
            plan.problems[scenario] = str(exc)
    plan.unpaired_rubrics = [
        feature_id for scenario, (feature_id, _) in rubrics.items() if scenario not in drives
    ]
    plan.serve_defaults = suggest_serve_defaults(list(drives.values()), threshold)
    return plan


def apply_serve_defaults(plan: MigrationPlan) -> None:
    """Drop every serve key a proof sets to the suggested default — only
    sound once darkroom.toml carries that ``[serve.defaults]`` block."""
    for proof in plan.proofs.values():
        serve = proof.get("serve")
        if not serve:
            continue
        kept = {
            k: v
            for k, v in serve.items()
            if not (k in plan.serve_defaults and repr(v) == repr(plan.serve_defaults[k]))
        }
        if kept:
            proof["serve"] = kept
        else:
            proof.pop("serve")


def write_migration(plan: MigrationPlan, out_dir: Path, force: bool = False) -> list[Path]:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    written = []
    for scenario in plan.proofs:
        target = out_dir / f"{scenario}{PROOF_SUFFIX}"
        if target.exists() and not force:
            raise MigrateError(f"{target} exists; pass --force to overwrite")
    for scenario in plan.proofs:
        target = out_dir / f"{scenario}{PROOF_SUFFIX}"
        target.write_text(plan.text(scenario))
        written.append(target)
    out_dir.chmod(0o700)
    return written


def defaults_block(serve_defaults: dict[str, object]) -> str:
    """The ``[serve.defaults]`` block to paste into darkroom.toml."""
    if not serve_defaults:
        return ""
    text = dumps_toml({"serve.defaults": serve_defaults})
    return text.replace('["serve.defaults"]', "[serve.defaults]")
