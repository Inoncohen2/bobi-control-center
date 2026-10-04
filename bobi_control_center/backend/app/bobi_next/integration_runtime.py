"""Runtime factory for optional Bobi Next cloud integrations."""

from __future__ import annotations

from pathlib import Path

from .cloud_identity import cloud_subject
from .integration_store import IntegrationStore
from .secret_vault import EncryptedSecretVault, SecretVaultError
from .setup_store import SetupStore
from .supabase_storage import BobiStorageClient
from .voucher_wallet import VoucherWallet


class IntegrationRuntimeError(RuntimeError):
    pass


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
        matches = integrations.list(integration_type="bobi_storage", enabled_only=True)
        if not matches:
            raise IntegrationRuntimeError("bobi_storage_not_configured")
        if len(matches) != 1:
            raise IntegrationRuntimeError("bobi_storage_ambiguous")
        integration = matches[0]
        if not integration.secret_ref:
            raise IntegrationRuntimeError("bobi_storage_secret_missing")
        try:
            token = vault.resolve(integration.secret_ref)
        except SecretVaultError as exc:
            raise IntegrationRuntimeError("bobi_storage_secret_unavailable") from exc

        subject = cloud_subject(setup.installation_id(), user_key)
        storage = BobiStorageClient(integration.endpoint, token)
        return VoucherWallet(storage, profile_external_id=subject)
    finally:
        vault.close()
        setup.close()
        integrations.close()
