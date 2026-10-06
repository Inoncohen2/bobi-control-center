from __future__ import annotations

import json
import sqlite3
import threading
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, replace

import pytest

from app.bobi_next.authorization import RiskLevel, UserPolicy
from app.bobi_next.expense_commands import (
    ExpenseMutationCommand,
    parse_expense_mutation,
    parse_manual_expense,
)
from app.bobi_next.expense_ledger import (
    ALREADY_RECORDED,
    EXPENSE_DELETED,
    EXPENSE_RECORDED,
    EXPENSE_RESTORED,
    EXPENSE_UPDATED,
    ExpenseLedger,
    expense_state_guard,
    manual_expense_id,
)
from tests.test_bobi_next_expenses import (
    MANUAL,
    close_system,
    confirm,
    open_system,
    request,
    reviewed,
)
from tests.test_bobi_next_expenses import (
    system as system,
)

EDIT = "עדכן את ההוצאה של מכולת 2026-10-05: סכום=40 ILS; קטגוריה=בית"
DELETE = "מחק את ההוצאה של מכולת 2026-10-05"
RESTORE = "שחזר את ההוצאה של מכולת 2026-10-05"
EXPENSE_POLICY = UserPolicy(
    "u1", allowed_capabilities=frozenset({"expenses.read", "expenses.write"}),
    allowed_domains=frozenset({"expenses"}), max_without_approval=RiskLevel.CRITICAL,
)


def recorded(system):
    request(system, MANUAL)
    assert confirm(system) == EXPENSE_RECORDED
    return system.expenses.search(owner_key="u1", query="מכולת")[0]


def mutate(system, text=EDIT, *, key="edit", now=1004, policy=EXPENSE_POLICY):
    return request(system, text, key=key, now=now, policy=policy)


@pytest.mark.parametrize(("text", "operation"), [
    (EDIT, "edit"), (EDIT.replace("עדכן", "תקני"), "edit"),
    ("update expense shop 2026-10-05: category=home", "edit"),
    (DELETE, "delete"), ("please remove the expense from shop", "delete"),
    (RESTORE, "restore"), ("restore expense shop", "restore"),
])
def test_expense_mutation_parser_requires_current_explicit_target_and_typed_patch(text, operation):
    command = parse_expense_mutation(text)
    assert isinstance(command, ExpenseMutationCommand)
    assert command.operation == operation


@pytest.mark.parametrize("text", [
    "אל " + EDIT, EDIT + "?", EDIT + " מחר", EDIT + " ואז שלם", EDIT + "\u200b",
    '"' + DELETE + '"', "הוא אמר: " + DELETE, DELETE + "\nכן", DELETE + ": סכום=1 ILS",
    "מחק את ההוצאה זאת!", "delete expense this.", "restore expense it", "מחק את ההוצאה %",
    "עדכן את ההוצאה מכולת", "עדכן את ההוצאה מכולת: לפי הקובץ",
    "עדכן את ההוצאה מכולת: סכום=0 ILS", "עדכן את ההוצאה מכולת: סכום=-1 ILS",
    "עדכן את ההוצאה מכולת: סכום=12.345 ILS", "עדכן את ההוצאה מכולת: סכום=12.34",
    "עדכן את ההוצאה מכולת: סכום=12 AUD", "עדכן את ההוצאה מכולת: מטבע=USD",
    "עדכן את ההוצאה מכולת: מס=1 ILS", "עדכן את ההוצאה מכולת: due date=2026-10-05",
    "עדכן את ההוצאה מכולת: תאריך=היום", "עדכן את ההוצאה מכולת: תאריך=2026-02-30",
    "עדכן את ההוצאה מכולת: סכום=1 ILS; total=2 ILS",
    "עדכן את ההוצאה מכולת: קטגוריה=מזון; category=home",
    "עדכן את ההוצאה מכולת: ספק=https://private.invalid",
])
def test_expense_mutation_parser_rejects_other_authority_and_untyped_fields(text):
    assert parse_expense_mutation(text) is None


def test_edit_delete_restore_are_exact_approved_audited_and_omit_deleted_totals(system):
    entry = recorded(system)
    original_receipt = system.expenses.receipt("expense", owner_key="u1")
    prompt = mutate(system)
    assert "40.00 ILS" in prompt and "בית" in prompt and "כן או לא" in prompt
    assert system.expenses.get(entry.expense_id, owner_key="u1") == entry
    assert confirm(system, key="edit-yes", now=1005, policy=EXPENSE_POLICY) == EXPENSE_UPDATED
    changed = system.expenses.get(entry.expense_id, owner_key="u1")
    assert changed.amount_minor == 4000 and changed.category == "בית" and changed.revision == 1
    audit = system.expenses.mutation_receipt("edit", owner_key="u1")
    assert audit.before == entry and audit.record == changed and audit.operation == "edit"
    assert system.expenses.receipt("expense", owner_key="u1") == original_receipt
    assert "40.00 ILS (1 הוצאה)" in system.expenses.month_reply(owner_key="u1", month="2026-10")
    assert mutate(system, DELETE, key="delete", now=1006).endswith("כן או לא.")
    assert confirm(system, key="delete-yes", now=1007, policy=EXPENSE_POLICY) == EXPENSE_DELETED
    deleted = system.expenses.get(entry.expense_id, owner_key="u1")
    assert deleted.revision == 2 and deleted.deleted_ts == 1007
    assert system.expenses.search(owner_key="u1", query="מכולת") == ()
    assert system.expenses.search(owner_key="u1", query="מכולת", deleted=True) == (deleted,)
    assert "אין הוצאות" in system.expenses.month_reply(owner_key="u1", month="2026-10")
    assert mutate(system, RESTORE, key="restore", now=1008).endswith("כן או לא.")
    assert confirm(system, key="restore-yes", now=1009, policy=EXPENSE_POLICY) == EXPENSE_RESTORED
    restored = system.expenses.get(entry.expense_id, owner_key="u1")
    assert restored.deleted_ts is None and restored.revision == 3 and restored.amount_minor == 4000
    assert system.expenses.get(entry.expense_id, owner_key="u2") is None
    assert mutate(system, DELETE, key="delete", now=1010) == EXPENSE_DELETED
    assert confirm(system, key="delete-yes", now=1010) == EXPENSE_DELETED
    assert system.expenses.get(entry.expense_id, owner_key="u1") == restored


@pytest.mark.parametrize("policy", [
    UserPolicy("u2"), UserPolicy("u1", allowed_domains=frozenset({"archive"})),
    UserPolicy("u1", allowed_capabilities=frozenset({"expenses.write"})),
    UserPolicy("u1", allowed_capabilities=frozenset({"expenses.read"})),
    UserPolicy("u1", denied_capabilities=frozenset({"expenses.read"})),
    UserPolicy("u1", denied_capabilities=frozenset({"expenses.write"})),
    UserPolicy("u1", denied_actions=frozenset({"edit"})),
    UserPolicy("u1", denied_actions=frozenset({"expenses.edit"})),
    UserPolicy("u1", denied_actions=frozenset({"expenses.details"})),
])
def test_mutation_permissions_are_checked_before_any_target_lookup(system, monkeypatch, policy):
    entry = recorded(system)

    def forbidden_search(**kwargs):
        raise AssertionError("Denied expense target lookup")

    monkeypatch.setattr(system.expenses, "search", forbidden_search)
    assert mutate(system, policy=policy) == "אין הרשאה לשנות את יומן ההוצאות."
    assert system.pending.get(system._approval_id("edit")) is None
    assert system.expenses.get(entry.expense_id, owner_key="u1") == entry


def test_target_resolution_is_private_and_never_selects_one_ambiguous_expense(system):
    first = recorded(system)
    command = parse_manual_expense(MANUAL.replace("מכולת", "ספק פרטי"))
    system.expenses.record_manual_once(
        request_id="private", owner_key="u2", plan_hash="private-plan",
        expense_id=manual_expense_id(owner_key="u2", request_id="private"),
        fields=command.financial_fields, category=command.category, now_ts=1000,
    )
    assert mutate(system, DELETE.replace("מכולת", "ספק פרטי")) == (
        "לא מצאתי הוצאה שמתאימה לבקשה הזאת."
    )
    request(system, MANUAL.replace("2026-10-05", "2026-10-06"), key="second", now=1004)
    confirm(system, key="second-yes", now=1005)
    ambiguous = mutate(system, "מחק את ההוצאה מכולת", key="ambiguous", now=1006)
    assert "כמה הוצאות" in ambiguous and "2026-10-05" in ambiguous and "2026-10-06" in ambiguous
    assert system.pending.get(system._approval_id("ambiguous")) is None
    assert system.expenses.get(first.expense_id, owner_key="u1").revision == 0


def test_receipt_expense_edit_preserves_archive_source_digest_and_original_review(system):
    source = reviewed(system)
    request(system)
    confirm(system)
    original = system.expenses.for_source(owner_key="u1", sha256=source.sha256)
    mutate(system, "עדכן את ההוצאה איקאה: סכום=5 USD; תאריך=2026-11-01", now=1004)
    assert confirm(system, key="edit-yes", now=1005, policy=EXPENSE_POLICY) == EXPENSE_UPDATED
    changed = system.expenses.get(original.expense_id, owner_key="u1")
    assert changed.amount_minor == 500 and changed.currency == "USD"
    assert changed.source_kind == "receipt" and changed.source_sha256 == source.sha256
    assert changed.source_object_id == source.object_id
    assert changed.source_review_request_id == original.source_review_request_id
    assert system.archive.get(source.object_id, owner_key="u1") == source
    assert system.expenses.receipt("expense", owner_key="u1").record == original
    assert "אין הוצאות" in system.expenses.month_reply(owner_key="u1", month="2026-10")
    assert "5.00 USD" in system.expenses.month_reply(owner_key="u1", month="2026-11")
    mutate(system, "מחק את ההוצאה איקאה", key="delete", now=1006)
    assert confirm(system, key="delete-yes", now=1007, policy=EXPENSE_POLICY) == EXPENSE_DELETED
    assert request(system, key="same-deleted-source", now=1008) == ALREADY_RECORDED
    assert system.pending.get(system._approval_id("same-deleted-source")) is None
    assert "אין הוצאות" in system.expenses.month_reply(owner_key="u1", month="2026-11")
    assert system.archive.get(source.object_id, owner_key="u1") == source


@pytest.mark.parametrize("revocation", ["read", "write", "action", "approve"])
def test_restart_rechecks_current_permissions_and_does_not_repeat_mutation(
    system, tmp_path, revocation,
):
    entry = recorded(system)
    mutate(system)
    close_system(system)
    system.__dict__.update(open_system(tmp_path).__dict__)
    kwargs = {
        "read": {"denied_capabilities": frozenset({"expenses.read"})},
        "write": {"denied_capabilities": frozenset({"expenses.write"})},
        "action": {"denied_actions": frozenset({"expenses.edit"})},
        "approve": {"can_approve": False},
    }[revocation]
    assert "לא שונה" in confirm(system, key="edit-yes", now=1005, policy=UserPolicy("u1", **kwargs))
    assert system.expenses.get(entry.expense_id, owner_key="u1") == entry
    assert system.expenses.mutation_receipt("edit", owner_key="u1") is None


def test_execution_receipt_recovers_restart_after_write_without_reapplying_patch(system, tmp_path):
    entry = recorded(system)
    mutate(system)
    execute = system._execute

    def execute_then_crash(*args, **kwargs):
        execute(*args, **kwargs)
        raise RuntimeError("restart after commit")

    system._execute = execute_then_crash
    with pytest.raises(RuntimeError, match="restart after commit"):
        confirm(system, key="edit-yes", now=1005)
    system._execute = execute
    close_system(system)
    system.__dict__.update(open_system(tmp_path).__dict__)
    assert confirm(system, key="edit-yes", now=1006, policy=UserPolicy("u1", can_approve=False)) == (
        EXPENSE_UPDATED
    )
    assert system.expenses.get(entry.expense_id, owner_key="u1").revision == 1
    assert system.expenses.mutation_receipt("edit", owner_key="u1").before == entry


def test_executor_rechecks_snapshot_under_sqlite_lock_after_approval(system, monkeypatch):
    entry = recorded(system)
    mutate(system, DELETE, key="delete")
    execute = system._execute

    def race(plan, **kwargs):
        system.expenses.apply_mutation_once(
            request_id="other", owner_key="u1", plan_hash="approved-other-plan",
            expense_id=entry.expense_id, operation="edit", expected_guard=expense_state_guard(entry),
            fields={"total_minor": 100, "currency": "ILS"}, now_ts=1005,
        )
        return execute(plan, **kwargs)

    monkeypatch.setattr(system, "_execute", race)
    assert "לא שונה" in confirm(system, key="delete-yes", now=1005)
    changed = system.expenses.get(entry.expense_id, owner_key="u1")
    assert changed.revision == 1 and changed.deleted_ts is None and changed.amount_minor == 100
    assert system.expenses.mutation_receipt("delete", owner_key="u1") is None


def test_delete_restore_cannot_reuse_an_approval_with_same_visible_values(system):
    entry = recorded(system)
    mutate(system)
    ledger = system.expenses
    deleted = ledger.apply_mutation_once(
        request_id="other-delete", owner_key="u1", plan_hash="delete-plan",
        expense_id=entry.expense_id, operation="delete", expected_guard=expense_state_guard(entry),
        now_ts=1005,
    ).record
    restored = ledger.apply_mutation_once(
        request_id="other-restore", owner_key="u1", plan_hash="restore-plan",
        expense_id=entry.expense_id, operation="restore", expected_guard=expense_state_guard(deleted),
        now_ts=1006,
    ).record
    assert restored.amount_minor == entry.amount_minor and restored.deleted_ts is None
    assert "לא שונה" in confirm(system, key="edit-yes", now=1007)
    assert ledger.get(entry.expense_id, owner_key="u1") == restored


@pytest.mark.parametrize("patch", [
    {"total_minor": 1.0, "currency": "ILS"}, {"total_minor": 0, "currency": "ILS"},
    {"total_minor": -1, "currency": "ILS"}, {"currency": "USD"}, {"merchant": ""},
    {"document_date": "2026-02-30"}, {"tax_minor": 1, "currency": "ILS"}, False, [],
])
def test_invalid_executor_patch_rolls_back_entry_and_receipt(system, patch):
    entry = recorded(system)
    with pytest.raises(ValueError):
        system.expenses.apply_mutation_once(
            request_id="invalid", owner_key="u1", plan_hash="plan", expense_id=entry.expense_id,
            operation="edit", expected_guard=expense_state_guard(entry), fields=patch,
            category="changed", now_ts=1005,
        )
    assert system.expenses.get(entry.expense_id, owner_key="u1") == entry
    assert system.expenses.mutation_receipt("invalid", owner_key="u1") is None


@pytest.mark.parametrize("same_request", [True, False])
def test_concurrent_exact_snapshot_writers_only_apply_one_mutation(system, same_request):
    entry = recorded(system)
    barrier = threading.Barrier(2, timeout=10)

    def execute(index):
        ledger = ExpenseLedger(system.archive.path)
        try:
            barrier.wait()
            return ledger.apply_mutation_once(
                request_id="same" if same_request else str(index), owner_key="u1", plan_hash="plan",
                expense_id=entry.expense_id, operation="delete",
                expected_guard=expense_state_guard(entry), now_ts=1005,
            )
        except ValueError as exc:
            return str(exc)
        finally:
            ledger.close()

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(execute, (1, 2)))
    assert system.expenses.get(entry.expense_id, owner_key="u1").revision == 1
    if same_request:
        assert results[0] == results[1]
    else:
        assert sum(result == "expense_state_changed" for result in results) == 1


def test_failed_audit_readback_rolls_back_the_mutation_and_receipt(system, monkeypatch):
    entry = recorded(system)
    original = system.expenses.mutation_receipt

    def missing_readback(request_id, *, owner_key):
        if request_id == "audit-failure":
            return None
        return original(request_id, owner_key=owner_key)

    monkeypatch.setattr(system.expenses, "mutation_receipt", missing_readback)
    with pytest.raises(RuntimeError, match="expense_mutation_receipt_not_verified"):
        system.expenses.apply_mutation_once(
            request_id="audit-failure", owner_key="u1", plan_hash="plan",
            expense_id=entry.expense_id, operation="delete", expected_guard=expense_state_guard(entry),
            now_ts=1005,
        )
    assert system.expenses.get(entry.expense_id, owner_key="u1") == entry
    assert original("audit-failure", owner_key="u1") is None


def test_request_identity_cannot_be_reused_across_creation_or_changed_mutation_plan(system):
    entry = recorded(system)
    kwargs = {
        "owner_key": "u1", "plan_hash": "approved-plan", "expense_id": entry.expense_id,
        "operation": "delete", "expected_guard": expense_state_guard(entry), "now_ts": 1005,
    }
    with pytest.raises(ValueError, match="expense_request_operation_changed"):
        system.expenses.apply_mutation_once(request_id="expense", **kwargs)
    receipt = system.expenses.apply_mutation_once(request_id="delete", **kwargs)
    with pytest.raises(ValueError, match="expense_request_plan_changed"):
        system.expenses.apply_mutation_once(request_id="delete", **{**kwargs, "plan_hash": "new"})
    with pytest.raises(ValueError, match="expense_request_owner_mismatch"):
        system.expenses.mutation_receipt("delete", owner_key="u2")
    command = parse_manual_expense(MANUAL)
    with pytest.raises(ValueError, match="expense_request_operation_changed"):
        system.expenses.record_manual_once(
            request_id="delete", owner_key="u1", plan_hash="new-creation",
            expense_id=manual_expense_id(owner_key="u1", request_id="delete"),
            fields=command.financial_fields, category=command.category, now_ts=1006,
        )
    assert system.expenses.get(entry.expense_id, owner_key="u1") == receipt.record


def test_v2_manual_upgrade_preserves_null_provenance_and_old_json_receipt(system, tmp_path):
    entry = recorded(system)
    fields = asdict(entry)
    for name in ("revision", "deleted_ts", "updated_ts"):
        fields.pop(name)
    path = tmp_path / "v2.db"
    with sqlite3.connect(path) as db:
        # Exact shipped v2 shape: nullable manual digest, owner/SHA uniqueness,
        # source-kind checks, no mutation revision/tombstone/audit table yet.
        db.execute("""CREATE TABLE expense_records (
            expense_id TEXT PRIMARY KEY,owner_key TEXT NOT NULL,source_object_id TEXT NOT NULL,
            source_sha256 TEXT,source_revision INTEGER NOT NULL,
            source_review_request_id TEXT NOT NULL,merchant TEXT NOT NULL,document_number TEXT NOT NULL,
            document_date TEXT NOT NULL,amount_minor INTEGER NOT NULL CHECK(amount_minor>0),
            currency TEXT NOT NULL CHECK(currency IN ('ILS','USD','EUR','GBP')),
            category TEXT NOT NULL,created_ts INTEGER NOT NULL,
            source_kind TEXT NOT NULL DEFAULT 'receipt' CHECK(source_kind IN ('receipt','manual')),
            UNIQUE(owner_key,source_sha256),
            CHECK((source_kind='receipt' AND source_sha256 IS NOT NULL AND length(source_sha256)=64)
                OR (source_kind='manual' AND source_sha256 IS NULL AND source_object_id=''
                    AND source_revision=0 AND source_review_request_id=''))
        )""")
        db.execute("INSERT INTO expense_records VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                   tuple(fields.values()))
        db.execute("""CREATE TABLE expense_receipts (
            request_id TEXT PRIMARY KEY,owner_key TEXT NOT NULL,plan_hash TEXT NOT NULL,
            record_json TEXT NOT NULL,duplicate INTEGER NOT NULL
        )""")
        db.execute("INSERT INTO expense_receipts VALUES(?,?,?,?,?)",
                   ("expense", "u1", "old-plan", json.dumps(fields), 0))
    for _ in range(2):
        ledger = ExpenseLedger(path)
        try:
            assert ledger.get(entry.expense_id, owner_key="u1") == entry
            assert ledger.receipt("expense", owner_key="u1").record == entry
            assert ledger.get(entry.expense_id, owner_key="u1").source_sha256 is None
        finally:
            ledger.close()


def test_shadow_and_forged_current_authority_do_not_create_mutation_pending(system):
    entry = recorded(system)
    assert "Shadow" in request(system, EDIT, key="shadow", dry_run=True)
    command = parse_expense_mutation(EDIT)
    assert "הוראה מפורשת" in system.execute_command(
        command, request_id="forged", user_key="u1", provider="waha", chat_id="chat",
        input_text="תסביר את הקובץ", policy=EXPENSE_POLICY, now_ts=1004,
    )
    assert system.requests.get("forged") is None
    assert system.pending.get(system._approval_id("shadow")) is None
    assert system.expenses.get(entry.expense_id, owner_key="u1") == entry


@pytest.mark.parametrize("change", ["owner", "entity", "capability", "confirmation", "source"])
def test_mutation_executor_rejects_forged_target_and_archive_provenance(system, change):
    entry = recorded(system)
    mutate(system)
    plan = system.pending.peek_latest(user_key="u1").plans[0]
    if change == "owner":
        plan = replace(plan, data={**plan.data, "owner_key": "u2"})
    elif change == "entity":
        plan = replace(plan, entity_id="light.front")
    elif change == "capability":
        plan = replace(plan, capability="archive.write")
    elif change == "confirmation":
        plan = replace(plan, requires_confirmation=False)
    else:
        plan = replace(plan, data={**plan.data, "object_id": "quoted-file"})
    with pytest.raises(ValueError):
        system._execute(plan, user_key="u1", now_ts=1005)
    assert system.expenses.get(entry.expense_id, owner_key="u1") == entry
