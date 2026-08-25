"""Shabbat clock logic.

The one rule worth stating explicitly: ``crosses_midnight`` is computed here and
only here. The frontend renders the flag it is given rather than re-deriving it,
so the badge on screen and the preview text can never disagree.
"""

from __future__ import annotations

from app.errors import ValidationError
from app.models import PreviewLine, ShabbatConfig, ShabbatDeviceSchedule, ShabbatDraft
from app.timeutil import crosses_midnight, duration_label, parse_hhmm

DAY_LABELS = {"friday": "שישי", "saturday": "שבת"}


def recompute(schedule: ShabbatDeviceSchedule) -> ShabbatDeviceSchedule:
    """Refresh every derived flag on one device schedule."""
    for time_range in schedule.ranges:
        time_range.crosses_midnight = crosses_midnight(time_range.start, time_range.end)
    return schedule


def recompute_all(schedules: list[ShabbatDeviceSchedule]) -> list[ShabbatDeviceSchedule]:
    return [recompute(schedule) for schedule in schedules]


def enrich_config(config: ShabbatConfig) -> ShabbatConfig:
    config.schedules = recompute_all(config.schedules)
    for template in config.templates:
        template.schedules = recompute_all(template.schedules)
    return config


def validate_draft(draft: ShabbatDraft) -> None:
    """Reject impossible windows before anything is previewed."""
    for schedule in draft.schedules:
        if not schedule.ranges and schedule.enabled:
            raise ValidationError(
                f"ל{schedule.device_name} אין אף טווח שעות",
                details={"schedule_id": schedule.id},
            )
        for time_range in schedule.ranges:
            for value in (time_range.start, time_range.end):
                try:
                    parse_hhmm(value)
                except ValueError as exc:
                    raise ValidationError(
                        f"שעה לא תקינה אצל {schedule.device_name}",
                        details={"schedule_id": schedule.id, "value": value},
                    ) from exc
            if time_range.start == time_range.end:
                raise ValidationError(
                    f"שעת ההתחלה והסיום זהות אצל {schedule.device_name}",
                    details={"schedule_id": schedule.id},
                )


def range_label(start: str, end: str) -> str:
    """'17:42 → 23:30' or '22:00 → 01:00 + יום הבא'."""
    if crosses_midnight(start, end):
        return f"{start} → {end} + יום הבא"
    return f"{start} → {end}"


def build_preview_lines(draft: ShabbatDraft) -> tuple[list[PreviewLine], list[str]]:
    """Human-readable preview plus any warnings worth surfacing."""
    lines: list[PreviewLine] = []
    warnings: list[str] = []

    enabled = [s for s in draft.schedules if s.enabled]
    disabled = [s for s in draft.schedules if not s.enabled]

    for schedule in enabled:
        lines.append(PreviewLine(text=f"{schedule.device_name} ({schedule.room})", emphasis=True))
        active_ranges = [r for r in schedule.ranges if r.enabled]
        if not active_ranges:
            lines.append(PreviewLine(text="  אין טווחים פעילים"))
            continue
        for time_range in active_ranges:
            day = DAY_LABELS.get(time_range.day, time_range.day)
            label = range_label(time_range.start, time_range.end)
            duration = duration_label(time_range.start, time_range.end)
            lines.append(PreviewLine(text=f"  {day}: {label} · {duration}"))
            if crosses_midnight(time_range.start, time_range.end):
                warnings.append(
                    f"{schedule.device_name}: הטווח {time_range.start}–{time_range.end} "
                    "ממשיך אל היום הבא."
                )

    for schedule in disabled:
        lines.append(PreviewLine(text=f"{schedule.device_name} — כבוי בשבת הקרובה"))

    if not enabled:
        warnings.append("אף מכשיר לא מתוזמן לשבת הקרובה.")

    return lines, warnings


def apply_draft(config: ShabbatConfig, draft: ShabbatDraft) -> ShabbatConfig:
    """Merge a confirmed draft onto the saved configuration."""
    config.enabled = draft.enabled
    config.schedules = recompute_all(draft.schedules)
    config.active_template_id = draft.active_template_id
    config.has_draft = False
    return config


def summarize(draft: ShabbatDraft) -> str:
    enabled = [s for s in draft.schedules if s.enabled]
    total_ranges = sum(len([r for r in s.ranges if r.enabled]) for s in enabled)
    crossing = sum(
        1
        for s in enabled
        for r in s.ranges
        if r.enabled and crosses_midnight(r.start, r.end)
    )
    summary = f"{len(enabled)} מכשירים · {total_ranges} טווחי שעות"
    if crossing:
        summary += f" · {crossing} ממשיכים אחרי חצות"
    return summary
