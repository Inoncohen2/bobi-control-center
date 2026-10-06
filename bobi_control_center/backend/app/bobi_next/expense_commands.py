"""Explicit expense authority; receipt extraction never creates a ledger entry."""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from typing import ClassVar

from .archive_mutation_commands import ArchiveMutationCommand
from .archive_retrieval_commands import parse_archive_target
from .authorization import UserPolicy
from .receipt_review import parse_explicit_financial_fields, validate_review_fields


@dataclass(slots=True, frozen=True)
class ManualExpenseCommand:
    financial_fields: dict[str, str | int]
    category: str
    operation: ClassVar[str] = "record_manual_expense"


@dataclass(slots=True, frozen=True)
class ExpenseMutationCommand:
    operation: str
    query: str
    financial_fields: dict[str, str | int] = field(default_factory=dict)
    category: str = ""


_MUTATION_LEAD = re.compile(
    r"^(?:(?:בובי|bobi)[,:]?\s+)?(?:(?:בבקשה|please)[,:]?\s+)?"
    r"(?P<verb>עדכן|עדכני|תעדכן|תעדכני|תקן|תקני|תתקן|תתקני|"
    r"מחק|מחקי|תמחק|תמחקי|שחזר|שחזרי|תשחזר|תשחזרי|update|correct|delete|remove|restore)"
    r"\s+(?:(?:את|the)\s+)?(?:ה?הוצאה|expense)\s+", re.I,
)


_MANUAL_LEAD = re.compile(
    r"^(?:(?:בובי|bobi)[,:]?\s+)?(?:(?:בבקשה|please)[,:]?\s+)?"
    r"(?:(?:רשום|רשמי|תרשום|תרשמי|הוסף|הוסיפי|תוסיף|תוסיפי)\s+הוצאה|"
    r"(?:record|add)\s+(?:an?\s+)?expense)\s*:", re.I,
)
_EXPENSE_REQUIRED = frozenset({"merchant", "document_date", "total_minor", "currency"})

_LEAD = re.compile(
    r"^(?:(?:בובי|bobi)[,:]?\s+)?(?:(?:בבקשה|please)[,:]?\s+)?"
    r"(?:(?:רשום|רשמי|תרשום|תרשמי|הוסף|הוסיפי|תוסיף|תוסיפי)\s+הוצאה\s+מ|"
    r"(?:record|add)\s+(?:an?\s+)?expense\s+from\s+)", re.I,
)
_CATEGORY = re.compile(r"\s+(?:בקטגוריית|בקטגוריה|in\s+(?:the\s+)?category)\s+(.+)$", re.I)
_UNSAFE = re.compile(
    r"[?？\n\r]|(?:^|\s)(?:אל|לא|אם|כאשר|מחר|אחר\s+כך|וגם|ואז)(?:\s|$)|"
    r"(?:^|\s)כש\S*|\b(?:not|don't|never|if|when|unless|later|tomorrow|and|then)\b", re.I,
)
_MONTH = re.compile(
    r"^(?:(?:בובי|bobi)[,:]?\s+)?"
    r"(?:(?:הצג|הציגי|תציג|תציגי|הראה|הראי)\s+(?:לי\s+)?הוצאות\s+לחודש|"
    r"(?:show|list)\s+(?:my\s+)?expenses\s+for\s+(?:month\s+)?)\s*"
    r"([0-9]{4}-(?:0[1-9]|1[0-2]))[.!?？]*$", re.I,
)


def validate_expense_category(value: object) -> str:
    if not isinstance(value, str):
        raise ValueError("expense_category_invalid")
    category = " ".join(value.split()).strip('"\'״')
    if (
        not category or len(category) > 80
        or any(unicodedata.category(c).startswith("C") for c in value)
        or re.search(r"https?://|[*_`~]", category, re.I)
    ):
        raise ValueError("expense_category_invalid")
    return category


def expense_requested(text: str) -> bool:
    return _LEAD.match(str(text or "").strip()) is not None


def validate_expense_fields(fields: object) -> dict[str, str | int]:
    validated = validate_review_fields(fields)
    if (
        not _EXPENSE_REQUIRED.issubset(validated)
        or set(validated) - (_EXPENSE_REQUIRED | {"document_number"})
        or validated["total_minor"] <= 0
    ):
        raise ValueError("expense_fields_invalid")
    return validated


def manual_expense_requested(text: str) -> bool:
    return _MANUAL_LEAD.match(str(text or "").strip()) is not None


def parse_manual_expense(text: str) -> ManualExpenseCommand | None:
    original = str(text or "").strip()
    if len(original) > 1600 or _UNSAFE.search(original) or any(
        unicodedata.category(c).startswith("C") for c in original
    ):
        return None
    lead = _MANUAL_LEAD.match(original)
    if lead is None:
        return None
    parts = original[lead.end():].split(";")
    if not 4 <= len(parts) <= 6:
        return None
    category = None
    financial = []
    for part in parts:
        pair = re.split(r"\s*[:=]\s*", part.strip(), maxsplit=1)
        if len(pair) != 2:
            return None
        if " ".join(pair[0].casefold().split()) in {"קטגוריה", "category"}:
            if category is not None:
                return None
            try:
                category = validate_expense_category(pair[1])
            except ValueError:
                return None
        else:
            financial.append(part)
    if category is None:
        return None
    fields = parse_explicit_financial_fields(";".join(financial))
    try:
        return ManualExpenseCommand(validate_expense_fields(fields), category)
    except ValueError:
        return None


def expense_mutation_requested(text: str) -> bool:
    return _MUTATION_LEAD.match(str(text or "").strip() + " ") is not None


def parse_expense_mutation(text: str) -> ExpenseMutationCommand | None:
    original = str(text or "").strip()
    if len(original) > 1600 or _UNSAFE.search(original) or any(
        unicodedata.category(c).startswith("C") for c in original
    ):
        return None
    lead = _MUTATION_LEAD.match(original)
    if lead is None:
        return None
    verb = lead["verb"].casefold()
    operation = (
        "restore" if verb.startswith(("שחזר", "תשחזר", "restore")) else
        "delete" if verb.startswith(("מחק", "תמחק", "delete", "remove")) else "edit"
    )
    body = original[lead.end():].strip()
    query, delimiter, values = body.partition(":")
    query = re.sub(r"^(?:של|from)\s+", "", query, flags=re.I).strip().rstrip(".!").strip('"\'״')
    if (
        not query or len(query) > 300 or re.search(r"https?://|[*_`~;%]", query, re.I)
        or query.casefold() in {
            "זה", "זאת", "הזה", "הזאת", "אותו", "אותה", "it", "this", "that",
        }
    ):
        return None
    if operation != "edit":
        return None if delimiter else ExpenseMutationCommand(operation, query.rstrip(".!"))
    if not delimiter:
        return None
    category = ""
    financial = []
    parts = values.split(";")
    if not 1 <= len(parts) <= 6:
        return None
    for part in parts:
        pair = re.split(r"\s*[:=]\s*", part.strip(), maxsplit=1)
        if len(pair) != 2:
            return None
        if " ".join(pair[0].casefold().split()) in {"קטגוריה", "category"}:
            if category:
                return None
            try:
                category = validate_expense_category(pair[1])
            except ValueError:
                return None
        else:
            financial.append(part)
    fields = parse_explicit_financial_fields(";".join(financial)) if financial else {}
    if fields is None or set(fields) - (_EXPENSE_REQUIRED | {"document_number"}):
        return None
    if "total_minor" in fields and fields["total_minor"] <= 0:
        return None
    return (
        ExpenseMutationCommand(operation, query, fields, category) if fields or category else None
    )


def expense_mutation_help() -> str:
    return (
        "יש לציין הוצאה קיימת במפורש, למשל ספק ותאריך. שינוי דורש אישור נפרד.\n"
        "עדכן את ההוצאה של מכולת 2026-10-05: סכום=40 ILS; קטגוריה=מזון\n"
        "מחק את ההוצאה של מכולת 2026-10-05\n"
        "שחזר את ההוצאה של מכולת 2026-10-05"
    )


def parse_expense_record(text: str) -> ArchiveMutationCommand | None:
    original = str(text or "").strip()
    if len(original) > 650 or _UNSAFE.search(original) or any(
        unicodedata.category(c).startswith("C") for c in original
    ):
        return None
    lead = _LEAD.match(original)
    if lead is None:
        return None
    body = original[lead.end():].rstrip(".!")
    location = _CATEGORY.search(body)
    if location is None:
        return None
    target = parse_archive_target(body[:location.start()].strip())
    if (
        target is None or target.kind != "receipt" or not target.query
        or len(target.query) > 300
        or target.query.casefold() in {
            "זה", "זאת", "הזה", "הזאת", "אותו", "אותה", "it", "this", "that",
        }
    ):
        return None
    try:
        category = validate_expense_category(location[1])
    except ValueError:
        return None
    return ArchiveMutationCommand("record_expense", target.query, "receipt", category)


def parse_expense_month(text: str) -> str | None:
    original = str(text or "").strip()
    if len(original) > 200 or any(unicodedata.category(c).startswith("C") for c in original):
        return None
    match = _MONTH.fullmatch(original)
    return match[1] if match and not match[1].startswith("0000") else None


def expense_allowed(policy: UserPolicy, *, user_key: str, action: str) -> bool:
    capability = "expenses.read" if action in {"summary", "details"} else "expenses.write"
    return bool(user_key) and policy.user_key == user_key and (
        "*" in policy.allowed_capabilities or capability in policy.allowed_capabilities
    ) and capability not in policy.denied_capabilities and (
        "*" in policy.allowed_domains or "expenses" in policy.allowed_domains
    ) and not {action, f"expenses.{action}"}.intersection(policy.denied_actions)


def expense_help() -> str:
    return (
        "כדי לרשום הוצאה דרושה קבלה שמורה עם סכום, מטבע, ספק ותאריך שכתבת ואישרת. "
        "לדוגמה: רשום הוצאה מהקבלה של איקאה בקטגוריית בית. לפני הרישום אבקש אישור."
    )


def manual_expense_help() -> str:
    return (
        "להוצאה ללא קבלה יש לכתוב סכום חיובי ומטבע, ספק, תאריך וקטגוריה. "
        "הרישום יישמר רק לאחר אישור.\n"
        "רשום הוצאה: סכום=35 ILS; ספק=מכולת; תאריך=2026-10-05; קטגוריה=מזון"
    )
