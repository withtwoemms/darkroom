"""Integration tests for the OpenBao vault backend, against a real server.

Runs against ``bao server -dev`` (or ``vault server -dev``) when a
binary is present; skipped otherwise. No mocks — the backend's whole
value is server-side behavior.
"""

import shutil
import socket
import subprocess
import time

import pytest

pytest.importorskip("hvac")

from darkroom.contract import loads_contract  # noqa: E402
from darkroom.vault import RubricVault, VaultError, derive_contract  # noqa: E402
from darkroom.vault_openbao import OpenBaoVault  # noqa: E402

BINARY = shutil.which("bao") or shutil.which("vault")
pytestmark = pytest.mark.skipif(
    BINARY is None, reason="no bao/vault binary on PATH"
)

RUBRIC_V1 = 'feature_id = "pay-invoices"\nversion = "1"\nscenario = "pay_invoices"\n\n[[criterion]]\nid = "settles"\npoints = 10\ndescription = "d"\nevidence = ["http_transcript"]\n'
RUBRIC_V2 = RUBRIC_V1.replace('version = "1"', 'version = "2"').replace(
    'evidence = ["http_transcript"]', 'evidence = ["http_transcript", "log"]'
)


@pytest.fixture(scope="module")
def server():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    address = f"http://127.0.0.1:{port}"
    process = subprocess.Popen(
        [
            BINARY, "server", "-dev",
            "-dev-root-token-id=darkroom-test",
            f"-dev-listen-address=127.0.0.1:{port}",
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        import hvac

        client = hvac.Client(url=address, token="darkroom-test")
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline:
            try:
                if client.sys.is_initialized():
                    break
            except Exception:
                time.sleep(0.2)
        else:
            raise RuntimeError("dev server never became ready")
        yield address
    finally:
        process.terminate()
        process.wait(timeout=5)


@pytest.fixture()
def vault(server, monkeypatch):
    monkeypatch.setenv("BAO_TOKEN", "darkroom-test")
    import uuid

    return OpenBaoVault(
        url=server, path=f"darkroom/test-{uuid.uuid4().hex[:8]}/rubrics"
    )


class TestOpenBaoVault:
    def test_protocol_conformance(self, vault):
        assert isinstance(vault, RubricVault)

    def test_write_list_read(self, vault):
        vault.write("pay-invoices", RUBRIC_V1)
        assert vault.list() == ["pay-invoices"]
        assert 'feature_id = "pay-invoices"' in vault.read("pay-invoices")

    def test_empty_vault_lists_nothing(self, vault):
        assert vault.list() == []

    def test_missing_rubric(self, vault):
        with pytest.raises(VaultError, match="no rubric"):
            vault.read("ghost")

    def test_versioned_read_walks_history(self, vault):
        vault.write("pay-invoices", RUBRIC_V1)
        vault.write("pay-invoices", RUBRIC_V2)
        assert 'version = "2"' in vault.read("pay-invoices")  # latest
        assert 'version = "1"' in vault.read("pay-invoices", version="1")
        assert 'version = "2"' in vault.read("pay-invoices", version="2")
        with pytest.raises(VaultError, match="no revision"):
            vault.read("pay-invoices", version="9")

    def test_derive_contract_through_backend(self, vault):
        vault.write("pay-invoices", RUBRIC_V2)
        contract = derive_contract(vault, project="press")
        scenario = contract.for_scenario("pay_invoices")
        assert [r.kind for r in scenario.requirements] == [
            "http_transcript", "log",
        ]
        assert loads_contract  # imported round-trip sanity elsewhere

    def test_missing_token_refused(self, server, monkeypatch):
        monkeypatch.delenv("BAO_TOKEN", raising=False)
        monkeypatch.delenv("VAULT_TOKEN", raising=False)
        with pytest.raises(VaultError, match="no vault token"):
            OpenBaoVault(url=server, path="darkroom/x/rubrics")
