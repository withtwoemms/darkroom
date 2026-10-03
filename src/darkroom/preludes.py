"""Preludes: named step sequences an exam includes instead of repeating.

Half the steps in a mature exam corpus are the same founding, joining,
and signing-in that every scenario starts from — copied by hand, and
drifting by hand. A project's operator home may hold ``preludes.toml``::

    [[prelude]]
    name = "founded_by_dad"
    [[prelude.step]]
    name = "found_circle"
    kind = "goto"
    ...

and an exam says ``include = ["founded_by_dad", "mom_joins"]``: the
engine expands the includes, in order, ahead of the exam's own steps.
Step names survive expansion, so a criterion's witnesses still resolve;
a name that would collide is refused rather than silently shadowed.
"""

from __future__ import annotations

import sys
from pathlib import Path

if sys.version_info >= (3, 11):
    import tomllib
else:  # pragma: no cover - exercised only on 3.10
    import tomli as tomllib


class PreludeError(Exception):
    pass


def loads_preludes(text: str) -> dict[str, list[dict]]:
    data = tomllib.loads(text)
    preludes: dict[str, list[dict]] = {}
    for entry in data.get("prelude", []):
        name = entry.get("name")
        if not name:
            raise PreludeError("every [[prelude]] needs a name")
        if name in preludes:
            raise PreludeError(f"prelude '{name}' is defined twice")
        steps = entry.get("step", [])
        if not steps:
            raise PreludeError(f"prelude '{name}' has no steps")
        preludes[name] = [dict(step) for step in steps]
    return preludes


def load_preludes(path: Path | None) -> dict[str, list[dict]]:
    """The project's preludes, or none when the file is absent."""
    if path is None or not Path(path).is_file():
        return {}
    return loads_preludes(Path(path).read_text())


def expand(script: dict, preludes: dict[str, list[dict]]) -> dict:
    """The script with its ``include`` list resolved into leading steps.
    Returns a new dict; the input is left as written."""
    includes = script.get("include", [])
    if not includes:
        return script
    if not isinstance(includes, list) or not all(isinstance(i, str) for i in includes):
        raise PreludeError(f"{script.get('scenario', '?')}: include must be a list of names")
    expanded: list[dict] = []
    seen: dict[str, str] = {}
    for include in includes:
        if include not in preludes:
            known = ", ".join(sorted(preludes)) or "none defined"
            raise PreludeError(
                f"{script.get('scenario', '?')}: unknown prelude '{include}' ({known})"
            )
        for step in preludes[include]:
            _claim(step, f"prelude '{include}'", seen, script)
            expanded.append(dict(step))
    for step in script.get("step", []):
        _claim(step, "the exam itself", seen, script)
        expanded.append(step)
    result = dict(script)
    result["step"] = expanded
    result.pop("include", None)
    return result


def _claim(step: dict, owner: str, seen: dict[str, str], script: dict) -> None:
    name = step.get("name")
    if not name:
        return
    if name in seen:
        raise PreludeError(
            f"{script.get('scenario', '?')}: step '{name}' from {owner} collides "
            f"with the same name from {seen[name]} — witnesses must be unambiguous"
        )
    seen[name] = owner
