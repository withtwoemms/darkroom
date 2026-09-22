"""OpenBao / HashiCorp Vault backend for the rubric vault.

Implements the :class:`darkroom.vault.RubricVault` protocol over KV v2
via ``hvac`` (API-compatible with both OpenBao and HashiCorp Vault),
behind the ``vault`` extra: ``pip install 'darkroom-ai[vault]'``.

What this backend buys over the filesystem vault: token-gated reads,
native version history, and server-side audit devices a compromised
builder cannot edit. The token lives in the *operator process*
environment (``BAO_TOKEN`` or ``VAULT_TOKEN``) — agent subprocesses
never hold it, since darkroom itself reads the vault and inlines rubric
text into judge prompts.

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
            return response["data"]["data"]["rubric"]

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
            text = response["data"]["data"]["rubric"]
            stored = str(tomllib.loads(text).get("version", ""))
            if stored == version:
                return text
        raise VaultError(
            f"no revision of rubric '{feature_id}' carries version "
            f"'{version}' within the last {VERSION_WALK_CAP} writes"
        )

    def write(self, feature_id: str, text: str) -> None:
        """Store a rubric (a new KV version if it already exists)."""
        self.client.secrets.kv.v2.create_or_update_secret(
            path=self._secret_path(feature_id),
            secret={"rubric": text},
            mount_point=self.mount,
        )
