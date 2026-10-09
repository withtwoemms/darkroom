"""A backdrops.toml beside the proofs wins over the operator home's."""

from darkroom.adapter import loads_adapter
from darkroom.drive import backdrops_file
from darkroom.homedir import default_backdrops


def _adapter(tmp_path, name="relay-service"):
    return loads_adapter(
        f'schema_version = "1.0"\n[project]\nname = "{name}"\n[commands]\nserve = "x"\ntest = "x"\n',
        root=tmp_path,
    )


class TestBackdropsFile:
    def test_beside_the_proofs_wins(self, tmp_path):
        proofs = tmp_path / "proofs"
        proofs.mkdir()
        (proofs / "backdrops.toml").write_text('[[backdrop]]\nname = "note_saved"\n[[backdrop.step]]\nname = "create"\n')
        assert backdrops_file(_adapter(tmp_path), proofs) == proofs / "backdrops.toml"

    def test_otherwise_the_home(self, tmp_path):
        proofs = tmp_path / "proofs"
        proofs.mkdir()
        assert backdrops_file(_adapter(tmp_path), proofs) == default_backdrops("relay-service")

    def test_no_project_name_means_none(self, tmp_path):
        from darkroom.backdrops import backdrops_for

        assert backdrops_for(None, tmp_path) is None
        assert backdrops_for("", None) is None
