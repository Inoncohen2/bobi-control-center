"""The public hostname is protected without changing HA Ingress."""

from __future__ import annotations

from fastapi.testclient import TestClient

from app.auth import COOKIE_NAME, hash_external_password, verify_external_password
from app.config import Settings
from app.main import create_app

HOSTNAME = "bobi.example.com"
PASSWORD = "a-long-test-password"


def external_client(tmp_path) -> TestClient:
    settings = Settings(
        adapter="mock",
        data_dir=tmp_path / "data",
        external_hostname=HOSTNAME,
        external_password_hash=hash_external_password(PASSWORD, salt=b"0123456789abcdef"),
    )
    return TestClient(create_app(settings), base_url=f"https://{HOSTNAME}")


def test_password_hash_is_salted_and_verifiable() -> None:
    first = hash_external_password(PASSWORD, salt=b"0123456789abcdef")
    second = hash_external_password(PASSWORD, salt=b"fedcba9876543210")
    assert first != second
    assert PASSWORD not in first
    assert verify_external_password(PASSWORD, first)
    assert not verify_external_password("wrong", first)
    assert not verify_external_password(PASSWORD, "malformed")


def test_ingress_host_keeps_working_without_second_login(mock_settings: Settings) -> None:
    mock_settings.external_hostname = HOSTNAME
    mock_settings.external_password_hash = hash_external_password(PASSWORD)
    with TestClient(create_app(mock_settings), base_url="https://ha.example.com") as client:
        session = client.get("/api/auth/session")
        assert session.status_code == 200
        assert session.json() == {"authenticated": True, "mode": "home_assistant"}
        assert client.get("/api/bobi/status").status_code == 200


def test_external_api_fails_closed_but_login_screen_can_load(tmp_path) -> None:
    with external_client(tmp_path) as client:
        protected = client.get("/api/bobi/status")
        assert protected.status_code == 401
        assert protected.json()["code"] == "authentication_required"
        assert client.get("/").status_code in {200, 404}  # static bundle is absent in tests


def test_external_login_uses_secure_server_side_cookie(tmp_path) -> None:
    with external_client(tmp_path) as client:
        rejected = client.post(
            "/api/auth/login",
            json={"password": "wrong"},
            headers={"Origin": f"https://{HOSTNAME}"},
        )
        assert rejected.status_code == 401
        assert COOKIE_NAME not in rejected.headers.get("set-cookie", "")

        accepted = client.post(
            "/api/auth/login",
            json={"password": PASSWORD},
            headers={"Origin": f"https://{HOSTNAME}"},
        )
        assert accepted.status_code == 200
        cookie = accepted.headers["set-cookie"]
        assert f"{COOKIE_NAME}=" in cookie
        assert "HttpOnly" in cookie
        assert "Secure" in cookie
        assert "SameSite=strict" in cookie
        assert PASSWORD not in cookie
        assert client.get("/api/bobi/status").status_code == 200


def test_external_writes_require_same_origin(tmp_path) -> None:
    with external_client(tmp_path) as client:
        login = client.post(
            "/api/auth/login",
            json={"password": PASSWORD},
            headers={"Origin": f"https://{HOSTNAME}"},
        )
        assert login.status_code == 200

        blocked = client.post("/api/bobi/manage/settings/preview", json={})
        assert blocked.status_code == 403
        assert blocked.json()["code"] == "origin_rejected"


def test_external_access_is_unavailable_until_a_hash_is_configured(tmp_path) -> None:
    settings = Settings(
        adapter="mock", data_dir=tmp_path / "data", external_hostname=HOSTNAME
    )
    with TestClient(create_app(settings), base_url=f"https://{HOSTNAME}") as client:
        response = client.get("/api/bobi/status")
        assert response.status_code == 503
        assert response.json()["code"] == "external_auth_unconfigured"
