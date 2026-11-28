"""Peak gates: per-scenario high-water marks with retreat points.

A gate asserts that no future run ships a scenario below its recorded
peak. Each :class:`PeakRecord` carries the evidence (``run_id``), the
retreat point (``commit``), and the ``rubric_version`` that scored it —
peaks are only comparable under the same rubric version, so a version
mismatch reports ``stale-peak`` (re-baseline needed), never
``regression``. A red gate must always mean something real.

``check_gates`` and ``update_gates`` are pure functions; the gates file
is committed JSON, so deliberate gate edits stay visible in history.

``provenance_findings`` inspects what an evaluation says about its own
making before a peak is ratcheted from it — the commit it was judged
against, whether that tree was clean, whether the rubric version it
claims is the one it was handed. A peak is a claim about a commit, and
these are the ways that claim can be false by accident: scoring a
three-day-old manifest, or ratcheting from a tree with uncommitted work
in it. They are findings rather than refusals by default; see
``darkroom gate update --strict-provenance``.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from darkroom.evaluation import Evaluation

CURRENT_GATES_SCHEMA_VERSION = "1.0"


@dataclass(frozen=True)
class PeakRecord:
    scenario: str
    score: float  # 0-100
    run_id: str
    recorded_at: datetime
    rubric_version: str = ""
    commit: str = ""


@dataclass
class GateFile:
    schema_version: str = CURRENT_GATES_SCHEMA_VERSION
    project: str = ""
    peaks: list[PeakRecord] = field(default_factory=list)

    def peak_for(self, scenario: str) -> PeakRecord | None:
        for peak in self.peaks:
            if peak.scenario == scenario:
                return peak
        return None


@dataclass(frozen=True)
class GateFinding:
    kind: str  # "regression" | "stale-peak" | "new-peak" | "held" | "ungated"
    scenario: str
    message: str
    score: float | None = None
    peak: PeakRecord | None = None


def has_regressions(findings: list[GateFinding]) -> bool:
    return any(f.kind == "regression" for f in findings)


@dataclass(frozen=True)
class ProvenanceFinding:
    kind: str  # "no-provenance" | "commit-mismatch" | "dirty-tree"
    #          | "rubric-version-mismatch"
    message: str


def provenance_findings(
    evaluation: Evaluation, commit: str = ""
) -> list[ProvenanceFinding]:
    """Ways the peak about to be recorded could misdescribe its evidence.

    Pure; reports and decides nothing. Checks only what the evaluation
    carries: no vault is opened and no repository is inspected, so this
    is as honest as the file — which is the trust boundary gates have
    always had, since ``gate update`` takes an evaluation by path.
    """
    provenance = evaluation.provenance or {}
    findings: list[ProvenanceFinding] = []

    if commit and not provenance:
        findings.append(
            ProvenanceFinding(
                "no-provenance",
                (
                    "the evaluation carries no provenance, so nothing ties "
                    f"it to commit {commit[:12]} — it predates evaluation "
                    "schema 1.1 or came from a scorer that stamps none"
                ),
            )
        )

    judged_at = str(provenance.get("tenant_commit", ""))
    if commit and judged_at and judged_at != commit:
        findings.append(
            ProvenanceFinding(
                "commit-mismatch",
                (
                    f"the evidence was judged against commit "
                    f"{judged_at[:12]}, but the peak would record "
                    f"{commit[:12]}"
                ),
            )
        )

    if provenance.get("tenant_dirty"):
        findings.append(
            ProvenanceFinding(
                "dirty-tree",
                (
                    "the tenant had uncommitted changes when this was "
                    "judged, so no commit fully describes the evidence"
                ),
            )
        )

    sealed = {
        str(version)
        for version in (provenance.get("rubric_versions") or {}).values()
        if str(version)
    }
    if sealed and evaluation.rubric_version and evaluation.rubric_version not in sealed:
        findings.append(
            ProvenanceFinding(
                "rubric-version-mismatch",
                (
                    f"the evaluation claims rubric version "
                    f"'{evaluation.rubric_version}'; the sealed rubric it "
                    f"was judged against was at "
                    f"{', '.join(repr(v) for v in sorted(sealed))}"
                ),
            )
        )
    return findings


# --- serialization --------------------------------------------------------


def dumps_gates(gates: GateFile) -> str:
    return json.dumps(
        {
            "schema_version": gates.schema_version,
            "project": gates.project,
            "peaks": [
                {
                    "scenario": p.scenario,
                    "score": p.score,
                    "run_id": p.run_id,
                    "recorded_at": p.recorded_at.isoformat(),
                    "rubric_version": p.rubric_version,
                    "commit": p.commit,
                }
                for p in sorted(gates.peaks, key=lambda p: p.scenario)
            ],
        },
        indent=2,
    )


def dump_gates(gates: GateFile, path: Path) -> None:
    Path(path).write_text(dumps_gates(gates))


def loads_gates(text: str) -> GateFile:
    data = json.loads(text)
    return GateFile(
        schema_version=data.get("schema_version", CURRENT_GATES_SCHEMA_VERSION),
        project=data.get("project", ""),
        peaks=[
            PeakRecord(
                scenario=p["scenario"],
                score=p["score"],
                run_id=p.get("run_id", ""),
                recorded_at=datetime.fromisoformat(p["recorded_at"]),
                rubric_version=p.get("rubric_version", ""),
                commit=p.get("commit", ""),
            )
            for p in data.get("peaks", [])
        ],
    )


def load_gates(path: Path) -> GateFile:
    return loads_gates(Path(path).read_text())


# --- gate logic -----------------------------------------------------------


def _scenario_scores(evaluation: Evaluation) -> list[tuple[str, float | None]]:
    scores = []
    for scenario in evaluation.scenarios:
        possible = scenario.points_possible
        score = 100.0 * scenario.points_earned / possible if possible else None
        scores.append((scenario.scenario, score))
    return scores


def check_gates(gates: GateFile, evaluation: Evaluation) -> list[GateFinding]:
    """Compare an evaluation against recorded peaks. Pure; changes nothing."""
    findings = []
    for name, score in _scenario_scores(evaluation):
        if score is None:
            findings.append(
                GateFinding("ungated", name, "no scored criteria; skipped")
            )
            continue
        peak = gates.peak_for(name)
        if peak is None:
            findings.append(
                GateFinding(
                    "ungated", name, f"no recorded peak (scored {score:.1f})",
                    score=score,
                )
            )
        elif peak.rubric_version != evaluation.rubric_version:
            findings.append(
                GateFinding(
                    "stale-peak",
                    name,
                    (
                        f"peak {peak.score:.1f} was scored under rubric "
                        f"'{peak.rubric_version}', evaluation under "
                        f"'{evaluation.rubric_version}' — re-baseline with "
                        "gate update"
                    ),
                    score=score,
                    peak=peak,
                )
            )
        elif score < peak.score:
            findings.append(
                GateFinding(
                    "regression",
                    name,
                    (
                        f"scored {score:.1f}, below peak {peak.score:.1f} "
                        f"(run {peak.run_id}"
                        + (f", commit {peak.commit}" if peak.commit else "")
                        + ")"
                    ),
                    score=score,
                    peak=peak,
                )
            )
        else:
            findings.append(
                GateFinding(
                    "held",
                    name,
                    f"scored {score:.1f}, at or above peak {peak.score:.1f}",
                    score=score,
                    peak=peak,
                )
            )
    return findings


def update_gates(
    gates: GateFile,
    evaluation: Evaluation,
    commit: str = "",
) -> tuple[GateFile, list[GateFinding]]:
    """Ratchet peaks upward from an evaluation; returns the new gate file.

    A rubric-version mismatch re-baselines (the new score becomes the
    peak under the new version). A same-rubric score below peak keeps the
    old peak and reports the regression. Scenarios absent from the
    evaluation keep their peaks untouched.
    """
    findings = check_gates(gates, evaluation)
    updated = {p.scenario: p for p in gates.peaks}
    now = datetime.now()

    for finding in findings:
        if finding.kind in ("ungated", "stale-peak") and finding.score is not None:
            updated[finding.scenario] = PeakRecord(
                scenario=finding.scenario,
                score=finding.score,
                run_id=evaluation.run_id,
                recorded_at=now,
                rubric_version=evaluation.rubric_version,
                commit=commit,
            )
        elif finding.kind == "held" and finding.score is not None:
            peak = finding.peak
            if peak is None or finding.score >= peak.score:
                updated[finding.scenario] = PeakRecord(
                    scenario=finding.scenario,
                    score=finding.score,
                    run_id=evaluation.run_id,
                    recorded_at=now,
                    rubric_version=evaluation.rubric_version,
                    commit=commit,
                )

    new_gates = GateFile(
        schema_version=gates.schema_version,
        project=gates.project or evaluation.project,
        peaks=list(updated.values()),
    )
    return new_gates, findings
