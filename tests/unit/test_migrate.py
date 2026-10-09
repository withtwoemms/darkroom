"""darkroom migrate: drive + rubric pairs become proof folders, Build: notes
become draft .surfaces, nothing lost."""

import sys
import textwrap

import pytest

from darkroom.cli import main
from darkroom.migrate import (
    MigrateError,
    apply_serve_defaults,
    defaults_block,
    plan_migration,
    suggest_serve_defaults,
    write_migration,
)
from darkroom.proof import EXPOSURE_FILE, RUBRIC_FILE, exposure, load_proof, rubric
from darkroom.tomlout import dumps_toml

if sys.version_info >= (3, 11):
    import tomllib
else:  # pragma: no cover
    import tomli as tomllib

DRIVE = """\
scenario = "{name}"

[serve]
ttl = {ttl}
strict_mode = 0

[[step]]
name = "keys"
kind = "keygen"
names = ["guest"]

[[step]]
name = "create"
kind = "http"
method = "POST"
url = "{{base_url}}/notes"
json = {{ title = "a \\"quoted\\" one", tags = ["x", "y"], meta = {{ deep = true }} }}
save = {{ note_id = "$.id" }}
expect = {{ status = 201 }}

[[step]]
name = "fill_it"
kind = "fill"
fields = {{ "#title" = "x" }}
"""

RUBRIC = """\
feature_id = "{feature_id}"
version = "3"
scenario = "{name}"

[[criterion]]
id = "created"
points = 10
description = "created"
evidence = ["http_transcript", "log"]
witnesses = ["create"]

[[criterion]]
id = "declared_only"
points = 5
description = "no witnesses, keeps its evidence"
evidence = ["screenshot"]

[[criterion]]
id = "overdeclared"
points = 1
description = "cites create but declares more than it implies"
evidence = ["http_transcript", "video"]
witnesses = ["create"]
"""


def _project(tmp_path, names=("alpha", "beta", "gamma"), ttls=(120, 120, 120), rubrics=None):
    drives = tmp_path / "drives"
    vault = tmp_path / "vault"
    drives.mkdir()
    vault.mkdir()
    for name, ttl in zip(names, ttls, strict=True):
        (drives / f"{name}.drive.toml").write_text(DRIVE.format(name=name, ttl=ttl))
    for name in rubrics if rubrics is not None else names:
        feature_id = name.replace("_", "-")
        (vault / f"{feature_id}.rubric.toml").write_text(
            RUBRIC.format(name=name, feature_id=feature_id)
        )
    return drives, vault


class TestTomlOut:
    def test_round_trips_exam_shapes(self):
        data = tomllib.loads(DRIVE.format(name="x", ttl=1))
        assert tomllib.loads(dumps_toml(data)) == data

    def test_quotes_keys_and_escapes(self):
        text = dumps_toml({"a": 'q"uote\n', "fields": {"#title": "x"}})
        assert text == 'a = "q\\"uote\\n"\n\n[fields]\n"#title" = "x"\n'


class TestPlan:
    def test_each_pair_becomes_a_proof_without_restatements(self, tmp_path):
        drives, vault = _project(tmp_path)
        plan = plan_migration(drives, vault)
        assert plan.ok and sorted(plan.proofs) == ["alpha", "beta", "gamma"]
        proof = plan.proofs["alpha"]
        assert proof["version"] == "3" and "feature_id" not in proof
        assert "kind" not in proof["step"][1] and proof["step"][0]["kind"] == "keygen"
        by_id = {c["id"]: c for c in proof["criterion"]}
        assert "evidence" not in by_id["created"]  # derivable from 'create' (expect → log)
        assert by_id["declared_only"]["evidence"] == ["screenshot"]
        assert by_id["overdeclared"]["evidence"] == ["http_transcript", "video"]

    def test_written_proofs_reproduce_exposure_and_rubric(self, tmp_path):
        drives, vault = _project(tmp_path)
        plan = plan_migration(drives, vault)
        written = write_migration(plan, tmp_path / "proofs")
        assert [p.name for p in written] == ["alpha", "beta", "gamma"]
        assert sorted(p.name for p in written[0].iterdir()) == [EXPOSURE_FILE, RUBRIC_FILE]
        assert (tmp_path / "proofs").stat().st_mode & 0o777 == 0o700
        assert written[0].stat().st_mode & 0o777 == 0o700
        original = tomllib.loads((drives / "alpha.drive.toml").read_text())
        proof = load_proof(tmp_path / "proofs" / "alpha")
        assert exposure(proof) == original
        assert "criterion" not in (written[0] / EXPOSURE_FILE).read_text()
        assert "[[step]]" not in (written[0] / RUBRIC_FILE).read_text()
        scored = rubric(proof)
        assert [c["evidence"] for c in scored["criterion"]] == [
            ["log", "http_transcript"], ["screenshot"], ["http_transcript", "video"],
        ]
        with pytest.raises(MigrateError, match="--force"):
            write_migration(plan, tmp_path / "proofs")

    def test_unpaired_are_reported_not_migrated(self, tmp_path):
        drives, vault = _project(tmp_path, rubrics=("alpha", "beta", "delta"))
        plan = plan_migration(drives, vault)
        assert not plan.ok
        assert plan.unpaired_drives == ["gamma"] and plan.unpaired_rubrics == ["delta"]
        assert sorted(plan.proofs) == ["alpha", "beta"]

    def test_a_broken_pair_is_a_problem(self, tmp_path):
        drives, vault = _project(tmp_path, names=("alpha",), ttls=(120,))
        text = (vault / "alpha.rubric.toml").read_text()
        (vault / "alpha.rubric.toml").write_text(
            text.replace('witnesses = ["create"]', 'witnesses = ["nope"]')
        )
        plan = plan_migration(drives, vault)
        assert "alpha" in plan.problems and "nope" in plan.problems["alpha"]


class TestServeDefaults:
    def test_keys_identical_in_ninety_percent_are_suggested(self, tmp_path):
        drives = [{"serve": {"ttl": 120, "flag": i % 2}} for i in range(10)]
        assert suggest_serve_defaults(drives) == {"ttl": 120}
        drives[0]["serve"]["ttl"] = 5
        assert suggest_serve_defaults(drives) == {"ttl": 120}  # 9 of 10
        drives[1]["serve"]["ttl"] = 5
        assert suggest_serve_defaults(drives) == {}

    def test_applying_defaults_drops_only_matching_keys(self, tmp_path):
        drives, vault = _project(tmp_path, ttls=(120, 120, 20))
        plan = plan_migration(drives, vault)
        assert plan.serve_defaults == {"strict_mode": 0}
        apply_serve_defaults(plan)
        assert plan.proofs["alpha"]["serve"] == {"ttl": 120}
        assert plan.proofs["gamma"]["serve"] == {"ttl": 20}
        assert defaults_block({"ttl": 120, "strict_mode": 0}) == (
            "[serve.defaults]\nttl = 120\nstrict_mode = 0\n"
        )


class TestCli:
    def _tenant(self, tmp_path, monkeypatch, defaults=""):
        monkeypatch.setenv("DARKROOM_HOME", str(tmp_path / "home"))
        root = tmp_path / "tenant"
        root.mkdir()
        (root / "darkroom.toml").write_text(
            textwrap.dedent(f"""
            [project]
            name = "press"
            {defaults}
            """)
        )
        return root

    def test_check_writes_nothing_and_suggests_defaults(self, tmp_path, monkeypatch, capsys):
        root = self._tenant(tmp_path, monkeypatch)
        drives, vault = _project(tmp_path)
        code = main([
            "migrate", "--check", "--project", str(root),
            "--drives", str(drives), "--vault", str(vault), "--out", str(tmp_path / "proofs"),
        ])
        out = capsys.readouterr().out
        assert code == 0 and not (tmp_path / "proofs").exists()
        assert "[serve.defaults]\nttl = 120\nstrict_mode = 0" in out
        assert "3 proof(s)" in out and "(check only)" in out

    def test_writes_into_the_home_and_drops_declared_defaults(self, tmp_path, monkeypatch, capsys):
        root = self._tenant(tmp_path, monkeypatch, "[serve.defaults]\nttl = 120\nstrict_mode = 0")
        drives, vault = _project(tmp_path)
        code = main([
            "migrate", "--project", str(root), "--drives", str(drives), "--vault", str(vault),
        ])
        out = capsys.readouterr().out
        assert code == 0 and "dropped from each proof" in out
        proofs = tmp_path / "home" / "projects" / "press" / "proofs"
        proof = load_proof(proofs / "alpha")
        assert "serve" not in proof
        assert not (root / "proofs").exists()  # the tenant gains no exam material

    def test_an_included_drive_is_posed_against_a_backdrop(self, tmp_path, monkeypatch):
        root = self._tenant(tmp_path, monkeypatch)
        drives, vault = _project(tmp_path, names=("alpha",), ttls=(120,))
        text = (drives / "alpha.drive.toml").read_text()
        (drives / "alpha.drive.toml").write_text(text.replace(
            'scenario = "alpha"\n', 'scenario = "alpha"\ninclude = ["founded"]\n'
        ))
        home = tmp_path / "home" / "projects" / "press"
        home.mkdir(parents=True)
        (home / "backdrops.toml").write_text(
            '[[backdrop]]\nname = "founded"\n[[backdrop.step]]\nname = "found"\nurl = "x"\n'
        )
        assert main([
            "migrate", "--project", str(root), "--drives", str(drives), "--vault", str(vault),
        ]) == 0
        exposure_text = (home / "proofs" / "alpha" / EXPOSURE_FILE).read_text()
        assert 'backdrop = ["founded"]' in exposure_text and "include" not in exposure_text

    def test_build_notes_become_draft_surfaces_beside_the_spec(self, tmp_path, monkeypatch, capsys):
        root = self._tenant(
            tmp_path, monkeypatch, '[scenarios]\nspec_glob = "scenarios/*.feature"'
        )
        specs = root / "scenarios"
        specs.mkdir()
        (specs / "alpha.feature").write_text(
            "Feature: a\n  Scenario: b\n    Given c\n\n  Build: `POST /notes` answers 201.\n"
        )
        (specs / "beta.feature").write_text("Feature: b\n  Scenario: plain\n    Given d\n")
        (specs / "gamma.feature").write_text("Feature: g\n\n  Build: `GET /x`.\n")
        (specs / "gamma.surfaces").write_text("[routes]\nGET /x   already published\n")
        drives, vault = _project(tmp_path)
        assert main([
            "migrate", "--check", "--project", str(root),
            "--drives", str(drives), "--vault", str(vault),
        ]) == 0
        assert "1 draft .surfaces" in capsys.readouterr().out
        assert not (specs / "alpha.surfaces").exists()
        assert main([
            "migrate", "--project", str(root), "--drives", str(drives), "--vault", str(vault),
        ]) == 0
        out = capsys.readouterr().out
        assert "scenarios/alpha.surfaces (draft" in out
        draft = (specs / "alpha.surfaces").read_text()
        assert "[routes]\nPOST /notes\n" in draft and "answers 201" in draft
        assert not (specs / "beta.surfaces").exists()
        assert (specs / "gamma.surfaces").read_text().startswith("[routes]\nGET /x   already")
        assert "Build:" in (specs / "alpha.feature").read_text()  # the spec is never edited

    def test_expose_is_drive(self, tmp_path, monkeypatch, capsys):
        root = self._tenant(tmp_path, monkeypatch)
        empty = tmp_path / "empty"
        empty.mkdir()
        code = main(["expose", "--project", str(root), "--drives", str(empty)])
        assert code == 2 and "no proofs" in capsys.readouterr().out
