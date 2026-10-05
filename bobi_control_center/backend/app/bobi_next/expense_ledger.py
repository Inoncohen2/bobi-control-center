"""Owner-private, exact-money ledger sharing the archive's SQLite write lock.

The receipt source recheck, verified expense and idempotency receipt commit in
one transaction. No OCR fallback, currency conversion, HA or cloud writes.
"""

from __future__ import annotations

import calendar
import json
import re
import sqlite3
import uuid
from dataclasses import asdict, dataclass
from pathlib import Path

from .expense_commands import validate_expense_category
from .receipt_review import (
    display_financial_text,
    format_financial_fields,
    reviewed_financial_fields,
    validate_review_fields,
)

ALREADY_RECORDED = "הקבלה כבר רשומה כהוצאה. לא נרשמה הוצאה נוספת."
EXPENSE_RECORDED = "✅ ההוצאה נרשמה ואומתה."
_REQUIRED = frozenset({"merchant", "document_date", "total_minor", "currency"})


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
    source_sha256: str
    source_revision: int
    source_review_request_id: str
    merchant: str
    document_number: str
    document_date: str
    amount_minor: int
    currency: str
    category: str
    created_ts: int


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
        # ArchiveStore owns the archive schema and must be initialized first.
        self._db.executescript("""
            CREATE TABLE IF NOT EXISTS expense_records (
                expense_id TEXT PRIMARY KEY,
                owner_key TEXT NOT NULL,
                source_object_id TEXT NOT NULL,
                source_sha256 TEXT NOT NULL,
                source_revision INTEGER NOT NULL,
                source_review_request_id TEXT NOT NULL,
                merchant TEXT NOT NULL,
                document_number TEXT NOT NULL,
                document_date TEXT NOT NULL,
                amount_minor INTEGER NOT NULL CHECK(amount_minor > 0),
                currency TEXT NOT NULL CHECK(currency IN ('ILS','USD','EUR','GBP')),
                category TEXT NOT NULL,
                created_ts INTEGER NOT NULL,
                UNIQUE(owner_key, source_sha256)
            );
            CREATE INDEX IF NOT EXISTS ix_expense_owner_date
                ON expense_records(owner_key, document_date, created_ts);
            CREATE TABLE IF NOT EXISTS expense_receipts (
                request_id TEXT PRIMARY KEY,
                owner_key TEXT NOT NULL,
                plan_hash TEXT NOT NULL,
                record_json TEXT NOT NULL,
                duplicate INTEGER NOT NULL
            );
        """)

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
                self._db.execute(
                    "INSERT INTO expense_records VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    tuple(asdict(record).values()),
                )
            if self.for_source(owner_key=owner_key, sha256=sha256) != record:
                raise RuntimeError("expense_not_verified")
            self._db.execute(
                "INSERT INTO expense_receipts VALUES(?,?,?,?,?)",
                (request_id, owner_key, plan_hash,
                 json.dumps(asdict(record), ensure_ascii=False),
                 int(existing is not None)),
            )
            receipt = self.receipt(request_id, owner_key=owner_key)
            if receipt is None or receipt.record != record or receipt.plan_hash != plan_hash:
                raise RuntimeError("expense_receipt_not_verified")
            self._db.commit()
            return receipt
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
