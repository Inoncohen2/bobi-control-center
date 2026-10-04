"""Deterministic authority helpers for explicit archive/save commands."""

from __future__ import annotations

import re
from pathlib import Path

from .authorization import UserPolicy
from .media_pipeline import LoadedMedia

_SAVE_PATTERNS = (
    re.compile(r"(?:^|\s)(?:שמור|שמרי|תשמור|תשמרי)(?:\s|$|[.!,:])"),
    re.compile(r"\b(?:please\s+)?(?:save|keep|archive|store)\b", re.IGNORECASE),
)
_NEGATED_SAVE_PATTERNS = (
    re.compile(r"(?:אל|לא)\s+(?:תשמור|תשמרי|שמור|שמרי|לשמור)"),
    re.compile(r"לא\s+(?:צריך|רוצה)\s+לשמור"),
    re.compile(r"\b(?:do\s+not|don't|dont|never)\s+(?:save|keep|archive|store)\b", re.IGNORECASE),
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
    return any(pattern.search(value) for pattern in _SAVE_PATTERNS)


def archive_write_allowed(policy: UserPolicy, *, user_key: str) -> bool:
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
    return "archive.save" not in policy.denied_actions


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
