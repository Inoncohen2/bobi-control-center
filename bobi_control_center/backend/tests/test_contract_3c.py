"""Regression coverage for the Home Assistant management contract 3c."""

from __future__ import annotations

import json

import httpx
import pytest

from app.models.manage import CommitRequest, PreviewRequest
from app.services.manage import ManagementService
from app.services.resources import SPECS
from app.services.roles import Actor, Role
from tests.conftest import json_response

#: These tests exercise the write flow, not the permission model, so the service
#: is built with an owner as its default actor. The application's own default is
#: a viewer — the weakest role — so a route that ever forgot to say who is
#: asking would be able to read and nothing else.
OWNER = Actor(role=Role.OWNER, source="ingress")

ALL_RESOURCES = [
    "tasks",
    "features",
    "settings",
    "users",
    "shabbat",
    "rules",
    "calendar",
    "devices",
    "system",
]

CONTRACT_3C = {
    "api_version": "1",
    "contract_version": "3c",
    "bridge_available": True,
    "writes_enabled": False,
    "requires_preview": True,
    "requires_confirmation": True,
    "requires_read_after_write": True,
    "resources": ALL_RESOURCES,
    "tasks": {
        "supported": True,
        "operations": ["add", "edit", "complete", "reopen", "delete"],
        "users": [{"id": "user_1", "name": "User 1"}],
    },
    "features": {
        "supported": True,
        "items": [
            {
                "id": "morning_auto",
                "label": "Morning",
                "risk": "low",
                "enabled": True,
            }
        ],
    },
}

SETTINGS = {
    "available": True,
    "items": [
        {
            "id": "morning_enabled",
            "label": "Morning enabled",
            "kind": "toggle",
            "value": True,
            "controllable": True,
            "operations": ["set"],
        }
    ],
}

USERS = {
    "available": True,
    "items": [
        {
            "id": "user_1",
            "label": "User 1",
            "kind": "toggle",
            "value": True,
            "controllable": True,
            "operations": ["rename"],
            "role": "admin",
            "enabled": True,
        },
        {
            "id": "user_2",
            "label": "User 2",
            "kind": "toggle",
            "value": True,
            "controllable": True,
            "operations": ["rename"],
            "role": "member",
            "enabled": True,
        },
    ],
}

SHABBAT = {
    "available": True,
    "items": [
        {
            "id": "night_off_time",
            "label": "Night off",
            "kind": "time",
            "value": "22:00",
            "controllable": True,
            "operations": ["set_timing"],
        }
    ],
}


@pytest.fixture
def bridge_client(make_real_adapter, recorded_requests):
    """Build the real adapter against an explicit service-response table."""

    def factory(responses: dict[str, dict]):
        def handler(request: httpx.Request) -> httpx.Response:
            recorded_requests.append(request)
            service = request.url.path.rsplit("/", 1)[-1]
            response = responses.get(service)
            if response is None:
                return json_response({"error": "missing"}, 404)
            return json_response({"service_response": response})

        adapter = make_real_adapter(handler)
        return adapter, adapter.management_bridge()

    return factory


def called_services(recorded_requests) -> list[str]:
    return [request.url.path.rsplit("/", 1)[-1] for request in recorded_requests]


def sent_body(recorded_requests, service: str) -> dict:
    for request in recorded_requests:
        if request.url.path.endswith(f"/{service}"):
            return json.loads(request.content)
    raise AssertionError(f"{service} was not called")


async def test_contract_3c_returns_all_resources(bridge_client) -> None:
    adapter, bridge = bridge_client({"bobi_cc_manage_contract": CONTRACT_3C})

    status = await bridge.status()
    await adapter.aclose()

    assert status.available is True
    assert status.contract_version == "3c"
    assert [resource.id for resource in status.resources] == ALL_RESOURCES
    for resource in status.resources:
        assert resource.available is True


async def test_unknown_contract_resources_are_ignored_fail_closed(bridge_client) -> None:
    payload = {**CONTRACT_3C, "resources": [*ALL_RESOURCES, "raw_services", "light.kitchen"]}
    adapter, bridge = bridge_client({"bobi_cc_manage_contract": payload})

    status = await bridge.status()
    await adapter.aclose()

    assert [resource.id for resource in status.resources] == ALL_RESOURCES


async def test_malformed_resources_array_does_not_fall_back(bridge_client) -> None:
    payload = {**CONTRACT_3C, "resources": "settings"}
    adapter, bridge = bridge_client({"bobi_cc_manage_contract": payload})

    status = await bridge.status()
    await adapter.aclose()

    assert status.available is True
    assert status.resources == []


@pytest.mark.parametrize(
    ("resource", "service", "snapshot", "preview_request"),
    [
        (
            "settings",
            "bobi_cc_settings_snapshot",
            SETTINGS,
            PreviewRequest(
                operation="set",
                resource_id="morning_enabled",
                payload={"value": False},
            ),
        ),
        (
            "users",
            "bobi_cc_users_manage_snapshot",
            USERS,
            PreviewRequest(
                operation="rename",
                resource_id="user_2",
                payload={"name": "User Two"},
            ),
        ),
        (
            "shabbat",
            "bobi_cc_shabbat",
            SHABBAT,
            PreviewRequest(
                operation="set_timing",
                resource_id="night_off_time",
                payload={"value": "23:00"},
            ),
        ),
    ],
)
async def test_3c_generic_previews_are_not_management_unavailable(
    bridge_client, resource, service, snapshot, preview_request
) -> None:
    adapter, bridge = bridge_client(
        {"bobi_cc_manage_contract": CONTRACT_3C, service: snapshot}
    )
    management = ManagementService(bridge, default_actor=OWNER)

    preview = await management.preview(resource, preview_request)
    await adapter.aclose()

    assert preview.valid is True
    assert preview.resource_type == resource
    assert preview.would_execute is False


@pytest.mark.parametrize(
    ("resource", "service"),
    [
        ("rules", "bobi_cc_rules"),
        ("calendar", "bobi_cc_calendar_snapshot"),
        ("devices", "bobi_cc_devices"),
        ("system", "bobi_cc_system_snapshot"),
    ],
)
async def test_3c_snapshots_use_only_the_declared_bridge(
    bridge_client, recorded_requests, resource, service
) -> None:
    payload = {
        "available": True,
        "items": [{"id": f"{resource}_item", "label": resource, "value": True}],
    }
    adapter, bridge = bridge_client({service: payload})

    snapshot = await bridge.resource_snapshot(resource)
    await adapter.aclose()

    assert snapshot.available is True
    assert snapshot.resource == resource
    assert called_services(recorded_requests) == [service]


async def test_users_commit_uses_plural_bridge_and_nonempty_token(
    bridge_client, recorded_requests
) -> None:
    writes_on = {**CONTRACT_3C, "writes_enabled": True}
    adapter, bridge = bridge_client(
        {
            "bobi_cc_manage_contract": writes_on,
            "bobi_cc_users_manage_snapshot": USERS,
            "bobi_cc_users_commit": {
                "executed": True,
                "verified": True,
                "reason": "ok",
                "resource_id": "user_2",
                "writes_enabled": True,
            },
        }
    )
    management = ManagementService(bridge, default_actor=OWNER)
    preview = await management.preview(
        "users",
        PreviewRequest(
            operation="rename",
            resource_id="user_2",
            payload={"name": "User Two"},
        ),
    )
    result = await management.commit(
        "users", CommitRequest(preview_id=preview.preview_id, confirmed=True)
    )
    await adapter.aclose()

    assert result.result.status == "committed"
    body = sent_body(recorded_requests, "bobi_cc_users_commit")
    assert body["preview_token"]
    assert body["confirmed"] is True
    assert "bobi_cc_user_commit" not in called_services(recorded_requests)


async def test_missing_commit_bridge_fails_closed_without_raw_fallback(
    bridge_client, recorded_requests
) -> None:
    writes_on = {**CONTRACT_3C, "writes_enabled": True}
    adapter, bridge = bridge_client(
        {
            "bobi_cc_manage_contract": writes_on,
            "bobi_cc_settings_snapshot": SETTINGS,
        }
    )
    management = ManagementService(bridge, default_actor=OWNER)
    preview = await management.preview(
        "settings",
        PreviewRequest(
            operation="set",
            resource_id="morning_enabled",
            payload={"value": False},
        ),
    )

    result = await management.commit(
        "settings", CommitRequest(preview_id=preview.preview_id, confirmed=True)
    )
    await adapter.aclose()

    assert result.result.status == "failed"
    assert result.result.reason == "bridge_service_missing"
    services = called_services(recorded_requests)
    assert services[-1] == "bobi_cc_settings_commit"
    assert all(service.startswith("bobi_cc_") for service in services)
    assert not any(
        service.startswith(prefix)
        for service in services
        for prefix in ("light", "climate", "calendar.", "automation", "todo", "input_boolean")
    )


def test_bridge_name_source_of_truth_matches_contract() -> None:
    assert SPECS["settings"].commit_service == "bobi_cc_settings_commit"
    assert SPECS["users"].commit_service == "bobi_cc_users_commit"
    assert SPECS["shabbat"].commit_service == "bobi_cc_shabbat_commit"
    assert SPECS["rules"].commit_service == "bobi_cc_rule_commit"
    assert SPECS["calendar"].commit_service == "bobi_cc_calendar_commit"
    assert SPECS["devices"].commit_service == "bobi_cc_device_commit"
    assert SPECS["system"].commit_service == "bobi_cc_system_commit"
