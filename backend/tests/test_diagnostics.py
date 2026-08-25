"""Diagnostics, regression suites, users, tasks and the audit log."""

from __future__ import annotations

from fastapi.testclient import TestClient


# --- diagnostics ------------------------------------------------------------
def test_diagnostics_are_grouped_by_severity(client: TestClient) -> None:
    report = client.get("/api/bobi/diagnostics").json()

    assert report["issues"]
    assert report["error_count"] >= 1
    assert report["warning_count"] >= 1
    counted = report["ok_count"] + report["warning_count"] + report["error_count"]
    assert counted == len(report["issues"])


def test_each_issue_is_readable_and_keeps_technical_detail_separate(
    client: TestClient,
) -> None:
    issues = client.get("/api/bobi/diagnostics").json()["issues"]

    for issue in issues:
        assert issue["title"]
        assert issue["description"]
        assert issue["component"]
        assert issue["first_seen"] and issue["last_seen"]
        assert issue["occurrences"] >= 1
        # A human title must not read like a stack trace.
        assert "Traceback" not in issue["title"]
        assert "Error:" not in issue["title"]

    camera = next(i for i in issues if i["id"] == "diag_camera_shaya")
    assert camera["severity"] == "error"
    assert camera["suggested_action"]
    assert "entity:" in camera["technical_details"]


# --- regression suites ------------------------------------------------------
def test_test_report_totals_add_up(client: TestClient) -> None:
    report = client.get("/api/bobi/tests").json()

    assert len(report["suites"]) == 5
    assert report["total"] == sum(s["total"] for s in report["suites"])
    assert report["passed"] == sum(s["passed"] for s in report["suites"])
    assert report["note"], "Phase 1 suites must say they are a simulation"

    understanding = next(s for s in report["suites"] if s["id"] == "understanding")
    assert understanding["total"] == 115
    assert understanding["passed"] == 115


def test_running_the_suites_updates_last_run(client: TestClient) -> None:
    before = client.get("/api/bobi/tests").json()["last_run"]
    after = client.post("/api/bobi/tests/run").json()
    assert after["last_run"] != before
    assert after["failed"] == 0


# --- users ------------------------------------------------------------------
def test_users_and_permission_catalogue(client: TestClient) -> None:
    body = client.get("/api/bobi/users").json()

    names = {u["name"] for u in body["users"]}
    assert {"ינון", "הודיה"} <= names
    assert len(body["permissions"]) == 7
    assert all(p["label"] and p["description"] for p in body["permissions"])


def test_mock_users_contain_no_real_phone_numbers(client: TestClient) -> None:
    for user in client.get("/api/bobi/users").json()["users"]:
        hint = user["whatsapp_hint"]
        assert "+" not in hint
        # At most a masked 4-digit suffix.
        assert sum(ch.isdigit() for ch in hint) <= 4


def test_permission_change_requires_preview_and_confirm(client: TestClient) -> None:
    payload = {"permissions": ["control_devices", "manage_tasks"]}

    preview = client.post(
        "/api/bobi/users/hodaya/permissions/preview", json=payload
    ).json()
    assert preview["destructive"] is True
    assert any("בוטל" in line["text"] for line in preview["lines"])

    result = client.post(
        "/api/bobi/users/hodaya/permissions/confirm",
        json={"payload": payload, "token": preview["token"]},
    ).json()
    assert result["success"] is True

    user = client.get("/api/bobi/users/hodaya").json()
    assert set(user["permissions"]) == {"control_devices", "manage_tasks"}


# --- tasks & calendar -------------------------------------------------------
def test_tasks_split_open_and_completed(client: TestClient) -> None:
    body = client.get("/api/bobi/tasks").json()
    assert body["open_tasks"] and body["completed_tasks"]
    assert all(not t["completed"] for t in body["open_tasks"])
    assert all(t["completed"] for t in body["completed_tasks"])


def test_completing_a_task_moves_it(client: TestClient) -> None:
    updated = client.patch("/api/bobi/tasks/task_1", json={"completed": True}).json()
    assert updated["completed"] is True

    body = client.get("/api/bobi/tasks").json()
    assert "task_1" not in {t["id"] for t in body["open_tasks"]}
    assert "task_1" in {t["id"] for t in body["completed_tasks"]}


def test_deleting_a_task(client: TestClient) -> None:
    result = client.delete("/api/bobi/tasks/task_3").json()
    assert result["success"] is True
    body = client.get("/api/bobi/tasks").json()
    assert "task_3" not in {t["id"] for t in body["open_tasks"]}


def test_calendar_events_carry_display_labels(client: TestClient) -> None:
    events = client.get("/api/bobi/calendar").json()["events"]
    assert events
    for event in events:
        assert event["day_label"].startswith("יום ")
        assert ":" in event["time_label"]
    assert any(event["bobi_features"] for event in events)


# --- notifications ----------------------------------------------------------
def test_notification_rules(client: TestClient) -> None:
    rules = client.get("/api/bobi/notifications").json()["rules"]
    by_id = {r["id"]: r for r in rules}

    meeting = by_id["meeting_soon"]
    assert meeting["recipients"] == ["ינון"]
    assert meeting["lead_time_minutes"] == 30
    assert meeting["quiet_hours"]["start"] == "23:00"
    assert meeting["enabled"] is True


def test_toggling_a_notification_rule(client: TestClient) -> None:
    rule = client.post(
        "/api/bobi/notifications/temperature_alert/toggle", json={"enabled": True}
    ).json()
    assert rule["enabled"] is True


# --- audit ------------------------------------------------------------------
def test_audit_log_is_newest_first_and_complete(client: TestClient) -> None:
    entries = client.get("/api/bobi/audit").json()["entries"]
    assert entries

    timestamps = [entry["timestamp"] for entry in entries]
    assert timestamps == sorted(timestamps, reverse=True)

    for entry in entries:
        assert entry["user"]
        assert entry["operation"]
        assert entry["resource_type"]
        assert entry["resource_id"]
        assert entry["source"] in {"web", "whatsapp", "automation", "system"}


def test_every_write_creates_an_audit_record(client: TestClient) -> None:
    before = len(client.get("/api/bobi/audit").json()["entries"])
    client.patch("/api/bobi/tasks/task_2", json={"completed": True})
    after = client.get("/api/bobi/audit").json()["entries"]

    assert len(after) == before + 1
    assert after[0]["resource_type"] == "task"
    assert after[0]["resource_id"] == "task_2"
