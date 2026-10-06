"""A small TOML writer for exam files (the stdlib reads TOML, never writes).

Covers what exams contain: scalars, lists, tables, arrays of tables, and
dict values rendered as inline tables (``json = { ... }``,
``save = { ... }``, ``fields = { "#title" = "x" }``). Top-level scalars
come first, then tables, then arrays of tables, so the output reads the
way a hand-written exam does.
"""

from __future__ import annotations

import re

_BARE_KEY = re.compile(r"^[A-Za-z0-9_-]+$")


def _key(name: str) -> str:
    return name if _BARE_KEY.match(name) else _string(name)


def _string(value: str) -> str:
    escaped = (
        value.replace("\\", "\\\\")
        .replace('"', '\\"')
        .replace("\n", "\\n")
        .replace("\t", "\\t")
        .replace("\r", "\\r")
    )
    return f'"{escaped}"'


def _value(value) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return repr(value)
    if isinstance(value, str):
        return _string(value)
    if isinstance(value, list):
        return "[" + ", ".join(_value(v) for v in value) + "]"
    if isinstance(value, dict):
        if not value:
            return "{}"
        return "{ " + ", ".join(f"{_key(k)} = {_value(v)}" for k, v in value.items()) + " }"
    raise TypeError(f"cannot write {type(value).__name__} to TOML")


def _is_table_array(value) -> bool:
    return isinstance(value, list) and bool(value) and all(isinstance(v, dict) for v in value)


def dumps_toml(data: dict) -> str:
    lines: list[str] = []
    scalars = {k: v for k, v in data.items() if not isinstance(v, dict) and not _is_table_array(v)}
    tables = {k: v for k, v in data.items() if isinstance(v, dict)}
    arrays = {k: v for k, v in data.items() if _is_table_array(v)}

    for name, value in scalars.items():
        lines.append(f"{_key(name)} = {_value(value)}")
    for name, table in tables.items():
        lines += ["", f"[{_key(name)}]"]
        lines += [f"{_key(k)} = {_value(v)}" for k, v in table.items()]
    for name, items in arrays.items():
        for item in items:
            lines += ["", f"[[{_key(name)}]]"]
            lines += [f"{_key(k)} = {_value(v)}" for k, v in item.items()]
    return "\n".join(lines).lstrip("\n") + "\n"
