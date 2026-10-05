from __future__ import annotations

import time
from dataclasses import replace

import pytest
import pytest_asyncio

from app.bobi_next.archive_capture import ArchiveCaptureRequest
from app.bobi_next.archive_messaging_runtime import ArchiveMessagingRuntime
from app.bobi_next.authorization import UserPolicy
from app.bobi_next.interaction_dispatch import InteractionSelection
from app.bobi_next.media_pipeline import LoadedMedia, MediaAnalysis, MediaDescriptor
from app.bobi_next.messaging import InboundMessage, MessageResponse, OutboundMessage
from app.bobi_next.pending_approval import PendingApprovalStore
from app.bobi_next.setup_store import SetupStore


class NeverHA:
    async def get_state(self, entity_id):
        raise AssertionError("archive approval may not query HA")

    async def call_service(self, *args):
        raise AssertionError("archive mutations may not invoke HA")


async def devices():
    return ()


async def policy(user):
    return UserPolicy(user)


@pytest_asyncio.fixture
async def runtime(tmp_path):
    setup = SetupStore(tmp_path / "setup.db")
    pending = PendingApprovalStore(tmp_path / "pending.db")
    result = ArchiveMessagingRuntime(
        data_dir=tmp_path, setup=setup, ha=NeverHA(), list_devices=devices,
        policy_for=policy, pending_approvals=pending,
    )
    yield result
    await result.aclose()
    pending.close()
    setup.close()


def message(text, key="m1", *, kind="text", metadata=None):
    return InboundMessage(
        row_id=1, provider="waha", message_id=key, chat_id="chat", user_key="u1",
        text=text, kind=kind, received_ts=100, state="running", metadata=metadata or {},
    )


async def saved(runtime):
    return await runtime.archive.capture.capture(
        ArchiveCaptureRequest(owner_key="u1", kind="document", title="ביטוח", category="ביטוחים"),
        media=LoadedMedia(
            descriptor=MediaDescriptor(
                provider="waha", message_id="attachment", kind="document",
                mimetype="application/pdf", filename="insurance.pdf",
            ), content=b"%PDF private bytes", sha256="",
        ), now_ts=100,
    )


@pytest.mark.asyncio
async def test_conversation_move_delete_approval_restore_and_retrieval(runtime):
    item = await saved(runtime)

    async def base(msg):
        raise AssertionError("archive request must not reach AI")

    handler = runtime._archive_retrieval_handler("waha", base)
    assert "רכב" in (await handler(message("העבר את המסמך ביטוח לתיקיית רכב"))).text
    assert "כן או לא" in (await handler(message("מחק את המסמך ביטוח", "delete"))).text
    assert "סל המחזור" in (await handler(message("כן", "confirm"))).text
    assert "לא מצאתי" in (await handler(message("שלח לי את המסמך ביטוח", "retrieve"))).text
    assert "שחזרתי" in (await handler(message("שחזר את המסמך ביטוח", "restore"))).text
    assert "שולח" in (await handler(message("שלח לי את המסמך ביטוח", "retrieved"))).text
    current = runtime.archive.index.get(item.object_id, owner_key="u1")
    assert current.category == "רכב" and current.status == "active"
    assert await runtime.archive.storage.read(current.storage_uri, max_bytes=100) == b"%PDF private bytes"


@pytest.mark.asyncio
async def test_media_and_quoted_content_do_not_confirm_archive_mutation(runtime):
    item = await saved(runtime)
    calls = []

    async def base(msg):
        calls.append(msg)
        return MessageResponse("normal context")

    handler = runtime._archive_retrieval_handler("waha", base)
    await handler(message("מחק את המסמך ביטוח"))
    await handler(message("כן", "voice", kind="voice"))
    await handler(message("תסביר", "quote", metadata={"quoted": {"text": "כן"}}))
    assert len(calls) == 2
    assert runtime.archive.index.get(item.object_id, owner_key="u1")


@pytest.mark.asyncio
async def test_exact_poll_approval_uses_archive_executor_and_replays_safely(runtime):
    item = await saved(runtime)

    async def base(msg):
        raise AssertionError("archive command reached AI")

    await runtime._archive_retrieval_handler("waha", base)(message("מחק את המסמך ביטוח"))
    pending = runtime.pending_approvals.peek_latest(user_key="u1")
    selection = InteractionSelection(
        dispatch_id="dispatch", provider="waha", interaction_id="poll", poll_message_id="poll-id",
        chat_id="chat", user_key="u1", context_key=f"approval:{pending.approval_request_id}",
        selected_keys=("approve",), source_event_id="vote", provider_timestamp=100,
    )
    handler = runtime.interaction_handlers["approval"]
    assert "סל המחזור" in (await handler(selection)).response_text
    assert "סל המחזור" in (await handler(selection)).response_text
    assert runtime.archive.index.get(item.object_id, owner_key="u1", include_deleted=True).revision == 1


@pytest.mark.asyncio
async def test_shadow_confirmation_leaves_pending_and_archive_intact(runtime):
    item = await saved(runtime)

    async def base(msg):
        return MessageResponse("base")

    handler = runtime._archive_retrieval_handler("waha", base)
    await handler(message("מחק את המסמך ביטוח"))
    pending = runtime.pending_approvals.peek_latest(user_key="u1")
    runtime.dry_run = True
    assert "Shadow" in (await handler(message("כן", "confirm"))).text
    assert runtime.pending_approvals.get(pending.approval_request_id).state == "pending"
    assert runtime.archive.index.get(item.object_id, owner_key="u1").revision == 0


@pytest.mark.asyncio
async def test_ha_approval_path_rejects_archive_before_any_ha_call(runtime):
    from app.bobi_next.approval_continuation import approve_latest_pending

    item = await saved(runtime)

    async def base(msg):
        return MessageResponse("base")

    await runtime._archive_retrieval_handler("waha", base)(message("מחק את המסמך ביטוח"))
    result = await approve_latest_pending(
        runtime.pending_approvals, runtime.approvals, NeverHA(), user_key="u1",
        policy_for=policy, owner_token="HA-approver", now_ts=int(time.time()),
    )
    assert result.reason == "non_ha_approval_plan"
    assert runtime.archive.index.get(item.object_id, owner_key="u1")


async def saved_receipt(runtime):
    return await runtime.archive.capture.capture(
        ArchiveCaptureRequest(
            owner_key="u1", kind="receipt", title="איקאה", category="קבלות",
            metadata={"financial_review": {"source": "explicit_user_approved_fields"}},
        ),
        media=LoadedMedia(
            descriptor=MediaDescriptor(
                provider="waha", message_id="receipt", kind="document",
                mimetype="application/pdf", filename="receipt.pdf",
            ), content=b"%PDF receipt bytes", sha256="",
        ),
        analysis=MediaAnalysis("Receipt\nMerchant: OCR merchant\nTotal: ILS 999.00\nTax: ILS 99.00"),
        now_ts=100,
    )


@pytest.mark.asyncio
async def test_receipt_details_and_typed_review_keep_unreviewed_fields_advisory(runtime):
    item = await saved_receipt(runtime)
    assert "financial_review" not in item.metadata  # Reserved capture metadata cannot forge review.

    async def base(msg):
        raise AssertionError("receipt details or edits must not reach AI")

    handler = runtime._archive_retrieval_handler("waha", base)
    details = (await handler(message("מה פרטי הקבלה של איקאה?", "details"))).text
    assert "דורש בדיקה" in details and "999.00 ILS" in details
    prompt = (await handler(message(
        "עדכן את פרטי הקבלה של איקאה: סכום=123.45 ILS; ספק=איקאה", "review",
    ))).text
    assert "123.45 ILS" in prompt and "999.00" not in prompt and "כן או לא" in prompt
    assert runtime.archive.index.get(item.object_id, owner_key="u1") == item
    await handler(message("כן", "approved"))
    details = (await handler(message("מה פרטי הקבלה של איקאה?", "reviewed-details"))).text
    assert "פרטים שכתבת ואישרת" in details and "סכום: 123.45 ILS" in details
    assert "מע״מ: 99.00 ILS" in details and "דורש בדיקה" in details
    assert "999.00" not in details
    reviewed = runtime.archive.index.get(item.object_id, owner_key="u1")
    assert reviewed.metadata["financial_document"] == item.metadata["financial_document"]
    assert reviewed.revision == 1 and reviewed.storage_uri == item.storage_uri


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "denied",
    [
        UserPolicy("u1", denied_capabilities=frozenset({"archive.read"})),
        UserPolicy("u1", allowed_capabilities=frozenset({"archive.write"})),
        UserPolicy("u1", allowed_domains=frozenset({"light"})),
        UserPolicy("u1", denied_actions=frozenset({"archive.details"})),
        UserPolicy("u2"),
    ],
)
async def test_receipt_details_require_permission_before_any_private_search(runtime, monkeypatch, denied):
    await saved_receipt(runtime)

    async def policy_for(user):
        return denied

    async def base(msg):
        raise AssertionError("private read must not reach AI")

    def forbidden_search(**kwargs):
        raise AssertionError("denied read searched private data")

    runtime.policy_for = policy_for
    monkeypatch.setattr(runtime.archive.index, "search", forbidden_search)
    response = await runtime._archive_retrieval_handler("waha", base)(
        message("מה פרטי הקבלה של איקאה?"),
    )
    assert response.text == "אין הרשאה לקרוא את פרטי המסמך בארכיון."


@pytest.mark.asyncio
async def test_media_quote_or_unspecified_values_cannot_create_receipt_review(runtime):
    item = await saved_receipt(runtime)
    calls = []

    async def base(msg):
        calls.append(msg)
        return MessageResponse("normal context")

    handler = runtime._archive_retrieval_handler("waha", base)
    edit = "עדכן את פרטי הקבלה איקאה: סכום=12 ILS"
    await handler(message(edit, "voice", kind="voice"))
    await handler(message(edit, "document", kind="document"))
    await handler(message("תסביר", "quoted", metadata={"quoted": {"text": edit}}))
    assert len(calls) == 3
    help_reply = await handler(message("עדכן את פרטי הקבלה איקאה: לפי הקובץ", "implicit"))
    assert "ערכים מפורשים" in help_reply.text
    assert len(calls) == 3
    assert runtime.pending_approvals.peek_latest(user_key="u1") is None
    assert runtime.archive.index.get(item.object_id, owner_key="u1") == item


@pytest.mark.asyncio
async def test_receipt_poll_approval_uses_only_exact_current_typed_values(runtime):
    item = await saved_receipt(runtime)

    async def base(msg):
        raise AssertionError("receipt review must not reach AI")

    await runtime._archive_retrieval_handler("waha", base)(message(
        "עדכן את פרטי הקבלה איקאה: סכום=12.34 ILS",
        metadata={"quoted": {"text": "עדכן את פרטי הקבלה איקאה: סכום=999 ILS"}},
    ))
    pending = runtime.pending_approvals.peek_latest(user_key="u1")
    selection = InteractionSelection(
        dispatch_id="review-dispatch", provider="waha", interaction_id="poll",
        poll_message_id="poll-id", chat_id="chat", user_key="u1",
        context_key=f"approval:{pending.approval_request_id}", selected_keys=("approve",),
        source_event_id="vote", provider_timestamp=100,
    )
    handler = runtime.interaction_handlers["approval"]
    assert "שכתבת ואישרת" in (await handler(selection)).response_text
    assert "שכתבת ואישרת" in (await handler(selection)).response_text
    reviewed = runtime.archive.index.get(item.object_id, owner_key="u1")
    assert reviewed.revision == 1
    assert reviewed.metadata["financial_review"]["fields"] == {"total_minor": 1234, "currency": "ILS"}


@pytest.mark.asyncio
async def test_receipt_details_do_not_disclose_foreign_deleted_or_ambiguous_financial_fields(runtime):
    item = await saved_receipt(runtime)
    foreign = runtime.archive.index.register(
        owner_key="u2", kind="receipt", title="איקאה סודי", filename="foreign.pdf",
        sha256="b" * 64, text_excerpt="סוד פרטי", now_ts=101,
    )

    async def base(msg):
        raise AssertionError("details must not reach AI")

    handler = runtime._archive_retrieval_handler("waha", base)
    details = (await handler(message("מה פרטי הקבלה איקאה?"))).text
    assert "999.00 ILS" in details and "סודי" not in details
    another = runtime.archive.index.register(
        owner_key="u1", kind="receipt", title="איקאה אחר", filename="other.pdf",
        sha256="c" * 64, now_ts=102,
    )
    ambiguity = (await handler(message("מה פרטי הקבלה איקאה?", "ambiguous"))).text
    assert "כמה מסמכים" in ambiguity and "999.00" not in ambiguity and "סודי" not in ambiguity
    runtime.archive.index.soft_delete(item.object_id, owner_key="u1", now_ts=103)
    runtime.archive.index.soft_delete(another.object_id, owner_key="u1", now_ts=103)
    assert "לא מצאתי" in (await handler(message("מה פרטי הקבלה איקאה?", "deleted"))).text
    assert runtime.archive.index.get(foreign.object_id, owner_key="u2")


@pytest.mark.asyncio
@pytest.mark.parametrize("change", ["user_disabled", "provider_disabled", "unlink", "relink", "scope"])
async def test_private_financial_dispatch_requires_the_current_enabled_actor_link(runtime, change):
    runtime.setup.upsert_provider(provider_key="waha", provider_type="waha", display_name="WAHA")
    runtime.setup.create_user(display_name="Owner", role="owner", user_key="u1")
    runtime.setup.link_identity(provider_key="waha", external_id="111@c.us", user_key="u1")
    actor = runtime.setup.identity_fingerprint("waha", "111@c.us")
    request = replace(message("מה פרטי הקבלה איקאה?"), chat_id="group@g.us", metadata={
        "sender_fingerprint": actor, "sender_fingerprint_scope": "waha",
    })
    reply = OutboundMessage("key", "waha", request.chat_id, request.message_id, "private", "prepared")
    assert await runtime._private_financial_reply_allowed(request, reply)
    if change == "user_disabled":
        runtime.setup.set_user_enabled("u1", False)
    elif change == "provider_disabled":
        runtime.setup.upsert_provider(
            provider_key="waha", provider_type="waha", display_name="WAHA", enabled=False,
        )
    elif change == "unlink":
        runtime.setup.unlink_identity(provider_key="waha", external_id="111@c.us")
    elif change == "relink":
        runtime.setup.unlink_identity(provider_key="waha", external_id="111@c.us")
        runtime.setup.create_user(display_name="Other", role="owner", user_key="u2")
        runtime.setup.link_identity(provider_key="waha", external_id="111@c.us", user_key="u2")
    else:
        request = replace(request, metadata={**request.metadata, "sender_fingerprint_scope": "other"})
    assert not await runtime._private_financial_reply_allowed(request, reply)


@pytest.mark.asyncio
async def test_older_private_inbox_rechecks_link_and_older_group_inbox_fails_closed(runtime):
    runtime.setup.upsert_provider(provider_key="waha", provider_type="waha", display_name="WAHA")
    runtime.setup.create_user(display_name="Owner", role="owner", user_key="u1")
    runtime.setup.link_identity(provider_key="waha", external_id="111@c.us", user_key="u1")
    request = replace(message("מה פרטי הקבלה איקאה?"), chat_id="111@c.us")
    reply = OutboundMessage("key", "waha", request.chat_id, request.message_id, "private", "prepared")
    assert await runtime._private_financial_reply_allowed(request, reply)
    group_request = replace(request, chat_id="group@g.us")
    assert not await runtime._private_financial_reply_allowed(group_request, reply)
    runtime.setup.unlink_identity(provider_key="waha", external_id="111@c.us")
    assert not await runtime._private_financial_reply_allowed(request, reply)
    # A static denial remains deliverable and contains no saved financial data.
    denied = replace(reply, text="אין הרשאה לקרוא את פרטי המסמך בארכיון.")
    assert await runtime._private_financial_reply_allowed(request, denied)
