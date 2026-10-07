"""The packaged skills and the check that keeps installed copies honest.

The darkroom skills ship inside the wheel (``darkroom/skills/``)
and are version-locked to the engine by construction. Anyone who
installs them by hand — a copy into ``~/.claude/skills`` — can drift as
the engine moves; ``darkroom skills check`` compares every installed
copy against the packaged one by content hash, so a stale or hand-edited
skill is reported instead of silently steering an operator wrong.
"""

from __future__ import annotations

import hashlib
import shutil
from dataclasses import dataclass
from pathlib import Path

SKILL_FILE = "SKILL.md"


def packaged_root() -> Path:
    """Where this engine's skills live (package data, editable or wheel)."""
    return Path(__file__).parent / "skills"


def packaged_skills() -> dict[str, Path]:
    """Skill name -> directory, for every skill shipped with this engine."""
    root = packaged_root()
    if not root.is_dir():
        return {}
    return {
        d.name: d
        for d in sorted(root.iterdir())
        if d.is_dir() and (d / SKILL_FILE).is_file()
    }


def _digest(skill_dir: Path) -> str:
    return hashlib.sha256((skill_dir / SKILL_FILE).read_bytes()).hexdigest()


@dataclass(frozen=True)
class Finding:
    skill: str
    status: str  # "current" | "stale" | "missing"
    path: Path | None
    detail: str

    @property
    def ok(self) -> bool:
        return self.status == "current"


def installed_locations(home: Path) -> list[Path]:
    """Every place Claude Code might load a darkroom skill from under a home."""
    claude = home / ".claude"
    found: list[Path] = []
    for d in sorted((claude / "skills").glob("darkroom-*")):
        if (d / SKILL_FILE).is_file():
            found.append(d)
    # plugin-installed copies: <plugins>/**/skills/darkroom-*/SKILL.md
    for f in sorted((claude / "plugins").glob(f"**/skills/darkroom-*/{SKILL_FILE}")):
        found.append(f.parent)
    return found


def check(home: Path | None = None) -> list[Finding]:
    """Compare installed skill copies against the packaged ones, by hash."""
    home = home or Path.home()
    packaged = packaged_skills()
    installed = installed_locations(home)
    findings: list[Finding] = []
    for name, src in packaged.items():
        copies = [d for d in installed if d.name == name]
        if not copies:
            findings.append(
                Finding(name, "missing", None, "not installed; run `darkroom skills install`")
            )
            continue
        want = _digest(src)
        for copy in copies:
            have = _digest(copy)
            if have == want:
                how = "symlink" if copy.is_symlink() else "copy"
                findings.append(Finding(name, "current", copy, f"matches the engine ({how})"))
            else:
                findings.append(
                    Finding(
                        name,
                        "stale",
                        copy,
                        "differs from this engine's skill; run "
                        "`darkroom skills install --force` (or update the plugin)",
                    )
                )
    return findings


def install(home: Path | None = None, *, link: bool = True, force: bool = False) -> list[Path]:
    """Install the packaged skills into ~/.claude/skills (symlinks by default)."""
    home = home or Path.home()
    dest_root = home / ".claude" / "skills"
    dest_root.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    for name, src in packaged_skills().items():
        dest = dest_root / name
        if dest.exists() or dest.is_symlink():
            if not force:
                continue
            if dest.is_symlink() or dest.is_file():
                dest.unlink()
            else:
                shutil.rmtree(dest)
        if link:
            dest.symlink_to(src, target_is_directory=True)
        else:
            shutil.copytree(src, dest)
        written.append(dest)
    return written
