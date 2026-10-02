"""The served app is a process tree (`make serve` -> `uv run` -> the server);
stopping the scenario must take the whole tree down, not just the shell."""

import os
import sys
import textwrap
import time

import pytest

from darkroom.adapter import loads_adapter
from darkroom.drive import _Server


def _alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    return True


@pytest.mark.skipif(sys.platform == "win32", reason="process groups")
def test_stop_takes_down_the_grandchild(tmp_path):
    pidfile = tmp_path / "grandchild.pid"
    # the shell runs a child shell that runs the "server"; the server's pid
    # is written before the parent waits — three generations, like make
    serve = textwrap.dedent(f"""
        sh -c '{sys.executable} -c "import time; time.sleep(300)" & echo $! > {pidfile}; wait'
    """).strip().replace("\n", " ")
    adapter = loads_adapter(
        f'[project]\nname = "tree"\n[commands]\nserve = """{serve}"""\n', root=tmp_path
    )
    server = _Server(adapter, {})
    try:
        for _ in range(100):
            if pidfile.exists() and pidfile.read_text().strip():
                break
            time.sleep(0.05)
        grandchild = int(pidfile.read_text().strip())
        assert _alive(grandchild)
    finally:
        server.stop()
    for _ in range(40):
        if not _alive(grandchild):
            break
        time.sleep(0.05)
    assert not _alive(grandchild), "the served app outlived the scenario"
