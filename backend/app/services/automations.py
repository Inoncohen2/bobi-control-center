"""Automation summaries and draft handling.

The human-readable summary is built **server-side** so the wizard preview, the
automation card and any future WhatsApp confirmation all read identically.
"""

from __future__ import annotations

import re
import unicodedata

from app.errors import ValidationError
from app.models import Advanced, Automation, AutomationDraft, AutomationType
from app.timeutil import crosses_midnight, day_names, duration_label, parse_hhmm

_SLUG_STRIP = re.compile(r"[^a-z0-9]+")


def slugify(name: str) -> str:
    """Build a stable ascii id from a Hebrew name.

    Hebrew has no useful ascii transliteration here, so a name that produces no
    ascii characters falls back to a hash-like suffix from its code points.
    """
    decomposed = unicodedata.normalize("NFKD", name)
    ascii_only = decomposed.encode("ascii", "ignore").decode().lower()
    slug = _SLUG_STRIP.sub("_", ascii_only).strip("_")
    if slug:
        return slug
    digest = sum(ord(ch) for ch in name)
    return f"automation_{digest:x}"


def _time_phrase(draft: AutomationDraft | Automation) -> str:
    if draft.automation_type is AutomationType.MULTI_TIME and draft.times:
        return "בשעות " + " ו".join(draft.times)
    if draft.start_time and draft.end_time:
        suffix = " (למחרת)" if crosses_midnight(draft.start_time, draft.end_time) else ""
        return f"בין {draft.start_time} ל-{draft.end_time}{suffix}"
    if draft.start_time:
        return f"בשעה {draft.start_time}"
    return ""


def _day_phrase(draft: AutomationDraft | Automation) -> str:
    if draft.automation_type is AutomationType.ONE_TIME:
        return "פעם אחת"
    if not draft.days:
        return ""
    names = day_names(draft.days)
    if names == "כל יום":
        return "בכל יום"
    if names == "ראשון–חמישי":
        return "בימים ראשון עד חמישי"
    return f"בכל יום {names}"


def build_summary(draft: AutomationDraft | Automation) -> str:
    """One Hebrew sentence describing exactly what will happen."""
    parts: list[str] = []

    day_phrase = _day_phrase(draft)
    if day_phrase:
        parts.append(day_phrase)

    time_phrase = _time_phrase(draft)
    if time_phrase:
        parts.append(time_phrase)

    action_labels = [action.label for action in draft.actions if action.label]
    target_names = [target.name for target in draft.targets]

    if action_labels and target_names:
        targets = " ו".join(target_names)
        parts.append(f"{action_labels[0]} את {targets}")
    elif action_labels:
        parts.append(action_labels[0])
    elif target_names:
        parts.append(" ו".join(target_names))

    for action in draft.actions[1:]:
        if action.value is not None:
            parts.append(f"{action.label}{action.value}")

    if draft.conditions:
        conditions = ", ".join(
            f"{c.label} {c.operator or ''} {c.value}".strip() for c in draft.conditions
        )
        parts.append(f"רק אם {conditions}")

    return " ".join(parts).strip() or draft.name


def validate_draft(draft: AutomationDraft) -> None:
    """Reject a draft the wizard should not have allowed through."""
    if not draft.name.strip():
        raise ValidationError("צריך לתת שם לאוטומציה", details={"field": "name"})
    if not draft.targets:
        raise ValidationError("צריך לבחור לפחות מכשיר אחד", details={"field": "targets"})
    if not draft.actions:
        raise ValidationError("צריך לבחור מה לעשות", details={"field": "actions"})

    for value in [draft.start_time, draft.end_time, *draft.times]:
        if value is None:
            continue
        try:
            parse_hhmm(value)
        except ValueError as exc:
            raise ValidationError(str(exc), details={"field": "time"}) from exc

    needs_days = draft.automation_type in (
        AutomationType.WEEKLY,
        AutomationType.MULTI_TIME,
    )
    if needs_days and not draft.days:
        raise ValidationError("צריך לבחור לפחות יום אחד", details={"field": "days"})

    if draft.automation_type is AutomationType.ONE_TIME and not draft.start_time:
        raise ValidationError("צריך לבחור שעה", details={"field": "start_time"})


def draft_to_automation(draft: AutomationDraft, existing: Automation | None = None) -> Automation:
    """Turn a validated draft into a full automation.

    ``existing`` preserves fields the wizard does not own (creation metadata,
    last-triggered time, the advanced block).
    """
    validate_draft(draft)

    automation_id = draft.id or existing.id if existing else draft.id
    if not automation_id:
        automation_id = slugify(draft.name)

    crosses = bool(
        draft.start_time
        and draft.end_time
        and crosses_midnight(draft.start_time, draft.end_time)
    )

    automation = Automation(
        id=automation_id,
        name=draft.name.strip(),
        enabled=draft.enabled,
        automation_type=draft.automation_type,
        targets=draft.targets,
        actions=draft.actions,
        days=draft.days,
        start_time=draft.start_time,
        end_time=draft.end_time,
        times=draft.times,
        run_date=draft.run_date,
        conditions=draft.conditions,
        owner=draft.owner or (existing.owner if existing else None),
        created_by=existing.created_by if existing else "ינון",
        source=existing.source if existing else "web",
        last_triggered=existing.last_triggered if existing else None,
        crosses_midnight=crosses,
        # The wizard does not own the advanced block; preserve it on edit and
        # start empty on create.
        advanced=existing.advanced if existing else Advanced(),
    )
    automation.summary = build_summary(automation)
    return automation


def enrich(automation: Automation) -> Automation:
    """Fill derived fields on an automation loaded from an adapter."""
    if automation.start_time and automation.end_time:
        automation.crosses_midnight = crosses_midnight(
            automation.start_time, automation.end_time
        )
    if not automation.summary:
        automation.summary = build_summary(automation)
    return automation


def window_label(start: str, end: str) -> str:
    """'22:00 → 01:00 · 3 שעות' — used by previews."""
    suffix = " + יום הבא" if crosses_midnight(start, end) else ""
    return f"{start} → {end}{suffix} · {duration_label(start, end)}"
