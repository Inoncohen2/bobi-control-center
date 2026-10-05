"""Runtime factory for optional Bobi Next cloud integrations."""

from __future__ import annotations

from pathlib import Path

import httpx

from .archive_capture import StoredArchiveBlob
from .archive_configuration import archive_connection_fingerprint
from .cloud_archive_storage import BobiCloudArchiveStorage
from .cloud_identity import cloud_subject
from .integration_store import ExternalIntegration, IntegrationStore
from .local_archive_storage import LocalArchiveStorage
from .secret_vault import EncryptedSecretVault, SecretVaultError
from .setup_store import SetupStore
from .supabase_storage import BobiStorageClient
from .voucher_wallet import VoucherWallet


class IntegrationRuntimeError(RuntimeError):
    pass


def _single_storage(
    integrations: IntegrationStore,
    integration_type: str,
) -> ExternalIntegration:
    matches = integrations.list(integration_type=integration_type, enabled_only=True)
    if not matches:
        raise IntegrationRuntimeError(f"{integration_type}_not_configured")
    if len(matches) != 1:
        raise IntegrationRuntimeError(f"{integration_type}_ambiguous")
    return matches[0]


def _resolve_storage_token(
    integration: ExternalIntegration,
    vault: EncryptedSecretVault,
) -> str:
    if not integration.secret_ref:
        raise IntegrationRuntimeError(f"{integration.integration_type}_secret_missing")
    try:
        return vault.resolve(integration.secret_ref)
    except SecretVaultError as exc:
        raise IntegrationRuntimeError(f"{integration.integration_type}_secret_unavailable") from exc


def build_archive_storage(
    data_dir: str | Path,
    *,
    client: httpx.AsyncClient | None = None,
):
    """Build the configured archive blob provider without network I/O.

    Local storage is the safe zero-configuration default. Cloud storage is used
    only after setup explicitly selects ``archive_storage_mode=cloud`` *and* the
    enabled integration advertises ``archive_enabled=true``. A dedicated
    ``bobi_archive`` integration takes precedence even when disabled; Bobi never
    silently switches its endpoint/token to a voucher integration. Existing
    explicit archive-capable ``bobi_storage`` configurations remain compatible
    when no dedicated archive integration has been configured. Cloud selection
    fails closed when its provider or secret is unavailable.
    """

    root = Path(data_dir)
    setup_path = root / "bobi-next-setup.db"
    setup = SetupStore(setup_path)
    integrations = IntegrationStore(setup_path)
    try:
        mode = str(setup.settings().get("archive_storage_mode", "local")).strip().lower()
        if mode in {"", "local"}:
            return LocalArchiveStorage(root / "bobi-next-archive-files")
        if mode != "cloud":
            raise IntegrationRuntimeError("archive_storage_mode_invalid")
        return _cloud_archive(root, setup, integrations, client=client, writer=True)
    finally:
        setup.close()
        integrations.close()


def _cloud_archive(
    root: Path,
    setup: SetupStore,
    integrations: IntegrationStore,
    *,
    client: httpx.AsyncClient | None = None,
    writer: bool = False,
) -> BobiCloudArchiveStorage:
    archive_type = (
        "bobi_archive" if integrations.list(integration_type="bobi_archive") else "bobi_storage"
    )
    integration = _single_storage(integrations, archive_type)
    if integration.config.get("archive_enabled") is not True:
        raise IntegrationRuntimeError(f"{archive_type}_archive_not_enabled")
    settings = setup.settings()
    if writer and settings.get("archive_connection_check_required") is True:
        proof = settings.get("archive_connection_proof")
        if (
            not isinstance(proof, dict)
            or proof.get("ready") is not True
            or proof.get("fingerprint")
            != archive_connection_fingerprint(setup.installation_id(), integration)
        ):
            raise IntegrationRuntimeError("archive_connection_check_required")
    vault = EncryptedSecretVault(root / "bobi-next-secrets.db", root / "bobi-next-secrets.key")
    try:
        token = _resolve_storage_token(integration, vault)
    finally:
        vault.close()
    storage = BobiStorageClient(integration.endpoint, token, client=client)
    return BobiCloudArchiveStorage(storage, installation_id=setup.installation_id(), client=client)


def build_cloud_archive_storage(
    data_dir: str | Path,
    *,
    client: httpx.AsyncClient | None = None,
) -> BobiCloudArchiveStorage:
    """Resolve existing cloud reads even when new uploads are explicitly local."""
    root = Path(data_dir)
    setup = SetupStore(root / "bobi-next-setup.db")
    integrations = IntegrationStore(root / "bobi-next-setup.db")
    try:
        return _cloud_archive(root, setup, integrations, client=client)
    finally:
        setup.close()
        integrations.close()


class RoutedArchiveStorage:
    """Choose new uploads by setting and existing reads by their exact URI kind.

    Reading a pre-existing local blob in cloud mode is a routed read, never an
    outage fallback. A failed cloud upload/read cannot switch provider or URI.
    """

    def __init__(self, data_dir: str | Path, *, client: httpx.AsyncClient | None = None):
        self.root = Path(data_dir)
        self.client = client
        # Validate the selected writer at construction without network I/O.
        build_archive_storage(self.root, client=client)

    async def upload(
        self,
        *,
        owner_key: str,
        content: bytes,
        filename: str,
        mime_type: str,
        sha256: str,
        idempotency_key: str,
    ) -> StoredArchiveBlob:
        return await build_archive_storage(self.root, client=self.client).upload(
            owner_key=owner_key,
            content=content,
            filename=filename,
            mime_type=mime_type,
            sha256=sha256,
            idempotency_key=idempotency_key,
        )

    async def read(self, storage_uri: str, *, max_bytes: int) -> bytes:
        if storage_uri.startswith("local-archive://"):
            reader = LocalArchiveStorage(self.root / "bobi-next-archive-files")
        elif storage_uri.startswith("bobi-storage://"):
            reader = build_cloud_archive_storage(self.root, client=self.client)
        else:
            raise ValueError("archive_provider_uri_invalid")
        return await reader.read(storage_uri, max_bytes=max_bytes)


def build_voucher_wallet(data_dir: str | Path, *, user_key: str) -> VoucherWallet:
    """Build the single enabled Bobi Storage voucher wallet for ``user_key``.

    The function performs no network I/O. It fails closed when the integration
    is missing, ambiguous, disabled or its encrypted secret cannot be resolved.
    """

    root = Path(data_dir)
    setup_path = root / "bobi-next-setup.db"
    integrations = IntegrationStore(setup_path)
    setup = SetupStore(setup_path)
    vault = EncryptedSecretVault(
        root / "bobi-next-secrets.db",
        root / "bobi-next-secrets.key",
    )
    try:
        integration = _single_storage(integrations, "bobi_storage")
        token = _resolve_storage_token(integration, vault)

        subject = cloud_subject(setup.installation_id(), user_key)
        storage = BobiStorageClient(integration.endpoint, token)
        return VoucherWallet(storage, profile_external_id=subject)
    finally:
        vault.close()
        setup.close()
        integrations.close()
