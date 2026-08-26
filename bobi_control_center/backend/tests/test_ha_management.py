"""The real Home Assistant write bridge.

These tests hold the bridge to the contract Home Assistant published: the five
service names, the exact parameter names, and the fact that the app reads the
master switch rather than setting it.

The payloads below are the shapes from that contract, not invented ones.
"""

from __future__ import annotations

import json
from datetime import timedelta

import httpx
import pytest

from app.adapters.real_management import (
    CONTRACT,
    FEATURE_COMMIT,
    TASK_ADD_COMMIT,
    TASK_SNAPSHOT,
    TASK_UPDATE_COMMIT,
)
from app.models.manage import CommitRequest, ObservedState, PreviewRequest
from app.services import manage
from app.services.manage import ManagementService, PreviewExpiredError
from tests.conftest import json_response

#: Stands in for the token the preview store mints. Its value is opaque to the
#: bridge; what matters is that this exact string reaches Home Assistant.
PREVIEW_TOKEN = "pt_ThIsIsTheOpaquePreviewToken_0123456789"

CONTRACT_PAYLOAD = {
    "api_version": "1",
    "contract_version": "3a",
    "bridge_available": True,
    "writes_enabled": False,
    "requires_preview": True,
    "requires_confirmation": True,
    "requires_read_after_write": True,
    "tasks": {
        "supported": True,
        "operations": ["add", "edit", "complete", "reopen", "delete"],
        "users": [{"id": "user_1", "name": "ינון"}, {"id": "user_2", "name": "הודיה"}],
    },
    "features": {
        "supported": True,
        "items": [
            {"id": "morning_auto", "label": "סיכום בוקר אוטומטי", "risk": "low"},
            {"id": "home_status_auto", "label": "מצב הבית האוטומטי", "risk": "low"},
            {"id": "meeting_alerts_default", "label": "התראות פגישות כברירת מחדל", "risk": "low"},
            {"id": "travel_alerts_default", "label": "התראות נסיעה כברירת מחדל", "risk": "low"},
        ],
    },
}

WRITES_ON = {**CONTRACT_PAYLOAD, "writes_enabled": True}
#: The contract now reports each feature's current state, so a feature is
#: previewable. Read from here — never from a raw `input_boolean`.
WRITES_ON_WITH_FEATURE_STATE = {
    **WRITES_ON,
    "features": {
        **CONTRACT_PAYLOAD["features"],
        "items": [
            {**item, "enabled": True}
            for item in CONTRACT_PAYLOAD["features"]["items"]
        ],
    },
}
COMMITTED = {"executed": True, "verified": True, "reason": "ok"}


SNAPSHOT_PAYLOAD = {
    "api_version": "1",
    "writes_enabled": False,
    "users": [
        {
            "id": "user_1",
            "name": "ינון",
            "items": [
                {"uid": "u-1", "summary": "לקבוע תור לרופא", "status": "needs_action", "due": ""},
                {"uid": "u-2", "summary": "לחדש ביטוח", "status": "completed", "due": ""},
            ],
        },
        {"id": "user_2", "name": "הודיה", "items": []},
    ],
}


@pytest.fixture
def bridge_client(make_real_adapter, recorded_requests):
    """A real adapter whose bridge services answer from a routing table."""

    def factory(responses: dict[str, dict]):
        def handler(request: httpx.Request) -> httpx.Response:
            recorded_requests.append(request)
            service = request.url.path.rsplit("/", 1)[-1]
            if service not in responses:
                return json_response({"error": "unexpected service"}, 500)
            return json_response({"service_response": responses[service]})

        adapter = make_real_adapter(handler)
        return adapter, adapter.management_bridge()

    return factory


def sent(recorded_requests, service: str) -> dict:
    """The body of the one call made to `service`."""
    for request in recorded_requests:
        if request.url.path.endswith(f"/{service}"):
            return json.loads(request.content)
    raise AssertionError(f"{service} was never called")


# --- the contract -----------------------------------------------------------
async def test_the_contract_is_read_and_never_assumed(bridge_client, recorded_requests) -> None:
    adapter, bridge = bridge_client({CONTRACT: CONTRACT_PAYLOAD})
    status = await bridge.status()
    await adapter.aclose()

    assert recorded_requests[0].url.path.endswith("/script/bobi_cc_manage_contract")
    assert status.available is True
    assert status.contract_version == "3a"
    # The master switch, as Home Assistant reports it.
    assert status.writes_enabled is False

    tasks = next(r for r in status.resources if r.id == "tasks")
    assert [op.id for op in tasks.operations] == ["add", "edit", "complete", "reopen", "delete"]
    assert next(op for op in tasks.operations if op.id == "delete").destructive is True
    assert {t.id for t in tasks.targets} == {"user_1", "user_2"}

    features = next(r for r in status.resources if r.id == "features")
    assert [t.id for t in features.targets] == [
        "morning_auto",
        "home_status_auto",
        "meeting_alerts_default",
        "travel_alerts_default",
    ]
    assert features.targets[0].label == "סיכום בוקר אוטומטי"
    # This older contract carried no state, and an absent one stays unknown
    # rather than being assumed. See the test below for the current shape.
    assert features.targets[0].enabled is None


async def test_the_contract_is_the_only_source_of_a_feature_state(
    bridge_client, recorded_requests
) -> None:
    """The bridge now reports `enabled` per feature, and it is authoritative.

    Nothing here reads an `input_boolean`, or any entity, to work out whether a
    feature is on: the contract says so, or the feature is not operable. Asking
    Home Assistant directly would be a second answer to a question that already
    has one, and the two could disagree.
    """
    adapter, bridge = bridge_client({CONTRACT: WRITES_ON_WITH_FEATURE_STATE})
    status = await bridge.status()
    await adapter.aclose()

    features = next(r for r in status.resources if r.id == "features")
    assert [t.enabled for t in features.targets] == [True, True, True, True]
    assert features.targets[0].risk == "low"
    for request in recorded_requests:
        assert "/input_boolean/" not in request.url.path
        assert "/states/" not in request.url.path


async def test_a_feature_the_contract_says_nothing_about_is_not_previewable(
    bridge_client,
) -> None:
    """Shown, but not operable: `expected_state` must be observed, not guessed."""
    adapter, bridge = bridge_client({CONTRACT: WRITES_ON})
    management = ManagementService(bridge)
    preview = await management.preview(
        "features",
        PreviewRequest(operation="set", resource_id="morning_auto", payload={"enabled": False}),
    )
    await adapter.aclose()

    assert preview.valid is False
    assert [e.code for e in preview.errors] == ["state_unavailable"]


async def test_a_bridge_that_says_it_is_unavailable_is_believed(bridge_client) -> None:
    adapter, bridge = bridge_client({CONTRACT: {**CONTRACT_PAYLOAD, "bridge_available": False}})
    status = await bridge.status()
    await adapter.aclose()

    assert status.available is False
    assert status.reason == "ניהול עדיין לא הופעל ב-Home Assistant"


async def test_an_operation_outside_the_closed_set_is_dropped(bridge_client) -> None:
    """A contract naming something this app does not implement offers nothing."""
    payload = {**CONTRACT_PAYLOAD, "tasks": {**CONTRACT_PAYLOAD["tasks"], "operations": ["nuke"]}}
    adapter, bridge = bridge_client({CONTRACT: payload})
    status = await bridge.status()
    await adapter.aclose()

    assert next(r for r in status.resources if r.id == "tasks").operations == []


# --- the snapshot -----------------------------------------------------------
async def test_the_snapshot_flattens_both_lists(bridge_client, recorded_requests) -> None:
    adapter, bridge = bridge_client({TASK_SNAPSHOT: SNAPSHOT_PAYLOAD})
    snapshot = await bridge.snapshot()
    await adapter.aclose()

    assert recorded_requests[0].url.path.endswith("/script/bobi_cc_task_snapshot")
    assert snapshot.count == 2
    assert [t.uid for t in snapshot.tasks] == ["u-1", "u-2"]
    assert [t.completed for t in snapshot.tasks] == [False, True]
    assert snapshot.tasks[0].owner_id == "user_1"
    assert snapshot.tasks[0].owner == "ינון"
    # An owner with no tasks is still someone a task can be added for.
    assert {o.id for o in snapshot.owners} == {"user_1", "user_2"}


# --- adding a task ----------------------------------------------------------
async def test_adding_a_task_calls_the_add_service_with_the_contract_fields(
    bridge_client, recorded_requests
) -> None:
    adapter, bridge = bridge_client(
        {
            TASK_ADD_COMMIT: {
                "executed": True,
                "verified": True,
                "reason": "ok",
                "operation": "add",
                "user_id": "user_1",
                "uid": "u-9",
                "summary": "לקנות חלב",
                "request_id": "req_x",
                "writes_enabled": True,
            }
        }
    )
    outcome = await bridge.apply(
        resource_type="tasks",
        operation="add",
        resource_id=None,
        payload={"user_id": "user_1", "summary": "לקנות חלב", "due_date": "2026-09-01"},
        observed=ObservedState(values={}),
        request_id="req_x",
        preview_token=PREVIEW_TOKEN,
    )
    await adapter.aclose()

    body = sent(recorded_requests, "bobi_cc_task_add_commit")
    assert body == {
        "user_id": "user_1",
        "summary": "לקנות חלב",
        "due_date": "2026-09-01",
        "preview_token": PREVIEW_TOKEN,
        "confirmed": True,
        "request_id": "req_x",
    }
    assert outcome.executed is True
    assert outcome.verified is True
    assert outcome.resource_id == "u-9"


async def test_a_missing_due_date_is_sent_as_an_empty_string(
    bridge_client, recorded_requests
) -> None:
    adapter, bridge = bridge_client({TASK_ADD_COMMIT: {"executed": True, "verified": True}})
    await bridge.apply(
        resource_type="tasks",
        operation="add",
        resource_id=None,
        payload={"user_id": "user_1", "summary": "לקנות חלב"},
        observed=ObservedState(values={}),
        request_id="req_x",
        preview_token=PREVIEW_TOKEN,
    )
    await adapter.aclose()

    assert sent(recorded_requests, "bobi_cc_task_add_commit")["due_date"] == ""


# --- updating a task --------------------------------------------------------
@pytest.mark.parametrize("operation", ["edit", "complete", "reopen", "delete"])
async def test_updating_sends_the_observed_state_as_expected(
    bridge_client, recorded_requests, operation
) -> None:
    """`expected_*` is what the preview saw — the basis of HA's staleness check."""
    adapter, bridge = bridge_client({TASK_UPDATE_COMMIT: {"executed": True, "verified": True}})
    await bridge.apply(
        resource_type="tasks",
        operation=operation,
        resource_id="u-1",
        payload={"new_summary": "לקבוע תור לשיניים"},
        observed=ObservedState(
            resource_id="u-1",
            label="לקבוע תור לרופא",
            values={
                "summary": "לקבוע תור לרופא",
                "status": "needs_action",
                "user_id": "user_1",
            },
        ),
        request_id="req_y",
        preview_token=PREVIEW_TOKEN,
    )
    await adapter.aclose()

    body = sent(recorded_requests, "bobi_cc_task_update_commit")
    assert body["operation"] == operation
    assert body["uid"] == "u-1"
    assert body["user_id"] == "user_1"
    assert body["expected_summary"] == "לקבוע תור לרופא"
    assert body["expected_status"] == "needs_action"
    assert body["preview_token"] == PREVIEW_TOKEN
    assert body["confirmed"] is True
    assert body["request_id"] == "req_y"
    assert set(body) == {
        "operation",
        "user_id",
        "uid",
        "new_summary",
        "expected_summary",
        "expected_status",
        "preview_token",
        "confirmed",
        "request_id",
    }


async def test_a_stale_preview_is_reported_not_retried(bridge_client) -> None:
    adapter, bridge = bridge_client(
        {TASK_UPDATE_COMMIT: {"executed": False, "verified": False, "reason": "stale_preview"}}
    )
    outcome = await bridge.apply(
        resource_type="tasks",
        operation="complete",
        resource_id="u-1",
        payload={},
        observed=ObservedState(values={"summary": "x", "status": "needs_action"}),
        request_id="req_z",
        preview_token=PREVIEW_TOKEN,
    )
    await adapter.aclose()

    assert outcome.executed is False
    assert outcome.reason == "stale_preview"


# --- features ---------------------------------------------------------------
async def test_a_feature_commit_sends_the_expected_state(
    bridge_client, recorded_requests
) -> None:
    adapter, bridge = bridge_client(
        {FEATURE_COMMIT: {"executed": True, "verified": True, "feature_id": "morning_auto"}}
    )
    await bridge.apply(
        resource_type="features",
        operation="set",
        resource_id="morning_auto",
        payload={"enabled": False},
        observed=ObservedState(values={"state": "on", "enabled": True}),
        request_id="req_f",
        preview_token=PREVIEW_TOKEN,
    )
    await adapter.aclose()

    body = sent(recorded_requests, "bobi_cc_feature_commit")
    assert body == {
        "feature_id": "morning_auto",
        "enabled": False,
        "expected_state": "on",
        "preview_token": PREVIEW_TOKEN,
        "confirmed": True,
        "request_id": "req_f",
    }


async def test_already_in_state_comes_through_untouched(bridge_client) -> None:
    adapter, bridge = bridge_client(
        {
            FEATURE_COMMIT: {
                "executed": False,
                "verified": True,
                "reason": "already_in_state",
                "feature_id": "morning_auto",
            }
        }
    )
    outcome = await bridge.apply(
        resource_type="features",
        operation="set",
        resource_id="morning_auto",
        payload={"enabled": True},
        observed=ObservedState(values={"state": "on"}),
        request_id="req_f",
        preview_token=PREVIEW_TOKEN,
    )
    await adapter.aclose()

    assert (outcome.executed, outcome.verified, outcome.reason) == (
        False,
        True,
        "already_in_state",
    )


# --- what it cannot do ------------------------------------------------------
async def test_the_bridge_reaches_only_the_five_management_services(
    bridge_client, recorded_requests
) -> None:
    adapter, bridge = bridge_client(
        {CONTRACT: CONTRACT_PAYLOAD, TASK_SNAPSHOT: SNAPSHOT_PAYLOAD}
    )
    await bridge.status()
    await bridge.snapshot()
    await bridge.observe("tasks", "u-1")
    await adapter.aclose()

    called = {request.url.path.rsplit("/", 1)[-1] for request in recorded_requests}
    assert called <= {CONTRACT, TASK_SNAPSHOT, TASK_ADD_COMMIT, TASK_UPDATE_COMMIT, FEATURE_COMMIT}
    for request in recorded_requests:
        assert "/todo/" not in request.url.path
        assert "/input_boolean/" not in request.url.path


async def test_an_undeclared_operation_raises_before_any_request(
    bridge_client, recorded_requests
) -> None:
    from app.errors import BobiError

    adapter, bridge = bridge_client({})
    with pytest.raises(BobiError):
        await bridge.apply(
            resource_type="tasks",
            operation="archive",
            resource_id="u-1",
            payload={},
            observed=ObservedState(values={}),
            request_id="req_q",
            preview_token=PREVIEW_TOKEN,
        )
    await adapter.aclose()

    assert recorded_requests == []


async def test_the_service_reports_the_master_switch_it_read(bridge_client) -> None:
    """End to end: contract → service → status, with writes still off."""
    adapter, bridge = bridge_client({CONTRACT: CONTRACT_PAYLOAD})
    status = await ManagementService(bridge).status()
    await adapter.aclose()

    assert status.available is True
    assert status.writes_enabled is False
    # And the flow requirements are never relaxed, whatever the bridge says.
    assert status.requires_preview is True
    assert status.requires_confirmation is True
    assert status.requires_read_after_write is True


# --- the preview token, over the wire ---------------------------------------
# The tests above hand `apply()` a token directly, so they can only prove the
# bridge forwards one it is given. These drive the whole flow — preview, then
# commit — and read the body that actually left for Home Assistant. That is the
# gap 2.2.0 shipped through: the flow was right, the bridge was right, and no
# token was passed between them, so every live commit came back
# `invalid_commit_request`.
async def committed_body(bridge_client, recorded_requests, responses, resource, request_, service):
    """Preview then commit through the service; return what reached HA."""
    adapter, bridge = bridge_client(responses)
    management = ManagementService(bridge)
    preview = await management.preview(resource, request_)
    assert preview.valid, preview.errors
    response = await management.commit(
        resource, CommitRequest(preview_id=preview.preview_id, confirmed=True)
    )
    await adapter.aclose()
    assert response.result.status == "committed"
    return sent(recorded_requests, service)


async def test_a_task_add_commit_reaches_home_assistant_with_its_token(
    bridge_client, recorded_requests
) -> None:
    body = await committed_body(
        bridge_client,
        recorded_requests,
        {CONTRACT: WRITES_ON, TASK_ADD_COMMIT: {**COMMITTED, "uid": "u-9"}},
        "tasks",
        PreviewRequest(
            operation="add",
            payload={"user_id": "user_1", "summary": "בדיקת Bobi CC E2E", "due_date": ""},
        ),
        TASK_ADD_COMMIT,
    )

    assert "preview_token" in body
    assert isinstance(body["preview_token"], str)
    assert body["preview_token"] != ""
    # The shape Home Assistant's script reads, in full.
    assert set(body) == {
        "user_id",
        "summary",
        "due_date",
        "preview_token",
        "confirmed",
        "request_id",
    }


async def test_a_task_update_commit_reaches_home_assistant_with_its_token(
    bridge_client, recorded_requests
) -> None:
    body = await committed_body(
        bridge_client,
        recorded_requests,
        {
            CONTRACT: WRITES_ON,
            TASK_SNAPSHOT: SNAPSHOT_PAYLOAD,
            TASK_UPDATE_COMMIT: {**COMMITTED, "uid": "u-1"},
        },
        "tasks",
        PreviewRequest(operation="complete", resource_id="u-1"),
        TASK_UPDATE_COMMIT,
    )

    assert body["preview_token"]
    # The token travels with the staleness evidence, not instead of it.
    assert body["expected_summary"] == "לקבוע תור לרופא"
    assert body["expected_status"] == "needs_action"


async def test_a_feature_commit_reaches_home_assistant_with_its_token(
    bridge_client, recorded_requests
) -> None:
    body = await committed_body(
        bridge_client,
        recorded_requests,
        {
            CONTRACT: WRITES_ON_WITH_FEATURE_STATE,
            FEATURE_COMMIT: {**COMMITTED, "feature_id": "morning_auto"},
        },
        "features",
        PreviewRequest(operation="set", resource_id="morning_auto", payload={"enabled": False}),
        FEATURE_COMMIT,
    )

    assert body["preview_token"]
    assert body["expected_state"] == "on"
    assert body["enabled"] is False


async def test_the_token_sent_is_the_one_the_preview_minted(
    bridge_client, recorded_requests
) -> None:
    """Not a fresh value made up at commit time — that would prove nothing."""
    adapter, bridge = bridge_client(
        {CONTRACT: WRITES_ON, TASK_ADD_COMMIT: {**COMMITTED, "uid": "u-9"}}
    )
    management = ManagementService(bridge)
    preview = await management.preview(
        "tasks",
        PreviewRequest(operation="add", payload={"user_id": "user_1", "summary": "לקנות חלב"}),
    )
    minted = management._previews[preview.preview_id].token
    await management.commit(
        "tasks", CommitRequest(preview_id=preview.preview_id, confirmed=True)
    )
    await adapter.aclose()

    assert sent(recorded_requests, TASK_ADD_COMMIT)["preview_token"] == minted
    # And it is not the id the browser was given.
    assert minted != preview.preview_id


async def test_a_stale_or_replayed_preview_never_becomes_a_request(
    bridge_client, recorded_requests
) -> None:
    """Expired, consumed, or pointed at a different target: no HTTP call."""
    adapter, bridge = bridge_client(
        {CONTRACT: WRITES_ON, TASK_ADD_COMMIT: {**COMMITTED, "uid": "u-9"}}
    )
    management = ManagementService(bridge)

    async def take_preview():
        return await management.preview(
            "tasks",
            PreviewRequest(operation="add", payload={"user_id": "user_1", "summary": "לקנות חלב"}),
        )

    expired = await take_preview()
    management._previews[expired.preview_id].expires_at = manage._now() - timedelta(seconds=1)

    replayed = await take_preview()
    await management.commit(
        "tasks", CommitRequest(preview_id=replayed.preview_id, confirmed=True)
    )
    commits_after_the_legitimate_one = 1

    altered = await take_preview()

    for request_ in (
        CommitRequest(preview_id=expired.preview_id, confirmed=True),
        CommitRequest(preview_id=replayed.preview_id, confirmed=True),
        CommitRequest(preview_id="pv_invented", confirmed=True),
        CommitRequest(preview_id=altered.preview_id, confirmed=True, operation="delete"),
    ):
        with pytest.raises(PreviewExpiredError):
            await management.commit("tasks", request_)
    await adapter.aclose()

    commits = [r for r in recorded_requests if r.url.path.endswith(f"/{TASK_ADD_COMMIT}")]
    assert len(commits) == commits_after_the_legitimate_one


async def test_a_bridge_called_without_a_token_refuses_before_the_request(
    bridge_client, recorded_requests
) -> None:
    """Defence in depth: the adapter will not build a tokenless commit at all.

    Home Assistant would reject it anyway — that is exactly what happened in
    2.2.0 — but a refusal that never leaves the process is the honest place to
    stop, and it keeps the failure attributable to this side.
    """
    from app.errors import BobiError

    adapter, bridge = bridge_client({TASK_ADD_COMMIT: COMMITTED})
    with pytest.raises(BobiError) as raised:
        await bridge.apply(
            resource_type="tasks",
            operation="add",
            resource_id=None,
            payload={"user_id": "user_1", "summary": "לקנות חלב"},
            observed=ObservedState(values={}),
            request_id="req_x",
            preview_token="",
        )
    await adapter.aclose()

    assert raised.value.code == "preview_token_missing"
    assert recorded_requests == []


async def test_the_token_is_not_written_to_the_debug_log(bridge_client, recorded_requests) -> None:
    """`debug_http` shows what was sent; a five-minute secret outlives the log."""
    from app.adapters.real import _loggable

    body = await committed_body(
        bridge_client,
        recorded_requests,
        {CONTRACT: WRITES_ON, TASK_ADD_COMMIT: {**COMMITTED, "uid": "u-9"}},
        "tasks",
        PreviewRequest(operation="add", payload={"user_id": "user_1", "summary": "לקנות חלב"}),
        TASK_ADD_COMMIT,
    )
    logged = _loggable(body)

    assert body["preview_token"] not in str(logged)
    # Still enough to answer the question the flag is turned on to answer.
    assert "chars" in logged["preview_token"]
    assert logged["summary"] == "לקנות חלב"
