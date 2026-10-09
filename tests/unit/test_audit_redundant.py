"""audit --redundant: scenarios whose touched surfaces another covers."""

import textwrap

from darkroom.audit import dumps_redundancy, redundancy
from darkroom.cli import main
from darkroom.vault import FilesystemVault


def _rubric(scenario, criteria=1, points=10):
    body = "\n".join(
        f'[[criterion]]\nid = "c{i}"\npoints = {points}\ndescription = "d"\nwitnesses = ["open"]\n'
        for i in range(criteria)
    )
    return f'version = "1"\nscenario = "{scenario}"\n\n{body}'


def _exposure(scenario, steps):
    out = [f'scenario = "{scenario}"']
    for kind, target in steps:
        if kind == "goto":
            out.append(
                f'[[step]]\nname = "open"\nkind = "goto"\nurl = "{{base_url}}{target}"\n'
                "expect = { status = 200 }"
            )
        elif kind == "click":
            out.append(
                f"[[step]]\nname = \"open\"\nkind = \"click\"\nselector = '{target}'\n"
                'expect = { url_contains = "/" }'
            )
        elif kind == "http":
            method, path = target.split(" ", 1)
            out.append(
                f'[[step]]\nname = "open"\nmethod = "{method}"\nurl = "{{base_url}}{path}"\n'
                "expect = { status = 200 }"
            )
    return "\n\n".join(out) + "\n"


def _tenant(tmp_path, scenarios, proofs=None):
    """scenarios: {name: (steps, published, criteria, points)}; returns
    (vault, proofs, specs)."""
    root = tmp_path / "tenant"
    (root / "scenarios").mkdir(parents=True)
    proofs = proofs or tmp_path / "home" / "proofs"
    specs = []
    for name, (steps, published, criteria, points) in scenarios.items():
        folder = proofs / name
        folder.mkdir(parents=True)
        (folder / "exposure.toml").write_text(_exposure(name, steps))
        (folder / "rubric.toml").write_text(_rubric(name, criteria, points))
        spec = root / "scenarios" / f"{name}.feature"
        spec.write_text(f"Feature: {name}\n  Scenario: s\n    Given x\n")
        if published:
            (root / "scenarios" / f"{name}.surfaces").write_text(textwrap.dedent(published))
        specs.append(spec)
    vault = FilesystemVault(tmp_path / "home" / "vault", proofs=proofs)
    vault.initialize()
    return vault, proofs, specs


PAGE = (
    "[routes]\n\n[commands]\n\n[pages]\n/   the notes page\n#save   the control\n"
    "#notes li[data-archived]   one per note\n\n[files]\n\n[notes]\n"
)


class TestRedundancy:
    def test_a_pure_duplicate_is_a_candidate(self, tmp_path):
        vault, proofs, specs = _tenant(tmp_path, {
            "notes_page": ([("goto", "/"), ("click", "#save")], PAGE, 2, 20),
            "notes_page_again": ([("goto", "/"), ("click", "#save")], PAGE, 1, 5),
        })
        report = {r.scenario: r for r in redundancy(vault, proofs, specs=specs)}
        assert report["notes_page_again"].candidate
        assert report["notes_page_again"].covered_by == ("notes_page",)
        # symmetric: each covers the other, so both are candidates — the
        # criterion counts are what tell a reader which to keep
        assert report["notes_page"].candidate
        assert (report["notes_page"].criteria, report["notes_page"].points) == (2, 40)

    def test_one_unique_surface_keeps_a_scenario_off_the_list(self, tmp_path):
        vault, proofs, specs = _tenant(tmp_path, {
            "notes_page": ([("goto", "/"), ("click", "#save")], PAGE, 1, 10),
            "archived_note_shows_its_state": (
                [("goto", "/"), ("click", '#notes li[data-archived="true"]')], PAGE, 1, 10,
            ),
        })
        report = {r.scenario: r for r in redundancy(vault, proofs, specs=specs)}
        assert not report["archived_note_shows_its_state"].candidate
        # the click narrowed to a state is reported as the element published
        assert report["archived_note_shows_its_state"].unique == ("#notes li[data-archived]",)
        assert not report["notes_page"].candidate  # alone on #save

    def test_a_candidate_still_shows_its_criteria(self, tmp_path):
        vault, proofs, specs = _tenant(tmp_path, {
            "note_lifecycle": ([("http", "POST /notes"), ("http", "GET /notes/1")], None, 1, 20),
            "note_fetch": ([("http", "GET /notes/1")], None, 3, 12),
        })
        report = redundancy(vault, proofs, specs=specs)
        text = dumps_redundancy(report)
        assert report[0].scenario == "note_fetch" and report[0].candidate
        assert "note_fetch  [3 criteria, 36 points]  covered by: note_lifecycle" in text
        assert "candidates: 1 of 2" in text
        assert "retires anything" in text

    def test_cli_flag(self, tmp_path, monkeypatch, capsys):
        # the audit command reads the project's home: DARKROOM_HOME/projects/<name>/
        home = tmp_path / "home" / "projects" / "relay"
        vault, proofs, specs = _tenant(tmp_path, {
            "notes_page": ([("goto", "/")], PAGE, 1, 10),
            "notes_page_again": ([("goto", "/")], PAGE, 1, 10),
        }, proofs=home / "proofs")
        root = tmp_path / "tenant"
        (root / "darkroom.toml").write_text(
            'schema_version = "1.0"\n[project]\nname = "relay"\n[commands]\nserve = "x"\ntest = "x"\n'
            '[scenarios]\nspec_glob = "scenarios/*.feature"\n'
        )
        operator = home / "operator.toml"
        operator.write_text('[vault]\nbackend = "filesystem"\n')
        monkeypatch.chdir(root)
        code = main(["audit", "--redundant", "--operator", str(operator)])
        out = capsys.readouterr().out
        assert code == 0
        assert "candidates: 2 of 2" in out
