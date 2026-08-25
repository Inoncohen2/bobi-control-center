"""Automation serialization, summaries and the preview/confirm flow."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.errors import ValidationError
from app.models import (
    AutomationAction,
    AutomationDraft,
    AutomationTarget,
    AutomationType,
)
from app.services.automations import build_summary, draft_to_automation, validate_draft


def _draft(**overrides: object) -> AutomationDraft:
    payload: dict[str, object] = {
        "name": "אור מטבח בערב",
        "automation_type": AutomationType.WEEKLY,
        "targets": [AutomationTarget(id="kitchen_light", name="אור מטבח", room="מטבח")],
        "actions": [AutomationAction(type="turn_on", label="להדליק")],
        "days": [0, 4],
        "start_time": "19:00",
    }
    payload.update(overrides)
    return AutomationDraft(**payload)  # type: ignore[arg-type]


# --- serialization ----------------------------------------------------------
def test_list_automations_covers_every_type(client: TestClient) -> None:
    automations = client.get("/api/bobi/automations").json()["automations"]
    types = {a["automation_type"] for a in automations}
    assert {
        "one_time",
        "weekly",
        "daily",
        "time_window",
        "multi_time",
        "conditional",
        "smart_notification",
    } <= types


def test_every_automation_has_a_human_summary(client: TestClient) -> None:
    automations = client.get("/api/bobi/automations").json()["automations"]
    assert all(a["summary"] for a in automations)


def test_cross_midnight_flag_is_computed_server_side(client: TestClient) -> None:
    automation = client.get("/api/bobi/automations/living_room_ac_night").json()
    assert automation["start_time"] == "22:00"
    assert automation["end_time"] == "01:00"
    assert automation["crosses_midnight"] is True

    same_day = client.get("/api/bobi/automations/kitchen_light_evening").json()
    assert same_day["crosses_midnight"] is False


def test_automation_never_exposes_home_assistant_yaml(client: TestClient) -> None:
    automation = client.get("/api/bobi/automations/kitchen_light_evening").json()
    assert "trigger" not in automation
    assert "condition" not in automation
    assert "service" not in automation
    # Anything technical lives under `advanced`.
    assert automation["advanced"]["object_id"] == "bobi_sched_0001"


# --- summaries --------------------------------------------------------------
def test_summary_reads_like_a_sentence() -> None:
    summary = build_summary(_draft())
    assert summary == "בכל יום ראשון וחמישי בשעה 19:00 להדליק את אור מטבח"


def test_summary_marks_a_window_that_crosses_midnight() -> None:
    summary = build_summary(_draft(start_time="22:00", end_time="01:00"))
    assert "למחרת" in summary


# --- validation -------------------------------------------------------------
@pytest.mark.parametrize(
    ("overrides", "field"),
    [
        ({"name": "  "}, "name"),
        ({"targets": []}, "targets"),
        ({"actions": []}, "actions"),
        ({"days": []}, "days"),
        ({"start_time": "25:00"}, "time"),
    ],
)
def test_invalid_drafts_are_rejected(overrides: dict, field: str) -> None:
    with pytest.raises(ValidationError) as exc:
        validate_draft(_draft(**overrides))
    assert exc.value.details["field"] == field


def test_draft_becomes_an_automation_with_derived_fields() -> None:
    automation = draft_to_automation(_draft(start_time="22:00", end_time="01:00"))
    assert automation.id
    assert automation.crosses_midnight is True
    assert automation.summary


# --- preview / confirm ------------------------------------------------------
def test_preview_then_confirm_saves(client: TestClient) -> None:
    draft = _draft(name="אור חצר חדש").model_dump(mode="json")

    preview = client.post("/api/bobi/automations/preview", json=draft).json()
    assert preview["requires_confirmation"] is True
    assert preview["token"]
    assert preview["summary"]

    result = client.post(
        "/api/bobi/automations/confirm", json={"draft": draft, "token": preview["token"]}
    ).json()
    assert result["success"] is True
    # Phase 1: recorded, but never applied to a real system.
    assert result["dry_run"] is True
    assert result["applied"] is False
    assert result["audit_id"]

    names = [a["name"] for a in client.get("/api/bobi/automations").json()["automations"]]
    assert "אור חצר חדש" in names


def test_confirm_without_a_preview_token_is_refused(client: TestClient) -> None:
    draft = _draft().model_dump(mode="json")
    response = client.post(
        "/api/bobi/automations/confirm", json={"draft": draft, "token": "made-up"}
    )
    assert response.status_code == 409
    assert response.json()["code"] == "preview_required"


def test_a_token_cannot_be_reused_for_a_different_payload(client: TestClient) -> None:
    draft = _draft().model_dump(mode="json")
    token = client.post("/api/bobi/automations/preview", json=draft).json()["token"]

    tampered = {**draft, "start_time": "03:00"}
    response = client.post(
        "/api/bobi/automations/confirm", json={"draft": tampered, "token": token}
    )
    assert response.status_code == 409
    assert response.json()["code"] == "preview_required"


def test_delete_requires_preview_and_is_marked_destructive(client: TestClient) -> None:
    preview = client.post(
        "/api/bobi/automations/vacuum_weekly/delete/preview"
    ).json()
    assert preview["destructive"] is True
    assert preview["warnings"]

    result = client.post(
        "/api/bobi/automations/vacuum_weekly/delete/confirm",
        json={"token": preview["token"]},
    ).json()
    assert result["success"] is True

    remaining = client.get("/api/bobi/automations").json()["automations"]
    assert "vacuum_weekly" not in {a["id"] for a in remaining}


def test_toggle_and_duplicate(client: TestClient) -> None:
    toggled = client.post(
        "/api/bobi/automations/kitchen_light_evening/toggle", json={"enabled": False}
    ).json()
    assert toggled["enabled"] is False

    clone = client.post("/api/bobi/automations/kitchen_light_evening/duplicate").json()
    assert clone["id"] != "kitchen_light_evening"
    assert clone["name"].endswith("(עותק)")
    # A duplicate starts disabled so it cannot fire unnoticed.
    assert clone["enabled"] is False
