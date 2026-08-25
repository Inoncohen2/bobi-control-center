"""Small time helpers shared by services and fixtures.

Kept dependency-free so both the mock data and the real service layer agree on
things like "does this window cross midnight".
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

# Israel is UTC+3 in summer. Phase 1 uses a fixed offset rather than pulling in
# a tz database; the real adapter will use Home Assistant's configured zone.
LOCAL_TZ = timezone(timedelta(hours=3))

#: 0 = Sunday, matching the Hebrew week used throughout the UI.
HEBREW_DAYS = ["ראשון", "שני", "שלישי", "רביעי", "חמישי", "שישי", "שבת"]


def now() -> datetime:
    """Current local time (timezone-aware)."""
    return datetime.now(LOCAL_TZ)


def minutes_ago(minutes: int) -> datetime:
    return now() - timedelta(minutes=minutes)


def hours_ago(hours: int) -> datetime:
    return now() - timedelta(hours=hours)


def days_ago(days: int) -> datetime:
    return now() - timedelta(days=days)


def days_ahead(days: int) -> datetime:
    return now() + timedelta(days=days)


def parse_hhmm(value: str) -> tuple[int, int]:
    """Parse ``HH:MM`` into ``(hour, minute)``.

    Raises :class:`ValueError` on anything malformed so callers can turn it into
    a structured API error rather than a 500.
    """
    parts = value.strip().split(":")
    if len(parts) != 2:
        raise ValueError(f"שעה לא תקינה: {value}")
    hour, minute = int(parts[0]), int(parts[1])
    if not (0 <= hour <= 23 and 0 <= minute <= 59):
        raise ValueError(f"שעה לא תקינה: {value}")
    return hour, minute


def to_minutes(value: str) -> int:
    hour, minute = parse_hhmm(value)
    return hour * 60 + minute


def crosses_midnight(start: str, end: str) -> bool:
    """True when ``end`` lands on the following day.

    An end time equal to the start is treated as a full 24h window, which also
    crosses midnight.
    """
    return to_minutes(end) <= to_minutes(start)


def duration_label(start: str, end: str) -> str:
    """Hebrew duration label for a window, e.g. '3 שעות ו-30 דקות'."""
    total = to_minutes(end) - to_minutes(start)
    if total <= 0:
        total += 24 * 60
    hours, minutes = divmod(total, 60)
    if hours and minutes:
        return f"{hours} שעות ו-{minutes} דקות"
    if hours:
        return "שעה" if hours == 1 else f"{hours} שעות"
    return f"{minutes} דקות"


def day_names(days: list[int]) -> str:
    """Turn ``[0, 4]`` into 'ראשון וחמישי'."""
    names = [HEBREW_DAYS[d] for d in sorted(days) if 0 <= d < 7]
    if not names:
        return ""
    if len(names) == 1:
        return names[0]
    if sorted(days) == [0, 1, 2, 3, 4]:
        return "ראשון–חמישי"
    if sorted(days) == list(range(7)):
        return "כל יום"
    return ", ".join(names[:-1]) + f" ו{names[-1]}"


def weekday_hebrew(value: datetime) -> int:
    """Convert a python weekday (0=Monday) into the Hebrew index (0=Sunday)."""
    return (value.weekday() + 1) % 7


def hebrew_day_label(value: datetime) -> str:
    return f"יום {HEBREW_DAYS[weekday_hebrew(value)]}"


def hhmm(value: datetime) -> str:
    return value.strftime("%H:%M")
