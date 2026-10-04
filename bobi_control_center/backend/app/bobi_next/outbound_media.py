"""Crash-safe outbound media journal for Bobi Next.

WAHA's current sendFile schema does not expose a caller-defined message id.
That creates an unavoidable ambiguity if the process dies after WAHA accepts a
file but before Bobi persists the provider message id. To prefer no duplicate
side effects, expired `sending` leases become `uncertain` and are never retried
automatically. `loading` leases are safe to retry because no provider call has
started yet.
"""

from __future__ import annotations

import hashlib
import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

_MAX_FILENAME = 255
_MAX_MIME = 160
_MAX_CAPTION = 4000
_MAX_STORAGE_URI = 2048


@dataclass(slots=True, frozen=True)
class OutboundMediaDispatch:
    dispatch_key: str
    provider: str
    chat_id: str
    owner_key: str
    object_id: str
    storage_uri: str
    filename: str
    mime_type: str
    size_bytes: int
    sha256: str
    caption: str
    reply_to: str
    state: str
    attempts: int
    owner_token: str = ""
    lease_until_ts: int = 0
    next_attempt_ts: int = 0
    provider_message_id: str = ""
    last_error: str = ""


@dataclass(slots=True, frozen=True)
class OutboundMediaPayload:
    content: bytes
    filename: str
    mime_type: str


class ArchiveBlobReader(Protocol):
    async def read(self, storage_uri: str, *, max_bytes: int) -> bytes: ...


class OutboundMediaTransport(Protocol):
    async def send_file(
        self,
        chat_id: str,
        payload: OutboundMediaPayload,
        *,
        caption: str,
        reply_to: str,
    ) -> str: ...


def media_dispatch_key(provider: str, request_id: str, object_id: str) -> str:
    raw = f"{provider}\0{request_id}\0{object_id}".encode()
    return hashlib.sha256(raw).hexdigest()


class OutboundMediaStore:
    """Durable outbound journal with an explicit uncertain crash state."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._db = sqlite3.connect(self.path)
        self._db.row_factory = sqlite3.Row
        self._db.execute("PRAGMA journal_mode=WAL")
        self._migrate()

    def close(self) -> None:
        self._db.close()

    def _migrate(self) -> None:
        self._db.executescript(
            """
            CREATE TABLE IF NOT EXISTS outbound_media (
                dispatch_key TEXT PRIMARY KEY,
                provider TEXT NOT NULL,
                chat_id TEXT NOT NULL,
                owner_key TEXT NOT NULL,
                object_id TEXT NOT NULL,
                storage_uri TEXT NOT NULL,
                filename TEXT NOT NULL DEFAULT '',
                mime_type TEXT NOT NULL,
                size_bytes INTEGER NOT NULL,
                sha256 TEXT NOT NULL,
                caption TEXT NOT NULL DEFAULT '',
                reply_to TEXT NOT NULL DEFAULT '',
                state TEXT NOT NULL DEFAULT 'pending',
                attempts INTEGER NOT NULL DEFAULT 0,
                owner_token TEXT NOT NULL DEFAULT '',
                lease_until_ts INTEGER NOT NULL DEFAULT 0,
                next_attempt_ts INTEGER NOT NULL DEFAULT 0,
                provider_message_id TEXT NOT NULL DEFAULT '',
                last_error TEXT NOT NULL DEFAULT '',
                created_ts INTEGER NOT NULL,
                updated_ts INTEGER NOT NULL
            );
            CREATE INDEX IF NOT EXISTS ix_outbound_media_due
                ON outbound_media(state, next_attempt_ts, created_ts);
            CREATE INDEX IF NOT EXISTS ix_outbound_media_owner
                ON outbound_media(owner_key, created_ts DESC);
            """
        )
        self._db.commit()

    @staticmethod
    def _row(row: sqlite3.Row | None) -> OutboundMediaDispatch | None:
        if row is None:
            return None
        return OutboundMediaDispatch(
            dispatch_key=str(row["dispatch_key"]),
            provider=str(row["provider"]),
            chat_id=str(row["chat_id"]),
            owner_key=str(row["owner_key"]),
            object_id=str(row["object_id"]),
            storage_uri=str(row["storage_uri"]),
            filename=str(row["filename"]),
            mime_type=str(row["mime_type"]),
            size_bytes=int(row["size_bytes"]),
            sha256=str(row["sha256"]),
            caption=str(row["caption"]),
            reply_to=str(row["reply_to"]),
            state=str(row["state"]),
            attempts=int(row["attempts"]),
            owner_token=str(row["owner_token"]),
            lease_until_ts=int(row["lease_until_ts"]),
            next_attempt_ts=int(row["next_attempt_ts"]),
            provider_message_id=str(row["provider_message_id"]),
            last_error=str(row["last_error"]),
        )

    def prepare(
        self,
        *,
        dispatch_key: str,
        provider: str,
        chat_id: str,
        owner_key: str,
        object_id: str,
        storage_uri: str,
        filename: str,
        mime_type: str,
        size_bytes: int,
        sha256: str,
        caption: str = "",
        reply_to: str = "",
        now_ts: int | None = None,
    ) -> OutboundMediaDispatch:
        values = {
            "dispatch_key": dispatch_key.strip(),
            "provider": provider.strip(),
            "chat_id": chat_id.strip(),
            "owner_key": owner_key.strip(),
            "object_id": object_id.strip(),
            "storage_uri": storage_uri.strip()[:_MAX_STORAGE_URI],
            "filename": filename.strip()[:_MAX_FILENAME],
            "mime_type": mime_type.strip().lower().split(";", 1)[0][:_MAX_MIME],
            "sha256": sha256.strip().lower(),
        }
        required = (
            "dispatch_key",
            "provider",
            "chat_id",
            "owner_key",
            "object_id",
            "storage_uri",
            "mime_type",
            "sha256",
        )
        if any(not values[key] for key in required):
            raise ValueError("outbound_media_identity_required")
        if len(values["sha256"]) != 64 or any(
            ch not in "0123456789abcdef" for ch in values["sha256"]
        ):
            raise ValueError("outbound_media_sha256_invalid")
        size = int(size_bytes)
        if size <= 0:
            raise ValueError("outbound_media_size_invalid")
        now = int(now_ts or time.time())
        with self._db:
            self._db.execute(
                """
                INSERT OR IGNORE INTO outbound_media(
                    dispatch_key,provider,chat_id,owner_key,object_id,storage_uri,
                    filename,mime_type,size_bytes,sha256,caption,reply_to,state,
                    attempts,owner_token,lease_until_ts,next_attempt_ts,
                    provider_message_id,last_error,created_ts,updated_ts
                ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,'pending',0,'',0,0,'','',?,?)
                """,
                (
                    values["dispatch_key"],
                    values["provider"],
                    values["chat_id"],
                    values["owner_key"],
                    values["object_id"],
                    values["storage_uri"],
                    values["filename"],
                    values["mime_type"],
                    size,
                    values["sha256"],
                    caption.strip()[:_MAX_CAPTION],
                    reply_to.strip()[:512],
                    now,
                    now,
                ),
            )
        result = self.get(values["dispatch_key"])
        if result is None:
            raise RuntimeError("outbound_media_not_persisted")
        return result

    def get(self, dispatch_key: str) -> OutboundMediaDispatch | None:
        row = self._db.execute(
            "SELECT * FROM outbound_media WHERE dispatch_key=?",
            (dispatch_key,),
        ).fetchone()
        return self._row(row)

    def claim_next(
        self,
        *,
        owner_token: str,
        now_ts: int | None = None,
        lease_seconds: int = 90,
    ) -> OutboundMediaDispatch | None:
        owner = owner_token.strip()
        if not owner:
            raise ValueError("outbound_media_owner_token_required")
        now = int(now_ts or time.time())
        lease_until = now + max(5, int(lease_seconds))
        self._db.execute("BEGIN IMMEDIATE")
        try:
            # Safe to retry expired loading: provider has not been called yet.
            self._db.execute(
                """
                UPDATE outbound_media
                SET state='retry', owner_token='', lease_until_ts=0,
                    next_attempt_ts=?, last_error='loading_lease_expired', updated_ts=?
                WHERE state='loading' AND lease_until_ts < ?
                """,
                (now, now, now),
            )
            # Never auto-retry expired sending: provider may already have accepted it.
            self._db.execute(
                """
                UPDATE outbound_media
                SET state='uncertain', owner_token='', lease_until_ts=0,
                    last_error='sending_lease_expired', updated_ts=?
                WHERE state='sending' AND lease_until_ts < ?
                """,
                (now, now),
            )
            row = self._db.execute(
                """
                SELECT dispatch_key FROM outbound_media
                WHERE state IN ('pending','retry') AND next_attempt_ts <= ?
                ORDER BY created_ts, dispatch_key LIMIT 1
                """,
                (now,),
            ).fetchone()
            if row is None:
                self._db.commit()
                return None
            key = str(row["dispatch_key"])
            self._db.execute(
                """
                UPDATE outbound_media
                SET state='loading', attempts=attempts+1, owner_token=?,
                    lease_until_ts=?, last_error='', updated_ts=?
                WHERE dispatch_key=?
                """,
                (owner, lease_until, now, key),
            )
            self._db.commit()
        except Exception:
            self._db.rollback()
            raise
        return self.get(key)

    def begin_send(
        self,
        dispatch: OutboundMediaDispatch,
        *,
        owner_token: str,
        now_ts: int | None = None,
        lease_seconds: int = 90,
    ) -> OutboundMediaDispatch:
        now = int(now_ts or time.time())
        lease_until = now + max(5, int(lease_seconds))
        with self._db:
            result = self._db.execute(
                """
                UPDATE outbound_media
                SET state='sending', lease_until_ts=?, updated_ts=?
                WHERE dispatch_key=? AND state='loading' AND owner_token=?
                """,
                (lease_until, now, dispatch.dispatch_key, owner_token),
            )
        if result.rowcount != 1:
            raise PermissionError("outbound_media_not_owned")
        updated = self.get(dispatch.dispatch_key)
        if updated is None:
            raise RuntimeError("outbound_media_disappeared")
        return updated

    def fail_before_send(
        self,
        dispatch: OutboundMediaDispatch,
        *,
        owner_token: str,
        error: str,
        retry_at_ts: int = 0,
        now_ts: int | None = None,
    ) -> OutboundMediaDispatch:
        now = int(now_ts or time.time())
        retry_at = max(0, int(retry_at_ts))
        state = "retry" if retry_at else "failed"
        with self._db:
            result = self._db.execute(
                """
                UPDATE outbound_media
                SET state=?, owner_token='', lease_until_ts=0, next_attempt_ts=?,
                    last_error=?, updated_ts=?
                WHERE dispatch_key=? AND state='loading' AND owner_token=?
                """,
                (
                    state,
                    retry_at,
                    str(error)[:1000],
                    now,
                    dispatch.dispatch_key,
                    owner_token,
                ),
            )
        if result.rowcount != 1:
            raise PermissionError("outbound_media_not_owned")
        updated = self.get(dispatch.dispatch_key)
        if updated is None:
            raise RuntimeError("outbound_media_disappeared")
        return updated

    def mark_sent(
        self,
        dispatch: OutboundMediaDispatch,
        *,
        owner_token: str,
        provider_message_id: str,
        now_ts: int | None = None,
    ) -> OutboundMediaDispatch:
        provider_id = provider_message_id.strip()
        if not provider_id:
            raise ValueError("outbound_media_provider_id_required")
        now = int(now_ts or time.time())
        with self._db:
            result = self._db.execute(
                """
                UPDATE outbound_media
                SET state='sent', owner_token='', lease_until_ts=0,
                    provider_message_id=?, last_error='', updated_ts=?
                WHERE dispatch_key=? AND state='sending' AND owner_token=?
                """,
                (provider_id, now, dispatch.dispatch_key, owner_token),
            )
        if result.rowcount != 1:
            raise PermissionError("outbound_media_not_owned")
        updated = self.get(dispatch.dispatch_key)
        if updated is None:
            raise RuntimeError("outbound_media_disappeared")
        return updated

    def mark_uncertain(
        self,
        dispatch: OutboundMediaDispatch,
        *,
        owner_token: str,
        error: str,
        now_ts: int | None = None,
    ) -> OutboundMediaDispatch:
        now = int(now_ts or time.time())
        with self._db:
            result = self._db.execute(
                """
                UPDATE outbound_media
                SET state='uncertain', owner_token='', lease_until_ts=0,
                    last_error=?, updated_ts=?
                WHERE dispatch_key=? AND state='sending' AND owner_token=?
                """,
                (str(error)[:1000], now, dispatch.dispatch_key, owner_token),
            )
        if result.rowcount != 1:
            raise PermissionError("outbound_media_not_owned")
        updated = self.get(dispatch.dispatch_key)
        if updated is None:
            raise RuntimeError("outbound_media_disappeared")
        return updated

    def resolve_uncertain(
        self,
        dispatch_key: str,
        *,
        resolution: str,
        provider_message_id: str = "",
        now_ts: int | None = None,
    ) -> OutboundMediaDispatch:
        """Operator/reconciliation-only resolution; never called by normal retries."""

        if resolution not in {"sent", "retry", "failed"}:
            raise ValueError("outbound_media_resolution_invalid")
        if resolution == "sent" and not provider_message_id.strip():
            raise ValueError("outbound_media_provider_id_required")
        now = int(now_ts or time.time())
        next_attempt = now if resolution == "retry" else 0
        with self._db:
            result = self._db.execute(
                """
                UPDATE outbound_media
                SET state=?, owner_token='', lease_until_ts=0, next_attempt_ts=?,
                    provider_message_id=?, last_error='', updated_ts=?
                WHERE dispatch_key=? AND state='uncertain'
                """,
                (
                    resolution,
                    next_attempt,
                    provider_message_id.strip(),
                    now,
                    dispatch_key,
                ),
            )
        if result.rowcount != 1:
            raise ValueError("outbound_media_not_uncertain")
        updated = self.get(dispatch_key)
        if updated is None:
            raise RuntimeError("outbound_media_disappeared")
        return updated


async def process_next_outbound_media(
    store: OutboundMediaStore,
    reader: ArchiveBlobReader,
    transport: OutboundMediaTransport,
    *,
    owner_token: str,
    now_ts: int | None = None,
    lease_seconds: int = 90,
    max_bytes: int = 25 * 1024 * 1024,
) -> OutboundMediaDispatch | None:
    """Process one dispatch without automatically repeating an ambiguous send."""

    now = int(now_ts or time.time())
    dispatch = store.claim_next(
        owner_token=owner_token,
        now_ts=now,
        lease_seconds=lease_seconds,
    )
    if dispatch is None:
        return None
    if dispatch.size_bytes > max_bytes:
        return store.fail_before_send(
            dispatch,
            owner_token=owner_token,
            error="outbound_media_too_large",
            now_ts=now,
        )

    try:
        content = await reader.read(dispatch.storage_uri, max_bytes=max_bytes)
    except Exception as exc:
        return store.fail_before_send(
            dispatch,
            owner_token=owner_token,
            error=f"blob_read:{type(exc).__name__}",
            retry_at_ts=now + 30,
            now_ts=now,
        )
    if not isinstance(content, bytes) or not content:
        return store.fail_before_send(
            dispatch,
            owner_token=owner_token,
            error="blob_read_invalid",
            now_ts=now,
        )
    if len(content) != dispatch.size_bytes:
        return store.fail_before_send(
            dispatch,
            owner_token=owner_token,
            error="blob_size_mismatch",
            now_ts=now,
        )
    if hashlib.sha256(content).hexdigest() != dispatch.sha256:
        return store.fail_before_send(
            dispatch,
            owner_token=owner_token,
            error="blob_digest_mismatch",
            now_ts=now,
        )

    sending = store.begin_send(
        dispatch,
        owner_token=owner_token,
        now_ts=now,
        lease_seconds=lease_seconds,
    )
    try:
        provider_id = await transport.send_file(
            sending.chat_id,
            OutboundMediaPayload(
                content=content,
                filename=sending.filename,
                mime_type=sending.mime_type,
            ),
            caption=sending.caption,
            reply_to=sending.reply_to,
        )
    except Exception as exc:
        return store.mark_uncertain(
            sending,
            owner_token=owner_token,
            error=f"provider_send:{type(exc).__name__}",
            now_ts=now,
        )
    return store.mark_sent(
        sending,
        owner_token=owner_token,
        provider_message_id=provider_id,
        now_ts=now,
    )
