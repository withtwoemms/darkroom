"""OpenBao / HashiCorp Vault backend for the rubric vault.

Implements the :class:`darkroom.vault.RubricVault` protocol over KV v2
via ``hvac`` (API-compatible with both OpenBao and HashiCorp Vault),
behind the ``vault`` extra: ``pip install 'darkroom-ai[vault]'``.

What this backend buys over the filesystem vault: policy-gated reads,
native version history, and server-side audit devices a compromised
builder cannot edit. The boundary is OpenBao's own RBAC: the operator's
token (``BAO_TOKEN`` or ``VAULT_TOKEN`` in the *operator process*
environment) carries a policy that reads the rubric path, and darkroom
itself uses it to inline rubric text into judge prompts. Agent
subprocesses never inherit it — ``agents.SCRUBBED_ENV`` strips those
names — and a builder that legitimately needs the vault is handed its
own token in its invoke template, bound to a policy that denies the
rubric path.

Version semantics: ``read(version=...)`` refers to the rubric's own
``version`` field (the identity evaluations pin), not KV revision
numbers. Versioned reads walk KV history newest-first (bounded) to find
the matching rubric.
"""

from __future__ import annotations

import os
import sys

if sys.version_info >= (3, 11):
    import tomllib
else:  # pragma: no cover - exercised only on 3.10
    import tomli as tomllib

from darkroom.vault import VaultError

VERSION_WALK_CAP = 20


def _rubric_half(text: str) -> str:
    """A stored proof carries steps; the judge is handed its criteria only."""
    data = tomllib.loads(text)
    if "step" not in data:
        return text
    from darkroom.proof import ProofError, loads_proof, rubric_text

    try:
        return rubric_text(loads_proof(text))
    except ProofError as exc:
        raise VaultError(str(exc)) from None


class OpenBaoVault:
    """Rubrics as KV v2 secrets, one per feature id, key ``rubric``."""

    def __init__(
        self,
        url: str,
        path: str,
        mount: str = "secret",
        token: str | None = None,
    ):
        try:
            import hvac
        except ImportError:
            raise VaultError(
                "the openbao backend needs the vault extra: "
                "pip install 'darkroom-ai[vault]'"
            ) from None
        token = token or os.environ.get("BAO_TOKEN") or os.environ.get("VAULT_TOKEN")
        if not token:
            raise VaultError(
                "no vault token: set BAO_TOKEN or VAULT_TOKEN in the "
                "operator environment (never in a config file)"
            )
        self.client = hvac.Client(url=url, token=token)
        self.mount = mount
        self.path = path.strip("/")

    def _secret_path(self, feature_id: str) -> str:
        return f"{self.path}/{feature_id}"

    def list(self) -> list[str]:
        import hvac

        try:
            response = self.client.secrets.kv.v2.list_secrets(
                path=self.path, mount_point=self.mount
            )
        except hvac.exceptions.InvalidPath:
            return []
        return sorted(response["data"]["keys"])

    def read(self, feature_id: str, version: str | None = None) -> str:
        import hvac

        if version is None:
            try:
                response = self.client.secrets.kv.v2.read_secret_version(
                    path=self._secret_path(feature_id),
                    mount_point=self.mount,
                    raise_on_deleted_version=True,
                )
            except hvac.exceptions.InvalidPath:
                raise VaultError(
                    f"no rubric '{feature_id}' in the vault"
                ) from None
            return _rubric_half(response["data"]["data"]["rubric"])

        metadata = self.client.secrets.kv.v2.read_secret_metadata(
            path=self._secret_path(feature_id), mount_point=self.mount
        )
        kv_versions = sorted(
            (int(v) for v in metadata["data"]["versions"]), reverse=True
        )
        for kv_version in kv_versions[:VERSION_WALK_CAP]:
            try:
                response = self.client.secrets.kv.v2.read_secret_version(
                    path=self._secret_path(feature_id),
                    version=kv_version,
                    mount_point=self.mount,
                    raise_on_deleted_version=True,
                )
            except hvac.exceptions.InvalidPath:
                continue
            text = _rubric_half(response["data"]["data"]["rubric"])
            stored = str(tomllib.loads(text).get("version", ""))
            if stored == version:
                return text
        raise VaultError(
            f"no revision of rubric '{feature_id}' carries version "
            f"'{version}' within the last {VERSION_WALK_CAP} writes"
        )

    def write(self, feature_id: str, text: str) -> None:
        """Store a rubric or a whole proof (a new KV version if it already
        exists). A proof is stored intact — exposure and rubric are one
        secret — and ``read`` hands back only its rubric half."""
        self.client.secrets.kv.v2.create_or_update_secret(
            path=self._secret_path(feature_id),
            secret={"rubric": text},
            mount_point=self.mount,
        )
