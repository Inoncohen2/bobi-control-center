"""The Phase 3A write flow.

Every test here defends one of the properties that make management safe:
a preview never writes, a commit needs a preview the user confirmed, a stale or
reused confirmation is refused, deleting needs more than an OK, and with no
Home Assistant write bridge declared, nothing works at all.
"""

from __future__ import annotations

from datetime import timedelta

import pytest

from app.errors import BobiError
from app.mock.management import MockManagementBridge
from app.models.manage import CommitRequest, PreviewRequest
from app.services import manage
from app.services.manage import (
    ConfirmationRequiredError,
    ManagementService,
    ManagementUnavailableError,
    PreviewExpiredError,
)


def service(**kwargs) -> ManagementService:
    return ManagementService(MockManagementBridge(**kwargs))


async def preview_create(svc: ManagementService, **payload):
    return await svc.preview(
        "tasks",
        PreviewRequest(
            operation="create",
            payload={"title": "לקבוע תור לרופא", "owner": "ינון", **payload},
        ),
    )


# --- fail closed ------------------------------------------------------------
async def test_without_a_write_bridge_nothing_is_available() -> None:
    status = await ManagementService(None).status()

    assert status.available is False
    assert status.reason == "ניהול עדיין לא הופעל ב-Home Assistant"
    assert status.resources == []


async def test_preview_fails_closed_without_a_write_bridge() -> None:
    with pytest.raises(ManagementUnavailableError):
        await preview_create(ManagementService(None))


async def test_commit_fails_closed_without_a_write_bridge() -> None:
    """Even a well-formed commit cannot get through — there is nothing to reach."""
    svc = ManagementService(None)
    with pytest.raises(PreviewExpiredError):
        await svc.commit("tasks", CommitRequest(preview_id="pv_anything", confirmed=True))


async def test_a_bridge_that_reports_unavailable_is_refused() -> None:
    with pytest.raises(ManagementUnavailableError):
        await preview_create(service(available=False))


async def test_the_app_never_reports_unrestricted_writes() -> None:
    """A bridge claiming writes_enabled cannot turn the Phase 2 invariant on."""
    status = await service().status()
    assert status.available is True
    assert status.writes_enabled is False


async def test_an_operation_the_bridge_does_not_declare_is_refused() -> None:
    svc = ManagementService(MockManagementBridge())
    with pytest.raises(BobiError):
        await svc.preview("features", PreviewRequest(operation="delete", resource_id="ai"))


# --- preview never writes ---------------------------------------------------
async def test_preview_performs_no_write() -> None:
    bridge = MockManagementBridge()
    svc = ManagementService(bridge)

    result = await preview_create(svc)

    assert result.valid is True
    assert result.would_execute is False
    # The one observable proof: the bridge was never asked to do anything.
    assert bridge.applied == []
    assert bridge.tasks == {}


async def test_preview_describes_the_change_in_hebrew() -> None:
    result = await preview_create(service())

    assert result.title == "הוספת משימה"
    rows = {c.label: (c.before, c.after) for c in result.changes}
    assert rows["משתמש"] == ("ינון", "ינון")
    assert rows["משימה"] == (None, "לקבוע תור לרופא")
    assert result.explanation


async def test_preview_rejects_an_empty_task_without_storing_it() -> None:
    svc = service()
    result = await svc.preview("tasks", PreviewRequest(operation="create", payload={}))

    assert result.valid is False
    assert {e.field for e in result.errors} == {"title", "owner"}
    # An invalid preview is not committable.
    with pytest.raises(PreviewExpiredError):
        await svc.commit("tasks", CommitRequest(preview_id=result.preview_id, confirmed=True))


# --- commit requires a preview and a confirmation ---------------------------
async def test_commit_requires_an_explicit_confirmation() -> None:
    svc = service()
    preview = await preview_create(svc)

    with pytest.raises(ConfirmationRequiredError):
        await svc.commit("tasks", CommitRequest(preview_id=preview.preview_id, confirmed=False))


async def test_commit_requires_a_preview_id_that_exists() -> None:
    with pytest.raises(PreviewExpiredError):
        await service().commit("tasks", CommitRequest(preview_id="pv_invented", confirmed=True))


async def test_an_expired_preview_cannot_commit() -> None:
    svc = service()
    preview = await preview_create(svc)

    stored = svc._previews[preview.preview_id]
    stored.expires_at = manage._now() - timedelta(seconds=1)

    with pytest.raises(PreviewExpiredError):
        await svc.commit("tasks", CommitRequest(preview_id=preview.preview_id, confirmed=True))


async def test_a_preview_cannot_be_committed_twice() -> None:
    """A confirmation is single-use, so it cannot be replayed against new state."""
    svc = service()
    preview = await preview_create(svc)

    await svc.commit("tasks", CommitRequest(preview_id=preview.preview_id, confirmed=True))
    with pytest.raises(PreviewExpiredError):
        await svc.commit("tasks", CommitRequest(preview_id=preview.preview_id, confirmed=True))


async def test_a_preview_cannot_commit_against_a_different_resource() -> None:
    svc = service()
    preview = await preview_create(svc)

    with pytest.raises(PreviewExpiredError):
        await svc.commit("features", CommitRequest(preview_id=preview.preview_id, confirmed=True))


# --- destructive ------------------------------------------------------------
async def test_deleting_a_task_is_marked_destructive_and_warns() -> None:
    svc = service(tasks={"t1": {"title": "ישן", "owner": "הודיה", "completed": False}})
    preview = await svc.preview(
        "tasks",
        PreviewRequest(
            operation="delete",
            resource_id="t1",
            payload={"owner": "הודיה", "current_title": "ישן"},
        ),
    )

    assert preview.title == "מחיקת משימה"
    assert preview.destructive is True
    assert preview.warning and "הפיכה" in preview.warning
    assert preview.confirm_word == manage.DESTRUCTIVE_CONFIRM_WORD
    assert preview.confirm_label == "מחק משימה"


async def test_deleting_requires_the_confirmation_word() -> None:
    bridge = MockManagementBridge(tasks={"t1": {"title": "ישן", "completed": False}})
    svc = ManagementService(bridge)
    preview = await svc.preview(
        "tasks", PreviewRequest(operation="delete", resource_id="t1", payload={})
    )

    # Confirmed, but without typing the word: refused, and nothing happened.
    with pytest.raises(ConfirmationRequiredError):
        await svc.commit("tasks", CommitRequest(preview_id=preview.preview_id, confirmed=True))
    assert bridge.applied == []
    assert "t1" in bridge.tasks

    response = await svc.commit(
        "tasks",
        CommitRequest(
            preview_id=preview.preview_id,
            confirmed=True,
            confirm_word=manage.DESTRUCTIVE_CONFIRM_WORD,
        ),
    )
    assert response.result.status == "committed"
    assert "t1" not in bridge.tasks


# --- commit, verify, report -------------------------------------------------
async def test_a_verified_commit_says_so() -> None:
    bridge = MockManagementBridge()
    svc = ManagementService(bridge)
    preview = await preview_create(svc)

    response = await svc.commit(
        "tasks", CommitRequest(preview_id=preview.preview_id, confirmed=True)
    )

    assert response.result.status == "committed"
    assert response.result.message == "השינוי בוצע ואומת"
    assert response.result.verification.verified is True
    assert response.result.verification.method == "read_after_write"
    assert len(bridge.tasks) == 1


async def test_a_commit_that_cannot_be_verified_is_not_reported_as_success() -> None:
    svc = ManagementService(MockManagementBridge(verifies=False))
    preview = await preview_create(svc)

    response = await svc.commit(
        "tasks", CommitRequest(preview_id=preview.preview_id, confirmed=True)
    )

    assert response.result.status == "committed_unverified"
    assert response.result.message == "השינוי בוצע אך לא הצלחנו לאמת"
    assert response.result.verification.verified is False


async def test_a_refused_write_reports_failure() -> None:
    svc = ManagementService(MockManagementBridge(fail_on="create"))
    preview = await preview_create(svc)

    response = await svc.commit(
        "tasks", CommitRequest(preview_id=preview.preview_id, confirmed=True)
    )

    assert response.result.status == "failed"
    assert response.result.message == "השינוי לא בוצע"
    assert response.result.verification.verified is False


# --- features ---------------------------------------------------------------
async def test_a_feature_preview_shows_current_and_proposed_state() -> None:
    svc = service(features={"vision": False})
    preview = await svc.preview(
        "features",
        PreviewRequest(
            operation="set",
            resource_id="vision",
            payload={"label": "עיבוד תמונות", "current": False, "enabled": True},
        ),
    )

    assert preview.title == "הפעלת עיבוד תמונות"
    rows = {c.label: (c.before, c.after) for c in preview.changes}
    assert rows["מצב"] == ("כבויה", "פעילה")
    assert preview.destructive is False
    assert preview.explanation


async def test_a_feature_commit_is_verified_by_reading_it_back() -> None:
    bridge = MockManagementBridge(features={"vision": False})
    svc = ManagementService(bridge)
    preview = await svc.preview(
        "features",
        PreviewRequest(
            operation="set", resource_id="vision", payload={"current": False, "enabled": True}
        ),
    )

    response = await svc.commit(
        "features", CommitRequest(preview_id=preview.preview_id, confirmed=True)
    )

    assert response.result.status == "committed"
    assert bridge.features["vision"] is True


async def test_a_feature_change_without_a_new_state_is_invalid() -> None:
    preview = await service().preview(
        "features", PreviewRequest(operation="set", resource_id="vision", payload={})
    )
    assert preview.valid is False
    assert [e.field for e in preview.errors] == ["enabled"]


# --- audit ------------------------------------------------------------------
async def test_every_preview_and_commit_is_audited() -> None:
    svc = service()
    preview = await preview_create(svc)
    await svc.commit("tasks", CommitRequest(preview_id=preview.preview_id, confirmed=True))

    log = svc.audit()
    assert [e.stage for e in log.records] == ["commit", "preview"]

    commit_entry = log.records[0]
    assert commit_entry.operation == "create"
    assert commit_entry.resource_type == "tasks"
    assert commit_entry.result == "committed"
    assert commit_entry.verified is True
    assert commit_entry.source == "web"
    assert commit_entry.timestamp


async def test_a_refusal_is_audited_too() -> None:
    svc = ManagementService(None)
    with pytest.raises(ManagementUnavailableError):
        await preview_create(svc)

    assert [e.result for e in svc.audit().records] == ["refused"]


async def test_the_audit_trail_carries_no_personal_detail() -> None:
    svc = service()
    await svc.preview(
        "tasks",
        PreviewRequest(
            operation="create",
            payload={
                "title": "לקנות חלב",
                "owner": "ינון",
                "phone": "0500000000",
                "chat_id": "abc@c.us",
                "token": "sekret",
            },
        ),
    )

    change = svc.audit().records[0].requested_change
    assert change == {"title": "לקנות חלב", "owner": "ינון"}


async def test_a_private_field_never_reaches_the_bridge_either() -> None:
    bridge = MockManagementBridge()
    svc = ManagementService(bridge)
    preview = await svc.preview(
        "tasks",
        PreviewRequest(
            operation="create",
            payload={"title": "לקנות חלב", "owner": "ינון", "phone": "0500000000"},
        ),
    )
    await svc.commit("tasks", CommitRequest(preview_id=preview.preview_id, confirmed=True))

    assert "phone" not in bridge.applied[0]["payload"]
