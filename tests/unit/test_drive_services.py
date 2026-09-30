"""Declared services beside a process-mode app: containers per scenario,
addresses substituted into the serve command, teardown with the server."""

import socket

import pytest

from darkroom.adapter import loads_adapter
from darkroom.drive import DriveError, _Server, _Services

ADAPTER = """
[project]
name = "press"

[commands]
serve = "echo app on {port} db at {postgres.host}:{postgres.port} cache {cache.host}"

[[environment.services]]
name = "postgres"
image = "postgres:16"
port = 5432
env = { POSTGRES_PASSWORD = "exam" }

[[environment.services]]
name = "cache"
image = "redis:7"
command = ["redis-server", "--save", ""]
"""


class _FakeContainer:
    """Just enough of testcontainers' DockerContainer: a real listening
    socket stands in for the mapped port so the readiness probe is real."""

    instances: list = []

    def __init__(self, image):
        self.image = image
        self.env = {}
        self.exposed = []
        self.sock = None
        self.stopped = False
        _FakeContainer.instances.append(self)

    def with_env(self, key, value):
        self.env[key] = value
        return self

    def with_command(self, command):
        self.command = command
        return self

    def with_exposed_ports(self, port):
        self.exposed.append(port)
        return self

    def start(self):
        self.sock = socket.socket()
        self.sock.bind(("127.0.0.1", 0))
        self.sock.listen(1)
        return self

    def get_container_host_ip(self):
        return "127.0.0.1"

    def get_exposed_port(self, port):
        return self.sock.getsockname()[1]

    def stop(self):
        self.stopped = True
        if self.sock is not None:
            self.sock.close()


class _BrokenContainer(_FakeContainer):
    def start(self):
        raise RuntimeError("image pull failed")


@pytest.fixture(autouse=True)
def _reset():
    _FakeContainer.instances = []
    yield
    for c in _FakeContainer.instances:
        c.stop()


@pytest.fixture()
def adapter(tmp_path):
    return loads_adapter(ADAPTER, root=tmp_path)


class TestServices:
    def test_each_service_starts_with_env_and_a_mapped_port(self, adapter):
        services = _Services(adapter, container_cls=_FakeContainer)
        pg, cache = _FakeContainer.instances
        assert pg.image == "postgres:16" and pg.env == {"POSTGRES_PASSWORD": "exam"}
        assert pg.exposed == [5432]
        assert services.namespaces["postgres"].host == "127.0.0.1"
        assert services.namespaces["postgres"].port == pg.sock.getsockname()[1]
        # a service with no declared port is started but never probed
        assert cache.exposed == [] and services.namespaces["cache"].port is None
        # a declared command replaces the image's; none declared leaves it alone
        assert cache.command == ["redis-server", "--save", ""]
        assert getattr(pg, "command", None) is None
        services.stop()
        assert pg.stopped and cache.stopped

    def test_a_command_must_be_an_array_of_strings(self, tmp_path):
        bad = ADAPTER.replace('command = ["redis-server", "--save", ""]', "command = [1, 2]")
        with pytest.raises(ValueError, match="command must be an array of strings"):
            loads_adapter(bad, root=tmp_path)

    def test_a_failed_start_tears_down_what_started(self, adapter):
        calls = []

        def pick(image):
            calls.append(image)
            return _BrokenContainer(image) if image.startswith("redis") else _FakeContainer(image)

        with pytest.raises(RuntimeError, match="image pull failed"):
            _Services(adapter, container_cls=pick)
        pg = _FakeContainer.instances[0]
        assert pg.stopped

    def test_unreachable_service_is_refused(self, adapter):
        def never(host, port, timeout=30.0):
            raise DriveError("service never accepted a connection")

        with pytest.raises(DriveError, match="never accepted"):
            _Services(adapter, container_cls=_FakeContainer, wait=never)


class TestServerWithServices:
    def test_addresses_reach_the_serve_command(self, adapter):
        services = _Services(adapter, container_cls=_FakeContainer)
        server = _Server(adapter, {}, services=services)
        try:
            pg = _FakeContainer.instances[0]
            assert f"db at 127.0.0.1:{pg.sock.getsockname()[1]}" in server.command
            assert f"app on {server.port}" in server.command
            assert "cache 127.0.0.1" in server.command
        finally:
            server.stop()
        assert all(c.stopped for c in _FakeContainer.instances)

    def test_no_services_means_no_change(self, tmp_path):
        plain = loads_adapter(
            '[project]\nname = "p"\n[commands]\nserve = "echo {port} {ttl}"', root=tmp_path
        )
        server = _Server(plain, {"ttl": 5})
        try:
            assert server.services is None and "5" in server.command
        finally:
            server.stop()


class TestDriveValues:
    def test_service_addresses_are_drive_values(self, adapter, monkeypatch):
        """The process-mode branch publishes {name.host}/{name.port} into the
        drive context; exercised through the same wiring the scenario runner
        uses, with the server and browser stubbed out."""
        import darkroom.drive as drive

        seen = {}

        class _StubServer:
            def __init__(self, adapter_, extra, services=None):
                self.base_url = "http://127.0.0.1:1"
                self.port = 1
                self.services = services
                seen["services"] = services

            def stop(self):
                pass

        monkeypatch.setattr(drive, "_Server", _StubServer)
        monkeypatch.setattr(drive, "_wait_healthy", lambda url: None)
        monkeypatch.setattr(
            drive, "_Services", lambda a: _Services(a, container_cls=_FakeContainer)
        )
        monkeypatch.setattr(drive, "_image_digest", lambda image: "sha256:test")
        script = {
            "scenario": "addr",
            "step": [
                {"name": "say", "kind": "command", "cmd": "echo {postgres.host}:{postgres.port}",
                 "expect": {"exit_code": 0}},
                # an http step is what makes the runner boot a server (and
                # so its services); it fails against the stub, after "say"
                {"name": "probe", "kind": "http", "url": "{base_url}/"},
            ],
        }
        result = drive.drive_scenario(adapter, script)
        assert result.steps[0].ok, result.steps[0].detail
        pg = _FakeContainer.instances[0]
        assert seen["services"].namespaces["postgres"].port == pg.sock.getsockname()[1]
