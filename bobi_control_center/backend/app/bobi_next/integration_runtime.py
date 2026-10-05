"""Runtime factory for optional Bobi Next cloud integrations."""

from __future__ import annotations

from pathlib import Path

from .cloud_archive_storage import BobiCloudArchiveStorage
from .cloud_identity import cloud_subject
from .integration_store import IntegrationStore
from .local_archive_storage import LocalArchiveStorage
from .secret_vault import EncryptedSecretVault, SecretVaultError
from .setup_store import SetupStore
from .supabase_storage import BobiStorageClient
from .voucher_wallet import VoucherWallet


class IntegrationRuntimeError(RuntimeError):
    pass


def _single_bobi_storage(integrations: IntegrationStore):
    matches = integrations.list(integration_type="bobi_storage", enabled_only=True)
    if not matches:
        raise IntegrationRuntimeError("bobi_storage_not_configured")
    if len(matches) != 1:
        raise IntegrationRuntimeError("bobi_storage_ambiguous")
    return matches[0]


def _resolve_storage_token(
    integration,
    vault: EncryptedSecretVault,
) -> str:
    if not integration.secret_ref:
        raise IntegrationRuntimeError("bobi_storage_secret_missing")
    try:
        return vault.resolve(integration.secret_ref)
    except SecretVaultError as exc:
        raise IntegrationRuntimeError("bobi_storage_secret_unavailable") from exc


def build_archive_storage(data_dir: str | Path):
    """Build the configured archive blob provider without network I/O.

    Local storage is the safe zero-configuration default. Cloud storage is used
    only after setup explicitly selects ``archive_storage_mode=cloud`` *and* the
    enabled Bobi Storage integration advertises ``archive_enabled=true``. An
    explicit cloud selection fails closed instead of silently persisting bytes
    locally when its integration or secret is unavailable.
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

        integration = _single_bobi_storage(integrations)
        if integration.config.get("archive_enabled") is not True:
            raise IntegrationRuntimeError("bobi_storage_archive_not_enabled")

        vault = EncryptedSecretVault(
            root / "bobi-next-secrets.db",
            root / "bobi-next-secrets.key",
        )
        try:
            token = _resolve_storage_token(integration, vault)
        finally:
            vault.close()

        storage = BobiStorageClient(integration.endpoint, token)
        return BobiCloudArchiveStorage(
            storage,
            installation_id=setup.installation_id(),
        )
    finally:
        setup.close()
        integrations.close()


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
        integration = _single_bobi_storage(integrations)
        token = _resolve_storage_token(integration, vault)

        subject = cloud_subject(setup.installation_id(), user_key)
        storage = BobiStorageClient(integration.endpoint, token)
        return VoucherWallet(storage, profile_external_id=subject)
    finally:
        vault.close()
        setup.close()
        integrations.close()
