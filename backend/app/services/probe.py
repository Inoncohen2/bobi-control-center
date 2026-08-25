"""Bobi's understanding pipeline, modelled as a probe.

Safety contract for this whole module:

* nothing here calls an adapter write method;
* :attr:`ProbeResult.would_execute` is set to ``False`` unconditionally by
  :meth:`ProbeEngine.probe` and is never derived from input;
* the engine only ever *reads* the device list it was constructed with.

Each stage is a small pure function so the Test Center can render the pipeline
as discrete, inspectable steps and so every stage is unit-testable on its own.
"""

from __future__ import annotations

import re
import time
import unicodedata
from dataclasses import dataclass

from app.models import (
    Device,
    ProbeFamily,
    ProbeResult,
    ProbeSchedule,
    ProbeStep,
    ProbeTarget,
)
from app.timeutil import HEBREW_DAYS, days_ahead, now

# --- vocabulary -------------------------------------------------------------

#: verb stems → (action, hebrew label, domain hint)
_ACTIONS: list[tuple[tuple[str, ...], str, str]] = [
    (("כבה", "לכבות", "תכבה", "כיבוי", "תכבי", "כבי"), "turn_off", "לכבות"),
    (("הדלק", "להדליק", "תדליק", "הדלקה", "תדליקי", "הדליקי"), "turn_on", "להדליק"),
    (("תפעיל", "להפעיל", "הפעל", "הפעלה"), "turn_on", "להפעיל"),
    (("תעצור", "לעצור", "עצור", "תפסיק", "להפסיק"), "turn_off", "לעצור"),
    (("תפתח", "לפתוח", "פתח"), "open", "לפתוח"),
    (("תסגור", "לסגור", "סגור"), "close", "לסגור"),
    (("תצלם", "לצלם", "צלם", "תמונה"), "snapshot", "לצלם"),
    (("תוסיף", "להוסיף", "הוסף", "תזכיר", "להזכיר"), "add", "להוסיף"),
    (("תמחק", "למחוק", "מחק"), "delete", "למחוק"),
    (("תכוון", "לכוון", "כוון", "תוריד", "תעלה"), "set_temperature", "לכוון"),
]

_QUERY_WORDS = ("מה", "כמה", "האם", "מתי", "איפה", "מי", "יש")

_TASK_WORDS = ("משימה", "משימות", "רשימה", "תזכורת", "תזכיר")
_CALENDAR_WORDS = ("יומן", "פגישה", "פגישות", "אירוע", "אירועים", "תור")
_SHABBAT_WORDS = ("שבת", "שעון שבת", "הדלקת נרות", "הבדלה")
_NOTIFY_WORDS = ("תודיע", "להודיע", "התראה", "תשלח", "לשלוח")

#: Words that make a request sensitive enough to require confirmation.
_SENSITIVE_TARGETS = ("דוד", "השקיה", "תריס", "תריסים")

_DAY_WORDS: dict[str, int] = {
    "ראשון": 0,
    "שני": 1,
    "שלישי": 2,
    "רביעי": 3,
    "חמישי": 4,
    "שישי": 5,
    "שבת": 6,
}

_NUMBER_WORDS: dict[str, int] = {
    "אחת": 1, "אחד": 1, "שתיים": 2, "שניים": 2, "שתים": 2, "שלוש": 3, "ארבע": 4,
    "חמש": 5, "שש": 6, "שבע": 7, "שמונה": 8, "תשע": 9, "עשר": 10,
    "אחת עשרה": 11, "שתים עשרה": 12,
}

_DOMAIN_BY_CATEGORY = {
    "light": "light",
    "climate": "climate",
    "camera": "camera",
    "cover": "cover",
    "switch": "switch",
    "boiler": "switch",
    "vacuum": "vacuum",
    "sensor": "sensor",
}


# --- stage 1: normalisation -------------------------------------------------

_PUNCTUATION = re.compile(r"[^\w\s:\u0590-\u05FF]", re.UNICODE)
_WHITESPACE = re.compile(r"\s+")


def normalize(text: str) -> str:
    """Strip niqqud, punctuation and the Hebrew ``ב-`` prefix dash.

    Kept deliberately conservative: it must not change the meaning of a command,
    only its shape.
    """
    stripped = unicodedata.normalize("NFKD", text)
    stripped = "".join(ch for ch in stripped if not unicodedata.combining(ch))
    stripped = stripped.replace("־", " ").replace("-", " ")
    stripped = _PUNCTUATION.sub(" ", stripped)
    return _WHITESPACE.sub(" ", stripped).strip()


# --- stage 2: intent family -------------------------------------------------


@dataclass(frozen=True)
class Intent:
    family: ProbeFamily
    action: str | None
    action_label: str | None


def classify(text: str) -> Intent:
    words = text.split()
    action: str | None = None
    action_label: str | None = None

    for stems, act, label in _ACTIONS:
        if any(any(word.startswith(stem) or stem in word for word in words) for stem in stems):
            action, action_label = act, label
            break

    if any(word in text for word in _SHABBAT_WORDS) and "שעון שבת" in text:
        return Intent(ProbeFamily.SHABBAT, action, action_label)
    if any(word in text for word in _TASK_WORDS):
        return Intent(ProbeFamily.TASK, action or "add", action_label or "להוסיף")
    if any(word in text for word in _CALENDAR_WORDS):
        return Intent(ProbeFamily.CALENDAR, action or "read", action_label or "לקרוא")
    if any(word in text for word in _NOTIFY_WORDS):
        return Intent(ProbeFamily.NOTIFICATION, action or "notify", action_label or "להודיע")
    if action is None and words and words[0] in _QUERY_WORDS:
        return Intent(ProbeFamily.QUERY, "read", "לבדוק")
    if action is None:
        return Intent(ProbeFamily.UNKNOWN, None, None)
    return Intent(ProbeFamily.CONTROL, action, action_label)


# --- stage 3: target resolution --------------------------------------------


#: Hebrew one-letter prefixes (definite article and common prepositions).
_PREFIX_LETTERS = "הבלו"


def _stem(word: str) -> str:
    """Strip leading Hebrew prefixes down to a stable fixpoint.

    Stripping greedily is what makes the comparison work: "המטבח", "במטבח" and
    "מטבח" all converge on the same stem, so an alias matches whether or not the
    speaker attached a definite article. The stem is not linguistically correct
    (``הורים`` becomes ``רים``) and does not need to be — it only has to be the
    *same* on both sides of the comparison.
    """
    while len(word) > 3 and word[0] in _PREFIX_LETTERS:
        word = word[1:]
    return word


def _stems(text: str) -> list[str]:
    return [_stem(word) for word in text.split() if word]


def resolve_target(text: str, devices: list[Device]) -> ProbeTarget:
    """Match spoken text against device aliases, most specific alias first.

    Matching is token-based rather than substring-based so "תדליק את אור המטבח"
    still resolves to the device whose alias is "אור מטבח". An alias matches only
    when *all* of its tokens appear, which keeps "מזגן סלון" from matching a
    sentence that talks about "מזגן הורים"; the longest matching alias wins, so
    "מזגן חדר בנות" beats a bare "מזגן".
    """
    text_stems = set(_stems(text))

    best: tuple[int, Device, str] | None = None
    for device in devices:
        candidates = {*device.aliases, device.display_name}
        for alias in candidates:
            alias_stems = _stems(normalize(alias))
            if not alias_stems or not all(stem in text_stems for stem in alias_stems):
                continue
            score = sum(len(stem) for stem in alias_stems)
            if best is None or score > best[0]:
                best = (score, device, alias)

    if best is None:
        return ProbeTarget(confidence=0.0)

    _, device, alias = best
    # Confidence grows with how much of the alias we matched, capped at 0.99.
    confidence = min(0.99, 0.55 + len(normalize(alias)) / 40)
    return ProbeTarget(
        id=device.id,
        name=device.display_name,
        room=device.room,
        matched_alias=alias,
        confidence=round(confidence, 2),
    )


# --- stage 4: schedule resolution ------------------------------------------

_TIME_RE = re.compile(r"\b(\d{1,2}):(\d{2})\b")
_BARE_HOUR_RE = re.compile(r"\bבשעה (\d{1,2})\b")


def _apply_day_part(hour: int, text: str) -> int:
    """Shift a 1–12 hour into 24h form using 'בערב' / 'בלילה' / 'בבוקר'."""
    if hour > 12:
        return hour
    if "בערב" in text or "בלילה" in text:
        # 1–5 at night is already the small hours; 6–12 becomes evening.
        return hour if hour <= 5 else hour + 12
    if "בצהריים" in text and hour < 12:
        return hour + 12
    if "אחר הצהריים" in text and hour < 12:
        return hour + 12
    return hour


def _extract_time(text: str) -> str | None:
    match = _TIME_RE.search(text)
    if match:
        hour = _apply_day_part(int(match.group(1)), text)
        minute = int(match.group(2))
        if 0 <= hour <= 23 and 0 <= minute <= 59:
            return f"{hour:02d}:{minute:02d}"
        return None

    match = _BARE_HOUR_RE.search(text)
    if match:
        hour = _apply_day_part(int(match.group(1)), text)
        if 0 <= hour <= 23:
            return f"{hour:02d}:00"
        return None

    for word, value in _NUMBER_WORDS.items():
        if f"בשעה {word}" in text:
            return f"{_apply_day_part(value, text):02d}:00"
    return None


def _extract_days(text: str) -> list[int]:
    days = [index for word, index in _DAY_WORDS.items() if f"יום {word}" in text or
            f"בימי {word}" in text or f"ובימי {word}" in text or f"ו{word}" in text]
    if "כל יום" in text or "כל יומ" in text:
        return list(range(7))
    if "בימי חול" in text:
        return [0, 1, 2, 3, 4]
    return sorted(set(days))


def resolve_schedule(text: str, family: ProbeFamily) -> ProbeSchedule | None:
    """Work out *when* the request should happen.

    Returns ``None`` when the request is immediate, which the caller renders as
    a skipped pipeline step rather than a failure.
    """
    if family in (ProbeFamily.QUERY, ProbeFamily.UNKNOWN):
        return None

    clock = _extract_time(text)
    days = _extract_days(text)
    current = now()

    if days:
        return ProbeSchedule(
            kind="weekly",
            time=clock,
            days=days,
            description=f"בכל יום {' ו'.join(HEBREW_DAYS[d] for d in days)}"
            + (f" בשעה {clock}" if clock else ""),
        )

    if "כל יום" in text:
        return ProbeSchedule(kind="daily", time=clock, description=f"כל יום בשעה {clock}")

    if clock is None:
        return ProbeSchedule(kind="immediate", description="מיד")

    # A clock time with no day: today if still ahead, otherwise tomorrow.
    target_date = current.date()
    hour, minute = int(clock[:2]), int(clock[3:])
    if "מחר" in text or (hour, minute) <= (current.hour, current.minute):
        target_date = days_ahead(1).date()

    day_word = "מחר" if target_date != current.date() else "היום"
    return ProbeSchedule(
        kind="one_time",
        time=clock,
        date=target_date.isoformat(),
        description=f"{day_word} בשעה {clock}",
    )


# --- stage 5: skill selection ----------------------------------------------


def select_skill(family: ProbeFamily, schedule: ProbeSchedule | None) -> str:
    if family is ProbeFamily.UNKNOWN:
        # Bobi would ask for clarification rather than pick a skill.
        return "clarify"
    if family is ProbeFamily.TASK:
        return "tasks"
    if family is ProbeFamily.CALENDAR:
        return "calendar"
    if family is ProbeFamily.SHABBAT:
        return "shabbat_clock"
    if family is ProbeFamily.NOTIFICATION:
        return "smart_notify"
    if family is ProbeFamily.QUERY:
        return "state_query"
    if schedule and schedule.kind in ("one_time", "daily", "weekly"):
        return "local_schedule"
    return "direct_control"


# --- the engine -------------------------------------------------------------


class ProbeEngine:
    """Runs text through every stage and assembles a :class:`ProbeResult`."""

    def __init__(self, devices: list[Device]) -> None:
        self._devices = devices

    def probe(self, text: str) -> ProbeResult:
        started = time.perf_counter()

        normalized = normalize(text)
        intent = classify(normalized)
        target = resolve_target(normalized, self._devices)
        schedule = resolve_schedule(normalized, intent.family)
        family = intent.family

        # A control verb aimed at a resolvable device, at a future time, is a
        # schedule rather than an immediate control action.
        if family is ProbeFamily.CONTROL and schedule and schedule.kind != "immediate":
            family = ProbeFamily.SCHEDULE

        skill = select_skill(family, schedule)
        domain = self._domain_for(target)
        warnings = self._warnings(family, target, schedule)
        safe = self._is_safe(normalized, target, warnings)
        confidence = self._confidence(family, target, schedule)

        result = ProbeResult(
            original_text=text,
            normalized_text=normalized,
            family=family,
            domain=domain,
            action=intent.action,
            target=target,
            schedule=schedule,
            skill=skill,
            safe=safe,
            # Hard-coded, never derived: the probe endpoint cannot execute.
            would_execute=False,
            warnings=warnings,
            confidence=confidence,
            duration_ms=int((time.perf_counter() - started) * 1000),
        )
        result.steps = self._steps(result, intent)
        return result

    # --- helpers ---------------------------------------------------------
    def _domain_for(self, target: ProbeTarget) -> str | None:
        if not target.id:
            return None
        device = next((d for d in self._devices if d.id == target.id), None)
        if device is None:
            return None
        category = (
            device.category.value if hasattr(device.category, "value") else str(device.category)
        )
        return _DOMAIN_BY_CATEGORY.get(category, category)

    def _warnings(
        self,
        family: ProbeFamily,
        target: ProbeTarget,
        schedule: ProbeSchedule | None,
    ) -> list[str]:
        warnings: list[str] = []
        if family is ProbeFamily.UNKNOWN:
            warnings.append("לא הצלחתי להבין מה מבקשים לעשות.")
        if family in (ProbeFamily.CONTROL, ProbeFamily.SCHEDULE) and not target.id:
            warnings.append("לא זיהיתי על איזה מכשיר מדובר.")
        if target.id:
            device = next((d for d in self._devices if d.id == target.id), None)
            if device is not None and not device.available:
                warnings.append(f"{device.display_name} אינו זמין כרגע.")
        if schedule and schedule.kind == "one_time" and schedule.time:
            hour = int(schedule.time[:2])
            if 0 <= hour < 5:
                warnings.append("הפעולה מתוזמנת לשעת לילה מאוחרת.")
        return warnings

    def _is_safe(self, text: str, target: ProbeTarget, warnings: list[str]) -> bool:
        """Sensitive targets are flagged so the UI asks before Phase 2 executes."""
        if any(word in text for word in _SENSITIVE_TARGETS):
            return False
        return not any("לא הצלחתי להבין" in w for w in warnings)

    def _confidence(
        self,
        family: ProbeFamily,
        target: ProbeTarget,
        schedule: ProbeSchedule | None,
    ) -> float:
        if family is ProbeFamily.UNKNOWN:
            return 0.1
        score = 0.5
        score += target.confidence * 0.35
        if schedule and schedule.kind != "immediate":
            score += 0.15
        return round(min(score, 0.99), 2)

    def _steps(self, result: ProbeResult, intent: Intent) -> list[ProbeStep]:
        family_labels = {
            ProbeFamily.SCHEDULE: "תזמון",
            ProbeFamily.CONTROL: "שליטה",
            ProbeFamily.QUERY: "שאלה",
            ProbeFamily.TASK: "משימה",
            ProbeFamily.CALENDAR: "יומן",
            ProbeFamily.NOTIFICATION: "התראה",
            ProbeFamily.SHABBAT: "שעון שבת",
            ProbeFamily.UNKNOWN: "לא זוהה",
        }
        steps = [
            ProbeStep(id="text", label="טקסט", status="ok", value=result.original_text),
            ProbeStep(id="normalize", label="נרמול", status="ok", value=result.normalized_text),
            ProbeStep(
                id="understand",
                label="הבנה",
                status="ok" if result.family is not ProbeFamily.UNKNOWN else "failed",
                value=family_labels[result.family],
                detail=intent.action_label,
            ),
            ProbeStep(
                id="target",
                label="יעד",
                status="ok" if result.target.id else "warning",
                value=result.target.name or "לא זוהה",
                detail=(
                    f"זוהה מהכינוי \u201e{result.target.matched_alias}\u201d"
                    if result.target.matched_alias
                    else "אין התאמה לכינוי מוכר"
                ),
            ),
        ]

        if result.schedule and result.schedule.kind != "immediate":
            steps.append(
                ProbeStep(
                    id="time",
                    label="זמן",
                    status="ok",
                    value=result.schedule.time or result.schedule.description,
                    detail=result.schedule.description,
                )
            )
        else:
            steps.append(
                ProbeStep(id="time", label="זמן", status="skipped", value="מיד",
                          detail="אין רכיב תזמון בבקשה")
            )

        steps.append(
            ProbeStep(id="skill", label="Skill", status="ok", value=result.skill)
        )
        steps.append(
            ProbeStep(
                id="safety",
                label="בדיקת בטיחות",
                status="ok" if result.safe else "warning",
                value="בטוח" if result.safe else "דורש אישור",
                detail="לא בוצעה שום פעולה",
            )
        )
        return steps
