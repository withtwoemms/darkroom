"""Packaged skills and the drift check."""

from darkroom import skills


class TestPackaged:
    def test_four_skills_ship_with_the_engine(self):
        assert set(skills.packaged_skills()) == {
            "darkroom-interview",
            "darkroom-converge",
            "darkroom-chronicle",
            "darkroom-status",
        }
        for d in skills.packaged_skills().values():
            assert (d / "SKILL.md").read_text().startswith("---")


class TestCheck:
    def test_missing_when_nothing_installed(self, tmp_path):
        findings = skills.check(home=tmp_path)
        assert {f.status for f in findings} == {"missing"}
        assert len(findings) == 4

    def test_install_links_and_checks_current(self, tmp_path):
        written = skills.install(home=tmp_path)
        assert len(written) == 4 and all(p.is_symlink() for p in written)
        findings = skills.check(home=tmp_path)
        assert all(f.ok for f in findings)
        assert all("symlink" in f.detail for f in findings)

    def test_copied_then_edited_is_stale(self, tmp_path):
        skills.install(home=tmp_path, link=False)
        edited = tmp_path / ".claude" / "skills" / "darkroom-converge" / "SKILL.md"
        edited.write_text(edited.read_text() + "\nlocal tweak\n")
        by_name = {f.skill: f for f in skills.check(home=tmp_path)}
        assert by_name["darkroom-converge"].status == "stale"
        assert by_name["darkroom-interview"].status == "current"
        assert "copy" in by_name["darkroom-interview"].detail

    def test_plugin_installed_copies_are_found(self, tmp_path):
        plug = tmp_path / ".claude" / "plugins" / "cache" / "darkroom" / "skills" / "darkroom-chronicle"
        plug.mkdir(parents=True)
        src = skills.packaged_skills()["darkroom-chronicle"] / "SKILL.md"
        (plug / "SKILL.md").write_bytes(src.read_bytes())
        by_name = {f.skill: f for f in skills.check(home=tmp_path)}
        assert by_name["darkroom-chronicle"].ok

    def test_install_does_not_clobber_without_force(self, tmp_path):
        skills.install(home=tmp_path, link=False)
        target = tmp_path / ".claude" / "skills" / "darkroom-interview" / "SKILL.md"
        target.write_text("edited")
        assert skills.install(home=tmp_path) == []  # nothing rewritten
        assert target.read_text() == "edited"
        skills.install(home=tmp_path, force=True)
        assert all(f.ok for f in skills.check(home=tmp_path))
