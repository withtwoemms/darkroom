"""The darkroom command-line interface.

Installed as both ``darkroom`` and its terse alias ``darkrm``.

Subcommands:
    verify  — check manifests structurally and against an evidence contract
    show    — human-readable summary of a run's manifest
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from darkroom.contract import load_contract
from darkroom.manifest import load_manifest
from darkroom.verify import VerificationResult, verify

DEFAULT_CONTRACT = Path("evidence-contract.toml")


def _finding_line(finding) -> str:
    scope = f" [{finding.scenario}]" if finding.scenario else ""
    return f"{finding.severity}{scope}: {finding.message}"


def _result_json(result: VerificationResult) -> dict:
    return {
        "ok": result.ok,
        "manifests": [str(p) for p in result.manifests],
        "findings": [
            {
                "severity": f.severity,
                "code": f.code,
                "message": f.message,
                "scenario": f.scenario,
                "manifest": str(f.manifest) if f.manifest else None,
            }
            for f in result.findings
        ],
    }


def _cmd_verify(args) -> int:
    contract = None
    contract_path = args.contract
    if contract_path is None and DEFAULT_CONTRACT.exists():
        contract_path = DEFAULT_CONTRACT
    if contract_path is not None:
        try:
            contract = load_contract(contract_path)
        except (OSError, ValueError) as exc:
            print(f"error: could not load contract {contract_path}: {exc}")
            return 2

    result = verify(args.manifests, contract)

    if args.json:
        print(json.dumps(_result_json(result), indent=2))
    else:
        for finding in result.findings:
            print(_finding_line(finding))
        checked = "structure only" if contract is None else f"contract: {contract_path}"
        print(
            f"{'ok' if result.ok else 'FAILED'}: {len(result.manifests)} "
            f"manifest(s), {len(result.errors)} error(s), "
            f"{len(result.warnings)} warning(s) ({checked})"
        )
    return 0 if result.ok else 1


def _cmd_show(args) -> int:
    try:
        manifest = load_manifest(args.manifest)
    except (OSError, ValueError, KeyError) as exc:
        print(f"error: could not load manifest: {exc}")
        return 2

    project = f" · project: {manifest.project}" if manifest.project else ""
    print(f"run: {manifest.run_id}{project}")
    print(f"schema: {manifest.schema_version} · written: {manifest.timestamp}")
    total = 0
    for bundle in manifest.scenarios:
        print(f"\n  {bundle.scenario}")
        for item in bundle.items:
            total += 1
            print(f"    {item.kind:<20} {item.step:<28} {item.path}")
    print(f"\n{len(manifest.scenarios)} scenario(s), {total} item(s)")
    return 0


def _cmd_gallery(args) -> int:
    from darkroom.gallery import write_gallery

    try:
        out = write_gallery(
            args.manifest,
            out=args.out,
            evaluation_path=args.evaluation,
            embed=args.embed,
        )
    except (OSError, ValueError, KeyError) as exc:
        print(f"error: could not render gallery: {exc}")
        return 2
    print(f"gallery written: {out}")
    return 0


DEFAULT_GATES = Path("evidence-gates.json")


def _load_gates_or_empty(path: Path):
    from darkroom.gates import GateFile, load_gates

    if path.exists():
        return load_gates(path)
    return GateFile()


def _load_evaluation_arg(path: Path):
    from darkroom.gallery import load_evaluation_lenient

    return load_evaluation_lenient(path)


def _cmd_gate(args) -> int:
    from darkroom.gates import check_gates, dump_gates, has_regressions, update_gates

    gates_path = args.gates or DEFAULT_GATES
    try:
        evaluation = _load_evaluation_arg(args.evaluation)
        gates = _load_gates_or_empty(gates_path)
    except (OSError, ValueError, KeyError) as exc:
        print(f"error: {exc}")
        return 2

    if args.gate_command == "check":
        findings = check_gates(gates, evaluation)
        for finding in findings:
            print(f"{finding.kind} [{finding.scenario}]: {finding.message}")
        regressed = has_regressions(findings)
        print(f"{'FAILED' if regressed else 'ok'}: {len(findings)} scenario(s) checked")
        return 1 if regressed else 0

    new_gates, findings = update_gates(gates, evaluation, commit=args.commit)
    dump_gates(new_gates, gates_path)
    for finding in findings:
        print(f"{finding.kind} [{finding.scenario}]: {finding.message}")
    print(f"gates written: {gates_path} ({len(new_gates.peaks)} peak(s))")
    return 0


def _cmd_diff(args) -> int:
    from darkroom.rundiff import diff_runs

    try:
        old = load_manifest(args.old)
        new = load_manifest(args.new)
    except (OSError, ValueError, KeyError) as exc:
        print(f"error: could not load manifest: {exc}")
        return 2

    diff = diff_runs(old, new)
    if diff.unchanged:
        print(f"no differences: {old.run_id} -> {new.run_id}")
        return 0
    print(f"diff: {old.run_id} -> {new.run_id}")
    for name in diff.scenarios_added:
        print(f"  + scenario {name}")
    for name in diff.scenarios_removed:
        print(f"  - scenario {name}")
    for name, items in diff.items_added.items():
        for item in items:
            print(f"  + {name}: {item}")
    for name, items in diff.items_removed.items():
        for item in items:
            print(f"  - {name}: {item}")
    return 0


def _find_adapter_or_error(project_dir: Path | None):
    from darkroom.adapter import find_adapter

    adapter_path = find_adapter(project_dir)
    if adapter_path is None:
        where = project_dir or Path.cwd()
        print(f"error: no darkroom.toml found in {where} or its parents")
    return adapter_path


def _cmd_preflight(args) -> int:
    from darkroom.preflight import preflight

    adapter_path = _find_adapter_or_error(args.project)
    if adapter_path is None:
        return 2
    result = preflight(adapter_path)

    if args.json:
        print(json.dumps({
            "ok": result.ok,
            "adapter": str(result.adapter_path),
            "findings": [
                {"severity": f.severity, "code": f.code, "message": f.message}
                for f in result.findings
            ],
        }, indent=2))
    else:
        for finding in result.findings:
            print(f"{finding.severity}: {finding.message}")
        print(
            f"{'ok' if result.ok else 'FAILED'}: {result.adapter_path} "
            f"({len(result.errors)} error(s), {len(result.warnings)} warning(s))"
        )
    return 0 if result.ok else 1


def _cmd_run(args) -> int:
    import subprocess

    from darkroom.adapter import load_adapter

    adapter_path = _find_adapter_or_error(args.project)
    if adapter_path is None:
        return 2
    try:
        adapter = load_adapter(adapter_path)
        substitutions = {
            key: value
            for key, value in (
                ("scenario", args.scenario),
                ("seed", args.seed),
                ("run_id", args.run_id),
            )
            if value is not None
        }
        command = adapter.command(args.name, **substitutions)
    except (OSError, ValueError, KeyError) as exc:
        print(f"error: {exc}")
        return 2

    argv = ["/bin/sh", "-c", command]
    if args.capture:
        from darkroom.capture import EvidenceCapture

        capture = EvidenceCapture(args.scenario or adapter.name)
        path = capture.command(args.name, argv, timeout=args.timeout)
        transcript = json.loads(path.read_text())
        print(f"transcript: {path}")
        code = transcript.get("exit_code")
        return code if isinstance(code, int) else 1

    completed = subprocess.run(argv, cwd=adapter.root)
    return completed.returncode


def _ticket_store(args):
    from darkroom.adapter import find_adapter, load_adapter
    from darkroom.tickets import TicketStore

    if args.state is not None:
        return TicketStore(args.state)
    adapter_path = find_adapter(None)
    if adapter_path is not None:
        adapter = load_adapter(adapter_path)
        state = adapter.defaults.get("state", ".darkroom/state")
        return TicketStore(adapter.root / state)
    return TicketStore(Path(".darkroom/state"))


def _cmd_ticket(args) -> int:
    from darkroom.tickets import TicketError

    store = _ticket_store(args)
    try:
        if args.ticket_command == "new":
            fields = dict(pair.split("=", 1) for pair in args.field)
            ticket = store.enqueue(args.role, args.title, body=args.body, **fields)
            print(f"enqueued: {args.role}/{ticket.id}")
            return 0
        if args.ticket_command == "list":
            roles = [args.role] if args.role else store.roles()
            total = 0
            for role in roles:
                for ticket in store.queue(role):
                    total += 1
                    claimed = " [claimed]" if store.is_claimed(ticket.id) else ""
                    print(f"{role}/{ticket.id}{claimed}: {ticket.title}")
            print(f"{total} open ticket(s)")
            return 0
        # resolve
        ticket = store.get(args.role, args.id)
        destination = store.resolve(ticket, args.disposition, note=args.note)
        print(f"resolved: {destination}")
        return 0
    except (TicketError, ValueError) as exc:
        print(f"error: {exc}")
        return 2


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        prog="darkroom",
        description="Evidence capture and manifest management for autonomous software delivery.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    verify_parser = sub.add_parser(
        "verify", help="check manifests structurally and against a contract"
    )
    verify_parser.add_argument("manifests", nargs="+", type=Path)
    verify_parser.add_argument(
        "--contract",
        type=Path,
        default=None,
        help=f"contract file (default: {DEFAULT_CONTRACT} if present)",
    )
    verify_parser.add_argument("--json", action="store_true")
    verify_parser.set_defaults(func=_cmd_verify)

    show_parser = sub.add_parser("show", help="summarize a run's manifest")
    show_parser.add_argument("manifest", type=Path)
    show_parser.set_defaults(func=_cmd_show)

    gallery_parser = sub.add_parser(
        "gallery", help="render a run's contact sheet as static HTML"
    )
    gallery_parser.add_argument("manifest", type=Path)
    gallery_parser.add_argument(
        "--evaluation", type=Path, default=None,
        help="evaluation JSON to overlay scores from",
    )
    gallery_parser.add_argument(
        "--embed", action="store_true",
        help="inline media as data URIs for a single shareable file",
    )
    gallery_parser.add_argument(
        "-o", "--out", type=Path, default=None,
        help="output path (default: gallery.html beside the manifest)",
    )
    gallery_parser.set_defaults(func=_cmd_gallery)

    gate_parser = sub.add_parser(
        "gate", help="check or ratchet per-scenario peak-score gates"
    )
    gate_sub = gate_parser.add_subparsers(dest="gate_command", required=True)
    for name, help_text in (
        ("check", "compare an evaluation against recorded peaks (exit 1 on regression)"),
        ("update", "ratchet peaks upward from an evaluation"),
    ):
        p = gate_sub.add_parser(name, help=help_text)
        p.add_argument("evaluation", type=Path)
        p.add_argument(
            "--gates", type=Path, default=None,
            help=f"gates file (default: {DEFAULT_GATES})",
        )
        if name == "update":
            p.add_argument("--commit", default="", help="VCS ref achieving these scores")
        p.set_defaults(func=_cmd_gate)

    diff_parser = sub.add_parser("diff", help="compare two runs' manifests")
    diff_parser.add_argument("old", type=Path)
    diff_parser.add_argument("new", type=Path)
    diff_parser.set_defaults(func=_cmd_diff)

    preflight_parser = sub.add_parser(
        "preflight", help="validate a project's darkroom wiring"
    )
    preflight_parser.add_argument(
        "--project", type=Path, default=None,
        help="directory to search for darkroom.toml (default: cwd, walking up)",
    )
    preflight_parser.add_argument("--json", action="store_true")
    preflight_parser.set_defaults(func=_cmd_preflight)

    run_parser = sub.add_parser(
        "run", help="execute a command declared in darkroom.toml"
    )
    run_parser.add_argument("name", help="command name, e.g. test")
    run_parser.add_argument("--project", type=Path, default=None)
    run_parser.add_argument("--scenario", default=None)
    run_parser.add_argument("--seed", default=None)
    run_parser.add_argument("--run-id", dest="run_id", default=None)
    run_parser.add_argument(
        "--capture", action="store_true",
        help="capture the execution as command-transcript evidence",
    )
    run_parser.add_argument("--timeout", type=float, default=600)
    run_parser.set_defaults(func=_cmd_run)

    ticket_parser = sub.add_parser("ticket", help="filesystem ticket queues")
    ticket_sub = ticket_parser.add_subparsers(dest="ticket_command", required=True)

    ticket_new = ticket_sub.add_parser("new", help="enqueue a ticket")
    ticket_new.add_argument("role")
    ticket_new.add_argument("title")
    ticket_new.add_argument("--body", default="")
    ticket_new.add_argument(
        "--field", action="append", default=[], metavar="KEY=VALUE"
    )
    ticket_new.add_argument("--state", type=Path, default=None)
    ticket_new.set_defaults(func=_cmd_ticket)

    ticket_list = ticket_sub.add_parser("list", help="list open tickets")
    ticket_list.add_argument("role", nargs="?", default=None)
    ticket_list.add_argument("--state", type=Path, default=None)
    ticket_list.set_defaults(func=_cmd_ticket)

    ticket_resolve = ticket_sub.add_parser(
        "resolve", help="resolve a ticket into history"
    )
    ticket_resolve.add_argument("role")
    ticket_resolve.add_argument("id")
    ticket_resolve.add_argument("--disposition", required=True)
    ticket_resolve.add_argument("--note", default="")
    ticket_resolve.add_argument("--state", type=Path, default=None)
    ticket_resolve.set_defaults(func=_cmd_ticket)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
