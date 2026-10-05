"""Explicit expense authority; receipt extraction never creates a ledger entry."""

from __future__ import annotations

import re
import unicodedata

from .archive_mutation_commands import ArchiveMutationCommand
from .archive_retrieval_commands import parse_archive_target
from .authorization import UserPolicy

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
    capability = "expenses.read" if action == "summary" else "expenses.write"
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
