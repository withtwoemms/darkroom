"""Proofs: the sealed exam for one scenario, as a folder of two files.

A proof holds the steps that expose the system under test (the
**exposure**, QA's file) and the criteria that score what the exposure
produced (the **rubric**, product's file). They share a lifecycle and a
folder, not an author — which is why they are two files rather than
one: each hat edits its own, and a diff to the standard never hides in
a diff to the mechanics. A criterion's ``witnesses`` resolve against
the exposure beside it, a cited step that does not exist is a load
error rather than a judge-time surprise, and the evidence kinds a
criterion rests on are derived from the steps it cites instead of
being restated.

Layout (``proofs/<scenario>/`` in the operator home)::

    exposure.toml                 # QA
      scenario = "deletion_guarded"
      backdrop = ["noted"]        # optional backdrops, expanded first
      [serve]  ...                # optional overrides of [serve.defaults]
      [browser] ...               # optional overrides of [browser.defaults]
      [[step]]                    # kind defaults to "http"
      name = "create"
      method = "POST"
      url = "{base_url}/notes"
      save = { note_id = "$.id" }

    rubric.toml                   # product
      version = "1"               # bump when the standard changes
      [[criterion]]
      id = "created"
      points = 10
      description = "a note is created and answers with its id"
      witnesses = ["create"]      # evidence derived: http_transcript

In memory the two halves are one dict (the exposure's keys plus
``version``, ``trials``, ``criterion``), so everything downstream reads
a proof the way it read a drive script with a rubric beside it. The
judge still receives rubric-shaped text; :func:`rubric_text` renders
exactly the criteria (never the steps), so judging code is untouched.
"""

from __future__ import annotations

import sys
from pathlib import Path

if sys.version_info >= (3, 11):
    import tomllib
else:  # pragma: no cover - exercised only on 3.10
    import tomli as tomllib

from darkroom.backdrops import BackdropError, expand
from darkroom.contract import EvidenceContract, EvidenceRequirement, ScenarioContract

EXPOSURE_FILE = "exposure.toml"
RUBRIC_FILE = "rubric.toml"

# the exposure's keys; everything else in a merged proof is the rubric's
EXPOSURE_KEYS = frozenset(
    {"scenario", "backdrop", "serve", "browser", "environment", "record", "step"}
)

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


def has_rubric(proof: dict) -> bool:
    """Whether the proof carries its rubric. A folder may hold the exposure
    alone while the exam is being written — it can be exposed, but not
    sealed, audited, judged, or held to a contract — and ``rubric_text``
    and friends refuse it by name."""
    return bool(proof.get("criterion"))


def validate_proof(proof: dict, name: str = "proof", rubric_required: bool = True) -> dict:
    """Check a merged proof's shape; returns it with step kinds defaulted
    (backdrops not yet expanded — see :func:`steps`)."""
    scenario = proof.get("scenario")
    if not scenario:
        raise ProofError(f"{name}: a proof needs a scenario")
    criteria = proof.get("criterion", [])
    if not criteria and rubric_required:
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
        if not criterion.get("witnesses") and not criterion.get("evidence"):
            raise ProofError(
                f"{name}: criterion '{cid}' cites no witnesses — name the steps "
                "whose records prove it (or declare the evidence kinds it rests on)"
            )
    for step in proof.get("step", []):
        step.setdefault("kind", "http")
    return proof


def loads_proof(exposure_text: str, rubric_text: str | None, name: str = "proof") -> dict:
    """Parse the two halves and validate them as one proof. ``rubric_text``
    may be None for a folder that holds the exposure alone."""
    try:
        exposure_data = tomllib.loads(exposure_text)
    except tomllib.TOMLDecodeError as exc:
        raise ProofError(f"{name}/{EXPOSURE_FILE}: {exc}") from None
    if rubric_text is None:
        for key in exposure_data:
            if key in ("criterion", "version", "trials"):
                raise ProofError(
                    f"{name}/{EXPOSURE_FILE}: '{key}' belongs to the rubric — put it "
                    f"in {RUBRIC_FILE} beside the exposure"
                )
        return validate_proof(dict(exposure_data), name, rubric_required=False)
    try:
        rubric_data = tomllib.loads(rubric_text)
    except tomllib.TOMLDecodeError as exc:
        raise ProofError(f"{name}/{RUBRIC_FILE}: {exc}") from None
    for key in rubric_data:
        if key in EXPOSURE_KEYS and key != "scenario":
            raise ProofError(
                f"{name}/{RUBRIC_FILE}: '{key}' belongs to the exposure — the rubric "
                "scores records, it does not drive"
            )
    for key in exposure_data:
        if key in ("criterion", "version", "trials"):
            raise ProofError(
                f"{name}/{EXPOSURE_FILE}: '{key}' belongs to the rubric — the exposure "
                "produces records, it does not score them"
            )
    declared = rubric_data.get("scenario")
    if declared and declared != exposure_data.get("scenario"):
        raise ProofError(
            f"{name}: {RUBRIC_FILE} names scenario '{declared}' but {EXPOSURE_FILE} "
            f"is '{exposure_data.get('scenario')}'"
        )
    merged = dict(exposure_data)
    merged.update({k: v for k, v in rubric_data.items() if k != "scenario"})
    return validate_proof(merged, name)


def is_proof(folder: Path) -> bool:
    folder = Path(folder)
    return folder.is_dir() and (folder / EXPOSURE_FILE).is_file()


def proof_dirs(proofs_dir: Path) -> list[Path]:
    """Every proof folder under a proofs directory, sorted by name."""
    proofs_dir = Path(proofs_dir)
    if not proofs_dir.is_dir():
        return []
    return sorted(p for p in proofs_dir.iterdir() if is_proof(p))


def load_proof(folder: Path) -> dict:
    folder = Path(folder)
    exposure_path = folder / EXPOSURE_FILE
    rubric_path = folder / RUBRIC_FILE
    if not exposure_path.is_file():
        raise ProofError(f"{folder.name}: no {EXPOSURE_FILE} — a proof folder needs the exposure")
    rubric_text_ = rubric_path.read_text() if rubric_path.is_file() else None
    proof = loads_proof(exposure_path.read_text(), rubric_text_, folder.name)
    if proof["scenario"] != folder.name:
        raise ProofError(
            f"{folder.name}: the exposure names scenario '{proof['scenario']}' — "
            "a proof folder is named after its scenario"
        )
    return proof


def load_proofs(proofs_dir: Path) -> dict[str, dict]:
    """Every proof in a directory, keyed by scenario."""
    found: dict[str, dict] = {}
    for folder in proof_dirs(proofs_dir):
        proof = load_proof(folder)
        found[proof["scenario"]] = proof
    return found


def split_proof(proof: dict) -> tuple[dict, dict]:
    """The two halves of a merged proof, as they are written to disk."""
    exposure_half = {k: v for k, v in proof.items() if k in EXPOSURE_KEYS}
    rubric_half = {k: v for k, v in proof.items() if k not in EXPOSURE_KEYS}
    return exposure_half, rubric_half


def exposure_source(proof: dict) -> str:
    """``exposure.toml`` for a merged proof."""
    from darkroom.tomlout import dumps_toml

    exposure_half, _ = split_proof(proof)
    return dumps_toml(exposure_half)


def rubric_source(proof: dict) -> str:
    """``rubric.toml`` for a merged proof — the file product edits, not
    the rendering the judge is handed (see :func:`rubric_text`)."""
    from darkroom.tomlout import dumps_toml

    _, rubric_half = split_proof(proof)
    ordered = {"version": str(rubric_half.get("version", "1"))}
    ordered.update({k: v for k, v in rubric_half.items() if k != "version"})
    return dumps_toml(ordered)


def steps(proof: dict, backdrops: dict[str, list[dict]] | None = None) -> list[dict]:
    """The exposure's steps with its backdrops expanded."""
    try:
        return expand(proof, backdrops or {}).get("step", [])
    except BackdropError as exc:
        raise ProofError(str(exc)) from None


def exposure(proof: dict, backdrops: dict[str, list[dict]] | None = None) -> dict:
    """The proof as a drive-shaped script the engine can run: scenario,
    serve/browser overrides, record flag, and the expanded steps."""
    script = {k: v for k, v in proof.items() if k in EXPOSURE_KEYS}
    script["step"] = steps(proof, backdrops)
    script.pop("backdrop", None)
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


def rubric(proof: dict, backdrops: dict[str, list[dict]] | None = None) -> dict:
    """The rubric half, in the shape judge and evaluation code already read:
    scenario, version, trials, and criteria with their evidence kinds."""
    if not has_rubric(proof):
        raise ProofError(
            f"{proof['scenario']}: no {RUBRIC_FILE} — the exposure can run, but nothing "
            "says what a good record shows"
        )
    by_name = {s.get("name"): s for s in steps(proof, backdrops) if s.get("name")}
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


def rubric_text(proof: dict, backdrops: dict[str, list[dict]] | None = None) -> str:
    """The rubric rendered as TOML — what a vault hands the judge. The
    steps are deliberately absent: the judge scores records, never the
    exposure that produced them."""
    data = rubric(proof, backdrops)
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


def provenance(folder: Path, proof: dict) -> dict[str, str]:
    """What a run of this proof exposed and will be judged by: the
    exposure file's digest and the rubric's version — recorded in the
    manifest so a verdict names the exam it answered."""
    import hashlib

    digest = hashlib.sha256((Path(folder) / EXPOSURE_FILE).read_bytes()).hexdigest()
    return {"exposure_sha256": digest, "rubric_version": str(proof.get("version", "1"))}


def derive_contract(
    proofs: list[dict], project: str = "", backdrops: dict[str, list[dict]] | None = None
) -> EvidenceContract:
    """The evidence contract every proof implies: per scenario, the kinds
    its criteria rest on — derived, so nothing need be committed. A proof
    without its rubric implies nothing and is left out."""
    scenarios = []
    for proof in proofs:
        if not has_rubric(proof):
            continue
        data = rubric(proof, backdrops)
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
