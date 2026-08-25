"""Every API endpoint, against the mock adapter."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient


def test_health(client: TestClient) -> None:
    body = client.get("/health").json()
    assert body["ok"] is True
    assert body["app"] == "bobi-control-center"
    assert body["writes_enabled"] is False


def test_connection(client: TestClient) -> None:
    body = client.get("/api/bobi/connection").json()
    assert body["adapter"] == "mock"
    assert body["connected"] is True
    assert body["writes_enabled"] is False
    assert body["phase"] == 2


# --- status -----------------------------------------------------------------
def test_status(client: TestClient) -> None:
    body = client.get("/api/bobi/status").json()
    assert body["ok"] is True
    assert body["components"], "the dashboard needs health rows"
    assert body["counts"]
    assert body["writes_enabled"] is False

    for component in body["components"]:
        assert component["name"]
        assert component["label"]


# --- devices ----------------------------------------------------------------
def test_devices_returns_the_canonical_catalog(client: TestClient) -> None:
    body = client.get("/api/bobi/devices").json()
    assert body["devices"]
    assert body["count"] == len(body["devices"])

    device = body["devices"][0]
    for field in ("id", "name", "entity_id", "area", "state", "available", "aliases",
                  "capabilities", "semantic_scopes", "handler", "domain", "group", "extra"):
        assert field in device


def test_devices_expose_exactly_one_collection(client: TestClient) -> None:
    """No empty legacy list sitting beside the populated one."""
    body = client.get("/api/bobi/devices").json()
    collections = [key for key, value in body.items() if isinstance(value, list)]
    assert sorted(collections) == ["areas", "devices", "groups"]
    assert "entries" not in body


def test_device_ids_are_unique(client: TestClient) -> None:
    ids = [d["id"] for d in client.get("/api/bobi/devices").json()["devices"]]
    assert len(ids) == len(set(ids))


def test_devices_scope_filters_server_side(client: TestClient) -> None:
    body = client.get("/api/bobi/devices?scope=climate").json()
    assert body["scope"] == "climate"
    assert body["devices"]
    assert all("climate" in d["semantic_scopes"] for d in body["devices"])


def test_devices_can_exclude_unavailable(client: TestClient) -> None:
    everything = client.get("/api/bobi/devices?include_unavailable=true").json()
    available = client.get("/api/bobi/devices?include_unavailable=false").json()

    assert len(available["devices"]) < len(everything["devices"])
    assert all(d["state"] not in {"unavailable", "unknown"} for d in available["devices"])


def test_unknown_scope_is_rejected_with_a_structured_error(client: TestClient) -> None:
    response = client.get("/api/bobi/devices?scope=nonsense")
    assert response.status_code == 422
    body = response.json()
    assert body["code"] == "validation_error"
    assert "allowed" in body["details"]


@pytest.mark.parametrize(
    "scope",
    ["all", "lighting", "climate", "cameras", "battery", "temperature",
     "humidity", "vacuum", "people", "switches", "scent"],
)
def test_every_documented_scope_is_accepted(client: TestClient, scope: str) -> None:
    assert client.get(f"/api/bobi/devices?scope={scope}").status_code == 200


# --- capabilities -----------------------------------------------------------
def test_capabilities_returns_the_registry(client: TestClient) -> None:
    body = client.get("/api/bobi/capabilities").json()
    assert body["capabilities"]

    capability = body["capabilities"][0]
    for field in ("handler", "local", "local_after_parse", "risk", "label", "example"):
        assert field in capability


def test_capability_toggles_are_returned_separately(client: TestClient) -> None:
    body = client.get("/api/bobi/capabilities").json()
    assert body["toggles"]
    for toggle in body["toggles"]:
        assert toggle["label"] or toggle["name"]


def test_unknown_capability_fields_are_preserved(client: TestClient) -> None:
    """The registry grows; extra keys must survive into the Advanced panel."""
    from app.services import normalize

    result = normalize.normalize_capabilities(
        {"registry": {"x": {"label": "חדש", "brand_new_field": "value"}}}
    )
    capability = result.capabilities[0]
    assert capability.label == "חדש"
    assert capability.extra["brand_new_field"] == "value"


def test_capabilities_expose_exactly_one_collection(client: TestClient) -> None:
    body = client.get("/api/bobi/capabilities").json()
    assert "registry" not in body
    assert body["capabilities"]
    assert len(body["capabilities"]) == body["count"]


# --- users ------------------------------------------------------------------
def test_users(client: TestClient) -> None:
    body = client.get("/api/bobi/users").json()
    assert body["users"]
    for user in body["users"]:
        assert user["name"]


def test_users_never_expose_phone_numbers_or_lids(client: TestClient) -> None:
    import re

    raw = client.get("/api/bobi/users").text
    assert not re.search(r"\+\d{9,15}", raw)
    assert not re.search(r"\b0\d{1,2}-?\d{7}\b", raw)
    for forbidden in ("whatsapp_number", "phone", "lid", "@c.us", "@s.whatsapp.net"):
        assert forbidden not in raw.lower()


# --- shabbat ----------------------------------------------------------------
def test_shabbat_is_read_only(client: TestClient) -> None:
    body = client.get("/api/bobi/shabbat").json()
    assert body["writes_enabled"] is False
    assert body["candle_lighting"]
    assert body["havdalah"]
    assert "has_draft" in body


def test_shabbat_resolves_device_tokens_server_side(client: TestClient) -> None:
    """The UI must never receive a raw device token to resolve itself."""
    body = client.get("/api/bobi/shabbat").json()

    assert body["profiles"], "the mock defines profiles"
    for profile in body["profiles"]:
        for device in profile["devices"]:
            # A friendly Hebrew name, not a snake_case token.
            assert "_" not in device, f"{device} looks like an unresolved token"

    for name in body["ac_temperatures"]:
        assert "_" not in name, f"{name} looks like an unresolved token"


def test_shabbat_flattens_profiles_into_one_list(client: TestClient) -> None:
    body = client.get("/api/bobi/shabbat").json()
    assert "upcoming" not in body
    assert "pre_off_profile" not in body
    assert body["candle_lighting"], "times are read out of `upcoming`"
    assert {p["kind"] for p in body["profiles"]} >= {"pre_off", "night_off"}


def test_tasks_expose_exactly_one_collection(client: TestClient) -> None:
    body = client.get("/api/bobi/tasks").json()
    assert "users" not in body
    assert body["tasks"]
    assert len(body["tasks"]) == body["count"]


def test_status_has_no_empty_legacy_fields(client: TestClient) -> None:
    body = client.get("/api/bobi/status").json()
    assert body["components"], "real components must be read, not left empty"
    assert body["counts"], "real figures must be read, not left empty"


def test_probe_is_flattened_from_the_nested_result(client: TestClient) -> None:
    body = client.post(
        "/api/bobi/probe", json={"text": "כבה מזגן הורים ב-1:30 בלילה"}
    ).json()
    assert "result" not in body
    assert body["handled"] is True
    assert body["skill"]


# --- rules ------------------------------------------------------------------
def test_rules(client: TestClient) -> None:
    body = client.get("/api/bobi/rules").json()
    assert body["rules"]
    for rule in body["rules"]:
        assert rule["name"] or rule["label"]


# --- tasks ------------------------------------------------------------------
def test_tasks(client: TestClient) -> None:
    body = client.get("/api/bobi/tasks").json()
    assert body["tasks"]
    assert any(task["completed"] is False for task in body["tasks"])
    assert any(task["completed"] is True for task in body["tasks"])


def test_tasks_carry_no_internal_description(client: TestClient) -> None:
    raw = client.get("/api/bobi/tasks").text
    for forbidden in ("description", "internal", "metadata", "raw_"):
        assert forbidden not in raw.lower()


# --- diagnostics ------------------------------------------------------------
def test_diagnostics(client: TestClient) -> None:
    body = client.get("/api/bobi/diagnostics").json()
    assert "ok" in body
    assert body["issue_count"] == len(body["issues"])
    assert body["checks"]

    for issue in body["issues"]:
        assert issue["title"] or issue["message"]
        assert "Traceback" not in (issue["title"] or "")


# --- probe ------------------------------------------------------------------
def test_probe_returns_the_bridge_fields(client: TestClient) -> None:
    body = client.post(
        "/api/bobi/probe", json={"text": "כבה מזגן הורים ב-1:30 בלילה"}
    ).json()

    for field in ("handled", "status", "terminal", "skill", "understanding",
                  "schedule_valid", "schedule_reason", "schedule_kind"):
        assert field in body

    assert body["handled"] is True
    assert body["skill"] == "local_schedule"
    assert body["schedule_valid"] is True
    assert body["understanding"]["target"] == "מזגן הורים"


@pytest.mark.parametrize(
    "text",
    [
        "כבה מזגן הורים ב-1:30 בלילה",
        "תדליק את אור המטבח",
        "מה הטמפרטורה בסלון",
        "תוסיף משימה לקנות חלב",
        "קשקוש גמור שאין לו משמעות",
        "תמחק הכל ותכבה את כל הבית",
    ],
)
def test_probe_never_executes(client: TestClient, text: str) -> None:
    body = client.post("/api/bobi/probe", json={"text": text}).json()
    assert body["would_execute"] is False
    assert body["probe_only"] is True


def test_probe_rejects_empty_text(client: TestClient) -> None:
    assert client.post("/api/bobi/probe", json={"text": ""}).status_code == 422


def test_probe_reports_a_request_it_could_not_understand(client: TestClient) -> None:
    body = client.post("/api/bobi/probe", json={"text": "בלה בלה בלה"}).json()
    assert body["handled"] is False
    assert body["status"] == "not_understood"
    assert body["would_execute"] is False


def test_probe_does_not_change_any_state(client: TestClient) -> None:
    before = client.get("/api/bobi/devices").json()
    client.post("/api/bobi/probe", json={"text": "תכבה את המזגן בסלון"})
    assert client.get("/api/bobi/devices").json() == before


# --- write surface ----------------------------------------------------------
@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("post", "/api/bobi/devices"),
        ("post", "/api/bobi/shabbat"),
        ("post", "/api/bobi/rules"),
        ("post", "/api/bobi/capabilities"),
        ("put", "/api/bobi/status"),
        ("patch", "/api/bobi/tasks"),
        ("delete", "/api/bobi/rules"),
        ("post", "/api/bobi/capabilities/vision/toggle"),
        ("post", "/api/bobi/shabbat/confirm"),
    ],
)
def test_no_write_endpoints_exist(client: TestClient, method: str, path: str) -> None:
    """Phase 2 exposes exactly one POST — the probe."""
    # `delete` takes no body in httpx, so the request is built explicitly.
    response = client.request(method.upper(), path, json={})
    assert response.status_code in (404, 405)


def test_probe_is_the_only_post_route(client: TestClient) -> None:
    from app.api.routes import router

    posts = [
        (route.path, sorted(route.methods))
        for route in router.routes
        if getattr(route, "methods", None) and "GET" not in route.methods
    ]
    assert posts == [("/api/bobi/probe", ["POST"])]
