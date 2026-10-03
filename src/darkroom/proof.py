"""Proofs: the sealed exam as one file — exposure and rubric together.

A proof holds, for one scenario, the steps that expose the system under
test (the exposure) and the criteria that score what the exposure
produced (the rubric). They were always one secret with one lifecycle;
drive scripts and vault rubrics kept them in two files only because
drives arrived two releases after rubrics. In a proof a criterion's
``witnesses`` resolve inside the same file, a cited step that does not
exist is a load error rather than a judge-time surprise, and the
evidence kinds a criterion rests on are derived from the steps it cites
instead of being restated.

Format (``<scenario>.proof.toml``, in the operator home's ``proofs/``)::

    scenario = "deletion_guarded"
    version = "1"                 # the rubric's version: bump when the
                                  # standard changes, not the mechanics
    include = ["founded"]         # optional preludes, expanded first
    [serve]  ...                  # optional overrides of [serve.defaults]
    [browser] ...                 # optional overrides of [browser.defaults]

    [[step]]                      # kind defaults to "http"
    name = "create"
    method = "POST"
    url = "{base_url}/notes"
    save = { note_id = "$.id" }

    [[criterion]]
    id = "created"
    points = 10
    description = "a note is created with an id"
    witnesses = ["create"]        # evidence derived: http_transcript

The judge still receives rubric-shaped text; :func:`rubric_text` renders
exactly the criteria (never the steps), so judging code is untouched.
"""

from __future__ import annotations

import sys
from pathlib import Path

if sys.version_info >= (3, 11):
    import tomllib
else:  # pragma: no cover - exercised only on 3.10
    import tomli as tomllib

from darkroom.contract import EvidenceContract, EvidenceRequirement, ScenarioContract
from darkroom.preludes import PreludeError, expand

PROOF_SUFFIX = ".proof.toml"

# what a step kind records, hence what a criterion citing it rests on
STEP_EVIDENCE: dict[str, str | None] = {
    "http": "http_transcript",
    "command": "command_transcript",
    "screenshot": "screenshot",
    "assert": "log",
    "goto": "log",
    "click": "log",
    "fill": "log",
    "container": "log",
    "wait": None,
    "keygen": None,
}


class ProofError(Exception):
    pass


def loads_proof(text: str, name: str = "proof") -> dict:
    """Parse and validate a proof; returns it as written (includes not yet
    expanded — see :func:`steps`)."""
    proof = tomllib.loads(text)
    scenario = proof.get("scenario")
    if not scenario:
        raise ProofError(f"{name}: a proof needs a scenario")
    criteria = proof.get("criterion", [])
    if not criteria:
        raise ProofError(f"{name}: a proof needs at least one [[criterion]]")
    ids: set[str] = set()
    for criterion in criteria:
        cid = criterion.get("id")
        if not cid:
            raise ProofError(f"{name}: every criterion needs an id")
        if cid in ids:
            raise ProofError(f"{name}: criterion '{cid}' is defined twice")
        ids.add(cid)
        if not isinstance(criterion.get("points"), (int, float)):
            raise ProofError(f"{name}: criterion '{cid}' needs numeric points")
        if not criterion.get("witnesses"):
            raise ProofError(
                f"{name}: criterion '{cid}' cites no witnesses — name the steps "
                "whose records prove it"
            )
    for step in proof.get("step", []):
        step.setdefault("kind", "http")
    return proof


def load_proof(path: Path) -> dict:
    return loads_proof(Path(path).read_text(), Path(path).name)


def steps(proof: dict, preludes: dict[str, list[dict]] | None = None) -> list[dict]:
    """The exposure: the proof's steps with its includes expanded."""
    try:
        return expand(proof, preludes or {}).get("step", [])
    except PreludeError as exc:
        raise ProofError(str(exc)) from None


def exposure(proof: dict, preludes: dict[str, list[dict]] | None = None) -> dict:
    """The proof as a drive-shaped script the engine can run: scenario,
    serve/browser overrides, record flag, and the expanded steps."""
    script = {k: v for k, v in proof.items() if k not in ("criterion", "version")}
    script["step"] = steps(proof, preludes)
    script.pop("include", None)
    return script


def _evidence_for(criterion: dict, by_name: dict[str, dict]) -> list[str]:
    declared = criterion.get("evidence")
    if declared:
        return list(declared)
    kinds: list[str] = []
    for cited in criterion.get("witnesses", []):
        step = by_name.get(cited)
        if step is None:
            continue
        kind = STEP_EVIDENCE.get(step.get("kind", "http"))
        if step.get("expect") and "log" not in kinds:
            kinds.append("log")  # the expectation witness is a log record
        if kind and kind not in kinds:
            kinds.append(kind)
    return kinds


def rubric(proof: dict, preludes: dict[str, list[dict]] | None = None) -> dict:
    """The rubric half, in the shape judge and evaluation code already read:
    scenario, version, trials, and criteria with their evidence kinds."""
    by_name = {s.get("name"): s for s in steps(proof, preludes) if s.get("name")}
    for criterion in proof.get("criterion", []):
        for cited in criterion.get("witnesses", []):
            if cited not in by_name:
                raise ProofError(
                    f"{proof['scenario']}: criterion '{criterion['id']}' cites "
                    f"witness '{cited}' but no step has that name"
                )
    return {
        "scenario": proof["scenario"],
        "feature_id": proof["scenario"].replace("_", "-"),
        "version": str(proof.get("version", "1")),
        "trials": int(proof.get("trials", 1)),
        "criterion": [
            {**criterion, "evidence": _evidence_for(criterion, by_name)}
            for criterion in proof["criterion"]
        ],
    }


def _toml_string(value: str) -> str:
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'


def rubric_text(proof: dict, preludes: dict[str, list[dict]] | None = None) -> str:
    """The rubric rendered as TOML — what a vault hands the judge. The
    steps are deliberately absent: the judge scores records, never the
    exposure that produced them."""
    data = rubric(proof, preludes)
    lines = [
        f"feature_id = {_toml_string(data['feature_id'])}",
        f"version = {_toml_string(data['version'])}",
        f"scenario = {_toml_string(data['scenario'])}",
    ]
    if data["trials"] != 1:
        lines.append(f"trials = {data['trials']}")
    for criterion in data["criterion"]:
        lines += ["", "[[criterion]]", f"id = {_toml_string(str(criterion['id']))}"]
        lines.append(f"points = {criterion['points']}")
        if "description" in criterion:
            lines.append(f"description = {_toml_string(str(criterion['description']))}")
        if criterion.get("confidence"):
            lines.append(f"confidence = {_toml_string(str(criterion['confidence']))}")
        kinds = ", ".join(_toml_string(k) for k in criterion["evidence"])
        lines.append(f"evidence = [{kinds}]")
        witnesses = ", ".join(_toml_string(w) for w in criterion.get("witnesses", []))
        lines.append(f"witnesses = [{witnesses}]")
    return "\n".join(lines) + "\n"


def derive_contract(
    proofs: list[dict], project: str = "", preludes: dict[str, list[dict]] | None = None
) -> EvidenceContract:
    """The evidence contract every proof implies: per scenario, the kinds
    its criteria rest on — derived, so nothing need be committed."""
    scenarios = []
    for proof in proofs:
        data = rubric(proof, preludes)
        kinds: list[str] = []
        for criterion in data["criterion"]:
            for kind in criterion["evidence"]:
                if kind not in kinds:
                    kinds.append(kind)
        scenarios.append(
            ScenarioContract(
                scenario=data["scenario"],
                requirements=[
                    EvidenceRequirement(kind=kind, trials=data["trials"]) for kind in kinds
                ],
            )
        )
    return EvidenceContract(project=project, scenarios=scenarios)


def load_proofs(proofs_dir: Path) -> dict[str, dict]:
    """Every proof in a directory, keyed by scenario."""
    found: dict[str, dict] = {}
    for path in sorted(Path(proofs_dir).glob(f"*{PROOF_SUFFIX}")):
        proof = load_proof(path)
        found[proof["scenario"]] = proof
    return found
