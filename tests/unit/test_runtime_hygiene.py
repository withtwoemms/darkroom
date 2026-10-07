"""The engine cleans up after a scenario and prepares its container runtime:
a listener an exposure left on the scenario's port is swept, evidence runs
are pruned to a declared count with gated runs kept, and colima's Ryuk
socket override is set when (and only when) it is needed."""

import json
import os
import socket
import subprocess
import sys
import time

import pytest

from darkroom import drive
from darkroom.adapter import loads_adapter


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.mark.skipif(sys.platform == "win32", reason="lsof")
class TestPortSweep:
    def test_a_detached_listener_on_the_port_is_swept(self):
        port = _free_port()
        # a server started in its own session, the way a restart scenario's
        # `nohup uvicorn …` escapes the engine's process group
        child = subprocess.Popen(
            [sys.executable, "-m", "http.server", str(port), "--bind", "127.0.0.1"],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True,
        )
        try:
            for _ in range(50):
                if drive._listeners(port):
                    break
                time.sleep(0.1)
            assert child.pid in drive._listeners(port)
            swept = drive._sweep_port(port)
            assert child.pid in swept
            child.wait(timeout=5)
            assert drive._listeners(port) == []
        finally:
            if child.poll() is None:
                child.kill()

    def test_nothing_to_sweep_is_quiet(self):
        assert drive._sweep_port(_free_port()) == []


class TestColimaOverride:
    def test_needed_only_for_a_colima_host_with_nothing_set(self, monkeypatch, tmp_path):
        monkeypatch.setenv("HOME", str(tmp_path))
        monkeypatch.delenv(drive.RYUK_SOCKET_OVERRIDE, raising=False)
        monkeypatch.delenv("TESTCONTAINERS_RYUK_DISABLED", raising=False)
        monkeypatch.setenv("DOCKER_HOST", "unix:///Users/me/.colima/default/docker.sock")
        assert drive.colima_socket_override_needed()
        assert drive.prepare_container_runtime() is True
        assert os.environ[drive.RYUK_SOCKET_OVERRIDE] == drive.VM_DOCKER_SOCKET
        assert drive.prepare_container_runtime() is False  # already set

    def test_properties_file_is_read_when_env_is_silent(self, monkeypatch, tmp_path):
        monkeypatch.setenv("HOME", str(tmp_path))
        monkeypatch.delenv("DOCKER_HOST", raising=False)
        monkeypatch.delenv(drive.RYUK_SOCKET_OVERRIDE, raising=False)
        monkeypatch.delenv("TESTCONTAINERS_RYUK_DISABLED", raising=False)
        (tmp_path / ".testcontainers.properties").write_text(
            "docker.host=unix:///Users/me/.colima/default/docker.sock\nryuk.container.privileged=true\n"
        )
        assert drive.docker_host_setting().endswith("/.colima/default/docker.sock")
        assert drive.colima_socket_override_needed()

    def test_not_needed_for_docker_desktop_or_when_ryuk_is_off(self, monkeypatch, tmp_path):
        monkeypatch.setenv("HOME", str(tmp_path))
        monkeypatch.delenv(drive.RYUK_SOCKET_OVERRIDE, raising=False)
        monkeypatch.setenv("DOCKER_HOST", "unix:///var/run/docker.sock")
        assert not drive.colima_socket_override_needed()
        monkeypatch.setenv("DOCKER_HOST", "unix:///Users/me/.colima/default/docker.sock")
        monkeypatch.setenv("TESTCONTAINERS_RYUK_DISABLED", "true")
        assert not drive.colima_socket_override_needed()


class TestPruneRuns:
    def _tenant(self, tmp_path, keep):
        root = tmp_path / "tenant"
        root.mkdir()
        evidence = root / "evidence" / "runs"
        for stamp in ("2026-10-01T00-00-00", "2026-10-02T00-00-00", "2026-10-03T00-00-00", "2026-10-04T00-00-00"):
            (evidence / stamp).mkdir(parents=True)
            (evidence / stamp / "manifest.json").write_text("{}")
        (root / "evidence-gates.json").write_text(json.dumps({
            "peaks": [{"scenario": "a", "score": 100.0, "run_id": "2026-10-01T00-00-00"}]
        }))
        text = '[project]\nname = "press"\n[evidence]\ngates = "evidence-gates.json"\n'
        if keep is not None:
            text += f"keep_runs = {keep}\n"
        return loads_adapter(text, root=root), evidence

    def test_newest_kept_gated_kept_rest_removed(self, tmp_path):
        adapter, evidence = self._tenant(tmp_path, keep=2)
        removed = drive.prune_runs(adapter)
        assert [p.name for p in removed] == ["2026-10-02T00-00-00"]
        assert sorted(p.name for p in evidence.iterdir()) == [
            "2026-10-01T00-00-00",  # cited by a gate
            "2026-10-03T00-00-00", "2026-10-04T00-00-00",  # the newest two
        ]

    def test_unset_prunes_nothing(self, tmp_path):
        adapter, evidence = self._tenant(tmp_path, keep=None)
        assert drive.prune_runs(adapter) == []
        assert len(list(evidence.iterdir())) == 4

    def test_keep_runs_must_be_a_positive_integer(self, tmp_path):
        with pytest.raises(ValueError, match="keep_runs"):
            loads_adapter('[project]\nname = "p"\n[evidence]\nkeep_runs = 0\n', root=tmp_path)
