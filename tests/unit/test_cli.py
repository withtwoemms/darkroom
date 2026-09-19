"""Unit tests for the darkroom CLI."""

import json
from datetime import datetime
from pathlib import Path

from darkroom.cli import main
from darkroom.manifest import dump_manifest
from darkroom.model import EvidenceItem, RunManifest, ScenarioBundle

CONTRACT = """
[[scenario]]
name = "approve_flow"

  [[scenario.requires]]
  kind = "log"
  steps = ["state"]
"""


def _make_run(run_dir: Path, scenario="approve_flow", items=(("log", "state"),)) -> Path:
    run_dir.mkdir(parents=True, exist_ok=True)
    bundle = ScenarioBundle(scenario=scenario, items=[])
    for index, (kind, step) in enumerate(items, start=1):
        rel = Path(scenario) / f"{index:02d}-{step}.bin"
        (run_dir / rel).parent.mkdir(parents=True, exist_ok=True)
        (run_dir / rel).write_bytes(b"content")
        bundle.add(
            EvidenceItem(
                kind=kind,
                mime="application/octet-stream",
                path=rel,
                scenario=scenario,
                step=step,
                captured_at=datetime(2026, 1, 1),
            )
        )
    manifest_path = run_dir / "manifest.json"
    dump_manifest(RunManifest(run_id="r", scenarios=[bundle]), manifest_path)
    return manifest_path


class TestVerifyCommand:
    def test_ok_without_contract(self, tmp_path, capsys, monkeypatch):
        monkeypatch.chdir(tmp_path)  # no default contract in cwd
        manifest = _make_run(tmp_path / "r1")
        assert main(["verify", str(manifest)]) == 0
        out = capsys.readouterr().out
        assert "ok:" in out and "structure only" in out

    def test_contract_failure_exits_nonzero(self, tmp_path, capsys):
        manifest = _make_run(tmp_path / "r1", items=(("screenshot", "x"),))
        contract = tmp_path / "contract.toml"
        contract.write_text(CONTRACT)
        assert main(["verify", str(manifest), "--contract", str(contract)]) == 1
        out = capsys.readouterr().out
        assert "FAILED" in out
        assert "[approve_flow]" in out

    def test_default_contract_discovered(self, tmp_path, capsys, monkeypatch):
        monkeypatch.chdir(tmp_path)
        (tmp_path / "evidence-contract.toml").write_text(CONTRACT)
        manifest = _make_run(tmp_path / "r1")
        assert main(["verify", str(manifest)]) == 0
        assert "evidence-contract.toml" in capsys.readouterr().out

    def test_json_output(self, tmp_path, capsys):
        manifest = _make_run(tmp_path / "r1", items=())
        contract = tmp_path / "contract.toml"
        contract.write_text(CONTRACT)
        assert main(["verify", str(manifest), "--contract", str(contract), "--json"]) == 1
        payload = json.loads(capsys.readouterr().out)
        assert payload["ok"] is False
        assert any(f["code"] == "unsatisfied-requirement" for f in payload["findings"])

    def test_bad_contract_is_usage_error(self, tmp_path, capsys):
        manifest = _make_run(tmp_path / "r1")
        missing = tmp_path / "nope.toml"
        assert main(["verify", str(manifest), "--contract", str(missing)]) == 2
        assert "could not load contract" in capsys.readouterr().out


class TestShowCommand:
    def test_summarizes_run(self, tmp_path, capsys):
        manifest = _make_run(tmp_path / "r1")
        assert main(["show", str(manifest)]) == 0
        out = capsys.readouterr().out
        assert "run: r" in out
        assert "approve_flow" in out
        assert "1 scenario(s), 1 item(s)" in out

    def test_unreadable_manifest(self, tmp_path, capsys):
        bad = tmp_path / "manifest.json"
        bad.write_text("{broken")
        assert main(["show", str(bad)]) == 2
        assert "could not load manifest" in capsys.readouterr().out
