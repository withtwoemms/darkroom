"""Typed evaluation records: the judge's side of the manifest handoff.

An :class:`Evaluation` is what a judge (or any scorer) hands back for a
run. Two loading paths exist deliberately:

- ``loads_evaluation`` / ``load_evaluation`` — strict, for documents
  darkroom itself wrote.
- ``coerce_evaluation`` / ``normalize_percentage`` — lenient, absorbing
  the drift LLM judges actually produce (percentages on a 0-1 scale,
  ``overall_score`` / ``pass_rate`` synonyms, criteria as mappings or
  lists, numbers as strings) into one typed place.

Scores are percentages on a 0-100 scale. ``rubric_version`` records what
"good" meant at scoring time: evaluations are only comparable under the
same rubric version.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

CURRENT_EVALUATION_SCHEMA_VERSION = "1.0"


@dataclass(frozen=True)
class CriterionResult:
    criterion: str
    passed: bool
    points_earned: float
    points_possible: float
    evidence: tuple[str, ...] = ()  # manifest item paths cited as basis
    notes: str = ""


@dataclass
class ScenarioEvaluation:
    scenario: str
    criteria: list[CriterionResult] = field(default_factory=list)

    @property
    def points_earned(self) -> float:
        return sum(c.points_earned for c in self.criteria)

    @property
    def points_possible(self) -> float:
        return sum(c.points_possible for c in self.criteria)

    @property
    def passed(self) -> bool:
        return bool(self.criteria) and all(c.passed for c in self.criteria)


@dataclass
class Evaluation:
    run_id: str
    evaluated_at: datetime
    schema_version: str = CURRENT_EVALUATION_SCHEMA_VERSION
    project: str = ""
    rubric_version: str = ""
    scenarios: list[ScenarioEvaluation] = field(default_factory=list)
    notes: str = ""

    @property
    def total_earned(self) -> float:
        return sum(s.points_earned for s in self.scenarios)

    @property
    def total_possible(self) -> float:
        return sum(s.points_possible for s in self.scenarios)

    @property
    def percentage(self) -> float:
        """Overall score, 0-100. An evaluation with no points is 0.0."""
        if self.total_possible == 0:
            return 0.0
        return 100.0 * self.total_earned / self.total_possible

    @property
    def all_passed(self) -> bool:
        return bool(self.scenarios) and all(s.passed for s in self.scenarios)

    def for_scenario(self, name: str) -> ScenarioEvaluation | None:
        for scenario in self.scenarios:
            if scenario.scenario == name:
                return scenario
        return None


# --- strict serialization -------------------------------------------------


def dumps_evaluation(evaluation: Evaluation) -> str:
    return json.dumps(
        {
            "schema_version": evaluation.schema_version,
            "run_id": evaluation.run_id,
            "evaluated_at": evaluation.evaluated_at.isoformat(),
            "project": evaluation.project,
            "rubric_version": evaluation.rubric_version,
            "notes": evaluation.notes,
            "summary": {
                "total_earned": evaluation.total_earned,
                "total_possible": evaluation.total_possible,
                "percentage": evaluation.percentage,
                "all_passed": evaluation.all_passed,
            },
            "scenarios": [
                {
                    "scenario": s.scenario,
                    "criteria": [
                        {
                            "criterion": c.criterion,
                            "passed": c.passed,
                            "points_earned": c.points_earned,
                            "points_possible": c.points_possible,
                            "evidence": list(c.evidence),
                            "notes": c.notes,
                        }
                        for c in s.criteria
                    ],
                }
                for s in evaluation.scenarios
            ],
        },
        indent=2,
    )


def dump_evaluation(evaluation: Evaluation, path: Path) -> None:
    Path(path).write_text(dumps_evaluation(evaluation))


def loads_evaluation(text: str) -> Evaluation:
    data = json.loads(text)
    return Evaluation(
        run_id=data["run_id"],
        evaluated_at=datetime.fromisoformat(data["evaluated_at"]),
        schema_version=data.get(
            "schema_version", CURRENT_EVALUATION_SCHEMA_VERSION
        ),
        project=data.get("project", ""),
        rubric_version=data.get("rubric_version", ""),
        notes=data.get("notes", ""),
        scenarios=[
            ScenarioEvaluation(
                scenario=s["scenario"],
                criteria=[
                    CriterionResult(
                        criterion=c["criterion"],
                        passed=c["passed"],
                        points_earned=c["points_earned"],
                        points_possible=c["points_possible"],
                        evidence=tuple(c.get("evidence", ())),
                        notes=c.get("notes", ""),
                    )
                    for c in s.get("criteria", [])
                ],
            )
            for s in data.get("scenarios", [])
        ],
    )


def load_evaluation(path: Path) -> Evaluation:
    return loads_evaluation(Path(path).read_text())


# --- lenient coercion -----------------------------------------------------


def _as_float(value, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _as_ratio_percentage(value) -> float:
    """Interpret a score that may be on a 0-1 or 0-100 scale as 0-100."""
    number = _as_float(value)
    return number * 100.0 if 0 <= number <= 1 else number


def normalize_percentage(data: dict) -> float:
    """Extract an overall 0-100 score from drifting judge JSON shapes."""
    summary = data.get("summary") or {}
    if isinstance(summary, dict):
        for key in ("percentage", "overall_score", "pass_rate"):
            if key in summary:
                return _as_ratio_percentage(summary[key])
        earned = summary.get("total_earned_score", summary.get("total_earned"))
        possible = summary.get("total_max_score", summary.get("total_possible"))
        if earned is not None and possible is not None and _as_float(possible):
            return 100.0 * _as_float(earned) / _as_float(possible)
    for key in ("percentage", "overall_score", "pass_rate"):
        if key in data:
            return _as_ratio_percentage(data[key])
    coerced = coerce_evaluation(data)
    if coerced.total_possible:
        return coerced.percentage
    raise ValueError("no recognizable score in evaluation data")


def _coerce_criteria(raw) -> list[CriterionResult]:
    if isinstance(raw, dict):
        entries = [{"criterion": name, **(value or {})} for name, value in raw.items()]
    elif isinstance(raw, list):
        entries = raw
    else:
        entries = []

    criteria = []
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        earned = _as_float(entry.get("points_earned", entry.get("earned", 0)))
        possible = _as_float(entry.get("points_possible", entry.get("possible", 0)))
        passed = entry.get("passed")
        if passed is None:
            passed = possible > 0 and earned >= possible
        evidence = entry.get("evidence", ())
        if isinstance(evidence, str):
            evidence = (evidence,)
        criteria.append(
            CriterionResult(
                criterion=str(entry.get("criterion", entry.get("id", ""))),
                passed=bool(passed),
                points_earned=earned,
                points_possible=possible,
                evidence=tuple(str(e) for e in evidence),
                notes=str(entry.get("notes", "")),
            )
        )
    return criteria


def coerce_evaluation(data: dict) -> Evaluation:
    """Best-effort conversion of drifting judge JSON into an Evaluation."""
    raw_scenarios = data.get("scenarios", {})
    if isinstance(raw_scenarios, dict):
        entries = [
            {"scenario": name, **(value or {})}
            for name, value in raw_scenarios.items()
        ]
    elif isinstance(raw_scenarios, list):
        entries = raw_scenarios
    else:
        entries = []

    scenarios = [
        ScenarioEvaluation(
            scenario=str(entry.get("scenario", entry.get("name", ""))),
            criteria=_coerce_criteria(entry.get("criteria", ())),
        )
        for entry in entries
        if isinstance(entry, dict)
    ]

    evaluated_at_raw = data.get("evaluated_at", "")
    try:
        evaluated_at = datetime.fromisoformat(evaluated_at_raw)
    except (TypeError, ValueError):
        evaluated_at = datetime.now()

    summary = data.get("summary")
    notes = str(data.get("notes", ""))
    if not notes and isinstance(summary, dict):
        notes = str(summary.get("notes", ""))

    return Evaluation(
        run_id=str(data.get("run_id", "")),
        evaluated_at=evaluated_at,
        project=str(data.get("project", "")),
        rubric_version=str(data.get("rubric_version", "")),
        notes=notes,
        scenarios=scenarios,
    )
