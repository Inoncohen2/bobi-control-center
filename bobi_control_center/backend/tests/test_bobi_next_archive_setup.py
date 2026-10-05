from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.bobi_next.archive_setup_api import archive_setup_status, create_archive_setup_router
from app.bobi_next.integration_api import create_integration_setup_router
from app.bobi_next.integration_runtime import (
    IntegrationRuntimeError,
    build_archive_storage,
    build_cloud_archive_storage,
)
from app.bobi_next.integration_store import IntegrationStore
from app.bobi_next.request_ledger import RequestLedger
from app.bobi_next.setup_api import create_setup_router
from app.bobi_next.setup_store import SetupStore
from app.bobi_next.supabase_storage import BobiStorageClient, BobiStorageError

ROOT = "/api/next/setup/archive"
TOKEN = "installation-token-" + "a" * 40
ENDPOINT = "https://archive-dev.example/functions/v1/bobi-archive-next"


@pytest.fixture
def setup_client(tmp_path):
    path = tmp_path / "bobi-next-setup.db"
    app = FastAPI()
    app.include_router(create_setup_router(path))
    app.include_router(create_integration_setup_router(path))
    app.include_router(create_archive_setup_router(path))
    with TestClient(app) as client:
        yield path, client


def configure(client, *, token=TOKEN, endpoint=ENDPOINT):
    response = client.post(
        "/api/next/setup/integrations",
        json={
            "integration_key": "archive",
            "integration_type": "bobi_archive",
            "display_name": "Documents",
            "endpoint": endpoint,
            "secret_value": token,
            "config": {"archive_enabled": True},
        },
    )
    assert response.status_code == 200
    assert token not in response.text and "vault:///" not in response.text


def proof_response(path):
    setup = SetupStore(path)
    try:
        return {
            "ok": True,
            "archive_enabled": True,
            "archive_protocol": "bobi-archive-v1",
            "installation_id": setup.installation_id(),
        }
    finally:
        setup.close()


def ping(monkeypatch, response, *, error=None, during=None):
    calls = []

    async def call(self, operation, **kwargs):
        calls.append((self.endpoint, self.token, operation, kwargs))
        assert operation == "ping" and kwargs == {}
        if during:
            during()
        if error:
            raise BobiStorageError(error)
        return response

    monkeypatch.setattr(BobiStorageClient, "_call", call)
    return calls


def test_default_local_needs_no_cloud_credentials_or_network(setup_client, monkeypatch):
    path, client = setup_client
    calls = ping(monkeypatch, {})
    snapshot = client.get(ROOT).json()
    assert snapshot["mode"] == "local" and snapshot["ready"]
    assert not snapshot["cloud"]["configured"]
    assert client.post(f"{ROOT}/check").status_code == 200
    assert client.put(ROOT, json={"mode": "cloud"}).status_code == 409
    assert client.put(ROOT, json={"mode": "local"}).status_code == 200
    assert calls == []
    assert not (path.parent / "bobi-next-archive-files").exists()


def test_read_only_handshake_binds_identity_and_enables_explicit_cloud_choice(
    setup_client,
    monkeypatch,
):
    path, client = setup_client
    configure(client)
    calls = ping(monkeypatch, proof_response(path))
    assert client.put(ROOT, json={"mode": "cloud"}).status_code == 409
    response = client.post(f"{ROOT}/check")
    assert response.status_code == 200
    assert response.json()["cloud"]["ready"] and response.json()["cloud"]["check_fresh"]
    assert response.json()["mode"] == "local"
    assert TOKEN not in response.text and "secret_ref" not in response.text
    assert "fingerprint" not in response.text and "vault:///" not in response.text
    assert calls == [(ENDPOINT, TOKEN, "ping", {})]
    selected = client.put(ROOT, json={"mode": "cloud"})
    assert selected.status_code == 200 and selected.json()["mode"] == "cloud"
    assert selected.json()["ready"]
    assert len(calls) == 1
    assert not (path.parent / "bobi-next-archive-files").exists()


@pytest.mark.parametrize(
    "changed,reason",
    [
        ({"archive_protocol": None}, "archive_generic_protocol_required"),
        ({"archive_protocol": "voucher-media-v1"}, "archive_generic_protocol_required"),
        ({"archive_enabled": False}, "archive_generic_protocol_required"),
        ({"installation_id": "another-installation"}, "archive_installation_mismatch"),
    ],
)
def test_voucher_and_foreign_installation_cannot_select_cloud(
    setup_client,
    monkeypatch,
    changed,
    reason,
):
    path, client = setup_client
    configure(client)
    ping(monkeypatch, {**proof_response(path), **changed})
    checked = client.post(f"{ROOT}/check").json()
    assert checked["cloud"]["reason"] == reason and not checked["cloud"]["ready"]
    assert client.put(ROOT, json={"mode": "cloud"}).status_code == 409
    assert client.get(ROOT).json()["mode"] == "local"


@pytest.mark.parametrize(
    "error,reason",
    [
        ("storage_timeout", "storage_timeout"),
        ("storage_unauthorized", "storage_unauthorized"),
        (TOKEN, "archive_connection_failed"),
    ],
)
def test_cloud_errors_never_echo_provider_secrets(setup_client, monkeypatch, error, reason):
    path, client = setup_client
    configure(client)
    ping(monkeypatch, proof_response(path), error=error)
    response = client.post(f"{ROOT}/check")
    assert response.status_code == 200
    assert response.json()["cloud"]["reason"] == reason
    assert TOKEN not in response.text
    assert client.put(ROOT, json={"mode": "cloud"}).status_code == 409


@pytest.mark.parametrize("mutation", ["credential", "endpoint", "disable"])
def test_configuration_changes_invalidate_verified_cloud_choice(
    setup_client,
    monkeypatch,
    mutation,
):
    path, client = setup_client
    configure(client)
    ping(monkeypatch, proof_response(path))
    assert client.post(f"{ROOT}/check").json()["cloud"]["ready"]
    assert client.put(ROOT, json={"mode": "cloud"}).status_code == 200
    if mutation == "credential":
        configure(client, token="b" * 40)
    elif mutation == "endpoint":
        configure(client, token="b" * 40, endpoint="https://other-dev.example/archive")
    else:
        assert client.post("/api/next/setup/integrations/archive/enabled/false").status_code == 200
    snapshot = client.get(ROOT).json()
    assert not snapshot["cloud"]["ready"] and not snapshot["ready"]
    assert client.put(ROOT, json={"mode": "cloud"}).status_code == 409
    assert client.put(ROOT, json={"mode": "local"}).json()["ready"]


def test_provider_change_during_ping_cannot_persist_proof_for_previous_token(
    setup_client,
    monkeypatch,
):
    path, client = setup_client
    configure(client)

    def change():
        store = IntegrationStore(path)
        try:
            store.set_enabled("archive", False)
        finally:
            store.close()

    ping(monkeypatch, proof_response(path), during=change)
    response = client.post(f"{ROOT}/check")
    assert response.status_code == 409
    assert response.json()["detail"] == "archive_configuration_changed"
    assert not client.get(ROOT).json()["cloud"]["ready"]


def test_expired_check_requires_recheck_for_selection_but_keeps_selected_mode_ready(
    setup_client,
    monkeypatch,
):
    path, client = setup_client
    configure(client)
    monkeypatch.setattr("app.bobi_next.archive_setup_api.time.time", lambda: 1000)
    ping(monkeypatch, proof_response(path))
    client.post(f"{ROOT}/check")
    assert client.put(ROOT, json={"mode": "cloud"}).status_code == 200
    monkeypatch.setattr("app.bobi_next.archive_setup_api.time.time", lambda: 1301)
    snapshot = client.get(ROOT).json()
    assert snapshot["ready"] and snapshot["cloud"]["ready"]
    assert not snapshot["cloud"]["check_fresh"]
    assert client.put(ROOT, json={"mode": "local"}).status_code == 200
    assert client.put(ROOT, json={"mode": "cloud"}).status_code == 409
    assert client.post(f"{ROOT}/check").json()["cloud"]["check_fresh"]
    assert client.put(ROOT, json={"mode": "cloud"}).status_code == 200


def test_runtime_blocks_new_uploads_after_credential_change_until_matching_recheck(
    setup_client,
    monkeypatch,
):
    path, client = setup_client
    configure(client)
    ping(monkeypatch, proof_response(path))
    client.post(f"{ROOT}/check")
    client.put(ROOT, json={"mode": "cloud"})
    assert build_archive_storage(path.parent).storage.token == TOKEN
    configure(client, token="b" * 40)
    with pytest.raises(IntegrationRuntimeError, match="archive_connection_check_required"):
        build_archive_storage(path.parent)
    # Existing cloud reads do not require a new upload authorization. They
    # remain subject to provider authentication and the archive read policy.
    assert build_cloud_archive_storage(path.parent).storage.token == "b" * 40
    client.post(f"{ROOT}/check")
    assert build_archive_storage(path.parent).storage.token == "b" * 40


def test_active_save_blocks_mode_change_even_after_lease_expiry(setup_client):
    path, client = setup_client
    requests = RequestLedger(path.with_name("bobi-next-requests.db"))
    try:
        requests.claim(
            request_id="archive-save:waha:current",
            user_key="owner",
            input_text="save",
            owner_token="worker",
            now_ts=100,
            lease_seconds=5,
        )
        response = client.put(ROOT, json={"mode": "local"})
        assert response.status_code == 409
        assert response.json()["detail"] == "archive_save_in_progress"
        requests.complete(
            "archive-save:waha:current",
            owner_token="worker",
            terminal_kind="archive_saved",
            now_ts=200,
        )
        assert client.put(ROOT, json={"mode": "local"}).status_code == 200
    finally:
        requests.close()


def test_missing_archive_proof_blocks_setup_completion_and_local_mode_removes_only_that_gap(
    setup_client,
):
    path, client = setup_client
    setup = SetupStore(path)
    setup.update_settings({"archive_storage_mode": "cloud"})
    setup.close()
    response = client.post("/api/next/setup/complete")
    assert response.status_code == 409
    assert "archive_connection_check" in response.json()["detail"]
    assert (
        "archive_connection_check"
        in client.get("/api/next/setup/status").json()["setup"]["missing_steps"]
    )
    client.put(ROOT, json={"mode": "local"})
    snapshot = client.get("/api/next/setup/status").json()
    assert "archive_connection_check" not in snapshot["setup"]["missing_steps"]
    assert not snapshot["setup"]["ready"]


@pytest.mark.parametrize("timestamp", ["invalid", -1, True, 2000])
def test_malformed_or_future_proof_is_not_trusted(setup_client, monkeypatch, timestamp):
    path, client = setup_client
    configure(client)
    monkeypatch.setattr("app.bobi_next.archive_setup_api.time.time", lambda: 1000)
    ping(monkeypatch, proof_response(path))
    client.post(f"{ROOT}/check")
    setup = SetupStore(path)
    settings = setup.settings()
    settings["archive_connection_proof"]["checked_ts"] = timestamp
    settings["archive_connection_proof"]["reason"] = [TOKEN]
    setup.update_settings(settings)
    setup.close()
    snapshot = archive_setup_status(path, now_ts=1000)
    assert not snapshot["cloud"]["ready"]
    assert not snapshot["cloud"]["check_fresh"]
    assert TOKEN not in str(snapshot)
