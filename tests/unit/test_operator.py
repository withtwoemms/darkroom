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
