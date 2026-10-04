from __future__ import annotations

import pytest

from app.bobi_next.scheduler import ScheduleStore


def test_scheduler_claims_only_due_jobs_and_preserves_payload(tmp_path):
    store = ScheduleStore(tmp_path / "bobi.db")
    try:
        store.create(
            job_id="due",
            user_key="u1",
            run_at_ts=100,
            payload={"device_ids": ["dev-1"], "capability": "power", "operation": "off"},
            now_ts=10,
        )
        store.create(
            job_id="later",
            user_key="u1",
            run_at_ts=200,
            payload={"device_ids": ["dev-2"], "capability": "power", "operation": "on"},
            now_ts=10,
        )

        claimed = store.claim_due(owner_token="worker-a", now_ts=150)
        assert [job.job_id for job in claimed] == ["due"]
        assert claimed[0].payload["device_ids"] == ["dev-1"]
        assert claimed[0].state == "running"
        assert store.get("later").state == "pending"
    finally:
        store.close()


def test_active_lease_prevents_double_execution(tmp_path):
    store = ScheduleStore(tmp_path / "bobi.db")
    try:
        store.create(
            job_id="job",
            user_key="u1",
            run_at_ts=100,
            payload={"operation": "off"},
            now_ts=10,
        )
        first = store.claim_due(
            owner_token="worker-a",
            now_ts=100,
            lease_seconds=60,
        )
        second = store.claim_due(
            owner_token="worker-b",
            now_ts=120,
            lease_seconds=60,
        )
        assert len(first) == 1
        assert second == ()

        reclaimed = store.claim_due(
            owner_token="worker-b",
            now_ts=161,
            lease_seconds=60,
        )
        assert len(reclaimed) == 1
        assert reclaimed[0].owner_token == "worker-b"
        assert reclaimed[0].attempts == 2
    finally:
        store.close()


def test_only_lease_owner_can_complete_job(tmp_path):
    store = ScheduleStore(tmp_path / "bobi.db")
    try:
        store.create(
            job_id="job",
            user_key="u1",
            run_at_ts=100,
            payload={},
            now_ts=10,
        )
        store.claim_due(owner_token="worker-a", now_ts=100)
        with pytest.raises(PermissionError, match="job_not_owned"):
            store.complete("job", owner_token="worker-b", now_ts=101)

        completed = store.complete("job", owner_token="worker-a", now_ts=101)
        assert completed.state == "completed"
        assert completed.owner_token == ""
    finally:
        store.close()


def test_recurring_job_returns_to_pending_with_next_occurrence(tmp_path):
    store = ScheduleStore(tmp_path / "bobi.db")
    try:
        store.create(
            job_id="daily-ish",
            user_key="u1",
            run_at_ts=100,
            payload={},
            recurrence_seconds=30,
            now_ts=10,
        )
        store.claim_due(owner_token="worker", now_ts=100)
        completed = store.complete("daily-ish", owner_token="worker", now_ts=101)
        assert completed.state == "pending"
        assert completed.run_at_ts == 130
    finally:
        store.close()


def test_failure_can_be_retried_without_losing_error(tmp_path):
    store = ScheduleStore(tmp_path / "bobi.db")
    try:
        store.create(
            job_id="job",
            user_key="u1",
            run_at_ts=100,
            payload={},
            now_ts=10,
        )
        store.claim_due(owner_token="worker", now_ts=100)
        failed = store.fail(
            "job",
            owner_token="worker",
            error="target_unavailable",
            retry_at_ts=160,
            now_ts=101,
        )
        assert failed.state == "retry"
        assert failed.run_at_ts == 160
        assert failed.last_error == "target_unavailable"
        assert store.claim_due(owner_token="worker-2", now_ts=159) == ()
        assert len(store.claim_due(owner_token="worker-2", now_ts=160)) == 1
    finally:
        store.close()


def test_cancelled_job_is_never_claimed(tmp_path):
    store = ScheduleStore(tmp_path / "bobi.db")
    try:
        store.create(
            job_id="job",
            user_key="u1",
            run_at_ts=100,
            payload={},
            now_ts=10,
        )
        cancelled = store.cancel("job", now_ts=20)
        assert cancelled.state == "cancelled"
        assert store.claim_due(owner_token="worker", now_ts=1000) == ()
    finally:
        store.close()
