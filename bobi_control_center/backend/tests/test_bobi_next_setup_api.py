from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.bobi_next.setup_api import create_setup_router
from app.bobi_next.setup_store import SetupStore


def _client(tmp_path):
    database_path = tmp_path / "setup.db"
    app = FastAPI()
    app.include_router(create_setup_router(database_path))
    return database_path, TestClient(app)


def test_status_starts_incomplete_without_leaking_sensitive_config(tmp_path):
    _, client = _client(tmp_path)
    response = client.get("/api/next/setup/status")
    assert response.status_code == 200
    body = response.json()
    assert body["setup"]["completed"] is False
    assert body["setup"]["ready"] is False
    assert body["providers"] == []


def test_full_setup_flow_can_finish_without_home_assistant_helpers(tmp_path):
    _, client = _client(tmp_path)
    provider = client.post(
        "/api/next/setup/providers",
        json={
            "provider_key": "waha:primary",
            "provider_type": "waha",
            "display_name": "WhatsApp",
            "endpoint": "http://private-provider.local",
            "session": "primary",
            "engine": "GOWS",
            "secret_ref": "secret://provider/api",
        },
    )
    assert provider.status_code == 200
    provider_body = provider.json()
    assert provider_body["provider_key"] == "waha:primary"
    assert provider_body["has_secret_ref"] is True
    assert "endpoint" not in provider_body
    assert "secret_ref" not in provider_body

    user = client.post(
        "/api/next/setup/users",
        json={
            "display_name": "Owner",
            "role": "owner",
            "user_key": "usr_owner",
        },
    )
    assert user.status_code == 200
    assert user.json()["policy"]["can_approve"] is True

    external_id = "private-external-sender"
    identity = client.post(
        "/api/next/setup/identities",
        json={
            "provider_key": "waha:primary",
            "external_id": external_id,
            "user_key": "usr_owner",
            "identity_label": "my phone",
        },
    )
    assert identity.status_code == 200
    assert external_id not in identity.text

    complete = client.post("/api/next/setup/complete")
    assert complete.status_code == 200
    snapshot = complete.json()
    assert snapshot["setup"]["ready"] is True
    assert snapshot["setup"]["completed"] is True
    assert external_id not in complete.text
    assert "secret://provider/api" not in complete.text
    assert "private-provider.local" not in complete.text


def test_complete_is_rejected_until_required_steps_exist(tmp_path):
    _, client = _client(tmp_path)
    response = client.post("/api/next/setup/complete")
    assert response.status_code == 409
    assert "setup_incomplete" in response.json()["detail"]


def test_policy_endpoint_persists_explicit_permissions(tmp_path):
    database_path, client = _client(tmp_path)
    created = client.post(
        "/api/next/setup/users",
        json={
            "display_name": "Member",
            "role": "member",
            "user_key": "usr_member",
        },
    )
    assert created.status_code == 200
    assert created.json()["policy"]["can_approve"] is False

    updated = client.put(
        "/api/next/setup/users/usr_member/policy",
        json={
            "allowed_capabilities": ["power", "temperature"],
            "denied_capabilities": ["lock"],
            "allowed_domains": ["switch", "climate"],
            "denied_actions": ["switch.turn_on"],
            "max_without_approval": 10,
            "can_approve": False,
        },
    )
    assert updated.status_code == 200
    policy = updated.json()["policy"]
    assert policy["allowed_capabilities"] == ["power", "temperature"]
    assert policy["denied_capabilities"] == ["lock"]
    assert policy["allowed_domains"] == ["climate", "switch"]
    assert policy["max_without_approval"] == 10

    store = SetupStore(database_path)
    try:
        reloaded = store.get_user("usr_member")
        assert reloaded is not None
        assert reloaded.policy.allowed_domains == frozenset({"switch", "climate"})
    finally:
        store.close()


def test_identity_api_fails_closed_for_unknown_user(tmp_path):
    _, client = _client(tmp_path)
    client.post(
        "/api/next/setup/providers",
        json={
            "provider_key": "waha:primary",
            "provider_type": "waha",
            "display_name": "WhatsApp",
        },
    )
    response = client.post(
        "/api/next/setup/identities",
        json={
            "provider_key": "waha:primary",
            "external_id": "sender",
            "user_key": "missing-user",
        },
    )
    assert response.status_code == 404
    assert response.json()["detail"] == "user_not_found"


def test_duplicate_external_identity_cannot_be_reassigned_via_api(tmp_path):
    _, client = _client(tmp_path)
    client.post(
        "/api/next/setup/providers",
        json={
            "provider_key": "waha:primary",
            "provider_type": "waha",
            "display_name": "WhatsApp",
        },
    )
    for key in ("usr_one", "usr_two"):
        client.post(
            "/api/next/setup/users",
            json={"display_name": key, "role": "member", "user_key": key},
        )
    first = client.post(
        "/api/next/setup/identities",
        json={
            "provider_key": "waha:primary",
            "external_id": "same-sender",
            "user_key": "usr_one",
        },
    )
    second = client.post(
        "/api/next/setup/identities",
        json={
            "provider_key": "waha:primary",
            "external_id": "same-sender",
            "user_key": "usr_two",
        },
    )
    assert first.status_code == 200
    assert second.status_code == 409
    assert second.json()["detail"] == "identity_already_linked"
