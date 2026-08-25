"""Shabbat clock: cross-midnight handling and the draft → preview → confirm flow."""

from __future__ import annotations

import copy

import pytest
from fastapi.testclient import TestClient

from app.errors import ValidationError
from app.models import ShabbatDeviceSchedule, ShabbatDraft, TimeRange
from app.services.shabbat import range_label, recompute, validate_draft
from app.timeutil import crosses_midnight, duration_label


# --- the cross-midnight rule ------------------------------------------------
@pytest.mark.parametrize(
    ("start", "end", "expected"),
    [
        ("17:42", "23:30", False),
        ("22:00", "01:00", True),
        ("18:00", "00:30", True),
        ("00:15", "06:00", False),
        ("23:59", "00:01", True),
    ],
)
def test_crosses_midnight(start: str, end: str, expected: bool) -> None:
    assert crosses_midnight(start, end) is expected


def test_duration_spans_midnight_correctly() -> None:
    assert duration_label("22:00", "01:00") == "3 שעות"
    assert duration_label("17:42", "23:30") == "5 שעות ו-48 דקות"


def test_range_label_marks_the_next_day() -> None:
    from app.services.shabbat import LRI, PDI

    assert range_label("22:00", "01:00") == f"{LRI}22:00 → 01:00{PDI} + יום הבא"
    assert range_label("17:42", "23:30") == f"{LRI}17:42 → 23:30{PDI}"


def test_range_label_isolates_the_arrow_for_rtl() -> None:
    """The window must be bidi-isolated so the arrow points start-to-end."""
    from app.services.shabbat import LRI, PDI

    label = range_label("22:00", "01:00")
    assert label.startswith(LRI)
    assert label.index(PDI) > label.index("→")


def test_recompute_sets_the_flag_on_every_range() -> None:
    schedule = ShabbatDeviceSchedule(
        id="s1",
        device_id="living_room_ac",
        device_name="מזגן סלון",
        room="סלון",
        ranges=[
            TimeRange(id="r1", start="18:00", end="01:00"),
            TimeRange(id="r2", start="12:00", end="16:00"),
        ],
    )
    recompute(schedule)
    assert schedule.ranges[0].crosses_midnight is True
    assert schedule.ranges[1].crosses_midnight is False


# --- the API ----------------------------------------------------------------
def test_config_is_served_with_flags_already_computed(client: TestClient) -> None:
    config = client.get("/api/bobi/shabbat").json()

    assert config["enabled"] is True
    assert config["times"]["candle_lighting"]
    assert config["schedules"]

    ac = next(s for s in config["schedules"] if s["device_id"] == "living_room_ac")
    friday = next(r for r in ac["ranges"] if r["day"] == "friday")
    assert friday["start"] == "18:00"
    assert friday["end"] == "01:00"
    # The frontend renders this flag rather than re-deriving it.
    assert friday["crosses_midnight"] is True


def test_templates_are_available(client: TestClient) -> None:
    config = client.get("/api/bobi/shabbat").json()
    assert {t["name"] for t in config["templates"]} >= {"שבת רגילה", "שבת עם אורחים"}


def test_preview_then_confirm(client: TestClient) -> None:
    config = client.get("/api/bobi/shabbat").json()
    draft = {
        "enabled": True,
        "schedules": config["schedules"],
        "active_template_id": config["active_template_id"],
    }
    # Move the living-room AC an hour later.
    ac = next(s for s in draft["schedules"] if s["device_id"] == "living_room_ac")
    ac["ranges"][0]["end"] = "02:00"

    preview = client.post("/api/bobi/shabbat/preview", json=draft).json()
    assert preview["summary"]
    assert preview["lines"]
    assert any("יום הבא" in line["text"] for line in preview["lines"])
    assert preview["warnings"], "a cross-midnight range should be called out"

    result = client.post(
        "/api/bobi/shabbat/confirm", json={"draft": draft, "token": preview["token"]}
    ).json()
    assert result["success"] is True
    assert result["dry_run"] is True

    saved = client.get("/api/bobi/shabbat").json()
    saved_ac = next(s for s in saved["schedules"] if s["device_id"] == "living_room_ac")
    assert saved_ac["ranges"][0]["end"] == "02:00"


def test_editing_never_applies_without_confirmation(client: TestClient) -> None:
    """A preview on its own must not change the saved configuration."""
    before = client.get("/api/bobi/shabbat").json()
    original_end = before["schedules"][0]["ranges"][0]["end"]

    # Deep-copied so editing the draft cannot also edit the recorded baseline.
    draft = {
        "enabled": True,
        "schedules": copy.deepcopy(before["schedules"]),
        "active_template_id": None,
    }
    draft["schedules"][0]["ranges"][0]["end"] = "23:59"
    client.post("/api/bobi/shabbat/preview", json=draft)

    after = client.get("/api/bobi/shabbat").json()
    assert after["schedules"][0]["ranges"][0]["end"] == original_end


def test_confirm_without_token_is_refused(client: TestClient) -> None:
    config = client.get("/api/bobi/shabbat").json()
    draft = {"enabled": True, "schedules": config["schedules"], "active_template_id": None}
    response = client.post(
        "/api/bobi/shabbat/confirm", json={"draft": draft, "token": "nope"}
    )
    assert response.status_code == 409


def test_identical_start_and_end_is_rejected() -> None:
    draft = ShabbatDraft(
        schedules=[
            ShabbatDeviceSchedule(
                id="s1",
                device_id="kitchen_light",
                device_name="אור מטבח",
                room="מטבח",
                ranges=[TimeRange(id="r1", start="18:00", end="18:00")],
            )
        ]
    )
    with pytest.raises(ValidationError):
        validate_draft(draft)


def test_saving_a_template(client: TestClient) -> None:
    config = client.get("/api/bobi/shabbat").json()
    template = client.post(
        "/api/bobi/shabbat/templates",
        json={
            "name": "שבת קצרה",
            "description": "בדיקה",
            "schedules": config["schedules"][:1],
        },
    ).json()

    assert template["id"].startswith("tpl_")
    assert template["name"] == "שבת קצרה"

    names = {t["name"] for t in client.get("/api/bobi/shabbat").json()["templates"]}
    assert "שבת קצרה" in names
