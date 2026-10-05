from __future__ import annotations

import threading
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace

import pytest

from app.bobi_next.archive_mutations import ArchiveMutationService
from app.bobi_next.archive_store import ArchiveStore, sha256_hex
from app.bobi_next.authorization import ApprovalStore, RiskLevel, UserPolicy
from app.bobi_next.expense_commands import parse_expense_month, parse_expense_record
from app.bobi_next.expense_ledger import (
    ALREADY_RECORDED,
    EXPENSE_RECORDED,
    ExpenseLedger,
    expense_source_fields,
)
from app.bobi_next.pending_approval import PendingApprovalStore
from app.bobi_next.receipt_review import parse_receipt_review
from app.bobi_next.request_ledger import RequestLedger

RECORD = "רשום הוצאה מהקבלה של איקאה בקטגוריית בית"
REVIEW = "עדכן את פרטי הקבלה איקאה: סכום=123.45 ILS; ספק=איקאה; תאריך=2026-10-05"


def open_system(path):
    archive = ArchiveStore(path / "archive.db")
    return ArchiveMutationService(
        archive, RequestLedger(path / "requests.db"), PendingApprovalStore(path / "pending.db"),
        ApprovalStore(path / "approvals.db"), ExpenseLedger(archive.path),
    )


def close_system(service):
    service.expenses.close()
    service.archive.close()
    service.requests.close()
    service.pending.close()
    service.approvals.close()


@pytest.fixture
def system(tmp_path):
    result = open_system(tmp_path)
    yield result
    close_system(result)


def receipt(system, *, owner="u1", title="איקאה", content=b"receipt", metadata=None):
    return system.archive.register(
        owner_key=owner, kind="receipt", title=title, sha256=sha256_hex(content),
        metadata=metadata, now_ts=1000,
    )


def request(system, text=RECORD, *, key="expense", policy=None, now=1002, dry_run=False):
    command = parse_expense_record(text) or parse_receipt_review(text)
    assert command is not None
    return system.execute_command(
        command, request_id=key, user_key="u1", provider="waha", chat_id="chat",
        input_text=text, policy=policy or UserPolicy("u1"), now_ts=now, dry_run=dry_run,
    )


def confirm(system, *, key="confirmed", policy=None, now=1003, choice="approve", **kwargs):
    return system.continue_latest(
        confirmation_id=key, choice=choice, user_key="u1", provider="waha", chat_id="chat",
        policy=policy or UserPolicy("u1"), now_ts=now, **kwargs,
    )


def reviewed(system, *, text=REVIEW):
    item = receipt(system)
    request(system, text, key="review", now=1000)
    confirm(system, key="review-confirm", now=1001)
    return system.archive.get(item.object_id, owner_key="u1")


@pytest.mark.parametrize("text", [
    RECORD, "רשמי הוצאה מהקבלה איקאה בקטגוריה בית",
    "please record an expense from receipt IKEA in category home",
    "add expense from invoice IKEA in category home",
])
def test_expense_parser_requires_explicit_receipt_and_category(text):
    command = parse_expense_record(text)
    assert command.operation == "record_expense" and command.kind == "receipt"
    assert command.category in {"בית", "home"}


@pytest.mark.parametrize("text", [
    "אל " + RECORD, RECORD + "?", RECORD + " מחר", RECORD + " ואז שלם",
    'הוא אמר: ' + RECORD, '"' + RECORD + '"', "רשום הוצאה מזה בקטגוריית בית",
    "רשום הוצאה מהקבלה הזאת בקטגוריית בית", "רשום הוצאה מהקבלה איקאה",
    "רשום הוצאה לפי הקובץ בקטגוריית בית", "record expense from bill water in category home",
    "record expense from receipt IKEA in category home and pay it",
    RECORD + "\nכן", RECORD + "\u200b", RECORD + "*", RECORD + "x" * 81,
])
def test_expense_parser_rejects_implicit_quoted_deferred_or_multiple_authority(text):
    assert parse_expense_record(text) is None


def test_month_parser_uses_an_explicit_month():
    assert parse_expense_month("הצג הוצאות לחודש 2026-10") == "2026-10"
    assert parse_expense_month("show my expenses for month 2026-10") == "2026-10"
    for text in ("הצג הוצאות", "הצג הוצאות לחודש 2026-13", "list expenses for 0000-10"):
        assert parse_expense_month(text) is None


@pytest.mark.parametrize("review", [None, "עדכן את פרטי הקבלה איקאה: סכום=123.45 ILS"])
def test_ocr_or_partial_review_never_creates_an_expense_or_approval(system, review):
    item = receipt(system, metadata={"financial_document": {
        "fields": {"total_minor": 12345, "currency": "ILS", "merchant": "איקאה", "document_date": "2026-10-05"},
    }})
    if review:
        request(system, review, key="review", now=1000)
        confirm(system, key="review-confirm", now=1001)
    assert "החילוץ האוטומטי אינו מספיק" in request(system)
    assert system.expenses.for_source(owner_key="u1", sha256=item.sha256) is None
    assert system.pending.get(system._approval_id("expense")) is None


def test_forged_review_metadata_without_a_verified_review_receipt_is_rejected(system):
    digest = sha256_hex(b"receipt")
    receipt(system, metadata={"financial_review": {
        "schema_version": 1, "source": "explicit_user_approved_fields", "user_key": "u1",
        "media_sha256": digest, "fields": {
            "total_minor": 12345, "currency": "ILS", "merchant": "איקאה", "document_date": "2026-10-05",
        }, "request_id": "forged", "plan_hash": "forged",
    }})
    assert "החילוץ האוטומטי אינו מספיק" in request(system)
    assert system.pending.peek_latest(user_key="u1") is None


def test_exact_expense_approval_and_month_summary_leave_the_source_immutable(system):
    item = reviewed(system)
    policy = UserPolicy("u1", max_without_approval=RiskLevel.CRITICAL)
    prompt = request(system, policy=policy)
    assert "123.45 ILS" in prompt and "2026-10-05" in prompt and "קטגוריה: בית" in prompt
    assert "כן או לא" in prompt
    pending = system.pending.peek_latest(user_key="u1")
    assert pending.plans[0].domain == "expenses" and pending.plans[0].capability == "expenses.write"
    assert pending.plans[0].requires_confirmation
    assert system.expenses.for_source(owner_key="u1", sha256=item.sha256) is None
    assert confirm(system, policy=policy) == EXPENSE_RECORDED
    entry = system.expenses.for_source(owner_key="u1", sha256=item.sha256)
    assert (entry.amount_minor, entry.currency, entry.merchant, entry.category) == (12345, "ILS", "איקאה", "בית")
    assert entry.source_revision == item.revision and entry.source_review_request_id == "review"
    assert system.archive.get(item.object_id, owner_key="u1") == item
    assert "סכום: 123.45 ILS" in system.expenses.month_reply(owner_key="u1", month="2026-10")
    assert "אין הוצאות" in system.expenses.month_reply(owner_key="u2", month="2026-10")
    assert "אין הוצאות" in system.expenses.month_reply(owner_key="u1", month="2026-09")


@pytest.mark.parametrize("policy", [
    UserPolicy("u2"), UserPolicy("u1", can_approve=False),
    UserPolicy("u1", denied_capabilities=frozenset({"expenses.write"})),
    UserPolicy("u1", allowed_capabilities=frozenset({"expenses.write"})),
    UserPolicy("u1", allowed_domains=frozenset({"archive"})),
    UserPolicy("u1", denied_actions=frozenset({"expenses.record"})),
    UserPolicy("u1", denied_actions=frozenset({"archive.details"})),
])
def test_denied_expenses_never_create_records_or_pending_approvals(system, policy):
    item = reviewed(system)
    assert "כן או לא" not in request(system, policy=policy)
    assert system.pending.get(system._approval_id("expense")) is None
    assert system.expenses.for_source(owner_key="u1", sha256=item.sha256) is None


@pytest.mark.parametrize("change", ["read_policy", "write_policy", "can_approve", "state", "expiry"])
def test_confirmation_rechecks_source_and_current_read_write_permissions(system, change):
    item = reviewed(system)
    request(system)
    policy = UserPolicy("u1")
    if change == "read_policy":
        policy = replace(policy, denied_capabilities=frozenset({"archive.read"}))
    elif change == "write_policy":
        policy = replace(policy, denied_actions=frozenset({"expenses.record"}))
    elif change == "can_approve":
        policy = replace(policy, can_approve=False)
    elif change == "state":
        system.archive.move_category(item.object_id, owner_key="u1", category="new", now_ts=1003)
    assert "✅" not in confirm(system, policy=policy, now=1400 if change == "expiry" else 1003)
    assert system.expenses.for_source(owner_key="u1", sha256=item.sha256) is None


def test_source_edit_between_token_consumption_and_executor_is_still_blocked(system, monkeypatch):
    item = reviewed(system)
    request(system)
    consume = system.approvals.consume

    def racing_consume(**kwargs):
        result = consume(**kwargs)
        system.archive.soft_delete(item.object_id, owner_key="u1", now_ts=1003)
        return result

    monkeypatch.setattr(system.approvals, "consume", racing_consume)
    assert "לא נרשמה" in confirm(system)
    assert system.expenses.for_source(owner_key="u1", sha256=item.sha256) is None
    assert system.expenses.receipt("expense", owner_key="u1") is None


def test_expense_restart_and_crash_after_verified_commit_recover_without_reexecution(system, tmp_path, monkeypatch):
    item = reviewed(system)
    request(system)
    close_system(system)
    reopened = open_system(tmp_path)
    system.__dict__.update(reopened.__dict__)
    complete = system.pending.complete

    def crash(*args, **kwargs):
        raise RuntimeError("simulated_restart")

    monkeypatch.setattr(system.pending, "complete", crash)
    with pytest.raises(RuntimeError, match="simulated_restart"):
        confirm(system)
    entry = system.expenses.for_source(owner_key="u1", sha256=item.sha256)
    assert entry
    monkeypatch.setattr(system.pending, "complete", complete)
    # Even a later policy revocation cannot cause a repeated write during recovery.
    assert confirm(system, policy=UserPolicy("u1", can_approve=False)) == EXPENSE_RECORDED
    assert system.expenses.for_source(owner_key="u1", sha256=item.sha256) == entry
    assert request(system, key="duplicate") == ALREADY_RECORDED
    assert confirm(system) == EXPENSE_RECORDED


def test_two_exact_approvals_for_one_source_cannot_double_count_or_change_category(system):
    item = reviewed(system)
    request(system)
    first = system.pending.peek_latest(user_key="u1")
    request(system, RECORD.replace("בית", "ריהוט"), key="expense2", now=1003)
    second = system.pending.peek_latest(user_key="u1")
    args = {"choice": "approve", "user_key": "u1", "provider": "waha", "chat_id": "chat",
            "policy": UserPolicy("u1"), "now_ts": 1004}
    assert system.continue_exact(first.approval_request_id, **args) == EXPENSE_RECORDED
    assert system.continue_exact(second.approval_request_id, **args) == ALREADY_RECORDED
    entry = system.expenses.for_source(owner_key="u1", sha256=item.sha256)
    assert entry.category == "בית"
    assert "(1 הוצאה)" in system.expenses.month_reply(owner_key="u1", month="2026-10")


def test_denied_and_shadow_commands_do_not_search_or_claim_private_sources(system, monkeypatch):
    def forbidden_search(**kwargs):
        raise AssertionError("denied expense searched the archive")

    monkeypatch.setattr(system.archive, "search", forbidden_search)
    assert "אין הרשאה" in request(system, policy=UserPolicy("u1", denied_capabilities=frozenset({"archive.read"})))
    assert "Shadow" in request(system, dry_run=True)
    assert system.requests.get("expense") is None


def test_receipt_query_ambiguity_and_foreign_owners_do_not_create_an_expense(system):
    reviewed(system)
    receipt(system, owner="u2", title="איקאה סודי")
    receipt(system, title="איקאה אחר", content=b"another")
    reply = request(system)
    assert "כמה מסמכים" in reply and "סודי" not in reply and "123.45" not in reply
    assert system.pending.get(system._approval_id("expense")) is None


@pytest.mark.parametrize("mutation", ["float", "bool", "owner", "no_confirmation", "capability", "amount"])
def test_executor_rejects_forged_expense_plan_fields(system, mutation):
    item = reviewed(system)
    request(system)
    plan = system.pending.peek_latest(user_key="u1").plans[0]
    if mutation in {"float", "bool", "amount", "owner"}:
        data = {**plan.data, "expense_fields": dict(plan.data["expense_fields"])}
        if mutation == "owner":
            data["owner_key"] = "u2"
        else:
            data["expense_fields"]["total_minor"] = {"float": 12345.0, "bool": True, "amount": 99999}[mutation]
        plan = replace(plan, data=data)
    elif mutation == "no_confirmation":
        plan = replace(plan, requires_confirmation=False)
    else:
        plan = replace(plan, capability="archive.write")
    with pytest.raises(ValueError):
        system._execute(plan, user_key="u1", now_ts=1003)
    assert system.expenses.for_source(owner_key="u1", sha256=item.sha256) is None


def test_direct_service_call_cannot_substitute_a_command_without_current_authority(system):
    item = reviewed(system)
    command = parse_expense_record(RECORD)
    reply = system.execute_command(
        command, request_id="forged", user_key="u1", provider="waha", chat_id="chat",
        input_text="תסביר את הקבלה", policy=UserPolicy("u1"), now_ts=1002,
    )
    assert "הוראה מפורשת" in reply and system.requests.get("forged") is None
    assert system.expenses.for_source(owner_key="u1", sha256=item.sha256) is None


def test_readback_failure_rolls_back_both_expense_and_receipt(system, monkeypatch):
    item = reviewed(system)
    request(system)
    lookup = system.expenses.for_source
    calls = 0

    def failed_readback(**kwargs):
        nonlocal calls
        calls += 1
        return None if calls == 2 else lookup(**kwargs)

    monkeypatch.setattr(system.expenses, "for_source", failed_readback)
    with pytest.raises(RuntimeError, match="expense_not_verified"):
        confirm(system)
    assert lookup(owner_key="u1", sha256=item.sha256) is None
    assert system.expenses.receipt("expense", owner_key="u1") is None


def test_month_summary_keeps_currencies_separate_and_covers_all_rows(system):
    # Populate historical audit entries directly, without testing a mirrored writer.
    with system.expenses._db:
        for i in range(23):
            system.expenses._db.execute(
                "INSERT INTO expense_records VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (str(i), "u1", str(i), sha256_hex(str(i).encode()), 1, "review", "merchant", "", "2026-10-05",
                 1 if i < 22 else 100, "ILS" if i < 22 else "USD", "home", 1000 + i),
            )
    reply = system.expenses.month_reply(owner_key="u1", month="2026-10")
    assert "0.22 ILS (22 הוצאות)" in reply and "1.00 USD (1 הוצאה)" in reply
    assert "20 ההוצאות האחרונות" in reply


@pytest.mark.parametrize("amount", ["0", "-1"])
def test_zero_and_refunds_require_a_separate_supported_contract(system, amount):
    item = reviewed(system, text=REVIEW.replace("123.45", amount))
    assert "סכום חיובי" in request(system)
    assert system.expenses.for_source(owner_key="u1", sha256=item.sha256) is None


def test_review_changes_and_archive_deletion_do_not_silently_rewrite_recorded_expenses(system):
    item = reviewed(system)
    request(system)
    confirm(system)
    entry = system.expenses.for_source(owner_key="u1", sha256=item.sha256)
    request(system, REVIEW.replace("123.45", "777.00"), key="new-review", now=1004)
    confirm(system, key="new-review-confirm", now=1005)
    assert request(system, key="duplicate", now=1006) == ALREADY_RECORDED
    system.archive.soft_delete(item.object_id, owner_key="u1", now_ts=1007)
    assert system.expenses.for_source(owner_key="u1", sha256=item.sha256) == entry
    assert "123.45 ILS" in system.expenses.month_reply(owner_key="u1", month="2026-10")


def test_concurrent_sqlite_executors_commit_one_verified_expense_for_the_same_digest(system):
    item = reviewed(system)
    fields = expense_source_fields(item.metadata, owner_key="u1", sha256=item.sha256)
    barrier = threading.Barrier(2, timeout=10)

    def execute(index):
        ledger = ExpenseLedger(system.archive.path)
        try:
            barrier.wait()
            return ledger.record_once(
                request_id=f"concurrent-{index}", owner_key="u1", plan_hash=f"plan-{index}",
                object_id=item.object_id, sha256=item.sha256, revision=item.revision, fields=fields,
                review_request_id="review", category=f"category-{index}", now_ts=1003,
            )
        finally:
            ledger.close()

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(execute, (1, 2)))
    assert sum(result.duplicate for result in results) == 1
    assert results[0].record == results[1].record
    assert "123.45 ILS (1 הוצאה)" in system.expenses.month_reply(owner_key="u1", month="2026-10")
