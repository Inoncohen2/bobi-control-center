from __future__ import annotations

from dataclasses import replace

import pytest

from app.bobi_next.archive_mutation_commands import parse_archive_mutation
from app.bobi_next.archive_mutations import ArchiveMutationService
from app.bobi_next.archive_store import ArchiveStore, sha256_hex
from app.bobi_next.authorization import ApprovalStore, RiskLevel, UserPolicy
from app.bobi_next.pending_approval import PendingApprovalStore
from app.bobi_next.request_ledger import RequestLedger


@pytest.fixture
def system(tmp_path):
    archive = ArchiveStore(tmp_path / "archive.db")
    requests = RequestLedger(tmp_path / "requests.db")
    pending = PendingApprovalStore(tmp_path / "pending.db")
    approvals = ApprovalStore(tmp_path / "approvals.db")
    service = ArchiveMutationService(archive, requests, pending, approvals)
    yield service
    archive.close()
    requests.close()
    pending.close()
    approvals.close()


def record(system, *, owner="u1", title="ביטוח", category="ביטוחים", content=b"policy"):
    return system.archive.register(
        owner_key=owner,
        kind="document",
        title=title,
        category=category,
        sha256=sha256_hex(content),
        storage_uri="private://immutable",
        size_bytes=len(content),
        filename=f"{title}.pdf",
        mime_type="application/pdf",
        now_ts=1000,
    )


def command(system, text, *, request="r1", policy=None, now=1000, dry_run=False):
    parsed = parse_archive_mutation(text)
    assert parsed is not None
    return system.execute_command(
        parsed,
        request_id=request,
        user_key="u1",
        provider="waha",
        chat_id="private-chat",
        input_text=text,
        policy=policy or UserPolicy("u1"),
        now_ts=now,
        dry_run=dry_run,
    )


def confirm(
    system,
    *,
    confirmation="c1",
    choice="approve",
    policy=None,
    now=1001,
    user="u1",
    provider="waha",
    chat="private-chat",
    dry_run=False,
):
    return system.continue_latest(
        confirmation_id=confirmation,
        choice=choice,
        user_key=user,
        provider=provider,
        chat_id=chat,
        policy=policy or UserPolicy(user),
        now_ts=now,
        dry_run=dry_run,
    )


@pytest.mark.parametrize(
    "text",
    [
        "אל תמחק את המסמך ביטוח",
        "הוא אמר: מחק את המסמך ביטוח",
        '"מחק את המסמך ביטוח"',
        "מחק את המסמך ביטוח?",
        "מחק את המסמך ביטוח מחר",
        "מחק את המסמך ביטוח ואז כבה אור",
        "מחק את זה",
        "מחק את המסמך הזה",
        "מחק את המסמכים",
        "מחק את האוטומציה ביטוח",
        "delete document insurance if expired",
        "delete document insurance\nturn off lights",
        "move document insurance",
        "restore it",
        "move document insurance to folder " + "x" * 161,
        "delete document " + "x" * 301,
    ],
)
def test_no_implicit_or_non_direct_archive_authority(text):
    assert parse_archive_mutation(text) is None


def test_move_updates_only_owner_metadata_and_survives_replay(system, tmp_path):
    item = record(system)
    other = record(system, owner="u2")
    text = "העבר את המסמך ביטוח לתיקיית רכב"
    assert command(system, text) == "✅ העברתי את המסמך לתיקיית רכב."
    moved = system.archive.get(item.object_id, owner_key="u1")
    assert moved.category == "רכב" and moved.revision == 1
    assert (moved.storage_uri, moved.sha256) == (item.storage_uri, item.sha256)
    system.archive.close()
    system.archive = ArchiveStore(tmp_path / "archive.db")
    assert command(system, text) == "✅ העברתי את המסמך לתיקיית רכב."
    assert system.archive.get(item.object_id, owner_key="u1").revision == 1
    assert system.archive.get(other.object_id, owner_key="u2").category == "ביטוחים"


def test_ambiguous_documents_do_not_mutate(system):
    first = record(system, title="ביטוח ינואר")
    second = record(system, title="ביטוח פברואר", content=b"second")
    assert "כמה מסמכים" in command(system, "העבר את המסמך ביטוח לתיקיית רכב")
    assert system.archive.get(first.object_id, owner_key="u1").revision == 0
    assert system.archive.get(second.object_id, owner_key="u1").revision == 0


def test_delete_requires_exact_single_use_approval_and_restore_is_explicit(system):
    item = record(system)
    assert "כן או לא" in command(system, "מחק את המסמך ביטוח")
    assert system.archive.get(item.object_id, owner_key="u1")
    assert "סל המחזור" in confirm(system)
    assert system.archive.get(item.object_id, owner_key="u1") is None
    assert system.archive.get(item.object_id, owner_key="u1", include_deleted=True).revision == 1
    assert "סל המחזור" in confirm(system)
    assert system.archive.get(item.object_id, owner_key="u1", include_deleted=True).revision == 1
    assert "שחזרתי" in command(system, "שחזר את המסמך ביטוח", request="restore")
    assert system.archive.get(item.object_id, owner_key="u1").revision == 2
    grants = system.approvals._db.execute("SELECT consumed_ts FROM approval_grants").fetchall()
    assert len(grants) == 1 and grants[0]["consumed_ts"] == 1001


def test_old_yes_cannot_confirm_a_new_pending_operation(system):
    first = record(system)
    second = record(system, title="רישום", category="רישומים", content=b"second")
    command(system, "מחק את המסמך ביטוח")
    confirm(system)
    command(system, "מחק את המסמך רישום", request="r2", now=1002)
    confirm(system, now=1003)  # replay of the exact old provider message
    assert system.archive.get(second.object_id, owner_key="u1")
    assert system.archive.get(first.object_id, owner_key="u1") is None
    confirm(system, confirmation="c2", now=1003)
    assert system.archive.get(second.object_id, owner_key="u1") is None


@pytest.mark.parametrize("change", ["state", "permission", "expiry", "channel", "provider"])
def test_approval_rechecks_current_state_permissions_expiry_and_channel(system, change):
    item = record(system)
    command(system, "מחק את המסמך ביטוח")
    options = {}
    if change == "state":
        system.archive.move_category(item.object_id, owner_key="u1", category="חדש", now_ts=1000)
    if change == "permission":
        options["policy"] = UserPolicy("u1", denied_actions=frozenset({"archive.delete"}))
    if change == "expiry":
        options["now"] = 1301
    if change == "channel":
        options["chat"] = "another-chat"
    if change == "provider":
        options["provider"] = "another-provider"
    response = confirm(system, **options)
    assert "✅" not in response
    assert system.archive.get(item.object_id, owner_key="u1")


def test_wrong_user_cannot_claim_or_expire_another_users_prompt(system):
    item = record(system)
    command(system, "מחק את המסמך ביטוח")
    pending = system.pending.peek_latest(user_key="u1")
    response = system.continue_exact(
        pending.approval_request_id,
        choice="approve",
        user_key="u2",
        provider="waha",
        chat_id="private-chat",
        policy=UserPolicy("u2"),
        now_ts=9999,
    )
    assert "אינו תקף" in response
    assert system.pending.get(pending.approval_request_id).state == "pending"
    assert system.archive.get(item.object_id, owner_key="u1")


def test_shadow_and_denied_policy_never_mutate_or_create_approval(system):
    item = record(system)
    assert "Shadow" in command(system, "מחק את המסמך ביטוח", dry_run=True)
    assert system.pending.peek_latest(user_key="u1") is None
    assert system.requests.get("r1") is None
    assert "אין הרשאה" in command(
        system,
        "העבר את המסמך ביטוח לתיקיית רכב",
        policy=UserPolicy("u1", denied_capabilities=frozenset({"archive.write"})),
    )
    assert system.archive.get(item.object_id, owner_key="u1").revision == 0


def test_conservative_policy_can_require_move_approval(system):
    item = record(system)
    policy = replace(UserPolicy("u1"), max_without_approval=RiskLevel.LOW)
    assert "כן או לא" in command(system, "העבר את המסמך ביטוח לתיקיית רכב", policy=policy)
    assert system.archive.get(item.object_id, owner_key="u1").category == "ביטוחים"
    assert "רכב" in confirm(system, policy=policy)
    assert system.archive.get(item.object_id, owner_key="u1").category == "רכב"


def test_reject_is_terminal_and_a_later_yes_does_not_reverse_it(system):
    item = record(system)
    command(system, "מחק את המסמך ביטוח")
    assert "בוטל" in confirm(system, choice="reject")
    assert "לא בוצעה" in confirm(system)
    assert system.archive.get(item.object_id, owner_key="u1")


def test_crash_after_atomic_mutation_recovers_without_second_execution(system, monkeypatch):
    item = record(system)
    command(system, "מחק את המסמך ביטוח")
    original = system.pending.complete

    def crash(*args, **kwargs):
        raise RuntimeError("crash after SQL commit")

    monkeypatch.setattr(system.pending, "complete", crash)
    with pytest.raises(RuntimeError):
        confirm(system)
    monkeypatch.setattr(system.pending, "complete", original)
    assert "סל המחזור" in confirm(system)
    assert system.archive.get(item.object_id, owner_key="u1", include_deleted=True).revision == 1
    assert system.pending.peek_latest(user_key="u1") is None


def test_compare_and_swap_and_exact_receipt_reject_stale_and_retargeted_plans(system):
    item = record(system)
    other = ArchiveStore(system.archive.path)
    other.move_category(item.object_id, owner_key="u1", category="changed", now_ts=1000)
    with pytest.raises(ValueError, match="archive_state_changed"):
        system.archive.apply_mutation_once(
            request_id="direct",
            owner_key="u1",
            plan_hash="first-plan",
            object_id=item.object_id,
            operation="delete",
            expected_revision=item.revision,
            now_ts=1000,
        )
    command(system, "העבר את המסמך ביטוח לתיקיית רכב")
    with pytest.raises(ValueError, match="archive_request_plan_changed"):
        system.archive.apply_mutation_once(
            request_id="r1",
            owner_key="u1",
            plan_hash="other-plan",
            object_id=item.object_id,
            operation="delete",
            expected_revision=2,
            now_ts=1000,
        )
    other.close()


def test_restore_does_not_create_a_second_active_copy(system):
    item = record(system)
    command(system, "מחק את המסמך ביטוח")
    confirm(system)
    replacement = record(system, title="ביטוח חדש")
    assert "✅" not in command(system, "שחזר את המסמך ביטוח", request="restore")
    assert system.archive.get(item.object_id, owner_key="u1") is None
    assert system.archive.get(replacement.object_id, owner_key="u1")


def test_search_treats_wildcards_as_literal_text(system):
    record(system)
    assert system.archive.search(owner_key="u1", query="%") == ()
    assert system.archive.search(owner_key="u1", query="_") == ()
