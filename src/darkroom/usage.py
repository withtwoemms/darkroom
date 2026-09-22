"""Usage metering for agent invocations: the cost ledger's raw material.

Each judge/builder invocation appends one JSON line to ``usage.jsonl``
in the loop's work directory — role, iteration, model, tokens, cost,
duration. With the default invoke template (``--output-format json``)
the ``claude`` CLI reports usage structurally; a custom template that
emits no parseable usage degrades to a *partial* record (model and
duration only). Metering is instrumentation, never policy: a metering
failure must never fail a run, and records carry no scores — but the
ledger lives operator-side with the rest of loop state.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path

USAGE_FILE = "usage.jsonl"


@dataclass(frozen=True)
class UsageRecord:
    role: str  # "judge" | "builder"
    iteration: int
    model: str
    duration_seconds: float
    recorded_at: str
    input_tokens: int | None = None
    output_tokens: int | None = None
    cost_usd: float | None = None
    partial: bool = False  # no parseable usage in the agent's output
    scenario: str = ""  # scenario-scoped runs attribute their spend


def parse_agent_output(stdout: str) -> dict | None:
    """Extract usage facts from an agent invocation's stdout, if any.

    Understands the ``claude -p --output-format json`` result shape and
    tolerates leading noise by scanning lines last-to-first for a JSON
    object. Returns ``{"input_tokens", "output_tokens", "cost_usd"}``
    (values may be None) or None when nothing parseable is present.
    """
    candidates = [stdout.strip()]
    candidates.extend(
        line.strip() for line in reversed(stdout.strip().splitlines())
    )
    for candidate in candidates:
        if not candidate.startswith("{"):
            continue
        try:
            data = json.loads(candidate)
        except ValueError:
            continue
        if not isinstance(data, dict):
            continue
        usage = data.get("usage") if isinstance(data.get("usage"), dict) else {}
        cost = data.get("total_cost_usd", data.get("cost_usd"))
        input_tokens = usage.get("input_tokens")
        output_tokens = usage.get("output_tokens")
        if cost is None and input_tokens is None and output_tokens is None:
            continue
        for extra in ("cache_creation_input_tokens", "cache_read_input_tokens"):
            if isinstance(usage.get(extra), int) and isinstance(input_tokens, int):
                input_tokens += usage[extra]
        return {
            "input_tokens": input_tokens if isinstance(input_tokens, int) else None,
            "output_tokens": output_tokens if isinstance(output_tokens, int) else None,
            "cost_usd": float(cost) if isinstance(cost, (int, float)) else None,
        }
    return None


def build_record(
    role: str,
    iteration: int,
    model: str,
    stdout: str,
    duration_seconds: float,
    scenario: str = "",
) -> UsageRecord:
    parsed = parse_agent_output(stdout)
    return UsageRecord(
        role=role,
        iteration=iteration,
        model=model,
        duration_seconds=round(duration_seconds, 3),
        recorded_at=datetime.now().isoformat(),
        input_tokens=parsed["input_tokens"] if parsed else None,
        output_tokens=parsed["output_tokens"] if parsed else None,
        cost_usd=parsed["cost_usd"] if parsed else None,
        partial=parsed is None,
        scenario=scenario,
    )


def record_usage(work_dir: Path, record: UsageRecord) -> None:
    """Append one record; never raises — metering must not fail a run."""
    try:
        work_dir.mkdir(parents=True, exist_ok=True)
        with open(work_dir / USAGE_FILE, "a") as f:
            f.write(json.dumps(asdict(record)) + "\n")
    except OSError:
        pass


def read_usage(work_dir: Path) -> list[UsageRecord]:
    path = Path(work_dir) / USAGE_FILE
    if not path.exists():
        return []
    records = []
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            records.append(UsageRecord(**json.loads(line)))
        except (ValueError, TypeError):
            continue
    return records
