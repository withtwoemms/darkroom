"""Operator configuration: the authority-side counterpart to darkroom.toml.

Everything the trust rule bars from the tenant file lives here — judge
and builder models, tool allowlists, invocation templates, the vault
location, and loop policy. This file must never live inside the tenant
repository; ``darkroom auto`` requires it explicitly (no default
location) precisely so it cannot be discovered from builder-writable
space.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass, field
from pathlib import Path

if sys.version_info >= (3, 11):
    import tomllib
else:  # pragma: no cover - exercised only on 3.10
    import tomli as tomllib

from darkroom.loop import LoopPolicy

DEFAULT_INVOKE = (
    'claude -p --model {model} --allowed-tools "{tools}" {add_dirs} < {prompt}'
)

JUDGE_DEFAULT_TOOLS = ["Read", "Write", "Glob", "Grep"]
BUILDER_DEFAULT_TOOLS = ["Read", "Write", "Edit", "Glob", "Grep"]
BUILDER_DIAGNOSTIC_TOOLS = ["Read", "Write", "Edit", "Glob", "Grep", "Bash"]


@dataclass(frozen=True)
class RoleConfig:
    model: str
    tools: tuple[str, ...]
    invoke: str = DEFAULT_INVOKE
    template_path: Path | None = None
    escalated_model: str | None = None
    diagnostic_tools: tuple[str, ...] = ()


@dataclass(frozen=True)
class OperatorConfig:
    judge: RoleConfig
    builder: RoleConfig
    vault_backend: str = "filesystem"
    vault_path: Path | None = None
    loop: LoopPolicy = field(default_factory=LoopPolicy)


def loads_operator(text: str) -> OperatorConfig:
    data = tomllib.loads(text)

    judge_raw = data.get("judge", {})
    builder_raw = data.get("builder", {})
    vault_raw = data.get("vault", {})
    loop_raw = data.get("loop", {})

    judge = RoleConfig(
        model=judge_raw.get("model", "claude-opus-5"),
        tools=tuple(judge_raw.get("tools", JUDGE_DEFAULT_TOOLS)),
        invoke=judge_raw.get("invoke", {}).get("command", DEFAULT_INVOKE)
        if isinstance(judge_raw.get("invoke"), dict)
        else judge_raw.get("invoke", DEFAULT_INVOKE),
        template_path=Path(judge_raw["template"]) if "template" in judge_raw else None,
    )
    builder = RoleConfig(
        model=builder_raw.get("model", "claude-sonnet-5"),
        tools=tuple(builder_raw.get("tools", BUILDER_DEFAULT_TOOLS)),
        invoke=builder_raw.get("invoke", {}).get("command", DEFAULT_INVOKE)
        if isinstance(builder_raw.get("invoke"), dict)
        else builder_raw.get("invoke", DEFAULT_INVOKE),
        template_path=Path(builder_raw["template"])
        if "template" in builder_raw
        else None,
        escalated_model=builder_raw.get("escalated_model", "claude-opus-5"),
        diagnostic_tools=tuple(
            builder_raw.get("diagnostic_tools", BUILDER_DIAGNOSTIC_TOOLS)
        ),
    )

    defaults = LoopPolicy()
    loop = LoopPolicy(
        max_iterations=loop_raw.get("max_iterations", defaults.max_iterations),
        target_score=loop_raw.get("target_score", defaults.target_score),
        diagnostic_after=loop_raw.get("diagnostic_after", defaults.diagnostic_after),
        escalate_model_after=loop_raw.get(
            "escalate_model_after", defaults.escalate_model_after
        ),
        rollback_on_regression=loop_raw.get(
            "rollback_on_regression", defaults.rollback_on_regression
        ),
    )

    vault_path = vault_raw.get("path")
    return OperatorConfig(
        judge=judge,
        builder=builder,
        vault_backend=vault_raw.get("backend", "filesystem"),
        vault_path=Path(vault_path).expanduser() if vault_path else None,
        loop=loop,
    )


def load_operator(path: Path) -> OperatorConfig:
    return loads_operator(Path(path).read_text())
