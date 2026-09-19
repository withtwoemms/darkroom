"""Unit tests for the gallery contact sheet."""

import json
from datetime import datetime
from pathlib import Path

from darkroom.cli import main
from darkroom.evaluation import (
    CriterionResult,
    Evaluation,
    ScenarioEvaluation,
    dump_evaluation,
)
from darkroom.gallery import render_gallery, write_gallery
from darkroom.manifest import dump_manifest, load_manifest
from darkroom.model import EvidenceItem, RunManifest, ScenarioBundle


def _make_run(run_dir: Path) -> Path:
    run_dir.mkdir(parents=True, exist_ok=True)
    scenario = "approve_flow"
    items = []
    specs = [
        ("screenshot", "before", "01-before.png", "image/png", b"png-bytes"),
        ("screenshot", "FAILURE", "02-FAILURE.png", "image/png", b"png-bytes"),
        ("log", "state", "03-state.json", "application/json", b'{"data": {"n": 1}}'),
        ("video", "walk", "04-walk.webm", "video/webm", b"webm-bytes"),
    ]
    for kind, step, name, mime, content in specs:
        rel = Path(scenario) / name
        (run_dir / rel).parent.mkdir(parents=True, exist_ok=True)
        (run_dir / rel).write_bytes(content)
        items.append(
            EvidenceItem(
                kind=kind, mime=mime, path=rel, scenario=scenario, step=step,
                captured_at=datetime(2026, 1, 1),
            )
        )
    manifest_path = run_dir / "manifest.json"
    dump_manifest(
        RunManifest(
            run_id="demo-run",
            project="bookbinder",
            scenarios=[ScenarioBundle(scenario=scenario, items=items)],
        ),
        manifest_path,
    )
    return manifest_path


def _evaluation() -> Evaluation:
    return Evaluation(
        run_id="demo-run",
        evaluated_at=datetime(2026, 1, 2),
        rubric_version="2",
        scenarios=[
            ScenarioEvaluation(
                scenario="approve_flow",
                criteria=[
                    CriterionResult(
                        criterion="renders",
                        passed=True,
                        points_earned=10,
                        points_possible=10,
                        evidence=("approve_flow/01-before.png",),
                    ),
                    CriterionResult(
                        criterion="notified",
                        passed=False,
                        points_earned=0,
                        points_possible=10,
                        notes="no outbox entry",
                    ),
                ],
            )
        ],
    )


class TestRenderGallery:
    def test_relative_refs_by_default(self, tmp_path):
        manifest_path = _make_run(tmp_path / "run")
        manifest = load_manifest(manifest_path)
        page = render_gallery(manifest, manifest_path.parent)
        assert '<img src="approve_flow/01-before.png"' in page
        assert '<video controls src="approve_flow/04-walk.webm"' in page
        assert "data:" not in page

    def test_failure_step_flagged(self, tmp_path):
        manifest_path = _make_run(tmp_path / "run")
        page = render_gallery(load_manifest(manifest_path), manifest_path.parent)
        assert 'class="shot failure"' in page

    def test_text_kinds_in_details(self, tmp_path):
        manifest_path = _make_run(tmp_path / "run")
        page = render_gallery(load_manifest(manifest_path), manifest_path.parent)
        assert "<details" in page and "&quot;n&quot;: 1" in page

    def test_embed_inlines_media(self, tmp_path):
        manifest_path = _make_run(tmp_path / "run")
        page = render_gallery(
            load_manifest(manifest_path), manifest_path.parent, embed=True
        )
        assert "data:image/png;base64," in page
        assert "data:video/webm;base64," in page

    def test_evaluation_overlay(self, tmp_path):
        manifest_path = _make_run(tmp_path / "run")
        page = render_gallery(
            load_manifest(manifest_path), manifest_path.parent,
            evaluation=_evaluation(),
        )
        assert "50.0%" in page                      # scenario + header badge
        assert "rubric v2" in page
        assert "no outbox entry" in page
        assert 'href="#item-approve_flow-01-before-png"' in page  # citation link
        assert 'id="item-approve_flow-01-before-png"' in page


class TestWriteGallery:
    def test_default_output_beside_manifest(self, tmp_path):
        manifest_path = _make_run(tmp_path / "run")
        out = write_gallery(manifest_path)
        assert out == manifest_path.parent / "gallery.html"
        assert out.read_text().startswith("<!doctype html>")

    def test_lenient_evaluation_loading(self, tmp_path):
        manifest_path = _make_run(tmp_path / "run")
        drifting = tmp_path / "eval.json"
        drifting.write_text(json.dumps({
            "run_id": "demo-run",
            "scenarios": {
                "approve_flow": {
                    "criteria": {
                        "renders": {"points_earned": 1, "points_possible": 1}
                    }
                }
            },
        }))
        out = write_gallery(manifest_path, evaluation_path=drifting)
        assert "100.0%" in out.read_text()


class TestGalleryCommand:
    def test_cli_writes_gallery(self, tmp_path, capsys):
        manifest_path = _make_run(tmp_path / "run")
        evaluation_path = tmp_path / "eval.json"
        dump_evaluation(_evaluation(), evaluation_path)
        code = main([
            "gallery", str(manifest_path),
            "--evaluation", str(evaluation_path),
            "-o", str(tmp_path / "sheet.html"),
        ])
        assert code == 0
        assert "gallery written:" in capsys.readouterr().out
        assert (tmp_path / "sheet.html").exists()

    def test_cli_bad_manifest(self, tmp_path, capsys):
        bad = tmp_path / "manifest.json"
        bad.write_text("{broken")
        assert main(["gallery", str(bad)]) == 2
        assert "could not render gallery" in capsys.readouterr().out
