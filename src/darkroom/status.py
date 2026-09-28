"""The standing report: where every scenario's campaign stands right now.

The dossier is the cross-run *record*; this is the *present tense* read
of the same state — the latest campaign per scenario (a campaign is a
run of iterations that restarts at 1), whether it converged, is still
moving, is blocked, or went quiet — plus the blocker brief, the ticket
queue, and metered spend. Everything here is derived from files the
loop already writes; nothing is judged or re-scored. States are
deliberately conservative: a campaign is "running" only while its last
iteration is recent, "exhausted" only when the operator's own iteration
cap says so, and otherwise "stopped" — the report never guesses that a
quiet run is finished.
"""

from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path

from darkroom.adapter import ProjectAdapter
from darkroom.dossier import _evaluations, _parse_builder_log, _usage
from darkroom.gates import load_gates
from darkroom.loop import BLOCKER_FILENAME
from darkroom.tickets import TicketStore
from darkroom.usage import read_usage

if sys.version_info >= (3, 11):
    import tomllib
else:  # pragma: no cover - exercised only on 3.10
    import tomli as tomllib

STATES = ("converged", "running", "blocked", "exhausted", "stopped")
DEFAULT_STALE_AFTER = 900.0  # seconds without an iteration before "running" lapses


def _parse_at(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    return parsed.replace(tzinfo=None) if parsed.tzinfo else parsed


def _campaigns(iterations: list[dict]) -> dict[str, list[dict]]:
    """The latest campaign per scenario: iteration numbering restarts at 1
    each time the loop is launched, so a `1` opens a fresh campaign."""
    latest: dict[str, list[dict]] = {}
    for entry in iterations:
        scenario = entry.get("scenario", "")
        if entry.get("number") == 1 or scenario not in latest:
            latest[scenario] = []
        latest[scenario].append(entry)
    return latest


def _max_iterations(state_dir: Path) -> int | None:
    """The operator's iteration cap, if an operator.toml sits beside the
    state (the darkroom home layout); None when unknown."""
    operator = Path(state_dir).parent / "operator.toml"
    if not operator.exists():
        return None
    try:
        loaded = tomllib.loads(operator.read_text())
    except (OSError, ValueError):
        return None
    value = loaded.get("loop", {}).get("max_iterations")
    return int(value) if isinstance(value, int) else None


def _campaign_state(
    campaign: list[dict],
    *,
    now: datetime,
    stale_after: float,
    blocked: bool,
    max_iterations: int | None,
) -> tuple[str, float | None]:
    last = campaign[-1]
    at = _parse_at(last.get("at"))
    age = (now - at).total_seconds() if at is not None else None
    if last.get("action") == "converged":
        return "converged", age
    if blocked:
        return "blocked", age
    if age is not None and age <= stale_after:
        return "running", age
    if max_iterations is not None and len(campaign) >= max_iterations:
        return "exhausted", age
    return "stopped", age


def _latest_evaluation_for(evaluations: list[dict], scenario: str) -> dict | None:
    for entry in reversed(evaluations):
        for s in entry["scenarios"]:
            if s["scenario"] == scenario:
                return s
    return None


def _queue(state_dir: Path) -> list[dict]:
    store = TicketStore(Path(state_dir))
    tickets = []
    try:
        roles = store.roles()
    except OSError:
        return tickets
    for role in roles:
        for ticket in store.queue(role):
            priority = ticket.fields.get("priority")
            try:
                sort_key = float(priority) if priority is not None else float("inf")
            except ValueError:
                sort_key = float("inf")
            tickets.append(
                {
                    "role": role,
                    "id": ticket.id,
                    "title": ticket.title,
                    "priority": priority,
                    "_sort": sort_key,
                }
            )
    tickets.sort(key=lambda t: (t["_sort"], t["id"]))
    for ticket in tickets:
        del ticket["_sort"]
    return tickets


def _campaign_spend(loop_dir: Path) -> dict[str, float | None]:
    """Metered cost of each scenario's latest run directory. `darkroom auto`
    writes one directory per invocation, so the newest directory holding a
    scenario's records is that scenario's latest campaign — a cleaner
    boundary than timestamps, since the judge's first usage record lands
    before the iteration line that opens the campaign."""
    spend: dict[str, float | None] = {}
    if not loop_dir.is_dir():
        return spend
    for sub in sorted(p for p in loop_dir.glob("*") if p.is_dir()):
        per_scenario: dict[str, list[float]] = {}
        for record in read_usage(sub):
            per_scenario.setdefault(record.scenario, [])
            if record.cost_usd is not None:
                per_scenario[record.scenario].append(record.cost_usd)
        for name, costs in per_scenario.items():
            spend[name] = round(sum(costs), 6) if costs else None
    return spend


def assemble_status(
    adapter: ProjectAdapter,
    state_dir: Path,
    scenario: str | None = None,
    *,
    stale_after: float = DEFAULT_STALE_AFTER,
    now: datetime | None = None,
) -> dict:
    """The present-tense bundle for a project (optionally one scenario)."""
    now = now or datetime.now()
    state_dir = Path(state_dir)
    loop_dir = state_dir / "loop"

    builder_log = state_dir / "builder-log.md"
    iterations = (
        _parse_builder_log(builder_log.read_text()) if builder_log.exists() else []
    )
    campaigns = _campaigns(iterations)
    if scenario is not None:
        campaigns = {k: v for k, v in campaigns.items() if k == scenario}

    blocker_path = adapter.resolve(BLOCKER_FILENAME)
    blocker_text = blocker_path.read_text() if blocker_path.exists() else None
    # a blocker file belongs to whichever unconverged campaign moved last
    blocked_scenario = None
    if blocker_text is not None:
        candidates = [
            (c[-1].get("at") or "", name)
            for name, c in campaigns.items()
            if c[-1].get("action") != "converged"
        ]
        if candidates:
            blocked_scenario = max(candidates)[1]

    gates: dict[str, dict] = {}
    gates_path = adapter.resolve(adapter.gates_path)
    if gates_path.exists():
        try:
            for peak in load_gates(gates_path).peaks:
                gates[peak.scenario] = {
                    "score": peak.score,
                    "recorded_at": peak.recorded_at.isoformat(),
                    "rubric_version": peak.rubric_version,
                }
        except (OSError, ValueError, KeyError):
            gates = {}

    evaluations = _evaluations(loop_dir, scenario)
    usage_all = _usage(loop_dir, None)
    max_iterations = _max_iterations(state_dir)
    campaign_spend = _campaign_spend(loop_dir)

    scenarios = []
    for name, campaign in campaigns.items():
        state, age = _campaign_state(
            campaign,
            now=now,
            stale_after=stale_after,
            blocked=(name == blocked_scenario),
            max_iterations=max_iterations,
        )
        latest = _latest_evaluation_for(evaluations, name)
        failing = (
            [c["criterion"] for c in latest["criteria"] if not c["passed"]]
            if latest is not None
            else []
        )
        dials: list[str] = []
        for entry in campaign:
            for dial in entry.get("escalation", []):
                if dial not in dials:
                    dials.append(dial)
        scenarios.append(
            {
                "scenario": name,
                "state": state,
                "iterations": len(campaign),
                "trajectory": [e.get("score") for e in campaign],
                "best": max((e.get("best_score") or 0.0) for e in campaign),
                "stagnation": campaign[-1].get("stagnation"),
                "last_action": campaign[-1].get("action"),
                "last_at": campaign[-1].get("at"),
                "seconds_since_activity": None if age is None else round(age),
                "escalation": dials,
                "blocker_raised": any(e.get("blocker") for e in campaign),
                "failing": failing if state != "converged" else [],
                "gate": gates.get(name),
                "campaign_spend_usd": campaign_spend.get(name),
            }
        )
    scenarios.sort(key=lambda s: s["last_at"] or "", reverse=True)

    counts = {state: sum(1 for s in scenarios if s["state"] == state) for state in STATES}
    return {
        "project": adapter.name,
        "generated_at": now.isoformat(),
        "scenario": scenario,
        "stale_after_seconds": stale_after,
        "max_iterations": max_iterations,
        "counts": counts,
        "scenarios": scenarios,
        "blocker": (
            None
            if blocker_text is None
            else {"scenario": blocked_scenario, "text": blocker_text}
        ),
        "queue": _queue(state_dir),
        "spend": usage_all["totals"],
    }


# --- markdown rendering ---------------------------------------------------


def _age(seconds: float | None) -> str:
    if seconds is None:
        return "unknown"
    if seconds < 90:
        return f"{int(seconds)}s ago"
    if seconds < 5400:
        return f"{int(seconds // 60)}m ago"
    return f"{seconds / 3600:.1f}h ago"


def _trajectory(scores: list[float | None]) -> str:
    return " → ".join("?" if s is None else f"{s:g}" for s in scores) or "—"


def _money(value: float | None) -> str:
    return "—" if value is None else f"${value:.2f}"


def dumps_status_markdown(bundle: dict) -> str:
    counts = bundle["counts"]
    total = len(bundle["scenarios"])
    lines = [f"# darkroom status — {bundle['project']} ({bundle['generated_at']})", ""]
    if total == 0:
        lines.append("no campaigns in loop state yet")
    else:
        parts = [f"{counts[s]} {s}" for s in STATES if counts[s]]
        lines.append(f"{total} campaign(s): " + " · ".join(parts))
    lines += ["", "## convergence", ""]
    if bundle["scenarios"]:
        lines.append("| scenario | state | iters | trajectory | best | gate | spend |")
        lines.append("|---|---|---|---|---|---|---|")
        for s in bundle["scenarios"]:
            gate = s["gate"]
            gate_cell = "—" if gate is None else f"{gate['score']:g}"
            lines.append(
                f"| {s['scenario']} | {s['state']} | {s['iterations']} | "
                f"{_trajectory(s['trajectory'])} | {s['best']:g} | "
                f"{gate_cell} | {_money(s['campaign_spend_usd'])} |"
            )
        for s in bundle["scenarios"]:
            if s["state"] == "converged":
                continue
            moved = _age(s["seconds_since_activity"])
            detail = f"- {s['scenario']}: {s['state']}, last moved {moved}"
            if s["escalation"]:
                detail += f"; dials: {', '.join(s['escalation'])}"
            if s["failing"]:
                detail += f"; failing: {', '.join(s['failing'])}"
            lines.append(detail)
    else:
        lines.append("(nothing has run)")
    lines += ["", "## blocker", ""]
    blocker = bundle["blocker"]
    if blocker is None:
        lines.append("none")
    else:
        lines.append(f"raised on {blocker['scenario'] or 'an unknown scenario'}:")
        lines.append("")
        lines.extend("> " + line for line in blocker["text"].strip().splitlines())
    lines += ["", "## queue", ""]
    if bundle["queue"]:
        for t in bundle["queue"]:
            priority = f" ({t['priority']})" if t["priority"] is not None else ""
            lines.append(f"- {t['role']}/{t['id']} — {t['title']}{priority}")
    else:
        lines.append("empty")
    lines += ["", "## spend", ""]
    spend = bundle["spend"]
    by_role = ", ".join(
        f"{role} {_money(v['cost_usd'])}" for role, v in spend.get("by_role", {}).items()
    )
    lines.append(
        f"project total {_money(spend.get('cost_usd'))} across {spend.get('calls', 0)} call(s)"
        + (f" ({by_role})" if by_role else "")
    )
    campaign_total = sum(
        s["campaign_spend_usd"] or 0.0 for s in bundle["scenarios"]
    )
    if bundle["scenarios"]:
        lines.append(f"campaigns in this report {_money(campaign_total)}")
    return "\n".join(lines) + "\n"
