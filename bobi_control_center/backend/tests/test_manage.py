"""The Phase 3A write flow, against the Home Assistant contract.

Two independent layers have to approve every change, and the tests are grouped
that way:

* **This application** — a preview that writes nothing, a server-side token that
  expires, is used once, and carries the payload so the client cannot alter what
  it confirmed, plus an explicit confirmation.
* **Home Assistant** — its master switch, its whitelists, its comparison of the
  state the preview observed, and its own read-after-write.

Neither is relaxed because the other exists, and the default in every fixture is
the safe one: the master switch starts **off**.
"""

from __future__ import annotations

from datetime import timedelta

import pytest

from app.mock.management import MockManagementBridge
from app.models.manage import CommitRequest, PreviewRequest
from app.services import manage
from app.services.manage import (
    ConfirmationRequiredError,
    ManagementService,
    ManagementUnavailableError,
    PreviewExpiredError,
    WritesDisabledError,
)

OPEN_TASK = {"summary": "לקבוע תור לרופא", "status": "needs_action", "user_id": "user_1"}
DONE_TASK = {"summary": "לחדש ביטוח", "status": "completed", "user_id": "user_2"}


def bridge(**kwargs) -> MockManagementBridge:
    """A bridge with one open and one completed task. Writes off unless asked."""
    kwargs.setdefault("tasks", {"uid_1": dict(OPEN_TASK), "uid_2": dict(DONE_TASK)})
    kwargs.setdefault("features", {"morning_auto": False, "home_status_auto": True})
    return MockManagementBridge(**kwargs)


def service(**kwargs) -> ManagementService:
    return ManagementService(bridge(**kwargs))


async def preview_add(svc: ManagementService, **payload):
    return await svc.preview(
        "tasks",
        PreviewRequest(
            operation="add",
            payload={"summary": "לקנות חלב", "user_id": "user_1", **payload},
        ),
    )


async def commit(svc: ManagementService, preview, resource="tasks", **kwargs):
    return await svc.commit(
        resource, CommitRequest(preview_id=preview.preview_id, confirmed=True, **kwargs)
    )


# --- the master switch ------------------------------------------------------
async def test_the_master_switch_is_reported_never_set() -> None:
    """Writes are off today, and this application only reads that."""
    status = await service().status()

    assert status.available is True
    assert status.writes_enabled is False


async def test_a_preview_still_works_while_writes_are_off() -> None:
    """This is the point of the split: the flow can be exercised safely."""
    result = await preview_add(service())

    assert result.valid is True
    assert result.title == "הוספת משימה"


async def test_a_commit_is_refused_while_writes_are_off() -> None:
    """A disabled feature, not a failure — and the wording says so."""
    holder = bridge()
    svc = ManagementService(holder)
    preview = await preview_add(svc)

    with pytest.raises(WritesDisabledError) as caught:
        await commit(svc, preview)

    assert caught.value.message == "ניהול עדיין לא הופעל ב-Home Assistant"
    assert caught.value.status_code == 409, "not a 5xx: nothing is broken"
    assert holder.applied == [], "the bridge was never asked to do anything"


async def test_the_application_never_reports_writes_it_cannot_do() -> None:
    from app.adapters import MockHomeAssistantAdapter, RealHomeAssistantAdapter

    assert RealHomeAssistantAdapter.writes_enabled is False
    assert MockHomeAssistantAdapter.writes_enabled is False


# --- fail closed ------------------------------------------------------------
async def test_without_a_bridge_nothing_is_available() -> None:
    status = await ManagementService(None).status()

    assert status.available is False
    assert status.reason == "ניהול עדיין לא הופעל ב-Home Assistant"


async def test_preview_and_snapshot_fail_closed_without_a_bridge() -> None:
    svc = ManagementService(None)
    with pytest.raises(ManagementUnavailableError):
        await preview_add(svc)
    with pytest.raises(ManagementUnavailableError):
        await svc.snapshot()


async def test_an_operation_the_bridge_does_not_declare_is_refused() -> None:
    from app.errors import BobiError

    with pytest.raises(BobiError):
        await service().preview(
            "features", PreviewRequest(operation="delete", resource_id="morning_auto")
        )


# --- preview never writes ---------------------------------------------------
async def test_preview_performs_no_write() -> None:
    holder = bridge(writes_enabled=True)
    svc = ManagementService(holder)

    await preview_add(svc)
    await svc.preview("tasks", PreviewRequest(operation="delete", resource_id="uid_1"))

    assert holder.applied == []
    assert set(holder.tasks) == {"uid_1", "uid_2"}


async def test_preview_binds_to_the_state_it_observed() -> None:
    """The dialog describes what is true now, not what the client claimed."""
    svc = service(writes_enabled=True)
    preview = await svc.preview(
        "tasks",
        PreviewRequest(
            operation="edit",
            resource_id="uid_1",
            # A lie about the current title must not reach the dialog.
            payload={"new_summary": "לקבוע תור לשיניים", "summary": "משהו אחר"},
        ),
    )

    rows = {c.label: (c.before, c.after) for c in preview.changes}
    assert rows["משימה"] == ("לקבוע תור לרופא", "לקבוע תור לשיניים")


async def test_a_task_that_no_longer_exists_cannot_be_previewed() -> None:
    preview = await service().preview(
        "tasks", PreviewRequest(operation="delete", resource_id="uid_gone")
    )

    assert preview.valid is False
    assert [e.code for e in preview.errors] == ["state_unavailable"]


async def test_a_feature_without_a_readable_state_cannot_be_previewed() -> None:
    """`expected_state` must be observed. An unknown state is not guessable."""
    preview = await service(reports_feature_state=False).preview(
        "features",
        PreviewRequest(operation="set", resource_id="morning_auto", payload={"enabled": True}),
    )

    assert preview.valid is False
    assert [e.code for e in preview.errors] == ["state_unavailable"]


async def test_preview_rejects_an_empty_task_without_storing_it() -> None:
    svc = service()
    result = await svc.preview("tasks", PreviewRequest(operation="add", payload={}))

    assert result.valid is False
    assert {e.field for e in result.errors} == {"summary", "user_id"}
    with pytest.raises(PreviewExpiredError):
        await commit(svc, result)


async def test_preview_rejects_a_malformed_due_date() -> None:
    result = await preview_add(service(), due_date="25/12/2026")

    assert result.valid is False
    assert [e.field for e in result.errors] == ["due_date"]


async def test_preview_says_so_when_nothing_would_change() -> None:
    result = await service().preview(
        "tasks", PreviewRequest(operation="complete", resource_id="uid_2")
    )
    assert result.valid is False
    assert [e.code for e in result.errors] == ["already"]


# --- the preview store ------------------------------------------------------
async def test_the_token_is_opaque_and_carries_nothing() -> None:
    preview = await preview_add(service())

    assert preview.preview_id.startswith("pv_")
    assert len(preview.preview_id) > 24
    for leak in ("user_1", "לקנות חלב", "tasks", "add"):
        assert leak not in preview.preview_id


async def test_the_token_expires_after_its_ttl() -> None:
    svc = service(writes_enabled=True)
    preview = await preview_add(svc)

    stored = svc._previews[preview.preview_id]
    stored.expires_at = manage._now() - timedelta(seconds=1)

    with pytest.raises(PreviewExpiredError):
        await commit(svc, preview)


async def test_the_ttl_is_five_minutes() -> None:
    assert timedelta(minutes=5) == manage.PREVIEW_TTL


async def test_the_token_is_single_use() -> None:
    svc = service(writes_enabled=True)
    preview = await preview_add(svc)

    await commit(svc, preview)
    with pytest.raises(PreviewExpiredError):
        await commit(svc, preview)


async def test_an_unknown_token_is_rejected() -> None:
    with pytest.raises(PreviewExpiredError):
        await service(writes_enabled=True).commit(
            "tasks", CommitRequest(preview_id="pv_invented", confirmed=True)
        )


async def test_an_altered_payload_cannot_reuse_a_token() -> None:
    """The commit carries no payload, and an echo that disagrees is rejected."""
    holder = bridge(writes_enabled=True)
    svc = ManagementService(holder)
    preview = await svc.preview(
        "tasks", PreviewRequest(operation="delete", resource_id="uid_1")
    )

    # Same valid token, a different target.
    with pytest.raises(PreviewExpiredError):
        await svc.commit(
            "tasks",
            CommitRequest(
                preview_id=preview.preview_id,
                confirmed=True,
                confirm_word=manage.DESTRUCTIVE_CONFIRM_WORD,
                resource_id="uid_2",
            ),
        )
    # Same valid token, a different operation.
    with pytest.raises(PreviewExpiredError):
        await svc.commit(
            "tasks",
            CommitRequest(
                preview_id=preview.preview_id, confirmed=True, operation="complete"
            ),
        )
    assert holder.applied == []
    assert set(holder.tasks) == {"uid_1", "uid_2"}


async def test_a_token_cannot_cross_resources() -> None:
    svc = service(writes_enabled=True)
    preview = await preview_add(svc)

    with pytest.raises(PreviewExpiredError):
        await commit(svc, preview, resource="features")


async def test_only_the_stored_payload_reaches_home_assistant() -> None:
    holder = bridge(writes_enabled=True)
    svc = ManagementService(holder)
    preview = await preview_add(svc, due_date="2026-09-01")

    await commit(svc, preview)

    sent = holder.applied[0]["payload"]
    assert sent == {"summary": "לקנות חלב", "user_id": "user_1", "due_date": "2026-09-01"}


# --- confirmation -----------------------------------------------------------
async def test_commit_requires_an_explicit_confirmation() -> None:
    svc = service(writes_enabled=True)
    preview = await preview_add(svc)

    with pytest.raises(ConfirmationRequiredError):
        await svc.commit(
            "tasks", CommitRequest(preview_id=preview.preview_id, confirmed=False)
        )


async def test_deleting_needs_the_confirmation_word() -> None:
    holder = bridge(writes_enabled=True)
    svc = ManagementService(holder)
    preview = await svc.preview(
        "tasks", PreviewRequest(operation="delete", resource_id="uid_1")
    )

    assert preview.destructive is True
    assert preview.warning and "הפיכה" in preview.warning

    with pytest.raises(ConfirmationRequiredError):
        await commit(svc, preview)
    assert holder.applied == []
    assert "uid_1" in holder.tasks

    response = await commit(svc, preview, confirm_word=manage.DESTRUCTIVE_CONFIRM_WORD)
    assert response.result.status == "committed"
    assert "uid_1" not in holder.tasks


# --- the Home Assistant layer -----------------------------------------------
async def test_an_expected_summary_mismatch_prevents_the_commit() -> None:
    """Someone renamed the task between preview and confirm."""
    holder = bridge(writes_enabled=True)
    svc = ManagementService(holder)
    preview = await svc.preview(
        "tasks",
        PreviewRequest(operation="edit", resource_id="uid_1", payload={"new_summary": "חדש"}),
    )

    holder.tasks["uid_1"]["summary"] = "מישהו שינה בינתיים"
    response = await commit(svc, preview)

    assert response.result.status == "failed"
    assert response.result.message == "השינוי לא בוצע"
    assert response.result.reason == "stale_preview"
    assert holder.tasks["uid_1"]["summary"] == "מישהו שינה בינתיים", "no mutation"


async def test_an_expected_status_mismatch_prevents_the_commit() -> None:
    holder = bridge(writes_enabled=True)
    svc = ManagementService(holder)
    preview = await svc.preview(
        "tasks", PreviewRequest(operation="complete", resource_id="uid_1")
    )

    holder.tasks["uid_1"]["status"] = "completed"
    response = await commit(svc, preview)

    assert response.result.status == "failed"
    assert response.result.reason == "stale_preview"


async def test_the_observed_state_is_what_is_sent_to_home_assistant() -> None:
    """`expected_*` comes from the preview's reading, never from the client."""
    holder = bridge(writes_enabled=True)
    svc = ManagementService(holder)
    preview = await svc.preview(
        "tasks", PreviewRequest(operation="complete", resource_id="uid_1")
    )
    await commit(svc, preview)

    observed = holder.applied[0]["observed"]
    assert observed["summary"] == "לקבוע תור לרופא"
    assert observed["status"] == "needs_action"
    assert observed["user_id"] == "user_1"


async def test_the_feature_expected_state_is_passed_to_home_assistant() -> None:
    holder = bridge(writes_enabled=True)
    svc = ManagementService(holder)
    preview = await svc.preview(
        "features",
        PreviewRequest(operation="set", resource_id="morning_auto", payload={"enabled": True}),
    )
    await commit(svc, preview, resource="features")

    assert holder.applied[0]["observed"]["state"] == "off"
    assert holder.features["morning_auto"] is True


async def test_a_feature_that_changed_since_the_preview_is_refused() -> None:
    holder = bridge(writes_enabled=True)
    svc = ManagementService(holder)
    preview = await svc.preview(
        "features",
        PreviewRequest(operation="set", resource_id="morning_auto", payload={"enabled": True}),
    )

    holder.features["morning_auto"] = True  # someone else turned it on
    response = await commit(svc, preview, resource="features")

    assert response.result.status == "failed"
    assert response.result.reason == "stale_preview"


async def test_already_in_state_is_a_verified_success() -> None:
    """Nothing needed doing, and the bridge confirmed the desired state holds."""
    holder = bridge(writes_enabled=True, features={"morning_auto": True})
    svc = ManagementService(holder)
    preview = await svc.preview(
        "features",
        PreviewRequest(operation="set", resource_id="morning_auto", payload={"enabled": True}),
    )
    response = await commit(svc, preview, resource="features")

    assert response.result.status == "committed"
    assert response.result.message == "השינוי בוצע ואומת"
    assert response.result.reason == "already_in_state"
    assert response.result.verification.detail == "המצב כבר היה כמבוקש — לא נדרש שינוי."


async def test_a_duplicate_task_is_refused_by_the_bridge() -> None:
    svc = service(writes_enabled=True)
    preview = await svc.preview(
        "tasks",
        PreviewRequest(
            operation="add", payload={"summary": "לקבוע תור לרופא", "user_id": "user_1"}
        ),
    )
    response = await commit(svc, preview)

    assert response.result.status == "failed"
    assert response.result.reason == "duplicate"
    assert "כבר קיימת" in (response.result.verification.detail or "")


# --- honest results ---------------------------------------------------------
async def test_a_verified_commit_says_so() -> None:
    holder = bridge(writes_enabled=True)
    svc = ManagementService(holder)
    preview = await preview_add(svc)

    response = await commit(svc, preview)

    assert response.result.status == "committed"
    assert response.result.message == "השינוי בוצע ואומת"
    assert response.result.verification.verified is True
    assert response.result.verification.method == "read_after_write"


async def test_a_commit_that_could_not_be_verified_is_not_a_success() -> None:
    svc = service(writes_enabled=True, verifies=False)
    preview = await preview_add(svc)

    response = await commit(svc, preview)

    assert response.result.status == "committed_unverified"
    assert response.result.message == "השינוי בוצע אך לא הצלחנו לאמת"


async def test_a_bridge_error_reports_failure() -> None:
    svc = service(writes_enabled=True, fail_on="add")
    preview = await preview_add(svc)

    response = await commit(svc, preview)

    assert response.result.status == "failed"
    assert response.result.message == "השינוי לא בוצע"


# --- audit ------------------------------------------------------------------
async def test_every_preview_and_commit_is_audited() -> None:
    svc = service(writes_enabled=True)
    preview = await preview_add(svc)
    await commit(svc, preview)

    records = svc.audit().records
    assert [r.stage for r in records] == ["commit", "preview"]

    entry = records[0]
    assert entry.operation == "add"
    assert entry.resource_type == "tasks"
    assert entry.result == "committed"
    assert entry.verified is True
    assert entry.source == "web"
    assert entry.timestamp


async def test_a_refusal_is_audited_too() -> None:
    svc = service()
    preview = await preview_add(svc)
    with pytest.raises(WritesDisabledError):
        await commit(svc, preview)

    assert [r.result for r in svc.audit().records] == ["refused", "previewed"]


async def test_the_audit_trail_carries_no_personal_detail() -> None:
    svc = service()
    await preview_add(svc, phone="0500000000", chat_id="abc@c.us", token="sekret")

    change = svc.audit().records[0].requested_change
    assert change == {"summary": "לקנות חלב", "user_id": "user_1"}


async def test_a_private_field_never_reaches_the_bridge_either() -> None:
    holder = bridge(writes_enabled=True)
    svc = ManagementService(holder)
    preview = await preview_add(svc, phone="0500000000")
    await commit(svc, preview)

    assert "phone" not in holder.applied[0]["payload"]


# --- the snapshot -----------------------------------------------------------
async def test_the_snapshot_returns_open_and_completed_tasks() -> None:
    snapshot = await service().snapshot()

    assert snapshot.count == 2
    assert {t.completed for t in snapshot.tasks} == {False, True}
    assert {o.id for o in snapshot.owners} == {"user_1", "user_2"}


async def test_the_snapshot_exposes_no_entity_id() -> None:
    snapshot = await service().snapshot()

    dumped = snapshot.model_dump_json()
    assert "todo." not in dumped
    assert "input_boolean" not in dumped
