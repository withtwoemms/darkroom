"""Run-to-run manifest diffing: what changed between two captures."""

from __future__ import annotations

from dataclasses import dataclass, field

from darkroom.model import RunManifest


def _item_keys(manifest: RunManifest, scenario: str) -> set[str]:
    for bundle in manifest.scenarios:
        if bundle.scenario == scenario:
            return {f"{item.kind}:{item.step}" for item in bundle.items}
    return set()


@dataclass
class RunDiff:
    scenarios_added: list[str] = field(default_factory=list)
    scenarios_removed: list[str] = field(default_factory=list)
    items_added: dict[str, list[str]] = field(default_factory=dict)
    items_removed: dict[str, list[str]] = field(default_factory=dict)

    @property
    def unchanged(self) -> bool:
        return not (
            self.scenarios_added
            or self.scenarios_removed
            or self.items_added
            or self.items_removed
        )


def diff_runs(old: RunManifest, new: RunManifest) -> RunDiff:
    """Compare two runs by scenario and (kind, step) item identity."""
    old_names = {b.scenario for b in old.scenarios}
    new_names = {b.scenario for b in new.scenarios}

    diff = RunDiff(
        scenarios_added=sorted(new_names - old_names),
        scenarios_removed=sorted(old_names - new_names),
    )
    for name in sorted(old_names & new_names):
        old_items = _item_keys(old, name)
        new_items = _item_keys(new, name)
        added = sorted(new_items - old_items)
        removed = sorted(old_items - new_items)
        if added:
            diff.items_added[name] = added
        if removed:
            diff.items_removed[name] = removed
    return diff
