"""Unit tests for operator configuration."""

from pathlib import Path

from darkroom.operator import (
    DEFAULT_INVOKE,
    loads_operator,
)

FULL = """
[judge]
model = "claude-opus-5"
tools = ["Read", "Write"]

[judge.invoke]
command = "my-harness --model {model} < {prompt}"

[builder]
model = "claude-sonnet-5"
escalated_model = "claude-opus-5"

[vault]
backend = "filesystem"
path = "~/vaults/press"

[loop]
max_iterations = 5
diagnostic_after = 1
"""


class TestOperatorConfig:
    def test_full_document(self):
        config = loads_operator(FULL)
        assert config.judge.model == "claude-opus-5"
        assert config.judge.tools == ("Read", "Write")
        assert config.judge.invoke == "my-harness --model {model} < {prompt}"
        assert config.builder.escalated_model == "claude-opus-5"
        assert config.vault_backend == "filesystem"
        assert config.vault_path == Path("~/vaults/press").expanduser()
        assert config.loop.max_iterations == 5
        assert config.loop.diagnostic_after == 1
        assert config.loop.target_score == 100.0  # default preserved

    def test_defaults(self):
        config = loads_operator("")
        assert config.judge.model == "claude-opus-5"
        assert config.builder.model == "claude-sonnet-5"
        assert config.judge.invoke == DEFAULT_INVOKE
        assert "Bash" in config.builder.diagnostic_tools
        assert "Bash" not in config.builder.tools
        assert config.vault_path is None
        assert config.loop.max_iterations == 8


class TestVaultBackendConfig:
    def test_openbao_section(self):
        config = loads_operator(
            '[vault]\nbackend = "openbao"\nurl = "http://127.0.0.1:8200"\n'
            'mount = "kv"\npath = "darkroom/press/rubrics"'
        )
        assert config.vault_backend == "openbao"
        assert config.vault_url == "http://127.0.0.1:8200"
        assert config.vault_mount == "kv"
        assert config.vault_kv_path == "darkroom/press/rubrics"
        assert config.vault_path is None  # path is a KV path, not a filesystem one

    def test_build_vault_filesystem_default(self, tmp_path, monkeypatch):
        from darkroom.operator import build_vault
        from darkroom.vault import FilesystemVault

        monkeypatch.setenv("DARKROOM_HOME", str(tmp_path))
        vault = build_vault(loads_operator(""), "press")
        assert isinstance(vault, FilesystemVault)
        assert "press" in str(vault.root)

    def test_build_vault_openbao_needs_url(self):
        import pytest

        from darkroom.operator import build_vault
        from darkroom.vault import VaultError

        with pytest.raises(VaultError, match="needs a url"):
            build_vault(loads_operator('[vault]\nbackend = "openbao"'), "press")

    def test_build_vault_openbao_default_kv_path(self, monkeypatch):
        __import__("pytest").importorskip("hvac")
        from darkroom.operator import build_vault

        monkeypatch.setenv("BAO_TOKEN", "t")
        vault = build_vault(
            loads_operator('[vault]\nbackend = "openbao"\nurl = "http://x:1"'),
            "press",
        )
        assert vault.path == "darkroom/press/rubrics"
