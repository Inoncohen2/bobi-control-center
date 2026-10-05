"""Deterministic natural-language routing for explicit archive retrieval.

The parser deliberately recognizes only direct archive-oriented requests. It
must not hijack generic requests such as "send me a cat picture" that belong to
other Bobi capabilities.
"""

from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(slots=True, frozen=True)
class ArchiveRetrievalCommand:
    query: str
    kind: str = ""


_HEBREW_LEAD = re.compile(
    r"^(?:תשלח|שלח|תשלחי|שלחי|תביא|הבא|תביאי|הביאי|תמצא|מצא|תמצאי|מצאי|"
    r"תראה|הראה|תראי|הראי)\s+לי\s+",
    re.IGNORECASE,
)
_ENGLISH_LEAD = re.compile(
    r"^(?:please\s+)?(?:send|find|get|show)\s+me\s+",
    re.IGNORECASE,
)
_ARCHIVE_SIGNAL = re.compile(
    r"(?:מסמ(?:ך|כים)|קוב(?:ץ|צים)|קבלה|קבלות|חשבונית|חשבוניות|אחריות|"
    r"חשבון\s+(?:חשמל|מים)|רישי(?:ו|וֹ)?ן\s+רכב|רשיון\s+רכב|ביטוח\s+רכב|"
    r"מהארכיון|ששמר(?:תי|ת|נו)|\b(?:document|file|receipt|invoice|warranty|"
    r"utility\s+bill|electric\s+bill|water\s+bill|vehicle\s+document|archive|saved)\b)",
    re.IGNORECASE,
)


def _kind_for(text: str) -> str:
    value = text.casefold()
    if any(term in value for term in ("קבלה", "חשבונית", "receipt", "invoice")):
        return "receipt"
    if any(term in value for term in ("אחריות", "warranty")):
        return "warranty"
    if any(
        term in value
        for term in (
            "חשבון חשמל",
            "חשבון מים",
            "utility bill",
            "electric bill",
            "water bill",
        )
    ):
        return "bill"
    if any(
        term in value
        for term in (
            "רישיון רכב",
            "רשיון רכב",
            "ביטוח רכב",
            "vehicle document",
            "car document",
        )
    ):
        return "vehicle_document"
    return ""


def _query_for(body: str, kind: str) -> str:
    value = " ".join(body.strip(" .,!?:;\t\n").split())
    value = re.sub(r"^(?:את\s+)?", "", value)
    if kind == "receipt":
        value = re.sub(
            r"^(?:ה?(?:קבלה|חשבונית|קבלות|חשבוניות)|receipt|invoice)\s*",
            "",
            value,
            flags=re.IGNORECASE,
        )
    elif kind == "warranty":
        value = re.sub(r"^(?:ה?אחריות|warranty)\s*", "", value, flags=re.IGNORECASE)
    elif kind == "bill":
        value = re.sub(
            r"^(?:ה?חשבון|utility\s+bill|electric\s+bill|water\s+bill)\s*",
            "",
            value,
            flags=re.IGNORECASE,
        )
    elif kind == "vehicle_document":
        value = re.sub(
            r"^(?:ה?(?:מסמך\s+רכב|רישיון\s+רכב|רשיון\s+רכב|ביטוח\s+רכב)|"
            r"vehicle\s+document|car\s+document)\s*",
            "",
            value,
            flags=re.IGNORECASE,
        )
    else:
        value = re.sub(
            r"^(?:ה?(?:מסמך|מסמכים|קובץ|קבצים)|document|file|archive)\s*",
            "",
            value,
            flags=re.IGNORECASE,
        )
    value = re.sub(r"^(?:של|מ|מה|from)\s+", "", value, flags=re.IGNORECASE)
    return value.strip(" .,!?:;")[:300]


def parse_archive_retrieval(text: str) -> ArchiveRetrievalCommand | None:
    """Parse only explicit user requests to retrieve a previously saved object."""

    value = " ".join(str(text or "").strip().split())
    if not value:
        return None
    match = _HEBREW_LEAD.match(value) or _ENGLISH_LEAD.match(value)
    if match is None:
        return None
    body = value[match.end() :].strip()
    if not body or _ARCHIVE_SIGNAL.search(body) is None:
        return None
    kind = _kind_for(body)
    return ArchiveRetrievalCommand(query=_query_for(body, kind), kind=kind)
