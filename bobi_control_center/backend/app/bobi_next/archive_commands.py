"""Deterministic authority helpers for explicit archive/save commands."""

from __future__ import annotations

import re
from pathlib import Path

from .authorization import UserPolicy
from .media_pipeline import LoadedMedia

_SAVE_PATTERNS = (
    re.compile(
        r"^(?:בובי[,:]?\s+)?(?:בבקשה[,:]?\s+)?"
        r"(?:שמור|שמרי|תשמור|תשמרי)(?:\s|$|[.!,:])"
    ),
    re.compile(
        r"^(?:bobi[,:]?\s+)?(?:please[,:]?\s+)?(?:save|keep|archive|store)\b",
        re.IGNORECASE,
    ),
)
_NEGATED_SAVE_PATTERNS = (
    re.compile(r"(?:אל|לא)\s+(?:תשמור|תשמרי|שמור|שמרי|לשמור)"),
    re.compile(r"לא\s+(?:צריך|רוצה)\s+לשמור"),
    re.compile(r"\b(?:do\s+not|don't|dont|never)\s+(?:save|keep|archive|store)\b", re.IGNORECASE),
)
_DEFERRED_SAVE = re.compile(
    r"(?:^|\s)(?:אם|כאשר|מחר|אחר\s+כך)(?:\s|$)|(?:^|\s)כש\S*|"
    r"\b(?:if|when|unless|later|tomorrow)\b",
    re.IGNORECASE,
)
_CATEGORY = re.compile(
    r"(?:^|\s)(?:(?:בתיקיית|לתיקיית|בתיקיה|לתיקיה|בתיקייה|לתיקייה|"
    r"בקטגוריית|לקטגוריית|בקטגוריה|לקטגוריה)\s*|"
    r"(?:in|into|to)\s+(?:the\s+)?(?:folder|category)\s*)(.*)$",
    re.IGNORECASE,
)
_RECEIPT_TERMS = ("קבלה", "חשבונית", "receipt", "invoice")
_WARRANTY_TERMS = ("אחריות", "warranty")
_BILL_TERMS = ("חשבון חשמל", "חשבון מים", "utility bill", "electric bill", "water bill")
_VEHICLE_TERMS = ("מסמך רכב", "רישיון רכב", "ביטוח רכב", "vehicle document", "car document")


def explicit_archive_save(text: str) -> bool:
    """Return true only for a direct, non-negated save instruction."""

    value = " ".join(str(text or "").strip().split())
    if not value:
        return False
    if any(pattern.search(value) for pattern in _NEGATED_SAVE_PATTERNS):
        return False
    if "?" in value or "？" in value or _DEFERRED_SAVE.search(value):
        return False
    return any(pattern.search(value) for pattern in _SAVE_PATTERNS)


def archive_save_category(text: str) -> str:
    """Read an explicit semantic folder label; never infer one from media/AI."""

    value = " ".join(str(text or "").strip().split())
    match = _CATEGORY.search(value)
    if match is None:
        return ""
    category = match.group(1).strip().rstrip(".!").strip()
    for opening, closing in (("\"", "\""), ("'", "'"), ("״", "״"), ("“", "”")):
        if category.startswith(opening) and category.endswith(closing):
            category = category[1:-1].strip()
            break
    if not category or len(category) > 160 or any(ord(char) < 32 for char in category):
        raise ValueError("archive_category_invalid")
    return category


def archive_write_allowed(policy: UserPolicy, *, user_key: str, action: str = "save") -> bool:
    """Apply the same allow/deny semantics to the non-HA archive domain."""

    if not policy.user_key.strip() or policy.user_key != user_key:
        return False
    capability = "archive.write"
    if capability in policy.denied_capabilities:
        return False
    if "*" not in policy.allowed_capabilities and capability not in policy.allowed_capabilities:
        return False
    if "*" not in policy.allowed_domains and "archive" not in policy.allowed_domains:
        return False
    return not {f"archive.{action}", action}.intersection(policy.denied_actions)


def infer_archive_kind(caption: str, media: LoadedMedia) -> str:
    """Use explicit user wording first, then safe media-type defaults."""

    value = str(caption or "").casefold()
    if any(term in value for term in _RECEIPT_TERMS):
        return "receipt"
    if any(term in value for term in _WARRANTY_TERMS):
        return "warranty"
    if any(term in value for term in _BILL_TERMS):
        return "bill"
    if any(term in value for term in _VEHICLE_TERMS):
        return "vehicle_document"
    if media.descriptor.mimetype.startswith("image/"):
        return "image"
    return "document"


def default_archive_title(media: LoadedMedia, *, kind: str) -> str:
    filename = Path(str(media.descriptor.filename or "")).name
    if filename:
        stem = Path(filename).stem.strip()
        if stem:
            return stem[:300]
    labels = {
        "receipt": "Saved receipt",
        "warranty": "Saved warranty",
        "bill": "Saved bill",
        "vehicle_document": "Saved vehicle document",
        "image": "Saved image",
        "document": "Saved document",
    }
    return labels.get(kind, "Saved object")
