from __future__ import annotations

import pytest

from app.bobi_next.memory import BobiMemory
from app.bobi_next.request_ledger import RequestLedger


def test_new_request_is_claimed_and_active_duplicate_is_not(tmp_path):
    ledger = RequestLedger(tmp_path / "bobi.db")
    try:
        first = ledger.claim(
            request_id="r1",
            user_key="u1",
            input_text="hello",
            owner_token="worker-a",
            now_ts=100,
            lease_seconds=30,
        )
        duplicate = ledger.claim(
            request_id="r1",
            user_key="u1",
            input_text="hello",
            owner_token="worker-b",
            now_ts=110,
            lease_seconds=30,
        )
        assert first.claimed is True
        assert first.reason == "claimed_new"
        assert duplicate.claimed is False
        assert duplicate.reason == "request_owned"
        assert duplicate.record.owner_token == "worker-a"
    finally:
        ledger.close()


def test_terminal_request_can_never_execute_again(tmp_path):
    ledger = RequestLedger(tmp_path / "bobi.db")
    try:
        ledger.claim(
            request_id="r1",
            user_key="u1",
            input_text="turn off",
            owner_token="worker-a",
            now_ts=100,
        )
        ledger.complete(
            "r1",
            owner_token="worker-a",
            terminal_kind="executed",
            outbound_message_id="msg-out",
            now_ts=101,
        )
        duplicate = ledger.claim(
            request_id="r1",
            user_key="u1",
            input_text="turn off",
            owner_token="worker-b",
            now_ts=1000,
        )
        assert duplicate.claimed is False
        assert duplicate.reason == "request_terminal"
        assert duplicate.record.state == "completed"
        assert duplicate.record.outbound_message_id == "msg-out"
    finally:
        ledger.close()


def test_expired_lease_is_reclaimed_after_worker_crash(tmp_path):
    ledger = RequestLedger(tmp_path / "bobi.db")
    try:
        ledger.claim(
            request_id="r1",
            user_key="u1",
            input_text="turn off",
            owner_token="dead-worker",
            now_ts=100,
            lease_seconds=10,
        )
        recovered = ledger.claim(
            request_id="r1",
            user_key="u1",
            input_text="turn off",
            owner_token="worker-b",
            now_ts=111,
            lease_seconds=20,
        )
        assert recovered.claimed is True
        assert recovered.reason == "claimed_recovery"
        assert recovered.record.owner_token == "worker-b"
        assert recovered.record.attempts == 2
    finally:
        ledger.close()


def test_request_id_cannot_be_reused_by_another_user(tmp_path):
    ledger = RequestLedger(tmp_path / "bobi.db")
    try:
        ledger.claim(
            request_id="r1",
            user_key="u1",
            input_text="hello",
            owner_token="worker-a",
            now_ts=100,
        )
        collision = ledger.claim(
            request_id="r1",
            user_key="u2",
            input_text="hello",
            owner_token="worker-b",
            now_ts=1000,
        )
        assert collision.claimed is False
        assert collision.reason == "request_user_mismatch"
    finally:
        ledger.close()


def test_only_request_owner_can_finish(tmp_path):
    ledger = RequestLedger(tmp_path / "bobi.db")
    try:
        ledger.claim(
            request_id="r1",
            user_key="u1",
            input_text="hello",
            owner_token="worker-a",
            now_ts=100,
        )
        with pytest.raises(PermissionError, match="request_not_owned"):
            ledger.complete(
                "r1",
                owner_token="worker-b",
                terminal_kind="executed",
                now_ts=101,
            )
        assert ledger.get("r1").state == "running"
    finally:
        ledger.close()


def test_retry_releases_request_for_a_fresh_claim(tmp_path):
    ledger = RequestLedger(tmp_path / "bobi.db")
    try:
        ledger.claim(
            request_id="r1",
            user_key="u1",
            input_text="hello",
            owner_token="worker-a",
            now_ts=100,
        )
        ledger.retry(
            "r1",
            owner_token="worker-a",
            error="temporary",
            now_ts=101,
        )
        recovered = ledger.claim(
            request_id="r1",
            user_key="u1",
            input_text="hello",
            owner_token="worker-b",
            now_ts=102,
        )
        assert recovered.claimed is True
        assert recovered.record.attempts == 2
    finally:
        ledger.close()


def test_request_ledger_migrates_memory_created_table_in_place(tmp_path):
    path = tmp_path / "shared.db"
    memory = BobiMemory(path)
    memory.close()

    ledger = RequestLedger(path)
    try:
        claim = ledger.claim(
            request_id="r1",
            user_key="u1",
            input_text="hello",
            owner_token="worker-a",
            now_ts=100,
        )
        assert claim.claimed is True
        assert claim.record.attempts == 1
        assert claim.record.lease_until_ts > 100
    finally:
        ledger.close()
