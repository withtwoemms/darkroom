"""Backdrops: named step sequences an exposure is posed against.

Half the steps in a mature exposure corpus are the same founding,
joining, and signing-in that every scenario starts from — copied by
hand, and drifting by hand. A backdrop is that setup named once: set
before the sitting, reused across many, and never the subject. A
project's operator home may hold ``backdrops.toml``::

    [[backdrop]]
    name = "note_saved"
    [[backdrop.step]]
    name = "save_note"
    kind = "goto"
    ...

and an exposure says ``backdrop = ["note_saved", "note_archived"]``:
the engine expands them, in order, ahead of the exposure's own steps.
Step names survive expansion, so a criterion's witnesses still
resolve; a name that would collide is refused rather than silently
shadowed. The authoring rule that follows: a witness is never in the
backdrop — what the scenario proves is in its own steps.
"""

from __future__ import annotations

import sys
from pathlib import Path

if sys.version_info >= (3, 11):
    import tomllib
else:  # pragma: no cover - exercised only on 3.10
    import tomli as tomllib

BACKDROPS_FILE = "backdrops.toml"
BACKDROP_MARK = "_backdrop"  # set on expanded steps: the backdrop they came from


class BackdropError(Exception):
    pass


def loads_backdrops(text: str) -> dict[str, list[dict]]:
    data = tomllib.loads(text)
    backdrops: dict[str, list[dict]] = {}
    for entry in data.get("backdrop", []):
        name = entry.get("name")
        if not name:
            raise BackdropError("every [[backdrop]] needs a name")
        if name in backdrops:
            raise BackdropError(f"backdrop '{name}' is defined twice")
        steps = entry.get("step", [])
        if not steps:
            raise BackdropError(f"backdrop '{name}' has no steps")
        backdrops[name] = [dict(step) for step in steps]
    return backdrops


def load_backdrops(path: Path | None) -> dict[str, list[dict]]:
    """The project's backdrops, or none when the file is absent."""
    if path is None or not Path(path).is_file():
        return {}
    return loads_backdrops(Path(path).read_text())


def expand(script: dict, backdrops: dict[str, list[dict]]) -> dict:
    """The script with its ``backdrop`` list resolved into leading steps.
    Returns a new dict; the input is left as written."""
    wanted = script.get("backdrop", [])
    if not wanted:
        return script
    if not isinstance(wanted, list) or not all(isinstance(i, str) for i in wanted):
        raise BackdropError(f"{script.get('scenario', '?')}: backdrop must be a list of names")
    expanded: list[dict] = []
    seen: dict[str, str] = {}
    for name in wanted:
        if name not in backdrops:
            known = ", ".join(sorted(backdrops)) or "none defined"
            raise BackdropError(
                f"{script.get('scenario', '?')}: unknown backdrop '{name}' ({known})"
            )
        for step in backdrops[name]:
            _claim(step, f"backdrop '{name}'", seen, script)
            # the engine ignores the marker; the audit uses it to leave a
            # backdrop's surfaces to the scenario that owns them
            expanded.append({**step, BACKDROP_MARK: name})
    for step in script.get("step", []):
        _claim(step, "the exposure itself", seen, script)
        expanded.append(step)
    result = dict(script)
    result["step"] = expanded
    result.pop("backdrop", None)
    return result


def _claim(step: dict, owner: str, seen: dict[str, str], script: dict) -> None:
    name = step.get("name")
    if not name:
        return
    if name in seen:
        raise BackdropError(
            f"{script.get('scenario', '?')}: step '{name}' from {owner} collides "
            f"with the same name from {seen[name]} — witnesses must be unambiguous"
        )
    seen[name] = owner
