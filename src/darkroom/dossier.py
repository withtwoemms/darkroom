"""The dossier: deterministic assembly of a project's cross-run record.

One bundle collates what the loop leaves behind — iteration memory,
evaluations with per-criterion scores, checkpoint subjects, gate
peaks, and the usage ledger — so narration tooling (and the operator)
reads one document instead of spelunking four file kinds. Assembly is
zero-LLM and side-effect free; interpretation (sticking points,
novelty) belongs to the narration layer.

Trust: the bundle carries score trajectories, so it is operator-facing
only — it must never be written inside the tenant, where it would
become a scores side-channel to the builder. The CLI enforces this.
"""

from __future__ import annotations

import re
import subprocess
from dataclasses import asdict
from datetime import datetime
from pathlib import Path

from darkroom.adapter import ProjectAdapter
from darkroom.gallery import load_evaluation_lenient
from darkroom.gates import load_gates
from darkroom.usage import read_usage

CURRENT_DOSSIER_SCHEMA_VERSION = "1.0"

_ITERATION_HEADING = re.compile(r"^## iteration (\d+) — (.+)$")


def _parse_builder_log(text: str) -> list[dict]:
    """Iteration entries from builder-log.md; tolerant of format drift."""
    iterations: list[dict] = []
    entry: dict | None = None
    for line in text.splitlines():
        heading = _ITERATION_HEADING.match(line)
        if heading:
            entry = {
                "number": int(heading.group(1)),
                "at": heading.group(2).strip(),
            }
            iterations.append(entry)
            continue
        if entry is None or not line.strip():
            continue
        if line.startswith("scenario: "):
            entry["scenario"] = line[len("scenario: "):].strip()
        elif line.startswith("score: "):
            match = re.match(
                r"score: ([\d.]+) \(best ([\d.]+)\) · "
                r"stagnation: (\d+) · action: (.+)",
                line,
            )
            if match:
                entry["score"] = float(match.group(1))
                entry["best_score"] = float(match.group(2))
                entry["stagnation"] = int(match.group(3))
                entry["action"] = match.group(4).strip()
        elif line.startswith("escalation: "):
            entry["escalation"] = [
                d.strip() for d in line[len("escalation: "):].split(",")
            ]
        elif line.startswith("changed: "):
            entry["changed"] = [
                f.strip() for f in line[len("changed: "):].split(",")
            ]
    return iterations


def _evaluations(loop_dir: Path, scenario: str | None) -> list[dict]:
    entries = []
    for path in sorted(loop_dir.glob("evaluation-*.json")):
        try:
            evaluation = load_evaluation_lenient(path)
        except (OSError, ValueError, KeyError):
            continue
        scenarios = []
        for s in evaluation.scenarios:
            if scenario is not None and s.scenario != scenario:
                continue
            possible = s.points_possible
            scenarios.append(
                {
                    "scenario": s.scenario,
                    "score": (
                        100.0 * s.points_earned / possible if possible else None
                    ),
                    "criteria": [
                        {
                            "criterion": c.criterion,
                            "passed": c.passed,
                            "points_earned": c.points_earned,
                            "points_possible": c.points_possible,
                        }
                        for c in s.criteria
                    ],
                }
            )
        if scenario is not None and not scenarios:
            continue
        entries.append(
            (
                evaluation.evaluated_at,
                {
                    "file": path.name,
                    "run_id": evaluation.run_id,
                    "evaluated_at": evaluation.evaluated_at.isoformat(),
                    "rubric_version": evaluation.rubric_version,
                    "scenarios": scenarios,
                },
            )
        )
    # chronological, robust to mixed naive/aware timestamps (a string
    # sort misorders mixed UTC-offset records)
    def _sortable(moment: datetime) -> float:
        if moment.tzinfo is None:
            moment = moment.astimezone()
        return moment.timestamp()

    entries.sort(key=lambda pair: _sortable(pair[0]))
    return [entry for _, entry in entries]


def _checkpoints(adapter: ProjectAdapter, limit: int = 100) -> list[dict]:
    completed = subprocess.run(
        ["git", "log", f"--max-count={limit}", "--grep=^auto: ",
         "--format=%h%x09%s"],
        cwd=adapter.root, capture_output=True, text=True,
    )
    if completed.returncode != 0:
        return []
    checkpoints = []
    for line in completed.stdout.splitlines():
        sha, _, subject = line.partition("\t")
        if subject:
            checkpoints.append({"commit": sha, "subject": subject})
    checkpoints.reverse()  # oldest first, matching the other sections
    return checkpoints


def _usage(loop_dir: Path, scenario: str | None) -> dict:
    records = [
        r for r in read_usage(loop_dir)
        if scenario is None or r.scenario == scenario
    ]
    costs = [r.cost_usd for r in records if r.cost_usd is not None]
    tokens_in = [r.input_tokens for r in records if r.input_tokens is not None]
    tokens_out = [r.output_tokens for r in records if r.output_tokens is not None]
    by_role: dict[str, dict] = {}
    for record in records:
        totals = by_role.setdefault(
            record.role, {"calls": 0, "cost_usd": 0.0, "models": []}
        )
        totals["calls"] += 1
        if record.cost_usd is not None:
            totals["cost_usd"] = round(totals["cost_usd"] + record.cost_usd, 6)
        if record.model not in totals["models"]:
            totals["models"].append(record.model)
    return {
        "records": [asdict(r) for r in records],
        "totals": {
            "calls": len(records),
            "metered_calls": len(costs),
            "cost_usd": round(sum(costs), 6) if costs else None,
            "input_tokens": sum(tokens_in) if tokens_in else None,
            "output_tokens": sum(tokens_out) if tokens_out else None,
            "by_role": by_role,
        },
    }


def assemble_dossier(
    adapter: ProjectAdapter,
    state_dir: Path,
    scenario: str | None = None,
) -> dict:
    """The cross-run bundle for a project (optionally one scenario)."""
    loop_dir = Path(state_dir) / "loop"

    builder_log = Path(state_dir) / "builder-log.md"
    iterations = (
        _parse_builder_log(builder_log.read_text())
        if builder_log.exists()
        else []
    )
    if scenario is not None:
        iterations = [
            i for i in iterations if i.get("scenario", scenario) == scenario
        ]

    gates = None
    gates_path = adapter.resolve(adapter.gates_path)
    if gates_path.exists():
        try:
            loaded = load_gates(gates_path)
            gates = [
                {
                    "scenario": p.scenario,
                    "score": p.score,
                    "run_id": p.run_id,
                    "recorded_at": p.recorded_at.isoformat(),
                    "rubric_version": p.rubric_version,
                    "commit": p.commit,
                }
                for p in loaded.peaks
                if scenario is None or p.scenario == scenario
            ]
        except (OSError, ValueError, KeyError):
            gates = None

    return {
        "schema_version": CURRENT_DOSSIER_SCHEMA_VERSION,
        "project": adapter.name,
        "generated_at": datetime.now().isoformat(),
        "scenario": scenario,
        "iterations": iterations,
        "evaluations": _evaluations(loop_dir, scenario),
        "checkpoints": _checkpoints(adapter),
        "gates": gates,
        "usage": _usage(loop_dir, scenario),
    }


# --- markdown rendering ---------------------------------------------------


def dumps_dossier_markdown(bundle: dict) -> str:
    lines = [
        f"# dossier: {bundle['project']}"
        + (f" · {bundle['scenario']}" if bundle["scenario"] else ""),
        "",
        f"generated: {bundle['generated_at']}",
        "",
    ]

    lines.append("## iterations")
    lines.append("")
    if bundle["iterations"]:
        for it in bundle["iterations"]:
            parts = [f"{it['number']}."]
            if "scenario" in it:
                parts.append(f"[{it['scenario']}]")
            if "score" in it:
                parts.append(
                    f"score {it['score']:.1f} (best {it['best_score']:.1f}), "
                    f"stagnation {it['stagnation']}, {it['action']}"
                )
            if "escalation" in it:
                parts.append(f"— escalated: {', '.join(it['escalation'])}")
            if "changed" in it:
                parts.append(f"— changed: {', '.join(it['changed'])}")
            lines.append(" ".join(parts))
    else:
        lines.append("(no iteration memory)")
    lines.append("")

    lines.append("## score trajectory")
    lines.append("")
    if bundle["evaluations"]:
        for entry in bundle["evaluations"]:
            for s in entry["scenarios"]:
                score = "-" if s["score"] is None else f"{s['score']:.1f}"
                failed = [
                    c["criterion"] for c in s["criteria"] if not c["passed"]
                ]
                suffix = f" · failing: {', '.join(failed)}" if failed else ""
                lines.append(
                    f"- {entry['evaluated_at']} · {s['scenario']}: {score} "
                    f"(rubric v{entry['rubric_version'] or '?'}){suffix}"
                )
    else:
        lines.append("(no evaluations in loop state)")
    lines.append("")

    lines.append("## gates")
    lines.append("")
    if bundle["gates"]:
        for peak in bundle["gates"]:
            lines.append(
                f"- {peak['scenario']}: {peak['score']:.1f} "
                f"(rubric v{peak['rubric_version'] or '?'}, "
                f"run {peak['run_id'] or '?'})"
            )
    else:
        lines.append("(no gates recorded)")
    lines.append("")

    lines.append("## checkpoints")
    lines.append("")
    if bundle["checkpoints"]:
        for checkpoint in bundle["checkpoints"]:
            lines.append(f"- {checkpoint['commit']} {checkpoint['subject']}")
    else:
        lines.append("(no auto checkpoints in tenant history)")
    lines.append("")

    totals = bundle["usage"]["totals"]
    lines.append("## spend")
    lines.append("")
    if totals["calls"]:
        cost = (
            f"${totals['cost_usd']:.4f}"
            if totals["cost_usd"] is not None
            else "unmetered"
        )
        lines.append(
            f"{totals['calls']} agent call(s), "
            f"{totals['metered_calls']} metered · total {cost}"
        )
        for role, r in totals["by_role"].items():
            lines.append(
                f"- {role}: {r['calls']} call(s), ${r['cost_usd']:.4f} "
                f"({', '.join(r['models'])})"
            )
    else:
        lines.append("(no usage records)")
    lines.append("")
    return "\n".join(lines)
