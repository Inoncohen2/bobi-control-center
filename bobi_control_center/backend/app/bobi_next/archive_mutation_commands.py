"""Direct, bounded archive mutations; quoted/media-derived text is never authority."""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from .archive_retrieval_commands import parse_archive_target


@dataclass(slots=True, frozen=True)
class ArchiveMutationCommand:
    operation: str
    query: str
    kind: str = ""
    category: str = ""
    financial_fields: dict[str, str | int] = field(default_factory=dict)


_LEAD = re.compile(
    r"^(?:(?:בובי|bobi)[,:]?\s+)?(?:(?:בבקשה|please)[,:]?\s+)?"
    r"(?P<verb>העבר|העבירי|תעביר|תעבירי|מחק|מחקי|תמחק|תמחקי|"
    r"שחזר|שחזרי|תשחזר|תשחזרי|move|delete|remove|restore)\s+(?P<body>.+)$",
    re.IGNORECASE,
)
_UNSAFE = re.compile(
    r"[?？\n\r]|(?:^|\s)(?:אל|לא|אם|כאשר|מחר|אחר\s+כך|וגם|ואז)(?:\s|$)|"
    r"(?:^|\s)כש\S*|\b(?:not|don't|never|if|when|unless|later|tomorrow|and|then)\b",
    re.IGNORECASE,
)
_CATEGORY = re.compile(
    r"\s+(?:לתיקיית|לתיקיה|לתיקייה|לקטגוריית|לקטגוריה|"
    r"(?:to|into)\s+(?:the\s+)?(?:folder|category))\s+(.+)$",
    re.IGNORECASE,
)
_REFERENCES = frozenset({"זה", "זאת", "הזה", "הזאת", "אותו", "אותה", "it", "this", "that"})


def parse_archive_mutation(text: str) -> ArchiveMutationCommand | None:
    original = str(text or "").strip()
    if not original or len(original) > 800 or _UNSAFE.search(original):
        return None
    value = " ".join(original.split()).rstrip(".!")
    match = _LEAD.fullmatch(value)
    if match is None:
        return None
    verb = match["verb"].casefold()
    operation = (
        "move"
        if verb in {"העבר", "העבירי", "תעביר", "תעבירי", "move"}
        else ("restore" if verb.startswith(("שחזר", "תשחזר", "restore")) else "delete")
    )
    body = match["body"]
    category = ""
    if operation == "move":
        location = _CATEGORY.search(body)
        if location is None:
            return None
        category = location[1].strip().strip("\"'״").strip()
        if not category or len(category) > 160 or any(ord(c) < 32 for c in category):
            return None
        body = body[: location.start()].strip()
    if len(body) > 300:
        return None
    target = parse_archive_target(body)
    if target is None or not target.query or len(target.query) > 300:
        return None
    if target.query.casefold() in _REFERENCES:
        return None
    return ArchiveMutationCommand(operation, target.query, target.kind, category)
