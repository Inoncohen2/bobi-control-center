"""Owner-private, exact-money ledger sharing the archive's SQLite write lock.

The receipt source recheck, verified expense and idempotency receipt commit in
one transaction. No OCR fallback, currency conversion, HA or cloud writes.
"""

from __future__ import annotations

import calendar
import hashlib
import json
import re
import sqlite3
import uuid
from dataclasses import asdict, dataclass
from pathlib import Path

from .expense_commands import validate_expense_category, validate_expense_fields
from .receipt_review import (
    display_financial_text,
    format_financial_fields,
    reviewed_financial_fields,
    validate_review_fields,
)

ALREADY_RECORDED = "הקבלה כבר רשומה כהוצאה. לא נרשמה הוצאה נוספת."
EXPENSE_RECORDED = "✅ ההוצאה נרשמה ואומתה."
_REQUIRED = frozenset({"merchant", "document_date", "total_minor", "currency"})
_RECORD_COLUMNS = (
    "expense_id,owner_key,source_object_id,source_sha256,source_revision,"
    "source_review_request_id,merchant,document_number,document_date,"
    "amount_minor,currency,category,created_ts"
)


def manual_expense_id(*, owner_key: str, request_id: str) -> str:
    if not owner_key or not request_id:
        raise ValueError("expense_identity_required")
    binding = json.dumps([owner_key, request_id], separators=(",", ":"))
    return "manual-" + hashlib.sha256(binding.encode()).hexdigest()


def expense_source_fields(metadata: dict, *, owner_key: str, sha256: str) -> dict:
    fields = reviewed_financial_fields(metadata, owner_key=owner_key, media_sha256=sha256)
    if not _REQUIRED.issubset(fields) or fields["total_minor"] <= 0 or not re.fullmatch(
        r"[0-9a-f]{64}", sha256,
    ):
        raise ValueError("expense_review_required")
    return {key: value for key, value in fields.items() if key in _REQUIRED | {"document_number"}}


@dataclass(slots=True, frozen=True)
class ExpenseRecord:
    expense_id: str
    owner_key: str
    source_object_id: str
    source_sha256: str | None
    source_revision: int
    source_review_request_id: str
    merchant: str
    document_number: str
    document_date: str
    amount_minor: int
    currency: str
    category: str
    created_ts: int
    source_kind: str = "receipt"


@dataclass(slots=True, frozen=True)
class ExpenseReceipt:
    request_id: str
    owner_key: str
    plan_hash: str
    record: ExpenseRecord
    duplicate: bool = False


class ExpenseLedger:
    """Uses the archive database so a concurrent edit cannot race the source check."""

    def __init__(self, archive_path: str | Path) -> None:
        self._db = sqlite3.connect(archive_path)
        self._db.row_factory = sqlite3.Row
        self._db.execute("PRAGMA journal_mode=WAL")
        try:
            self._migrate()
        except BaseException:
            self._db.close()
            raise

    def _migrate(self) -> None:
        # Serialize schema inspection too: two starting workers must not both
        # attempt the same table rebuild. No executescript implicit commit.
        self._db.execute("BEGIN IMMEDIATE")
        try:
            columns = {
                row["name"] for row in self._db.execute("PRAGMA table_info(expense_records)")
            }
            legacy = bool(columns) and "source_kind" not in columns
            if legacy:
                self._db.execute("ALTER TABLE expense_records RENAME TO expense_records_legacy")
            self._db.execute("""CREATE TABLE IF NOT EXISTS expense_records (
                expense_id TEXT PRIMARY KEY,
                owner_key TEXT NOT NULL,
                source_object_id TEXT NOT NULL,
                source_sha256 TEXT,
                source_revision INTEGER NOT NULL,
                source_review_request_id TEXT NOT NULL,
                merchant TEXT NOT NULL,
                document_number TEXT NOT NULL,
                document_date TEXT NOT NULL,
                amount_minor INTEGER NOT NULL CHECK(amount_minor > 0),
                currency TEXT NOT NULL CHECK(currency IN ('ILS','USD','EUR','GBP')),
                category TEXT NOT NULL,
                created_ts INTEGER NOT NULL,
                source_kind TEXT NOT NULL DEFAULT 'receipt'
                    CHECK(source_kind IN ('receipt','manual')),
                UNIQUE(owner_key, source_sha256),
                CHECK (
                    (source_kind='receipt' AND source_sha256 IS NOT NULL
                        AND length(source_sha256)=64)
                    OR (source_kind='manual' AND source_sha256 IS NULL AND source_object_id=''
                        AND source_revision=0 AND source_review_request_id='')
                )
            )""")
            if legacy:
                self._db.execute(
                    f"INSERT INTO expense_records({_RECORD_COLUMNS},source_kind) "
                    f"SELECT {_RECORD_COLUMNS},'receipt' FROM expense_records_legacy"
                )
                before = self._db.execute(
                    "SELECT COUNT(*) FROM expense_records_legacy"
                ).fetchone()[0]
                after = self._db.execute("SELECT COUNT(*) FROM expense_records").fetchone()[0]
                changed = self._db.execute(
                    f"SELECT {_RECORD_COLUMNS} FROM expense_records_legacy "
                    f"EXCEPT SELECT {_RECORD_COLUMNS} FROM expense_records LIMIT 1"
                ).fetchone()
                if before != after or changed is not None:
                    raise RuntimeError("expense_migration_not_verified")
                self._db.execute("DROP TABLE expense_records_legacy")
            self._db.execute(
                "CREATE INDEX IF NOT EXISTS ix_expense_owner_date "
                "ON expense_records(owner_key, document_date, created_ts)"
            )
            self._db.execute("""CREATE TABLE IF NOT EXISTS expense_receipts (
                request_id TEXT PRIMARY KEY,
                owner_key TEXT NOT NULL,
                plan_hash TEXT NOT NULL,
                record_json TEXT NOT NULL,
                duplicate INTEGER NOT NULL
            )""")
            self._db.commit()
        except BaseException:
            self._db.rollback()
            raise

    def close(self) -> None:
        self._db.close()

    @staticmethod
    def _record(row: sqlite3.Row | None) -> ExpenseRecord | None:
        return ExpenseRecord(**dict(row)) if row else None

    def for_source(self, *, owner_key: str, sha256: str) -> ExpenseRecord | None:
        return self._record(self._db.execute(
            "SELECT * FROM expense_records WHERE owner_key=? AND source_sha256=?",
            (owner_key, sha256),
        ).fetchone())

    def get(self, expense_id: str, *, owner_key: str) -> ExpenseRecord | None:
        return self._record(self._db.execute(
            "SELECT * FROM expense_records WHERE expense_id=? AND owner_key=?",
            (expense_id, owner_key),
        ).fetchone())

    def manual_state_guard(self, expense_id: str, *, owner_key: str) -> dict:
        return {
            "expense_id": expense_id, "owner_key": owner_key,
            "status": "exists" if self.get(expense_id, owner_key=owner_key) else "absent",
        }

    def _insert_verified(self, record: ExpenseRecord) -> None:
        self._db.execute(
            f"INSERT INTO expense_records({_RECORD_COLUMNS},source_kind) "
            "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)", tuple(asdict(record).values()),
        )
        if self.get(record.expense_id, owner_key=record.owner_key) != record:
            raise RuntimeError("expense_not_verified")

    def _commit_receipt(
        self, *, request_id: str, owner_key: str, plan_hash: str, record: ExpenseRecord,
        duplicate: bool = False,
    ) -> ExpenseReceipt:
        self._db.execute(
            "INSERT INTO expense_receipts VALUES(?,?,?,?,?)",
            (request_id, owner_key, plan_hash, json.dumps(asdict(record), ensure_ascii=False),
             int(duplicate)),
        )
        receipt = self.receipt(request_id, owner_key=owner_key)
        if receipt is None or receipt.record != record or receipt.plan_hash != plan_hash:
            raise RuntimeError("expense_receipt_not_verified")
        self._db.commit()
        return receipt

    def receipt(self, request_id: str, *, owner_key: str) -> ExpenseReceipt | None:
        row = self._db.execute(
            "SELECT * FROM expense_receipts WHERE request_id=?", (request_id,),
        ).fetchone()
        if row is None:
            return None
        if row["owner_key"] != owner_key:
            raise ValueError("expense_request_owner_mismatch")
        return ExpenseReceipt(
            request_id, owner_key, row["plan_hash"],
            ExpenseRecord(**json.loads(row["record_json"])),
            bool(row["duplicate"]),
        )

    def check_source(
        self, *, owner_key: str, object_id: str, sha256: str, revision: int,
        fields: dict, review_request_id: str,
    ) -> None:
        if (
            type(revision) is not int or revision < 0 or not object_id or not owner_key
            or not isinstance(review_request_id, str) or not review_request_id
            or validate_review_fields(fields) != fields
            or set(fields) - (_REQUIRED | {"document_number"})
        ):
            raise ValueError("expense_source_invalid")
        row = self._db.execute(
            "SELECT * FROM archive_objects WHERE object_id=? AND owner_key=?",
            (object_id, owner_key),
        ).fetchone()
        if row is None or (
            row["status"] != "active" or row["kind"] != "receipt"
            or row["sha256"] != sha256 or row["revision"] != revision
        ):
            raise ValueError("expense_source_changed")
        metadata = json.loads(row["metadata_json"])
        if expense_source_fields(metadata, owner_key=owner_key, sha256=sha256) != fields:
            raise ValueError("expense_source_changed")
        review = metadata["financial_review"]
        receipt = self._db.execute(
            "SELECT * FROM archive_mutation_receipts WHERE request_id=? AND owner_key=? "
            "AND operation='review' AND plan_hash=?",
            (review_request_id, owner_key, review.get("plan_hash")),
        ).fetchone()
        if receipt is None or review.get("request_id") != review_request_id:
            raise ValueError("expense_review_not_verified")
        verified = json.loads(receipt["record_json"])
        if (
            verified.get("object_id") != object_id or verified.get("owner_key") != owner_key
            or verified.get("sha256") != sha256
            or verified.get("metadata", {}).get("financial_review") != review
        ):
            raise ValueError("expense_review_not_verified")

    def record_once(
        self, *, request_id: str, owner_key: str, plan_hash: str, object_id: str,
        sha256: str, revision: int, fields: dict, review_request_id: str,
        category: str, now_ts: int,
    ) -> ExpenseReceipt:
        if not request_id or not owner_key or not plan_hash or not review_request_id:
            raise ValueError("expense_identity_required")
        category = validate_expense_category(category)
        self._db.execute("BEGIN IMMEDIATE")
        try:
            prior = self.receipt(request_id, owner_key=owner_key)
            if prior is not None:
                if prior.plan_hash != plan_hash:
                    raise ValueError("expense_request_plan_changed")
                self._db.commit()
                return prior
            self.check_source(
                owner_key=owner_key, object_id=object_id, sha256=sha256, revision=revision,
                fields=fields, review_request_id=review_request_id,
            )
            existing = self.for_source(owner_key=owner_key, sha256=sha256)
            record = existing or ExpenseRecord(
                uuid.uuid4().hex, owner_key, object_id, sha256, revision, review_request_id,
                str(fields["merchant"]), str(fields.get("document_number", "")),
                str(fields["document_date"]), fields["total_minor"], str(fields["currency"]),
                category, now_ts,
            )
            if existing is None:
                self._insert_verified(record)
            if self.for_source(owner_key=owner_key, sha256=sha256) != record:
                raise RuntimeError("expense_not_verified")
            return self._commit_receipt(
                request_id=request_id, owner_key=owner_key, plan_hash=plan_hash, record=record,
                duplicate=existing is not None,
            )
        except BaseException:
            self._db.rollback()
            raise

    def record_manual_once(
        self, *, request_id: str, owner_key: str, plan_hash: str, expense_id: str,
        fields: dict, category: str, now_ts: int,
    ) -> ExpenseReceipt:
        if not plan_hash or expense_id != manual_expense_id(
            owner_key=owner_key, request_id=request_id,
        ):
            raise ValueError("expense_identity_required")
        validated = validate_expense_fields(fields)
        category = validate_expense_category(category)
        self._db.execute("BEGIN IMMEDIATE")
        try:
            prior = self.receipt(request_id, owner_key=owner_key)
            if prior is not None:
                if prior.plan_hash != plan_hash:
                    raise ValueError("expense_request_plan_changed")
                self._db.commit()
                return prior
            if self.get(expense_id, owner_key=owner_key) is not None:
                raise ValueError("expense_state_changed")
            record = ExpenseRecord(
                expense_id, owner_key, "", None, 0, "", str(validated["merchant"]),
                str(validated.get("document_number", "")), str(validated["document_date"]),
                validated["total_minor"], str(validated["currency"]), category, now_ts, "manual",
            )
            self._insert_verified(record)
            return self._commit_receipt(
                request_id=request_id, owner_key=owner_key, plan_hash=plan_hash, record=record,
            )
        except BaseException:
            self._db.rollback()
            raise

    def month_reply(self, *, owner_key: str, month: str) -> str:
        if not re.fullmatch(r"(?!0000)[0-9]{4}-(?:0[1-9]|1[0-2])", month):
            raise ValueError("expense_month_invalid")
        year, month_number = map(int, month.split("-"))
        last_day = calendar.monthrange(year, month_number)[1]
        period = (owner_key, f"{month}-01", f"{month}-{last_day:02d}")
        # Summary totals include every entry, with no implicit exchange rate.
        with self._db:
            self._db.execute("BEGIN")
            totals = self._db.execute(
                "SELECT currency,SUM(amount_minor) total,COUNT(*) count FROM expense_records "
                "WHERE owner_key=? AND document_date BETWEEN ? AND ? "
                "GROUP BY currency ORDER BY currency",
                period,
            ).fetchall()
            rows = self._db.execute(
                "SELECT * FROM expense_records WHERE owner_key=? AND document_date BETWEEN ? AND ? "
                "ORDER BY document_date DESC,created_ts DESC,expense_id LIMIT 20",
                period,
            ).fetchall()
        if not totals:
            return f"אין הוצאות רשומות לחודש {month}."
        lines = [f"הוצאות רשומות לחודש {month}:"]
        for total in totals:
            amount = format_financial_fields({
                "total_minor": total["total"], "currency": total["currency"],
            })
            unit = "הוצאה" if total["count"] == 1 else "הוצאות"
            lines.append(f"{amount} ({total['count']} {unit})")
        for row in rows:
            amount = format_financial_fields({
                "total_minor": row["amount_minor"], "currency": row["currency"],
            })
            lines.append(
                f"{row['document_date']} · {display_financial_text(row['merchant'])} · "
                f"{amount} · {display_financial_text(row['category'])}"
            )
        if sum(total["count"] for total in totals) > len(rows):
            lines.append("מוצגות 20 ההוצאות האחרונות; הסיכומים כוללים את כל החודש.")
        return "\n".join(lines)
