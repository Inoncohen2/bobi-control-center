"""Explicit receipt edits and safe presentation of advisory versus reviewed data.

These parsers accept the current user's plain text only. Reviewing never copies
OCR fields: each changed value must be typed, validated and separately approved.
The original extraction stays advisory, including after a partial review.
"""

from __future__ import annotations

import re
import unicodedata
from contextlib import suppress
from typing import TYPE_CHECKING

from .archive_mutation_commands import _REFERENCES, _UNSAFE, ArchiveMutationCommand
from .archive_retrieval_commands import ArchiveRetrievalCommand, parse_archive_target
from .receipt_metadata import parse_financial_date, parse_financial_money

if TYPE_CHECKING:
    from .archive_store import ArchiveRecord

_PREFIX = re.compile(
    r"^(?:(?:בובי|bobi)[,:]?\s+)?(?:(?:בבקשה|please)[,:]?\s+)?"
    r"(?:(?:עדכן|עדכני|תעדכן|תעדכני|תקן|תקני|תתקן|תתקני)\s+(?:את\s+)?פרטי\s+|"
    r"(?:update|correct)\s+(?:the\s+)?(?:financial\s+)?details\s+of\s+)",
    re.I,
)
_DETAILS = re.compile(
    r"^(?:מה\s+(?:ה)?פרטי\s+|(?:הראה|הראי|תראה|תראי)\s+לי\s+פרטי\s+|"
    r"(?:please\s+)?show\s+me\s+(?:the\s+)?(?:financial\s+)?details\s+of\s+|"
    r"what\s+are\s+(?:the\s+)?details\s+of\s+)",
    re.I,
)
_LABELS = {
    "ספק": "merchant", "בית עסק": "merchant", "merchant": "merchant", "vendor": "merchant",
    "supplier": "merchant",
    "מספר": "document_number", "מספר קבלה": "document_number",
    "מספר חשבונית": "document_number", "number": "document_number",
    "document number": "document_number", "receipt number": "document_number",
    "invoice number": "document_number",
    "תאריך": "document_date", "date": "document_date",
    "מועד תשלום": "due_date", "due date": "due_date",
    "סכום": "total_minor", 'סה"כ': "total_minor", "סה״כ": "total_minor", "total": "total_minor",
    'מע"מ': "tax_minor", "מע״מ": "tax_minor", "מס": "tax_minor", "tax": "tax_minor",
}
_LABEL_TITLES = {
    "merchant": "ספק", "document_number": "מספר מסמך", "document_date": "תאריך",
    "due_date": "מועד תשלום", "total_minor": "סכום", "tax_minor": 'מע״מ',
}
_MONEY_KEYS = frozenset({"total_minor", "tax_minor"})
_CURRENCIES = frozenset({"ILS", "USD", "EUR", "GBP"})


def _has_controls(text: str) -> bool:
    return any(unicodedata.category(char).startswith("C") for char in text)


def validate_review_fields(fields: object) -> dict[str, str | int]:
    """Fail closed at both planning and SQLite execution, including forged plans."""
    if (
        not isinstance(fields, dict) or not fields
        or set(fields) - (_LABEL_TITLES.keys() | {"currency"})
    ):
        raise ValueError("archive_review_fields_invalid")
    result: dict[str, str | int] = {}
    for name, raw in fields.items():
        if name in _MONEY_KEYS:
            if type(raw) is not int or abs(raw) > 100_000_000_000_000:
                raise ValueError("archive_review_amount_invalid")
            result[name] = raw
        elif name == "currency":
            if not isinstance(raw, str) or raw not in _CURRENCIES:
                raise ValueError("archive_review_currency_invalid")
            result[name] = raw
        else:
            if not isinstance(raw, str) or _has_controls(raw):
                raise ValueError("archive_review_text_invalid")
            value = " ".join(raw.split())
            if name == "merchant":
                if not value or len(value) > 160 or re.search(r"https?://|[*_`~]", value, re.I):
                    raise ValueError("archive_review_merchant_invalid")
            elif name == "document_number":
                if re.fullmatch(r"[A-Z0-9/-]{1,64}", value, re.I) is None:
                    raise ValueError("archive_review_number_invalid")
            elif re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", value) is None or (
                parse_financial_date(value) != value
            ):
                raise ValueError("archive_review_date_invalid")
            result[name] = value
    if bool(_MONEY_KEYS.intersection(result)) != ("currency" in result):
        raise ValueError("archive_review_currency_required")
    return result


def _financial_target(body: str) -> ArchiveRetrievalCommand | None:
    if len(body) > 300:
        return None
    target = parse_archive_target(body)
    if (
        target is None or target.kind not in {"receipt", "bill"} or not target.query
        or target.query.casefold() in _REFERENCES
    ):
        return None
    return target


def receipt_review_requested(text: str) -> bool:
    """Recognized malformed edits get help instead of being interpreted by AI."""
    return _PREFIX.match(str(text or "").strip()) is not None


def parse_receipt_review(text: str) -> ArchiveMutationCommand | None:
    original = str(text or "").strip()
    if len(original) > 1600 or _has_controls(original) or _UNSAFE.search(original):
        return None
    lead = _PREFIX.match(original)
    if lead is None:
        return None
    body, delimiter, values = original[lead.end():].partition(":")
    target = _financial_target(body.strip())
    if not delimiter or target is None:
        return None
    validated = parse_explicit_financial_fields(values)
    return ArchiveMutationCommand(
        "review", target.query, target.kind, financial_fields=validated,
    ) if validated else None


def parse_explicit_financial_fields(values: str) -> dict[str, str | int] | None:
    """Parse typed values only; this helper grants no action or target authority."""
    if len(values) > 1600 or _has_controls(values) or _UNSAFE.search(values):
        return None
    parts = values.split(";")
    if not 1 <= len(parts) <= 6:
        return None
    fields: dict[str, str | int] = {}
    for part in parts:
        pair = re.split(r"\s*[:=]\s*", part.strip(), maxsplit=1)
        if len(pair) != 2:
            return None
        label, raw = pair
        name = _LABELS.get(" ".join(label.casefold().split()))
        if name is None or name in fields:
            return None
        raw = raw.strip()
        if name in _MONEY_KEYS:
            # A single separator followed by three digits can mean grouping
            # or unsupported fractional cents. Typed authority must not guess.
            if re.search(r"(?<![\d.,])\d{1,3}[.,]\d{3}(?![\d.,])", raw):
                return None
            money = parse_financial_money(raw)
            if money is None or fields.get("currency", money[1]) != money[1]:
                return None
            fields[name], fields["currency"] = money
        elif name.endswith("date"):
            parsed = parse_financial_date(raw, hebrew=bool(re.search(r"[א-ת]", label)))
            if parsed is None:
                return None
            fields[name] = parsed
        else:
            fields[name] = raw
    try:
        return validate_review_fields(fields)
    except ValueError:
        return None


def parse_receipt_details(text: str) -> ArchiveRetrievalCommand | None:
    original = str(text or "").strip().rstrip("?？.! ")
    if len(original) > 650 or _has_controls(original) or _UNSAFE.search(original):
        return None
    lead = _DETAILS.match(original)
    return _financial_target(original[lead.end():].strip()) if lead else None


def reviewed_financial_fields(
    metadata: dict, *, owner_key: str, media_sha256: str,
) -> dict[str, str | int]:
    review = metadata.get("financial_review")
    if not isinstance(review, dict) or (
        review.get("schema_version") != 1
        or review.get("source") != "explicit_user_approved_fields"
        or review.get("user_key") != owner_key or review.get("media_sha256") != media_sha256
    ):
        return {}
    try:
        return validate_review_fields(review.get("fields"))
    except ValueError:
        return {}


def merge_review_fields(previous: dict, patch: object) -> dict[str, str | int]:
    explicit = validate_review_fields(patch)
    if (
        previous.get("currency") and explicit.get("currency")
        and previous["currency"] != explicit["currency"]
        and (_MONEY_KEYS.intersection(previous) - explicit.keys())
    ):
        # A new currency must never silently reinterpret a previously reviewed amount.
        raise ValueError("archive_review_currency_conflict")
    return validate_review_fields({**previous, **explicit})


def display_financial_text(text: str) -> str:
    return " ".join("".join(
        char if not unicodedata.category(char).startswith("C") and char not in "*_`~" else " "
        for char in text
    ).split())[:300]


def format_financial_fields(fields: dict, *, exclude: frozenset[str] = frozenset()) -> str:
    lines = []
    for name, label in _LABEL_TITLES.items():
        if name not in fields or name in exclude:
            continue
        value = fields[name]
        if name in _MONEY_KEYS:
            minor = int(value)
            sign = "-" if minor < 0 else ""
            value = f"{sign}{abs(minor) // 100}.{abs(minor) % 100:02d} {fields['currency']}"
        lines.append(f"{label}: {display_financial_text(str(value))}")
    return "\n".join(lines)


def receipt_review_help() -> str:
    return (
        "כדי לעדכן יש לציין מסמך וערכים מפורשים. "
        "לכל סכום יש לציין מטבע. השינוי יישמר רק לאחר אישור.\n"
        "עדכן את פרטי הקבלה של איקאה: סכום=123.45 ILS; תאריך=2026-10-05"
    )


def receipt_details_reply(record: ArchiveRecord) -> str:
    reviewed = reviewed_financial_fields(
        record.metadata, owner_key=record.owner_key, media_sha256=record.sha256,
    )
    advisory = record.metadata.get("financial_document")
    extracted: dict[str, str | int] = {}
    if isinstance(advisory, dict) and (
        advisory.get("schema_version") == 1
        and advisory.get("source") == "media_derived_labeled_text"
        and advisory.get("media_sha256") == record.sha256
        and advisory.get("requires_review") is True
    ):
        with suppress(ValueError):
            extracted = validate_review_fields(advisory.get("fields"))
    pieces = [f'📄 פרטי המסמך "{display_financial_text(record.title)}".']
    if reviewed:
        pieces.append("פרטים שכתבת ואישרת:\n" + format_financial_fields(reviewed))
    unreviewed = format_financial_fields(extracted, exclude=frozenset(reviewed))
    if unreviewed:
        pieces.append("חילוץ אוטומטי — דורש בדיקה:\n" + unreviewed)
    if not reviewed and not unreviewed:
        pieces.append("אין פרטים כספיים זמינים. אפשר להזין אותם במפורש.")
    pieces.append("רק השדות שכתבת ואישרת נחשבים בדוקים. " + receipt_review_help())
    return "\n".join(pieces)
