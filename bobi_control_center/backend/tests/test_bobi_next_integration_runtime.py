from __future__ import annotations

import pytest

from app.bobi_next.cloud_identity import cloud_subject
from app.bobi_next.integration_runtime import IntegrationRuntimeError, build_voucher_wallet
from app.bobi_next.integration_store import IntegrationStore
from app.bobi_next.secret_vault import EncryptedSecretVault
from app.bobi_next.setup_store import SetupStore


def test_cloud_subject_is_stable_and_does_not_embed_identity() -> None:
    value = cloud_subject("install-1", "usr_private")
    assert value == cloud_subject("install-1", "usr_private")
    assert value != cloud_subject("install-1", "usr_other")
    assert value.startswith("bobi2_")
    assert "usr_private" not in value
    assert "install-1" not in value


def _configure_storage(data_dir, *, key: str = "supabase", enabled: bool = True) -> None:
    setup_path = data_dir / "bobi-next-setup.db"
    # Ensure installation identity exists before runtime construction.
    setup = SetupStore(setup_path)
    setup.close()

    vault = EncryptedSecretVault(
        data_dir / "bobi-next-secrets.db",
        data_dir / "bobi-next-secrets.key",
    )
    ref = vault.put(f"integration:{key}", "s" * 40)
    vault.close()

    integrations = IntegrationStore(setup_path)
    integrations.upsert(
        integration_key=key,
        integration_type="bobi_storage",
        display_name="Bobi cloud",
        enabled=enabled,
        endpoint="https://example.supabase.co/functions/v1/bobi-storage",
        secret_ref=ref,
    )
    integrations.close()


def test_runtime_factory_fails_closed_when_storage_missing(tmp_path) -> None:
    with pytest.raises(IntegrationRuntimeError, match="bobi_storage_not_configured"):
        build_voucher_wallet(tmp_path, user_key="usr_1")


def test_runtime_factory_ignores_disabled_storage(tmp_path) -> None:
    _configure_storage(tmp_path, enabled=False)
    with pytest.raises(IntegrationRuntimeError, match="bobi_storage_not_configured"):
        build_voucher_wallet(tmp_path, user_key="usr_1")


def test_runtime_factory_rejects_ambiguous_storage(tmp_path) -> None:
    _configure_storage(tmp_path, key="cloud-a")
    _configure_storage(tmp_path, key="cloud-b")
    with pytest.raises(IntegrationRuntimeError, match="bobi_storage_ambiguous"):
        build_voucher_wallet(tmp_path, user_key="usr_1")


def test_runtime_factory_resolves_secret_and_uses_opaque_cloud_subject(tmp_path) -> None:
    _configure_storage(tmp_path)
    setup = SetupStore(tmp_path / "bobi-next-setup.db")
    expected_subject = cloud_subject(setup.installation_id(), "usr_1")
    setup.close()

    wallet = build_voucher_wallet(tmp_path, user_key="usr_1")

    assert wallet.profile_external_id == expected_subject
    assert wallet.profile_external_id.startswith("bobi2_")
    assert "usr_1" not in wallet.profile_external_id
    assert wallet.storage.endpoint == "https://example.supabase.co/functions/v1/bobi-storage"
    assert wallet.storage.token == "s" * 40
