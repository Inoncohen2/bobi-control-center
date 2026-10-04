"""Local semantic archive index for Bobi Next documents and saved objects.

Binary media remains owned by a storage provider (for example the existing
Bobi storage Edge boundary). This module stores only Bobi-owned semantics and a
provider URI, so document identity, categories, tags and search survive without
Home Assistant helpers/scripts and without copying cloud credentials into the
brain.
"""

from __future__ import annotations

import hashlib
import json
import re
import sqlite3
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

_MAX_TEXT = 16_000
_MAX_TITLE = 300
_MAX_CATEGORY = 160
_MAX_FILENAME = 255
_MAX_TAGS = 32
_MAX_METADATA_BYTES = 32_000
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_ALLOWED_KINDS = frozenset(
    {
        "document",
        "receipt",
        "image",
        "note",
        "product",
        "warranty",
        "vehicle_document",
        "bill",
        "other",
    }
)


@dataclass(slots=True, frozen=True)
class ArchiveRecord:
    object_id: str
    owner_key: str
    kind: str
    title: str
    category: str
    filename: str
    mime_type: str
    size_bytes: int
    sha256: str
    storage_uri: str
    source_message_id: str
    text_excerpt: str
    tags: tuple[str, ...]
    metadata: dict[str, Any] = field(default_factory=dict)
    status: str = "active"
    created_ts: int = 0
    updated_ts: int = 0


def sha256_hex(data: bytes) -> str:
    if not isinstance(data, bytes) or not data:
        raise ValueError("archive_bytes_required")
    return hashlib.sha256(data).hexdigest()


def _json_object(raw: Any) -> dict[str, Any]:
    try:
        value = json.loads(str(raw or "{}"))
    except (TypeError, ValueError):
        return {}
    return value if isinstance(value, dict) else {}


def _json_tags(raw: Any) -> tuple[str, ...]:
    try:
        value = json.loads(str(raw or "[]"))
    except (TypeError, ValueError):
        return ()
    if not isinstance(value, list):
        return ()
    return tuple(str(item) for item in value if str(item).strip())


def _normalize_tags(tags: list[str] | tuple[str, ...] | None) -> tuple[str, ...]:
    result: list[str] = []
    seen: set[str] = set()
    for raw in tags or ():
        tag = " ".join(str(raw).strip().split())[:80]
        if not tag:
            continue
        key = tag.casefold()
        if key in seen:
            continue
        seen.add(key)
        result.append(tag)
        if len(result) >= _MAX_TAGS:
            break
    return tuple(result)


def _safe_metadata(value: dict[str, Any] | None) -> dict[str, Any]:
    metadata = dict(value or {})
    encoded = json.dumps(metadata, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    if len(encoded.encode("utf-8")) > _MAX_METADATA_BYTES:
        raise ValueError("archive_metadata_too_large")
    return metadata


class ArchiveStore:
    """SQLite semantic index for private objects whose bytes live elsewhere."""

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
            CREATE TABLE IF NOT EXISTS archive_objects (
                object_id TEXT PRIMARY KEY,
                owner_key TEXT NOT NULL,
                kind TEXT NOT NULL,
                title TEXT NOT NULL,
                category TEXT NOT NULL DEFAULT '',
                filename TEXT NOT NULL DEFAULT '',
                mime_type TEXT NOT NULL DEFAULT '',
                size_bytes INTEGER NOT NULL DEFAULT 0,
                sha256 TEXT NOT NULL DEFAULT '',
                storage_uri TEXT NOT NULL DEFAULT '',
                source_message_id TEXT NOT NULL DEFAULT '',
                text_excerpt TEXT NOT NULL DEFAULT '',
                tags_json TEXT NOT NULL DEFAULT '[]',
                metadata_json TEXT NOT NULL DEFAULT '{}',
                status TEXT NOT NULL DEFAULT 'active',
                created_ts INTEGER NOT NULL,
                updated_ts INTEGER NOT NULL
            );
            CREATE INDEX IF NOT EXISTS ix_archive_owner_status
                ON archive_objects(owner_key, status, updated_ts DESC);
            CREATE INDEX IF NOT EXISTS ix_archive_owner_category
                ON archive_objects(owner_key, category, status, updated_ts DESC);
            CREATE INDEX IF NOT EXISTS ix_archive_owner_sha
                ON archive_objects(owner_key, sha256, status);
            """
        )
        self._db.commit()

    @staticmethod
    def _record(row: sqlite3.Row | None) -> ArchiveRecord | None:
        if row is None:
            return None
        return ArchiveRecord(
            object_id=str(row["object_id"]),
            owner_key=str(row["owner_key"]),
            kind=str(row["kind"]),
            title=str(row["title"]),
            category=str(row["category"]),
            filename=str(row["filename"]),
            mime_type=str(row["mime_type"]),
            size_bytes=max(0, int(row["size_bytes"])),
            sha256=str(row["sha256"]),
            storage_uri=str(row["storage_uri"]),
            source_message_id=str(row["source_message_id"]),
            text_excerpt=str(row["text_excerpt"]),
            tags=_json_tags(row["tags_json"]),
            metadata=_json_object(row["metadata_json"]),
            status=str(row["status"]),
            created_ts=int(row["created_ts"]),
            updated_ts=int(row["updated_ts"]),
        )

    def register(
        self,
        *,
        owner_key: str,
        kind: str,
        title: str,
        storage_uri: str = "",
        category: str = "",
        filename: str = "",
        mime_type: str = "",
        size_bytes: int = 0,
        sha256: str = "",
        source_message_id: str = "",
        text_excerpt: str = "",
        tags: list[str] | tuple[str, ...] | None = None,
        metadata: dict[str, Any] | None = None,
        object_id: str = "",
        now_ts: int | None = None,
    ) -> ArchiveRecord:
        owner = str(owner_key or "").strip()
        normalized_kind = str(kind or "").strip().lower()
        normalized_title = " ".join(str(title or "").strip().split())[:_MAX_TITLE]
        digest = str(sha256 or "").strip().lower()
        if not owner:
            raise ValueError("archive_owner_required")
        if normalized_kind not in _ALLOWED_KINDS:
            raise ValueError("archive_kind_invalid")
        if not normalized_title:
            raise ValueError("archive_title_required")
        if digest and _SHA256_RE.fullmatch(digest) is None:
            raise ValueError("archive_sha256_invalid")
        size = max(0, int(size_bytes))
        normalized_tags = _normalize_tags(tags)
        safe_metadata = _safe_metadata(metadata)
        now = int(now_ts or time.time())

        if digest:
            existing = self._db.execute(
                """
                SELECT * FROM archive_objects
                WHERE owner_key=? AND sha256=? AND status='active'
                ORDER BY updated_ts DESC LIMIT 1
                """,
                (owner, digest),
            ).fetchone()
            record = self._record(existing)
            if record is not None:
                return record

        identifier = str(object_id or "").strip() or str(uuid.uuid4())
        with self._db:
            self._db.execute(
                """
                INSERT INTO archive_objects(
                    object_id,owner_key,kind,title,category,filename,mime_type,
                    size_bytes,sha256,storage_uri,source_message_id,text_excerpt,
                    tags_json,metadata_json,status,created_ts,updated_ts
                ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,'active',?,?)
                """,
                (
                    identifier,
                    owner,
                    normalized_kind,
                    normalized_title,
                    " ".join(str(category or "").strip().split())[:_MAX_CATEGORY],
                    str(filename or "").strip()[:_MAX_FILENAME],
                    str(mime_type or "").lower().split(";", 1)[0].strip()[:160],
                    size,
                    digest,
                    str(storage_uri or "").strip()[:2048],
                    str(source_message_id or "").strip()[:512],
                    str(text_excerpt or "").strip()[:_MAX_TEXT],
                    json.dumps(list(normalized_tags), ensure_ascii=False, separators=(",", ":")),
                    json.dumps(
                        safe_metadata,
                        ensure_ascii=False,
                        sort_keys=True,
                        separators=(",", ":"),
                    ),
                    now,
                    now,
                ),
            )
        record = self.get(identifier, owner_key=owner, include_deleted=True)
        if record is None:
            raise RuntimeError("archive_record_not_persisted")
        return record

    def get(
        self,
        object_id: str,
        *,
        owner_key: str,
        include_deleted: bool = False,
    ) -> ArchiveRecord | None:
        sql = "SELECT * FROM archive_objects WHERE object_id=? AND owner_key=?"
        params: list[Any] = [str(object_id), str(owner_key)]
        if not include_deleted:
            sql += " AND status='active'"
        row = self._db.execute(sql, tuple(params)).fetchone()
        return self._record(row)

    def move_category(
        self,
        object_id: str,
        *,
        owner_key: str,
        category: str,
        now_ts: int | None = None,
    ) -> ArchiveRecord:
        normalized = " ".join(str(category or "").strip().split())[:_MAX_CATEGORY]
        now = int(now_ts or time.time())
        with self._db:
            result = self._db.execute(
                """
                UPDATE archive_objects SET category=?, updated_ts=?
                WHERE object_id=? AND owner_key=? AND status='active'
                """,
                (normalized, now, object_id, owner_key),
            )
        if result.rowcount != 1:
            raise KeyError("archive_object_not_found")
        record = self.get(object_id, owner_key=owner_key)
        if record is None:
            raise RuntimeError("archive_record_disappeared")
        return record

    def set_tags(
        self,
        object_id: str,
        *,
        owner_key: str,
        tags: list[str] | tuple[str, ...],
        now_ts: int | None = None,
    ) -> ArchiveRecord:
        normalized = _normalize_tags(tags)
        now = int(now_ts or time.time())
        with self._db:
            result = self._db.execute(
                """
                UPDATE archive_objects SET tags_json=?, updated_ts=?
                WHERE object_id=? AND owner_key=? AND status='active'
                """,
                (
                    json.dumps(list(normalized), ensure_ascii=False, separators=(",", ":")),
                    now,
                    object_id,
                    owner_key,
                ),
            )
        if result.rowcount != 1:
            raise KeyError("archive_object_not_found")
        record = self.get(object_id, owner_key=owner_key)
        if record is None:
            raise RuntimeError("archive_record_disappeared")
        return record

    def soft_delete(
        self,
        object_id: str,
        *,
        owner_key: str,
        now_ts: int | None = None,
    ) -> ArchiveRecord:
        return self._set_status(object_id, owner_key=owner_key, status="deleted", now_ts=now_ts)

    def restore(
        self,
        object_id: str,
        *,
        owner_key: str,
        now_ts: int | None = None,
    ) -> ArchiveRecord:
        return self._set_status(object_id, owner_key=owner_key, status="active", now_ts=now_ts)

    def _set_status(
        self,
        object_id: str,
        *,
        owner_key: str,
        status: str,
        now_ts: int | None,
    ) -> ArchiveRecord:
        now = int(now_ts or time.time())
        with self._db:
            result = self._db.execute(
                (
                    "UPDATE archive_objects SET status=?, updated_ts=? "
                    "WHERE object_id=? AND owner_key=?"
                ),
                (status, now, object_id, owner_key),
            )
        if result.rowcount != 1:
            raise KeyError("archive_object_not_found")
        record = self.get(object_id, owner_key=owner_key, include_deleted=True)
        if record is None:
            raise RuntimeError("archive_record_disappeared")
        return record

    def search(
        self,
        *,
        owner_key: str,
        query: str = "",
        kind: str = "",
        category: str = "",
        include_deleted: bool = False,
        limit: int = 50,
    ) -> tuple[ArchiveRecord, ...]:
        clauses = ["owner_key=?"]
        params: list[Any] = [str(owner_key)]
        if not include_deleted:
            clauses.append("status='active'")
        if kind:
            normalized_kind = str(kind).strip().lower()
            if normalized_kind not in _ALLOWED_KINDS:
                raise ValueError("archive_kind_invalid")
            clauses.append("kind=?")
            params.append(normalized_kind)
        if category:
            clauses.append("category=?")
            params.append(" ".join(str(category).strip().split())[:_MAX_CATEGORY])
        needle = " ".join(str(query or "").strip().split())
        if needle:
            pattern = f"%{needle[:300]}%"
            clauses.append(
                "(title LIKE ? COLLATE NOCASE OR filename LIKE ? COLLATE NOCASE "
                "OR category LIKE ? COLLATE NOCASE OR tags_json LIKE ? COLLATE NOCASE "
                "OR text_excerpt LIKE ? COLLATE NOCASE)"
            )
            params.extend([pattern] * 5)
        params.append(max(1, min(int(limit), 200)))
        rows = self._db.execute(
            f"SELECT * FROM archive_objects WHERE {' AND '.join(clauses)} "
            "ORDER BY updated_ts DESC, created_ts DESC LIMIT ?",
            tuple(params),
        ).fetchall()
        return tuple(record for row in rows if (record := self._record(row)) is not None)
