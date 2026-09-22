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

# --output-format json makes the CLI report token usage and cost on
# stdout, which the loop meters into usage.jsonl; a custom template
# without it still works — its usage records are just partial.
DEFAULT_INVOKE = (
    "claude -p --model {model} --output-format json "
    '--allowed-tools "{tools}" {add_dirs} < {prompt}'
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
    vault_url: str = ""
    vault_mount: str = "secret"
    vault_kv_path: str = ""
    containers_mode: str = "auto"
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

    backend = vault_raw.get("backend", "filesystem")
    path_raw = vault_raw.get("path")
    if backend == "openbao":
        vault_path, kv_path = None, (path_raw or "")
    else:
        vault_path = Path(path_raw).expanduser() if path_raw else None
        kv_path = ""
    return OperatorConfig(
        judge=judge,
        builder=builder,
        vault_backend=backend,
        vault_path=vault_path,
        vault_url=vault_raw.get("url", ""),
        vault_mount=vault_raw.get("mount", "secret"),
        vault_kv_path=kv_path,
        containers_mode=data.get("containers", {}).get("mode", "auto"),
        loop=loop,
    )


def load_operator(path: Path) -> OperatorConfig:
    return loads_operator(Path(path).read_text())


def build_vault(config: OperatorConfig, project_name: str):
    """The configured rubric vault backend for a project."""
    if config.vault_backend == "openbao":
        from darkroom.vault import VaultError
        from darkroom.vault_openbao import OpenBaoVault

        if not config.vault_url:
            raise VaultError("[vault] backend = 'openbao' needs a url")
        kv_path = config.vault_kv_path or f"darkroom/{project_name}/rubrics"
        return OpenBaoVault(
            url=config.vault_url, path=kv_path, mount=config.vault_mount
        )
    from darkroom.homedir import default_vault
    from darkroom.vault import FilesystemVault

    return FilesystemVault(config.vault_path or default_vault(project_name))
