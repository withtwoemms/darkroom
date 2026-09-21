"""Unit tests for the darkroom home."""

from pathlib import Path

import pytest

from darkroom.cli import main
from darkroom.homedir import (
    darkroom_home,
    default_drives,
    default_state,
    default_vault,
    ensure_project_home,
    find_operator_config,
    project_home,
)


class TestResolution:
    def test_env_override(self, tmp_path, monkeypatch):
        monkeypatch.setenv("DARKROOM_HOME", str(tmp_path / "custom"))
        assert darkroom_home() == tmp_path / "custom"
        assert project_home("p") == tmp_path / "custom" / "projects" / "p"

    def test_default_under_user_home(self, monkeypatch):
        monkeypatch.delenv("DARKROOM_HOME", raising=False)
        assert darkroom_home() == Path.home() / ".darkroom"

    def test_project_name_required(self):
        with pytest.raises(ValueError, match="project name"):
            project_home("")

    def test_defaults_partition_by_project(self, tmp_path, monkeypatch):
        monkeypatch.setenv("DARKROOM_HOME", str(tmp_path))
        assert default_vault("a") != default_vault("b")
        assert default_state("a").parts[-2:] == ("a", "state")
        assert default_drives("a").parts[-1] == "drives"


class TestEnsure:
    def test_creates_partitioned_tree_mode_700(self, tmp_path, monkeypatch):
        monkeypatch.setenv("DARKROOM_HOME", str(tmp_path / "home"))
        project = ensure_project_home("watch")
        for sub in ("vault", "drives", "state"):
            assert (project / sub).is_dir()
        assert ((tmp_path / "home").stat().st_mode & 0o777) == 0o700
        assert (project.stat().st_mode & 0o777) == 0o700

    def test_operator_discovery(self, tmp_path, monkeypatch):
        monkeypatch.setenv("DARKROOM_HOME", str(tmp_path))
        assert find_operator_config("p") is None
        project = ensure_project_home("p")
        (project / "operator.toml").write_text('[judge]\nmodel = "m"')
        assert find_operator_config("p") == project / "operator.toml"


class TestHomeCLI:
    def test_init_and_path(self, tmp_path, capsys, monkeypatch):
        monkeypatch.setenv("DARKROOM_HOME", str(tmp_path / "home"))
        (tmp_path / "darkroom.toml").write_text('[project]\nname = "press"')
        monkeypatch.chdir(tmp_path)

        assert main(["home", "init"]) == 0
        out = capsys.readouterr().out
        assert "home initialized:" in out and "vault/" in out
        assert (tmp_path / "home" / "projects" / "press" / "state").is_dir()

        assert main(["home", "path"]) == 0
        assert capsys.readouterr().out.strip().endswith("projects/press")


class TestHomeDefaultsInCommands:
    def test_vault_seal_defaults_to_home(self, tmp_path, capsys, monkeypatch):
        monkeypatch.setenv("DARKROOM_HOME", str(tmp_path / "home"))
        root = tmp_path / "tenant"
        (root / "scenarios").mkdir(parents=True)
        (root / "scenarios" / "a.rubric.toml").write_text(
            'feature_id = "a"\nversion = "1"\n[[criterion]]\nid = "c"\n'
            'points = 1\ndescription = "d"\nevidence = ["log"]'
        )
        (root / "darkroom.toml").write_text(
            '[project]\nname = "press"\n[scenarios]\n'
            'rubric_glob = "scenarios/*.rubric.toml"'
        )
        monkeypatch.chdir(root)
        assert main(["vault", "seal"]) == 0
        capsys.readouterr()
        assert (
            tmp_path / "home" / "projects" / "press" / "vault" / "a.rubric.toml"
        ).exists()

    def test_ticket_store_defaults_to_home(self, tmp_path, capsys, monkeypatch):
        monkeypatch.setenv("DARKROOM_HOME", str(tmp_path / "home"))
        root = tmp_path / "tenant"
        root.mkdir()
        (root / "darkroom.toml").write_text('[project]\nname = "press"')
        monkeypatch.chdir(root)
        assert main(["ticket", "new", "builder", "hello"]) == 0
        capsys.readouterr()
        queue = tmp_path / "home" / "projects" / "press" / "state" / "queue" / "builder"
        assert queue.is_dir() and list(queue.glob("*.md"))
        assert not (root / ".darkroom").exists()  # nothing leaks into the tenant