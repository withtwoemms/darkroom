"""[serve.defaults], [serve.env], [browser.defaults] in darkroom.toml: an
exam carries only what differs from the project's defaults, and the engine
sets the served process's environment itself."""

import os
import sys
import textwrap
import time
from types import SimpleNamespace

import pytest

from darkroom.adapter import loads_adapter
from darkroom.drive import DriveError, _serve_env, _Server

ADAPTER = """
[project]
name = "press"

[commands]
serve = "echo {port} {ttl} {strict_mode}"

[serve.defaults]
ttl = 120
strict_mode = 0
billing_stub = 1

[serve.env]
APP_TTL_SECONDS = "{ttl}"
APP_DATABASE_URL = "postgresql://exam@{postgres.host}:{postgres.port}/app"
APP_PORT = "{port}"

[browser.defaults]
webauthn = true
prf = true
"""


class TestAdapterDefaults:
    def test_serve_defaults_merge_under_the_exam(self, tmp_path):
        adapter = loads_adapter(ADAPTER, root=tmp_path)
        assert adapter.serve_vars({"ttl": 20}) == {
            "ttl": 20, "strict_mode": 0, "billing_stub": 1,
        }
        assert adapter.serve_vars(None) == adapter.serve_defaults

    def test_browser_defaults_merge_under_the_exam(self, tmp_path):
        adapter = loads_adapter(ADAPTER, root=tmp_path)
        assert adapter.browser_options({"prf": False}) == {"webauthn": True, "prf": False}
        assert adapter.browser_options(None) == {"webauthn": True, "prf": True}

    def test_env_templates_must_be_strings(self, tmp_path):
        bad = ADAPTER.replace('APP_PORT = "{port}"', "APP_PORT = 8080")
        with pytest.raises(ValueError, match=r"\[serve\.env\] APP_PORT"):
            loads_adapter(bad, root=tmp_path)

    def test_absent_tables_leave_old_adapters_untouched(self, tmp_path):
        adapter = loads_adapter('[project]\nname = "p"', root=tmp_path)
        assert adapter.serve_defaults == {} and adapter.serve_env == ()
        assert adapter.serve_vars({"ttl": 5}) == {"ttl": 5}


class TestServeEnv:
    def test_templates_resolve_port_vars_and_services(self, tmp_path):
        adapter = loads_adapter(ADAPTER, root=tmp_path)
        env = _serve_env(
            adapter, 4242,
            {"ttl": 20, "postgres": SimpleNamespace(host="127.0.0.1", port=55432)},
        )
        assert env == {
            "APP_TTL_SECONDS": "20",
            "APP_DATABASE_URL": "postgresql://exam@127.0.0.1:55432/app",
            "APP_PORT": "4242",
        }

    def test_a_missing_placeholder_is_named(self, tmp_path):
        adapter = loads_adapter(ADAPTER, root=tmp_path)
        with pytest.raises(DriveError, match=r"APP_DATABASE_URL needs a value for \{postgres\}"):
            _serve_env(adapter, 1, {"ttl": 20})

    @pytest.mark.skipif(sys.platform == "win32", reason="sh")
    def test_the_served_process_sees_the_env(self, tmp_path):
        out = tmp_path / "env.txt"
        adapter = loads_adapter(
            textwrap.dedent(f"""
            [project]
            name = "p"
            [commands]
            serve = "sh -c 'echo $APP_TTL_SECONDS:$APP_PORT > {out}'"
            [serve.defaults]
            ttl = 7
            [serve.env]
            APP_TTL_SECONDS = "{{ttl}}"
            APP_PORT = "{{port}}"
            """),
            root=tmp_path,
        )
        server = _Server(adapter, adapter.serve_vars({}))
        try:
            for _ in range(100):
                if out.exists() and out.read_text().strip():
                    break
                time.sleep(0.05)
        finally:
            server.stop()
        assert out.read_text().strip() == f"7:{server.port}"
        assert "APP_TTL_SECONDS" not in os.environ  # set on the child only
