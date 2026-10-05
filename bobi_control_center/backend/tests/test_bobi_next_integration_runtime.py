from __future__ import annotations

import pytest

from app.bobi_next.cloud_archive_storage import BobiCloudArchiveStorage
from app.bobi_next.cloud_identity import cloud_subject
from app.bobi_next.integration_runtime import (
    IntegrationRuntimeError,
    build_archive_storage,
    build_voucher_wallet,
)
from app.bobi_next.integration_store import IntegrationStore
from app.bobi_next.local_archive_storage import LocalArchiveStorage
from app.bobi_next.secret_vault import EncryptedSecretVault
from app.bobi_next.setup_store import SetupStore


def test_cloud_subject_is_stable_and_does_not_embed_identity() -> None:
    value = cloud_subject("install-1", "usr_private")
    assert value == cloud_subject("install-1", "usr_private")
    assert value != cloud_subject("install-1", "usr_other")
    assert value.startswith("bobi2_")
    assert "usr_private" not in value
    assert "install-1" not in value


def _configure_storage(
    data_dir,
    *,
    key: str = "supabase",
    enabled: bool = True,
    config: dict | None = None,
    integration_type: str = "bobi_storage",
    token: str = "s" * 40,
) -> None:
    setup_path = data_dir / "bobi-next-setup.db"
    # Ensure installation identity exists before runtime construction.
    setup = SetupStore(setup_path)
    setup.close()

    vault = EncryptedSecretVault(
        data_dir / "bobi-next-secrets.db",
        data_dir / "bobi-next-secrets.key",
    )
    ref = vault.put(f"integration:{key}", token)
    vault.close()

    integrations = IntegrationStore(setup_path)
    integrations.upsert(
        integration_key=key,
        integration_type=integration_type,
        display_name="Bobi cloud",
        enabled=enabled,
        endpoint=(
            "https://example.supabase.co/functions/v1/bobi-archive-next"
            if integration_type == "bobi_archive"
            else "https://example.supabase.co/functions/v1/bobi-storage"
        ),
        secret_ref=ref,
        config=config,
    )
    integrations.close()


def _set_archive_mode(data_dir, mode: str) -> None:
    setup = SetupStore(data_dir / "bobi-next-setup.db")
    setup.update_settings({"archive_storage_mode": mode})
    setup.close()


def test_archive_storage_defaults_to_local_without_cloud_configuration(tmp_path) -> None:
    storage = build_archive_storage(tmp_path)
    assert isinstance(storage, LocalArchiveStorage)


def test_archive_cloud_selection_fails_closed_when_storage_missing(tmp_path) -> None:
    _set_archive_mode(tmp_path, "cloud")
    with pytest.raises(IntegrationRuntimeError, match="bobi_storage_not_configured"):
        build_archive_storage(tmp_path)


def test_archive_cloud_selection_requires_explicit_archive_capability(tmp_path) -> None:
    _configure_storage(tmp_path)
    _set_archive_mode(tmp_path, "cloud")
    with pytest.raises(IntegrationRuntimeError, match="bobi_storage_archive_not_enabled"):
        build_archive_storage(tmp_path)


def test_archive_cloud_selection_builds_adapter_without_network_io(tmp_path) -> None:
    _configure_storage(tmp_path, config={"archive_enabled": True})
    _set_archive_mode(tmp_path, "cloud")

    storage = build_archive_storage(tmp_path)

    assert isinstance(storage, BobiCloudArchiveStorage)
    assert storage.storage.endpoint == "https://example.supabase.co/functions/v1/bobi-storage"
    assert storage.storage.token == "s" * 40


def test_archive_storage_rejects_unknown_mode(tmp_path) -> None:
    _set_archive_mode(tmp_path, "elsewhere")
    with pytest.raises(IntegrationRuntimeError, match="archive_storage_mode_invalid"):
        build_archive_storage(tmp_path)


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


def test_dedicated_archive_keeps_voucher_endpoint_and_secret_separate(tmp_path) -> None:
    _configure_storage(tmp_path, key="vouchers", config={"archive_enabled": True})
    _configure_storage(
        tmp_path, key="archive", integration_type="bobi_archive",
        config={"archive_enabled": True}, token="a" * 40,
    )
    _set_archive_mode(tmp_path, "cloud")

    archive = build_archive_storage(tmp_path)
    wallet = build_voucher_wallet(tmp_path, user_key="usr_1")

    assert isinstance(archive, BobiCloudArchiveStorage)
    assert archive.storage.endpoint.endswith("/bobi-archive-next")
    assert archive.storage.token == "a" * 40
    assert wallet.storage.endpoint.endswith("/bobi-storage")
    assert wallet.storage.token == "s" * 40


def test_dedicated_archive_does_not_enable_cloud_implicitly(tmp_path) -> None:
    _configure_storage(
        tmp_path, integration_type="bobi_archive", config={"archive_enabled": True},
    )
    assert isinstance(build_archive_storage(tmp_path), LocalArchiveStorage)


@pytest.mark.parametrize(
    ("enabled", "config", "error"),
    [
        (False, {"archive_enabled": True}, "bobi_archive_not_configured"),
        (True, {}, "bobi_archive_archive_not_enabled"),
    ],
)
def test_dedicated_archive_failure_does_not_fall_back_to_vouchers(
    tmp_path, enabled, config, error,
) -> None:
    _configure_storage(tmp_path, key="vouchers", config={"archive_enabled": True})
    _configure_storage(
        tmp_path, key="archive", integration_type="bobi_archive", enabled=enabled, config=config,
    )
    _set_archive_mode(tmp_path, "cloud")
    with pytest.raises(IntegrationRuntimeError, match=error):
        build_archive_storage(tmp_path)


def test_ambiguous_dedicated_archive_does_not_fall_back_to_vouchers(tmp_path) -> None:
    _configure_storage(tmp_path, key="vouchers", config={"archive_enabled": True})
    for key in ("archive-a", "archive-b"):
        _configure_storage(
            tmp_path, key=key, integration_type="bobi_archive", config={"archive_enabled": True},
        )
    _set_archive_mode(tmp_path, "cloud")
    with pytest.raises(IntegrationRuntimeError, match="bobi_archive_ambiguous"):
        build_archive_storage(tmp_path)


def test_dedicated_archive_never_becomes_a_voucher_wallet(tmp_path) -> None:
    _configure_storage(
        tmp_path, integration_type="bobi_archive", config={"archive_enabled": True},
    )
    with pytest.raises(IntegrationRuntimeError, match="bobi_storage_not_configured"):
        build_voucher_wallet(tmp_path, user_key="usr_1")


def test_missing_dedicated_archive_secret_does_not_fall_back_to_vouchers(tmp_path) -> None:
    _configure_storage(tmp_path, key="vouchers", config={"archive_enabled": True})
    store = IntegrationStore(tmp_path / "bobi-next-setup.db")
    store.upsert(
        integration_key="archive", integration_type="bobi_archive", display_name="Archive",
        endpoint="https://example.supabase.co/functions/v1/bobi-archive-next",
        config={"archive_enabled": True},
    )
    store.close()
    _set_archive_mode(tmp_path, "cloud")
    with pytest.raises(IntegrationRuntimeError, match="bobi_archive_secret_missing"):
        build_archive_storage(tmp_path)
