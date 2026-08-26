"""The trail on disk: bounded, redacted, and never worth failing a change over.

Three properties, each of which is the reason the file exists at all:

* It survives a restart, which is when someone actually wants to read it.
* It cannot grow without limit on a household's SD card.
* Nothing in it identifies anyone. The redaction happens on the way in, so a
  number that was never written cannot be recovered by reading the file.
"""

from __future__ import annotations

import json

from app.models.manage import AuditEntry
from app.services.audit import REDACTED, AuditTrail, build_trail, redact


def entry(**kwargs) -> AuditEntry:
    fields = {
        "id": "au_1",
        "timestamp": "2026-08-26T09:00:00+00:00",
        "stage": "commit",
        "operation": "set",
        "resource_type": "settings",
        "resource_id": "morning_enabled",
        "requested_change": {},
        "result": "committed",
        "verified": True,
    }
    fields.update(kwargs)
    return AuditEntry(**fields)


# --- redaction --------------------------------------------------------------
def test_a_private_key_is_replaced_whatever_it_holds() -> None:
    safe = redact({"phone": "0000000000", "lid": "1@lid", "token": "abc", "summary": "לקנות חלב"})

    assert safe["phone"] == REDACTED
    assert safe["lid"] == REDACTED
    assert safe["token"] == REDACTED
    assert safe["summary"] == "לקנות חלב"


def test_a_phone_shaped_value_under_an_innocent_key_is_still_caught() -> None:
    """Redaction by key alone would miss this, and this is the shape that leaks."""
    safe = redact({"contact": "+972 54 000 0000", "note": "נקבע ל-14:00"})

    assert safe["contact"] == REDACTED
    assert safe["note"] == "נקבע ל-14:00"


def test_redaction_reaches_into_nested_structures() -> None:
    safe = redact({"users": [{"name": "ינון", "phone": "0000000000"}]})

    assert safe["users"][0]["name"] == "ינון"
    assert safe["users"][0]["phone"] == REDACTED


def test_a_camera_image_never_gets_in() -> None:
    safe = redact({"image": "data:image/png;base64,AAAA", "snapshot_url": "…"})

    assert safe["image"] == REDACTED
    assert safe["snapshot_url"] == REDACTED


# --- persistence ------------------------------------------------------------
def test_a_line_is_written_and_read_back(tmp_path) -> None:
    trail = AuditTrail(tmp_path / "audit.jsonl")
    trail.append(entry())

    records = trail.read(10)
    assert [record.id for record in records] == ["au_1"]
    assert records[0].resource_type == "settings"


def test_the_newest_line_comes_first(tmp_path) -> None:
    trail = AuditTrail(tmp_path / "audit.jsonl")
    for index in range(3):
        trail.append(entry(id=f"au_{index}"))

    assert [record.id for record in trail.read(10)] == ["au_2", "au_1", "au_0"]


def test_nothing_private_reaches_the_file(tmp_path) -> None:
    path = tmp_path / "audit.jsonl"
    trail = AuditTrail(path)
    trail.append(entry(requested_change={"phone": "0000000000", "role": "admin"}))

    raw = path.read_text("utf-8")
    assert "0000000000" not in raw
    assert "admin" in raw


def test_the_file_is_rotated_and_only_one_generation_is_kept(tmp_path) -> None:
    path = tmp_path / "audit.jsonl"
    trail = AuditTrail(path, max_bytes=400)
    for index in range(60):
        trail.append(entry(id=f"au_{index}"))

    assert path.stat().st_size < 4_000
    assert path.with_suffix(".jsonl.1").exists()
    # Exactly one older generation — never a growing pile of them.
    assert not path.with_suffix(".jsonl.2").exists()


def test_both_generations_are_read(tmp_path) -> None:
    """A rotation must not make this week's history vanish from the screen."""
    path = tmp_path / "audit.jsonl"
    trail = AuditTrail(path, max_bytes=400)
    for index in range(30):
        trail.append(entry(id=f"au_{index}"))

    ids = [record.id for record in trail.read(100)]
    assert "au_29" in ids
    assert len(ids) > 1


def test_a_truncated_line_costs_only_that_line(tmp_path) -> None:
    """The power went out mid-write. One line is lost, not the history."""
    path = tmp_path / "audit.jsonl"
    trail = AuditTrail(path)
    trail.append(entry(id="au_good"))
    with path.open("a", encoding="utf-8") as handle:
        handle.write('{"id": "au_trunc", "sta')

    assert [record.id for record in trail.read(10)] == ["au_good"]


def test_a_trail_that_cannot_be_written_does_not_break_anything(tmp_path) -> None:
    """A full disk degrades the diary, not the house."""
    path = tmp_path / "nowhere" / "audit.jsonl"
    trail = AuditTrail(path)
    path.parent.rmdir()

    trail.append(entry())  # must not raise
    assert trail.read(10) == []


def test_no_data_directory_means_memory_only(tmp_path) -> None:
    trail = build_trail(None)

    assert trail.path is None
    trail.append(entry())
    assert trail.read(10) == []


def test_a_real_data_directory_is_used(tmp_path) -> None:
    trail = build_trail(tmp_path)

    assert trail.path == tmp_path / "audit.jsonl"


def test_the_written_line_is_valid_json_per_line(tmp_path) -> None:
    path = tmp_path / "audit.jsonl"
    trail = AuditTrail(path)
    trail.append(entry())
    trail.append(entry(id="au_2"))

    lines = path.read_text("utf-8").strip().splitlines()
    assert len(lines) == 2
    for line in lines:
        assert json.loads(line)["source"] == "web"
