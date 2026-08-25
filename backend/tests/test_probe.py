"""The probe endpoint and each stage of the pipeline."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.models import ProbeFamily
from app.services.probe import classify, normalize, resolve_schedule


def probe(client: TestClient, text: str) -> dict:
    response = client.post("/api/bobi/probe", json={"text": text})
    assert response.status_code == 200
    return response.json()


# --- the safety contract ----------------------------------------------------
@pytest.mark.parametrize(
    "text",
    [
        "כבה מזגן הורים ב-1:30 בלילה",
        "תדליק את הדוד",
        "תמחק את כל האוטומציות",
        "בלה בלה בלה",
        "",
    ],
)
def test_probe_never_executes(client: TestClient, text: str) -> None:
    if not text:
        # An empty request is rejected before it reaches the pipeline.
        assert client.post("/api/bobi/probe", json={"text": text}).status_code == 422
        return
    assert probe(client, text)["would_execute"] is False


def test_probe_does_not_change_any_state(client: TestClient) -> None:
    before = client.get("/api/bobi/devices").json()
    probe(client, "תכבה את המזגן בסלון")
    assert client.get("/api/bobi/devices").json() == before


# --- the worked example from the product spec -------------------------------
def test_scheduled_turn_off(client: TestClient) -> None:
    result = probe(client, "כבה מזגן הורים ב-1:30 בלילה")

    assert result["family"] == "schedule"
    assert result["action"] == "turn_off"
    assert result["domain"] == "climate"
    assert result["target"]["id"] == "parents_ac"
    assert result["target"]["name"] == "מזגן הורים"
    assert result["schedule"]["kind"] == "one_time"
    assert result["schedule"]["time"] == "01:30"
    assert result["schedule"]["date"]
    assert result["skill"] == "local_schedule"
    assert result["would_execute"] is False


def test_pipeline_steps_are_rendered_in_order(client: TestClient) -> None:
    result = probe(client, "כבה מזגן הורים ב-1:30 בלילה")
    assert [step["id"] for step in result["steps"]] == [
        "text",
        "normalize",
        "understand",
        "target",
        "time",
        "skill",
        "safety",
    ]
    assert result["steps"][-1]["detail"] == "לא בוצעה שום פעולה"


# --- individual stages ------------------------------------------------------
def test_normalize_strips_punctuation_and_dashes() -> None:
    assert normalize("כבה, את המזגן! ב-1:30") == "כבה את המזגן ב 1:30"


@pytest.mark.parametrize(
    ("text", "family"),
    [
        ("תדליק את אור הסלון", ProbeFamily.CONTROL),
        ("מה הטמפרטורה בסלון", ProbeFamily.QUERY),
        ("תוסיף משימה לקנות חלב", ProbeFamily.TASK),
        ("מה יש לי ביומן מחר", ProbeFamily.CALENDAR),
        ("קשקוש גמור", ProbeFamily.UNKNOWN),
    ],
)
def test_classify(text: str, family: ProbeFamily) -> None:
    assert classify(normalize(text)).family is family


def test_evening_hour_is_interpreted_as_pm() -> None:
    schedule = resolve_schedule(normalize("תדליק בשעה 8 בערב"), ProbeFamily.CONTROL)
    assert schedule is not None
    assert schedule.time == "20:00"


def test_small_hours_stay_in_the_small_hours() -> None:
    schedule = resolve_schedule(normalize("כבה ב-1:30 בלילה"), ProbeFamily.CONTROL)
    assert schedule is not None
    assert schedule.time == "01:30"


def test_weekly_days_are_detected() -> None:
    schedule = resolve_schedule(
        normalize("בימי ראשון וחמישי בשעה 19:00"), ProbeFamily.CONTROL
    )
    assert schedule is not None
    assert schedule.kind == "weekly"
    assert schedule.days == [0, 4]


# --- target resolution ------------------------------------------------------
@pytest.mark.parametrize(
    ("text", "device_id"),
    [
        ("תדליק את אור המטבח", "kitchen_light"),
        ("תכבה את המזגן בסלון", "living_room_ac"),
        ("תדליק את מזגן חדר בנות", "girls_ac"),
        ("תצלם את מצלמת הכניסה", "entrance_camera"),
    ],
)
def test_aliases_resolve_with_or_without_the_definite_article(
    client: TestClient, text: str, device_id: str
) -> None:
    assert probe(client, text)["target"]["id"] == device_id


def test_the_most_specific_alias_wins(client: TestClient) -> None:
    # "מזגן" alone appears in several aliases; the full phrase must win.
    assert probe(client, "תדליק את מזגן חדר בנות")["target"]["id"] == "girls_ac"


# --- warnings and safety ----------------------------------------------------
def test_unresolvable_target_warns_instead_of_failing(client: TestClient) -> None:
    result = probe(client, "תדליק את הדבר ההוא")
    assert result["target"]["id"] is None
    assert result["warnings"]


def test_unavailable_device_is_flagged(client: TestClient) -> None:
    result = probe(client, "תצלם את מצלמת ליה")
    assert any("אינו זמין" in warning for warning in result["warnings"])


def test_sensitive_target_is_not_marked_safe(client: TestClient) -> None:
    assert probe(client, "תדליק את הדוד")["safe"] is False


def test_late_night_schedule_warns(client: TestClient) -> None:
    result = probe(client, "כבה מזגן הורים ב-1:30 בלילה")
    assert any("לילה" in warning for warning in result["warnings"])


# --- history ----------------------------------------------------------------
def test_history_records_recent_probes(client: TestClient) -> None:
    probe(client, "תדליק את אור המטבח")
    probe(client, "תכבה את המזגן בסלון")

    entries = client.get("/api/bobi/probe/history").json()["entries"]
    assert len(entries) == 2
    # Newest first.
    assert entries[0]["text"] == "תכבה את המזגן בסלון"
    assert entries[0]["summary"]
