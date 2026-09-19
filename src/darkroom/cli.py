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

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
