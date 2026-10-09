"""The warm services pool: services once per run, a database or a name
per scenario, the opt-out, and a worker that never starts services."""

import subprocess
from types import SimpleNamespace

import pytest

import darkroom.drive as drive
from darkroom.adapter import loads_adapter
from darkroom.drive import (
    DriveError,
    ServicePool,
    _opts_out_of_pool,
    _serve_env,
    bucket_name,
    database_name,
)

ADAPTER = """
[project]
name = "press"

[commands]
serve = "echo app {port} db {postgres.host}:{postgres.port}/{postgres.database} bucket {objects.name}"

[serve.env]
APP_DATABASE_URL = "postgresql://exam@{postgres.host}:{postgres.port}/{postgres.database}"
APP_BUCKET = "{objects.name}"

[[environment.services]]
name = "postgres"
image = "postgres:16"
port = 5432
env = { POSTGRES_PASSWORD = "exam" }
fresh = "database"

[[environment.services]]
name = "objects"
image = "adobe/s3mock:latest"
port = 9090
fresh = "name"
"""


@pytest.fixture
def adapter(tmp_path):
    return loads_adapter(ADAPTER, root=tmp_path)


class _Exec:
    """Records every docker exec and answers as told."""

    def __init__(self, fail_matching=()):
        self.calls: list[tuple[str, list[str]]] = []
        self.fail_matching = tuple(fail_matching)

    def __call__(self, container_id, argv):
        self.calls.append((container_id, argv))
        statement = argv[-1]
        code = 1 if any(f in statement for f in self.fail_matching) else 0
        return subprocess.CompletedProcess(argv, code, stdout="", stderr="refused" if code else "")

    def statements(self):
        return [argv[-1] for _, argv in self.calls]


def _pool():
    return ServicePool(
        specs=[
            {"name": "postgres", "fresh": "database", "user": "postgres"},
            {"name": "objects", "fresh": "name", "user": "postgres"},
            {"name": "cache", "fresh": None, "user": "postgres"},
        ],
        namespaces={
            "postgres": {"host": "127.0.0.1", "port": 54321},
            "objects": {"host": "127.0.0.1", "port": 9091},
            "cache": {"host": "127.0.0.1", "port": None},
        },
        container_ids={"postgres": "pg-id", "objects": "s3-id", "cache": "c-id"},
        digests={"postgres": "sha256:pg"},
    )


class TestAdapter:
    def test_fresh_is_read_and_validated(self, adapter, tmp_path):
        assert {s.name: s.fresh for s in adapter.services} == {
            "postgres": "database", "objects": "name",
        }
        with pytest.raises(ValueError, match='fresh must be "database" or "name"'):
            loads_adapter(ADAPTER.replace('fresh = "name"', 'fresh = "bucket"'), root=tmp_path)


class TestNames:
    def test_database_name_is_an_identifier_with_the_run_stamp(self):
        assert database_name("read_once_note", "2026-01-02T03-04-05") == "read_once_note_030405"
        assert database_name("Notes Page!", "2026-01-02T03-04-05") == "notes_page__030405"
        assert database_name("9lives", "x").startswith("s_9lives")
        assert len(database_name("s" * 100, "2026-01-02T03-04-05")) == 63

    def test_bucket_name_is_s3_safe(self):
        assert bucket_name("read_once_note", "2026-01-02T03-04-05") == "read-once-note-030405"
        assert bucket_name("_leading", "1") == "leading-1"  # dashes trimmed, digits allowed first
        assert len(bucket_name("s" * 100, "2026-01-02T03-04-05")) == 63


class TestPool:
    def test_a_scenario_draws_a_database_and_a_name(self, monkeypatch):
        calls = _Exec()
        monkeypatch.setattr(drive, "_docker_exec", calls)
        pool = _pool()
        spaces = pool.namespace_for("read_once_note", "2026-01-02T03-04-05")
        assert spaces["postgres"].database == "read_once_note_030405"
        assert spaces["postgres"].port == 54321
        assert spaces["objects"].name == "read-once-note-030405"
        assert not hasattr(spaces["cache"], "database")  # shared as-is
        assert calls.statements() == ['CREATE DATABASE "read_once_note_030405"']
        assert calls.calls[0][0] == "pg-id" and calls.calls[0][1][:3] == ["psql", "-U", "postgres"]

        pool.release("read_once_note")
        assert calls.statements()[-1] == 'DROP DATABASE "read_once_note_030405" WITH (FORCE)'
        pool.release("read_once_note")  # idempotent
        assert len(calls.calls) == 2

    def test_drop_falls_back_without_force_on_an_older_server(self, monkeypatch):
        calls = _Exec(fail_matching=("WITH (FORCE)",))
        monkeypatch.setattr(drive, "_docker_exec", calls)
        pool = _pool()
        pool.namespace_for("s", "1")
        pool.release("s")
        assert calls.statements()[-2:] == ['DROP DATABASE "s_1" WITH (FORCE)', 'DROP DATABASE "s_1"']

    def test_a_refused_create_is_a_drive_error(self, monkeypatch):
        calls = _Exec(fail_matching=("CREATE",))
        monkeypatch.setattr(drive, "_docker_exec", calls)
        monkeypatch.setattr(drive.time, "sleep", lambda s: None)
        with pytest.raises(DriveError, match="could not create database"):
            _pool().namespace_for("s", "1")

    def test_round_trips_as_plain_data(self):
        pool = _pool()
        again = ServicePool.from_dict(pool.to_dict())
        assert again.specs == pool.specs and again.namespaces == pool.namespaces
        assert again.container_ids == pool.container_ids and again.digests == pool.digests


class TestSubstitution:
    def test_database_and_name_reach_the_serve_command_and_env(self, adapter, monkeypatch):
        monkeypatch.setattr(drive, "_docker_exec", _Exec())
        spaces = ServicePool(
            specs=[
                {"name": "postgres", "fresh": "database", "user": "postgres"},
                {"name": "objects", "fresh": "name", "user": "postgres"},
            ],
            namespaces={"postgres": {"host": "h", "port": 5}, "objects": {"host": "h", "port": 9}},
            container_ids={"postgres": "pg", "objects": "s3"},
        ).namespace_for("notes_page", "2026-01-02T03-04-05")
        command = adapter.command("serve", port=8000, **spaces)
        assert "db h:5/notes_page_030405 bucket notes-page-030405" in command
        env = _serve_env(adapter, 8000, spaces)
        assert env["APP_DATABASE_URL"] == "postgresql://exam@h:5/notes_page_030405"
        assert env["APP_BUCKET"] == "notes-page-030405"


class TestOptOut:
    def test_fresh_services_and_container_steps_opt_out(self):
        assert _opts_out_of_pool({"environment": {"fresh_services": True}, "step": []})
        assert _opts_out_of_pool({"step": [{"kind": "container", "action": "stop"}]})
        assert not _opts_out_of_pool({"step": [{"kind": "http", "url": "x"}]})
        assert not _opts_out_of_pool({"environment": {"fresh_services": False}, "step": []})


class TestScenarioOnThePool:
    def test_draws_from_the_pool_and_never_starts_services(self, adapter, monkeypatch):
        """With a pool in hand the scenario runner asks it for a namespace,
        hands the names to the server, publishes them as drive values, and
        releases them afterwards — and never constructs services of its own."""
        calls = _Exec()
        monkeypatch.setattr(drive, "_docker_exec", calls)
        seen = {}

        class _StubServer:
            def __init__(self, adapter_, extra, services=None, namespaces=None):
                self.base_url = "http://127.0.0.1:1"
                self.port = 1
                self.services = services
                seen["namespaces"] = namespaces
                seen["command"] = adapter_.command("serve", port=1, **(namespaces or {}))

            def stop(self):
                pass

        def never(*args, **kwargs):
            raise AssertionError("services must not start per scenario on the pool")

        monkeypatch.setattr(drive, "_Server", _StubServer)
        monkeypatch.setattr(drive, "_Services", never)
        monkeypatch.setattr(drive, "_wait_healthy", lambda url: None)
        pool = _pool()
        script = {
            "scenario": "notes_page",
            "step": [
                {"name": "say", "kind": "command",
                 "cmd": "echo {postgres.database} {objects.name}", "expect": {"exit_code": 0}},
                {"name": "probe", "kind": "http", "url": "{base_url}/"},
            ],
        }
        result = drive.drive_scenario(adapter, script, pool=pool, run_id="2026-01-02T03-04-05")
        assert result.steps[0].ok, result.steps[0].detail
        assert seen["namespaces"]["postgres"].database == "notes_page_030405"
        assert "bucket notes-page-030405" in seen["command"]
        assert calls.statements() == [
            'CREATE DATABASE "notes_page_030405"',
            'DROP DATABASE "notes_page_030405" WITH (FORCE)',
        ]

    def test_an_opted_out_scenario_gets_its_own_services(self, adapter, monkeypatch):
        started = []

        class _OwnServices:
            def __init__(self, adapter_):
                started.append(adapter_.name)
                self.namespaces = {
                    "postgres": SimpleNamespace(host="own", port=1),
                    "objects": SimpleNamespace(host="own", port=2),
                }

            def digests(self):
                return {}

            def stop(self):
                pass

        class _StubServer:
            def __init__(self, adapter_, extra, services=None, namespaces=None):
                self.base_url = "http://127.0.0.1:1"
                self.port = 1
                self.services = services

            def stop(self):
                pass

        monkeypatch.setattr(drive, "_Services", _OwnServices)
        monkeypatch.setattr(drive, "_Server", _StubServer)
        monkeypatch.setattr(drive, "_wait_healthy", lambda url: None)
        monkeypatch.setattr(drive, "_docker_exec", _Exec())
        script = {
            "scenario": "restart",
            "environment": {"fresh_services": True},
            "step": [{"name": "probe", "kind": "http", "url": "{base_url}/"}],
        }
        drive.drive_scenario(adapter, script, pool=_pool(), run_id="1")
        assert started == ["press"]


class TestExposureCarriesEnvironment:
    def test_fresh_services_survives_the_proof_loader(self):
        from darkroom.proof import exposure

        proof = {
            "scenario": "s", "environment": {"fresh_services": True},
            "step": [{"name": "a", "kind": "command", "cmd": "true"}],
        }
        assert exposure(proof)["environment"] == {"fresh_services": True}
