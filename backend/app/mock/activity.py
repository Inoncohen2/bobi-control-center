"""Mock dashboard activity, diagnostics, regression suites, audit and tasks."""

from __future__ import annotations

from app.models import (
    ActivityEntry,
    Advanced,
    AttentionItem,
    AuditEntry,
    CalendarEvent,
    ComponentHealth,
    DiagnosticIssue,
    HealthState,
    Severity,
    Source,
    StatItem,
    Task,
    TestCase,
    TestSuite,
)
from app.timeutil import (
    days_ago,
    days_ahead,
    hebrew_day_label,
    hhmm,
    hours_ago,
    minutes_ago,
)

MOCK_COMPONENTS: list[ComponentHealth] = [
    ComponentHealth(
        id="bobi",
        name="בובי",
        state=HealthState.ONLINE,
        label="פעיל",
        detail="מגיב לפקודות כרגיל",
    ),
    ComponentHealth(
        id="whatsapp",
        name="WhatsApp",
        state=HealthState.ONLINE,
        label="מחובר",
        detail="החיבור יציב מאז אתמול",
    ),
    ComponentHealth(
        id="ai",
        name="AI",
        state=HealthState.ONLINE,
        label="פעיל",
        detail="נעזר במודל שפה כשצריך",
    ),
    ComponentHealth(
        id="home_assistant",
        name="Home Assistant",
        state=HealthState.ONLINE,
        label="מחובר",
        detail="מצב הדגמה — אין גישה למערכת אמיתית",
    ),
]


def build_stats(
    active_automations: int,
    schedules: int,
    notifications: int,
    open_tasks: int,
    attention: int,
) -> list[StatItem]:
    return [
        StatItem(id="automations", label="אוטומציות פעילות", value=active_automations,
                 hint="מתוך כלל האוטומציות"),
        StatItem(id="schedules", label="תזמונים", value=schedules, hint="כולל שעון שבת"),
        StatItem(id="notifications", label="הודעות חכמות", value=notifications,
                 hint="כללים פעילים"),
        StatItem(id="tasks", label="משימות פתוחות", value=open_tasks),
        StatItem(
            id="attention",
            label="בעיות שדורשות תשומת לב",
            value=attention,
            severity=Severity.WARNING if attention else Severity.OK,
        ),
    ]


def build_activity() -> list[ActivityEntry]:
    raw = [
        (12, "בובי שלח תזכורת לפגישה", "פגישת צוות בשעה 10:00", "bell", Severity.OK),
        (39, "מזגן סלון כובה לפי תזמון", "תזמון: מזגן סלון בלילה", "air-vent", Severity.OK),
        (84, "הופעל שעון שבת", "נטענו 6 תזמוני מכשירים", "candlestick", Severity.OK),
        (110, "נוספה משימה חדשה", "לקבוע תור לרופא", "check-square", Severity.OK),
        (145, "מצלמת ליה הפסיקה לשדר", "בובי ניסה להתחבר מחדש 3 פעמים", "camera-off",
         Severity.WARNING),
        (190, "אור מטבח הודלק", "פקודה בוואטסאפ מינון", "lightbulb", Severity.OK),
        (240, "רובי סיים ניקוי", "מטבח וסלון", "bot", Severity.OK),
        (320, "בובי לא הבין פקודה", "'תדליק את הדבר ההוא' — נשלחה בקשת הבהרה", "help-circle",
         Severity.WARNING),
    ]
    entries: list[ActivityEntry] = []
    for index, (mins, title, detail, icon, severity) in enumerate(raw):
        stamp = minutes_ago(mins)
        entries.append(
            ActivityEntry(
                id=f"act_{index}",
                time=hhmm(stamp),
                timestamp=stamp,
                title=title,
                detail=detail,
                icon=icon,
                severity=severity,
            )
        )
    return entries


MOCK_ATTENTION: list[AttentionItem] = [
    AttentionItem(
        id="att_camera_lia",
        title="מצלמת ליה אינה זמינה",
        description="בובי לא מצליח להתחבר למצלמה כבר כשעתיים. לא ניתן לצלם ממנה תמונה.",
        severity=Severity.WARNING,
        component="מצלמות",
        technical_details="camera.demo_lia_room · state=unavailable · last_seen 02:12",
        action_label="למסך התקלות",
        action_href="/diagnostics",
    ),
    AttentionItem(
        id="att_camera_shaya",
        title="מצלמת שיה אינה זמינה",
        description="גם המצלמה השנייה בחדר הבנות לא משדרת. ייתכן שהמתח בשקע נותק.",
        severity=Severity.WARNING,
        component="מצלמות",
        technical_details="camera.demo_shaya_room · state=unavailable · last_seen 01:58",
        action_label="למסך התקלות",
        action_href="/diagnostics",
    ),
    AttentionItem(
        id="att_ac_left_on",
        title="מזגן חדר בנות דולק כבר 5 שעות",
        description="אפשר לכבות אותו מכאן או להגדיר כיבוי אוטומטי.",
        severity=Severity.WARNING,
        component="מזגנים",
        technical_details="climate.demo_girls_ac · state=cool · since 09:40",
        action_label="למסך המכשירים",
        action_href="/devices",
    ),
]


MOCK_DIAGNOSTICS: list[DiagnosticIssue] = [
    DiagnosticIssue(
        id="diag_camera_shaya",
        severity=Severity.ERROR,
        title="מצלמת שיה אינה זמינה",
        description="המצלמה לא משדרת ובובי לא יכול לצלם ממנה. בדרך כלל זה נפתר בניתוק וחיבור של השקע.",
        component="מצלמות",
        first_seen=hours_ago(9),
        last_seen=minutes_ago(4),
        occurrences=27,
        suggested_action="לנתק ולחבר את שקע המצלמה, ואם זה לא עוזר לבדוק את חיבור הרשת.",
        technical_details=(
            "entity: camera.demo_shaya_room\n"
            "state: unavailable\n"
            "integration: generic (mock)\n"
            "last_error: ConnectTimeout after 5.0s"
        ),
    ),
    DiagnosticIssue(
        id="diag_camera_lia",
        severity=Severity.ERROR,
        title="מצלמת ליה אינה זמינה",
        description="בובי מנסה להתחבר מחדש כל כמה דקות ולא מצליח.",
        component="מצלמות",
        first_seen=hours_ago(2),
        last_seen=minutes_ago(2),
        occurrences=14,
        suggested_action="לבדוק שהמצלמה מקבלת חשמל ושהיא מופיעה ברשת הביתית.",
        technical_details=(
            "entity: camera.demo_lia_room\nstate: unavailable\nretries: 14\n"
            "last_error: ConnectTimeout after 5.0s"
        ),
    ),
    DiagnosticIssue(
        id="diag_whatsapp",
        severity=Severity.WARNING,
        title="WhatsApp נותק וחובר מחדש",
        description="החיבור נפל לכ-40 שניות ואז חזר לבד. הודעות שנשלחו באותו זמן נשלחו שוב.",
        component="WhatsApp",
        first_seen=hours_ago(19),
        last_seen=hours_ago(19),
        occurrences=2,
        suggested_action="אין צורך בפעולה. אם זה חוזר כמה פעמים ביום כדאי לבדוק את חיבור האינטרנט.",
        technical_details="session reconnect · downtime 41s · messages_requeued=2",
    ),
    DiagnosticIssue(
        id="diag_missing_entity",
        severity=Severity.WARNING,
        title="מכשיר שבובי הכיר כבר לא קיים",
        description="תזמון ישן מפנה למכשיר שהוסר מהבית. התזמון לא ירוץ.",
        component="תזמונים",
        first_seen=days_ago(4),
        last_seen=hours_ago(6),
        occurrences=6,
        suggested_action="למחוק את התזמון הישן או להפנות אותו למכשיר אחר.",
        technical_details="referenced entity 'switch.demo_old_heater' not found in registry",
    ),
    DiagnosticIssue(
        id="diag_task_missing",
        severity=Severity.WARNING,
        title="משימה שבובי חיפש לא נמצאה",
        description="ניסית לסמן משימה כהושלמה אבל היא כבר נמחקה מהרשימה.",
        component="משימות",
        first_seen=days_ago(2),
        last_seen=days_ago(2),
        occurrences=1,
        suggested_action="אין צורך בפעולה.",
        technical_details="todo item id 'task_legacy_11' not present in list 'משימות ינון'",
    ),
    DiagnosticIssue(
        id="diag_regression",
        severity=Severity.OK,
        title="כל בדיקות הרגרסיה עברו",
        description="הריצה האחרונה של הבדיקות האוטומטיות הסתיימה בהצלחה.",
        component="בדיקות",
        first_seen=hours_ago(6),
        last_seen=hours_ago(6),
        occurrences=1,
        suggested_action=None,
        technical_details="suites=5 passed=252 failed=0",
    ),
]


def build_test_suites() -> list[TestSuite]:
    definitions = [
        ("understanding", "הבנת פקודות", "בובי מבין נכון מה ביקשו ממנו.", 115, 0, 4120),
        ("safety", "בטיחות", "פקודות מסוכנות נחסמות או דורשות אישור.", 30, 0, 980),
        ("multi_intent", "Multi Intent", "כמה בקשות בהודעה אחת.", 22, 0, 1340),
        ("schedules", "תזמונים", "פירוק זמנים, ימים וחציית חצות.", 76, 0, 2560),
        ("tasks", "משימות", "הוספה, סימון ומחיקה של משימות.", 9, 0, 410),
    ]
    suites: list[TestSuite] = []
    for suite_id, name, description, passed, failed, duration in definitions:
        cases = [
            TestCase(
                id=f"{suite_id}_case_{i}",
                name=f"{name} — מקרה {i + 1}",
                passed=True,
                duration_ms=max(4, duration // max(passed, 1)),
            )
            for i in range(min(passed, 5))
        ]
        suites.append(
            TestSuite(
                id=suite_id,
                name=name,
                description=description,
                total=passed + failed,
                passed=passed,
                failed=failed,
                duration_ms=duration,
                last_run=hours_ago(6),
                cases=cases,
            )
        )
    return suites


MOCK_TASKS: list[Task] = [
    Task(id="task_1", title="לקבוע תור לרופא", owner="ינון", completed=False,
         due=days_ahead(2), due_label="בעוד יומיים", list_name="משימות ינון",
         created_by="בובי", advanced=Advanced(object_id="todo_item_1")),
    Task(id="task_2", title="לקנות חלב וביצים", owner="הודיה", completed=False,
         due=days_ahead(1), due_label="מחר", list_name="משימות הודיה", created_by="הודיה"),
    Task(id="task_3", title="לשלם ארנונה", owner="ינון", completed=False,
         due=days_ahead(5), due_label="בעוד 5 ימים", list_name="משימות ינון", created_by="ינון"),
    Task(id="task_4", title="להזמין מתנה ליום הולדת", owner="הודיה", completed=False,
         due=days_ahead(9), due_label="בעוד 9 ימים", list_name="משימות הודיה",
         created_by="בובי"),
    Task(id="task_5", title="לבדוק את מסנן המזגן", owner="ינון", completed=False,
         due=None, due_label=None, list_name="משימות ינון", created_by="בובי"),
    Task(id="task_6", title="לחדש ביטוח רכב", owner="ינון", completed=True,
         due=days_ago(2), due_label="הושלמה", list_name="משימות ינון", created_by="ינון"),
    Task(id="task_7", title="לתאם גננת", owner="הודיה", completed=True,
         due=days_ago(4), due_label="הושלמה", list_name="משימות הודיה", created_by="הודיה"),
]


def build_calendar_events() -> list[CalendarEvent]:
    definitions = [
        (1, 9, 30, "רופא שיניים", "ינון", "מרפאת שיניים, רמת גן",
         ["התראות פגישה", "נסיעות"]),
        (1, 17, 0, "חוג התעמלות — ליה", "הודיה", "מתנ\"ס", ["התראות פגישה"]),
        (2, 10, 0, "פגישת צוות", "ינון", None, ["התראות פגישה"]),
        (3, 8, 15, "אסיפת הורים", "הודיה", "בית ספר", ["התראות פגישה", "נסיעות"]),
        (5, 19, 0, "ארוחת שישי", "הודיה", "בית", ["שעון שבת"]),
    ]
    events: list[CalendarEvent] = []
    for index, (offset, hour, minute, title, owner, location, features) in enumerate(definitions):
        start = days_ahead(offset).replace(hour=hour, minute=minute, second=0, microsecond=0)
        events.append(
            CalendarEvent(
                id=f"event_{index}",
                title=title,
                owner=owner,
                start=start,
                end=None,
                day_label=hebrew_day_label(start),
                time_label=hhmm(start),
                location=location,
                bobi_features=features,
                advanced=Advanced(object_id=f"calendar_event_{index}"),
            )
        )
    return events


def build_audit_entries() -> list[AuditEntry]:
    definitions = [
        (8, "ינון", "update", "עודכן", "automation", "kitchen_light_evening", "אור מטבח בערב",
         {"end_time": "21:30"}, {"end_time": "22:00"}, Source.WEB),
        (55, "ינון", "toggle", "הופעל", "capability", "vision", "עיבוד תמונות",
         {"enabled": True}, {"enabled": False}, Source.WEB),
        (95, "בובי", "create", "נוצר", "automation", "parents_ac_one_time",
         "כיבוי מזגן הורים הלילה", None, {"time": "01:30"}, Source.WHATSAPP),
        (140, "ינון", "update", "עודכן", "shabbat", "sch_living_room_ac", "מזגן סלון",
         {"end": "00:30"}, {"end": "01:00"}, Source.WEB),
        (300, "הודיה", "create", "נוצרה", "task", "task_2", "לקנות חלב וביצים",
         None, {"title": "לקנות חלב וביצים"}, Source.WHATSAPP),
        (420, "מערכת", "update", "עודכן", "system", "shabbat_times", "זמני שבת",
         None, {"candle_lighting": "18:52"}, Source.SYSTEM),
        (900, "ינון", "delete", "נמחק", "automation", "old_heater_schedule", "תזמון תנור ישן",
         {"enabled": True}, None, Source.WEB),
        (1500, "ינון", "update", "עודכנו הרשאות", "user", "hodaya", "הודיה",
         {"permissions": 4}, {"permissions": 5}, Source.WEB),
    ]
    entries: list[AuditEntry] = []
    for index, (
        mins, user, operation, op_label, r_type, r_id, r_label, before, after, source
    ) in enumerate(definitions):
        entries.append(
            AuditEntry(
                id=f"audit_{index}",
                timestamp=minutes_ago(mins),
                user=user,
                operation=operation,
                operation_label=op_label,
                resource_type=r_type,
                resource_id=r_id,
                resource_label=r_label,
                before=before,
                after=after,
                success=True,
                source=source,
            )
        )
    return entries
