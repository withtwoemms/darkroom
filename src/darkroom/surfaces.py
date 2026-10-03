"""The surfaces doc string: the spec's declared contract, audited.

A spec names every surface the scenario rests on — routes with the
outcome the builder must produce, selectors with the state attributes a
page must carry — in a Gherkin doc string whose media type is
``surfaces``, on whichever step claims it::

    And the surfaces hold:
      \"\"\"surfaces
      POST /notes                        → 201 {id, token}
      DELETE /notes/{id}  X-Note-Token   → 204; wrong token → 403
      #delete-button [data-state=armed|fired]
      \"\"\"

A doc string is legal Gherkin anywhere a step is, so the spec stays a
``.feature`` any tool can parse; the media type is what makes this one
the contract. Left of the arrow is the surface: a line opening with an
HTTP method is a route (``{name}`` segments match anything), anything
else a selector — everything up to the first run of two spaces, so
``#notes li`` is one selector and what follows is its description. The audit
cross-checks the block against the scenario's exam both ways: a step
touching a surface the spec never names is ``surface-undeclared`` (the
spec is the builder's whole contract, so the exam is testing something
the builder was never told), and a declared surface no step touches is
``surface-untouched`` (declared, but unproven). A spec without the doc
string declares nothing and gets no findings.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

HTTP_METHODS = frozenset({"GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"})

# a doc string opens with """ or ``` and an optional media type; only one
# typed `surfaces` is the contract — other doc strings are the step's own
_FENCE_OPEN = re.compile(r'^\s*("""|```)\s*surfaces\s*$')
_FENCE_CLOSE = re.compile(r'^\s*("""|```)\s*$')
_ARROW = re.compile(r"\s*(?:→|->)\s*")
_COLUMN_GAP = re.compile(r"\s{2,}")
_PLACEHOLDER = re.compile(r"\{[^}]*\}")


@dataclass(frozen=True)
class Surface:
    kind: str  # "route" | "selector"
    method: str = ""  # routes only
    target: str = ""  # a normalized path for routes, the selector token otherwise
    line: str = ""  # as written in the spec

    def __str__(self) -> str:
        return f"{self.method} {self.target}" if self.kind == "route" else self.target


def normalize_path(url: str) -> str:
    """The path a URL or template addresses, placeholders widened to ``*``:
    ``{base_url}/notes/{note_id}?x=1`` and ``/notes/{id}`` both become
    ``/notes/*``."""
    url = _PLACEHOLDER.sub("*", url)
    if url.startswith("*"):
        url = url[1:]  # an interpolated base_url
    if "://" in url:
        authority_and_path = url.split("://", 1)[1]
        url = "/" + authority_and_path.split("/", 1)[1] if "/" in authority_and_path else "/"
    path = url.split("?", 1)[0].split("#", 1)[0]
    if not path.startswith("/"):
        path = "/" + path
    return path.rstrip("/") or "/"


def route(method: str, url: str) -> Surface:
    return Surface("route", method.upper(), normalize_path(url))


def selector(text: str) -> Surface:
    return Surface("selector", target=text.strip())


def parse_surfaces(text: str) -> list[Surface] | None:
    """The surfaces a spec declares, or None when it has no surfaces doc
    string. Several such doc strings (one per scenario, say) add up."""
    lines = text.splitlines()
    found = False
    surfaces: list[Surface] = []
    index = 0
    while index < len(lines):
        if _FENCE_OPEN.match(lines[index]) is None:
            index += 1
            continue
        found = True
        index += 1
        while index < len(lines) and _FENCE_CLOSE.match(lines[index]) is None:
            body = lines[index].strip()
            index += 1
            entry = _ARROW.split(body, maxsplit=1)[0].strip() if body else ""
            if not entry:
                continue
            first, *rest = entry.split()
            if first.upper() in HTTP_METHODS and rest:
                surfaces.append(Surface("route", first.upper(), normalize_path(rest[0]), body))
            else:
                # a selector may have descendant parts ("#notes li"); the
                # description column starts at the first run of 2+ spaces
                target = _COLUMN_GAP.split(entry, maxsplit=1)[0].strip()
                surfaces.append(Surface("selector", target=target, line=body))
        index += 1  # past the closing fence
    return surfaces if found else None


def load_surfaces(path: Path) -> list[Surface] | None:
    return parse_surfaces(Path(path).read_text())


def touched_surfaces(script: dict) -> list[Surface]:
    """Every surface an exam's steps address, in step order, deduplicated."""
    seen: list[Surface] = []

    def _add(surface: Surface) -> None:
        if surface not in seen:
            seen.append(surface)

    for step in script.get("step", []):
        kind = step.get("kind", "http")
        if kind == "http" and step.get("url"):
            _add(route(step.get("method", "GET"), step["url"]))
        elif kind == "goto" and step.get("url"):
            _add(route("GET", step["url"]))
        elif kind == "click" and step.get("selector"):
            _add(selector(step["selector"]))
        elif kind == "fill":
            for sel in step.get("fields", {}):
                _add(selector(sel))
        visible = step.get("expect", {}).get("selector_visible")
        if visible:
            _add(selector(visible))
    return seen


def _routes_match(declared: Surface, touched: Surface) -> bool:
    if declared.method != touched.method:
        return False
    left, right = declared.target.split("/"), touched.target.split("/")
    return len(left) == len(right) and all(
        a == b or a == "*" or b == "*" for a, b in zip(left, right, strict=True)
    )


def matches(declared: Surface, touched: Surface) -> bool:
    if declared.kind != touched.kind:
        return False
    if declared.kind == "route":
        return _routes_match(declared, touched)
    return touched.target == declared.target or touched.target == declared.line


def cross_check(declared: list[Surface], script: dict) -> list[tuple[str, str]]:
    """(code, message) pairs: ``surface-undeclared`` for a touched surface
    the spec never names, ``surface-untouched`` for a declared one no step
    reaches."""
    findings: list[tuple[str, str]] = []
    touched = touched_surfaces(script)
    for surface in touched:
        if not any(matches(d, surface) for d in declared):
            findings.append(
                (
                    "surface-undeclared",
                    f"the exam touches {surface.kind} '{surface}' but the spec's "
                    "surfaces never name it — the builder was not told",
                )
            )
    for surface in declared:
        if not any(matches(surface, t) for t in touched):
            findings.append(
                (
                    "surface-untouched",
                    f"the spec declares {surface.kind} '{surface}' but no step "
                    "touches it — declared, not proven",
                )
            )
    return findings
