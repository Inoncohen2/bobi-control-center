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
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from .receipt_review import merge_review_fields, reviewed_financial_fields, validate_review_fields

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
    revision: int = 0


@dataclass(slots=True, frozen=True)
class ArchiveMutationReceipt:
    request_id: str
    owner_key: str
    plan_hash: str
    operation: str
    record: ArchiveRecord


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
            CREATE TABLE IF NOT EXISTS archive_mutation_receipts (
                request_id TEXT PRIMARY KEY,
                owner_key TEXT NOT NULL,
                plan_hash TEXT NOT NULL,
                operation TEXT NOT NULL,
                record_json TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS archive_confirmation_bindings (
                request_id TEXT PRIMARY KEY,
                owner_key TEXT NOT NULL,
                approval_request_id TEXT NOT NULL,
                choice TEXT NOT NULL
            );
            """
        )
        columns = {row["name"] for row in self._db.execute("PRAGMA table_info(archive_objects)")}
        if "revision" not in columns:
            self._db.execute(
                "ALTER TABLE archive_objects ADD COLUMN revision INTEGER NOT NULL DEFAULT 0"
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
            revision=int(row["revision"]),
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

        # Serialize the digest check with insertion, including different message
        # ids/workers saving identical bytes. Restores use the same write lock.
        self._db.execute("BEGIN IMMEDIATE")
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
                self._db.commit()
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
                UPDATE archive_objects SET category=?, updated_ts=?, revision=revision+1
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
                UPDATE archive_objects SET tags_json=?, updated_ts=?, revision=revision+1
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
                    "UPDATE archive_objects SET status=?, updated_ts=?, revision=revision+1 "
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
        status: str = "",
        limit: int = 50,
    ) -> tuple[ArchiveRecord, ...]:
        clauses = ["owner_key=?"]
        params: list[Any] = [str(owner_key)]
        if status:
            if status not in {"active", "deleted"}:
                raise ValueError("archive_status_invalid")
            clauses.append("status=?")
            params.append(status)
        elif not include_deleted:
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
            literal = needle[:300].replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
            pattern = f"%{literal}%"
            clauses.append(
                "(title LIKE ? ESCAPE '\\' COLLATE NOCASE "
                "OR filename LIKE ? ESCAPE '\\' COLLATE NOCASE "
                "OR category LIKE ? ESCAPE '\\' COLLATE NOCASE "
                "OR tags_json LIKE ? ESCAPE '\\' COLLATE NOCASE "
                "OR text_excerpt LIKE ? ESCAPE '\\' COLLATE NOCASE "
                "OR (CASE WHEN json_valid(metadata_json) THEN ("
                "json_extract(metadata_json, '$.financial_review.schema_version')=1 AND "
                "json_extract(metadata_json, '$.financial_review.source')="
                "'explicit_user_approved_fields' AND "
                "json_extract(metadata_json, '$.financial_review.user_key')=owner_key AND "
                "json_extract(metadata_json, '$.financial_review.media_sha256')=sha256 AND ("
                "json_extract(metadata_json, '$.financial_review.fields.merchant') "
                "LIKE ? ESCAPE '\\' COLLATE NOCASE OR "
                "json_extract(metadata_json, '$.financial_review.fields.document_number') "
                "LIKE ? ESCAPE '\\' COLLATE NOCASE)) ELSE 0 END))"
            )
            params.extend([pattern] * 7)
        params.append(max(1, min(int(limit), 200)))
        rows = self._db.execute(
            f"SELECT * FROM archive_objects WHERE {' AND '.join(clauses)} "
            "ORDER BY updated_ts DESC, created_ts DESC LIMIT ?",
            tuple(params),
        ).fetchall()
        return tuple(record for row in rows if (record := self._record(row)) is not None)

    def mutation_receipt(self, request_id: str, *, owner_key: str) -> ArchiveMutationReceipt | None:
        row = self._db.execute(
            "SELECT * FROM archive_mutation_receipts WHERE request_id=?", (request_id,)
        ).fetchone()
        if row is None:
            return None
        if row["owner_key"] != owner_key:
            raise ValueError("archive_request_owner_mismatch")
        payload = json.loads(row["record_json"])
        payload["tags"] = tuple(payload["tags"])
        return ArchiveMutationReceipt(
            request_id, owner_key, str(row["plan_hash"]), str(row["operation"]),
            ArchiveRecord(**payload),
        )

    def has_cloud_objects(self) -> bool:
        # Trash also retains immutable bytes and must remain restorable.
        return self._db.execute(
            "SELECT 1 FROM archive_objects WHERE storage_uri LIKE 'bobi-storage://%' LIMIT 1"
        ).fetchone() is not None

    def apply_mutation_once(
        self,
        *,
        request_id: str,
        owner_key: str,
        plan_hash: str,
        object_id: str,
        operation: str,
        expected_revision: int,
        category: str = "",
        financial_fields: dict[str, str | int] | None = None,
        now_ts: int | None = None,
    ) -> ArchiveMutationReceipt:
        """CAS the exact object and persist its verified receipt in one transaction."""
        if not request_id or not owner_key or not plan_hash:
            raise ValueError("archive_mutation_identity_required")
        if operation not in {"move", "delete", "restore", "review"}:
            raise ValueError("archive_mutation_invalid")
        explicit_fields = validate_review_fields(financial_fields) if operation == "review" else {}
        normalized = " ".join(category.strip().split())
        if operation == "move" and (not normalized or len(normalized) > _MAX_CATEGORY):
            raise ValueError("archive_category_invalid")
        self._db.execute("BEGIN IMMEDIATE")
        try:
            previous = self.mutation_receipt(request_id, owner_key=owner_key)
            if previous is not None:
                if previous.plan_hash != plan_hash:
                    raise ValueError("archive_request_plan_changed")
                self._db.commit()
                return previous
            record = self.get(object_id, owner_key=owner_key, include_deleted=True)
            expected_status = "deleted" if operation == "restore" else "active"
            if (
                record is None or record.status != expected_status
                or record.revision != expected_revision
            ):
                raise ValueError("archive_state_changed")
            if operation == "restore" and record.sha256:
                duplicate = self._db.execute(
                    "SELECT 1 FROM archive_objects WHERE owner_key=? AND sha256=? "
                    "AND status='active' AND object_id!=? LIMIT 1",
                    (owner_key, record.sha256, object_id),
                ).fetchone()
                if duplicate:
                    raise ValueError("archive_active_duplicate")
            target_status = "deleted" if operation == "delete" else "active"
            target_category = normalized if operation == "move" else record.category
            target_metadata = dict(record.metadata)
            if operation == "review":
                if record.kind not in {"receipt", "bill"}:
                    raise ValueError("archive_review_kind_invalid")
                previous_fields = reviewed_financial_fields(
                    record.metadata, owner_key=owner_key, media_sha256=record.sha256,
                )
                target_metadata["financial_review"] = {
                    "schema_version": 1,
                    "source": "explicit_user_approved_fields",
                    "fields": merge_review_fields(previous_fields, explicit_fields),
                    "user_key": owner_key,
                    "media_sha256": record.sha256,
                    "request_id": request_id,
                    "plan_hash": plan_hash,
                    "reviewed_ts": int(now_ts or time.time()),
                }
            metadata_json = json.dumps(
                _safe_metadata(target_metadata), ensure_ascii=False, sort_keys=True,
                separators=(",", ":"),
            )
            updated = self._db.execute(
                "UPDATE archive_objects SET status=?, category=?, metadata_json=?, updated_ts=?, "
                "revision=revision+1 "
                "WHERE object_id=? AND owner_key=? AND revision=? AND status=?",
                (target_status, target_category, metadata_json, int(now_ts or time.time()),
                 object_id,
                 owner_key, expected_revision, expected_status),
            )
            verified = self.get(object_id, owner_key=owner_key, include_deleted=True)
            if updated.rowcount != 1 or verified is None or (
                verified.status != target_status or verified.category != target_category
                or verified.metadata != target_metadata
                or verified.revision != expected_revision + 1
            ):
                raise RuntimeError("archive_mutation_not_verified")
            self._db.execute(
                "INSERT INTO archive_mutation_receipts VALUES(?,?,?,?,?)",
                (request_id, owner_key, plan_hash, operation,
                 json.dumps(asdict(verified), ensure_ascii=False, sort_keys=True)),
            )
            self._db.commit()
        except BaseException:
            self._db.rollback()
            raise
        receipt = self.mutation_receipt(request_id, owner_key=owner_key)
        if receipt is None:
            raise RuntimeError("archive_mutation_receipt_missing")
        return receipt

    def confirmation_binding(self, request_id: str, *, owner_key: str) -> tuple[str, str] | None:
        row = self._db.execute(
            "SELECT * FROM archive_confirmation_bindings WHERE request_id=?", (request_id,)
        ).fetchone()
        if row is None:
            return None
        if row["owner_key"] != owner_key:
            raise ValueError("archive_request_owner_mismatch")
        return str(row["approval_request_id"]), str(row["choice"])

    def bind_confirmation(
        self, request_id: str, *, owner_key: str, approval_request_id: str, choice: str,
    ) -> tuple[str, str]:
        with self._db:
            self._db.execute(
                "INSERT OR IGNORE INTO archive_confirmation_bindings VALUES(?,?,?,?)",
                (request_id, owner_key, approval_request_id, choice),
            )
        binding = self.confirmation_binding(request_id, owner_key=owner_key)
        if binding != (approval_request_id, choice):
            raise ValueError("archive_confirmation_changed")
        return binding
