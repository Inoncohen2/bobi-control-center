"""The management trail, kept on disk.

Phase 3A held the trail in memory, which meant a restart lost it. A record of
who changed what is worth more than that, so 3.0 appends every line to a file in
the app's `/data` directory — the one path Home Assistant preserves across
restarts and updates.

Three properties are the whole design:

* **Bounded.** The file is rotated once it passes a size, and exactly one older
  generation is kept. A household's control centre should not be able to fill a
  Raspberry Pi's SD card with its own history.
* **Append-only, line by line.** One JSON object per line, flushed as it is
  written. A truncated last line — the power went out mid-write — costs that one
  line and nothing else, because reading skips what it cannot parse.
* **Redacted before it is written, not before it is shown.** A phone number, a
  LID, a token or a preview secret that never reaches the file cannot leak from
  it later. The redaction happens on the way in; there is no path that writes a
  raw value and filters it on the way out.

Never written here, whatever a caller passes: phone numbers, LIDs and chat ids,
Home Assistant tokens, preview tokens, and camera images. The first four are
dropped by key and by shape; the last has no way in, because an image is not a
field this module accepts.
"""

from __future__ import annotations

import json
import logging
import os
import re
import tempfile
from pathlib import Path
from typing import Any

from app.models.manage import AuditEntry

logger = logging.getLogger("bobi.audit")

#: Rotate past this, keeping one previous generation. Roughly a few thousand
#: lines — months of a household's changes, and a few hundred kilobytes.
MAX_BYTES = 512 * 1024

#: How many lines the API will ever return, however large the file.
MAX_RECORDS = 500

#: Key fragments never written. The same list the preview store uses, so a field
#: that cannot reach the bridge cannot reach the trail either.
_PRIVATE_KEYS = (
    "phone",
    "lid",
    "jid",
    "chat_id",
    "wa_id",
    "number",
    "token",
    "secret",
    "password",
    "image",
    "snapshot",
)

#: Values that look like a phone number or a LID even under an innocent key.
#: Redaction by key alone would miss `{"contact": "+972…"}`.
_PHONE_SHAPED = re.compile(r"\+?\d[\d\s\-()]{7,}")
_LID_SHAPED = re.compile(r"\d+@[a-z.]+")

REDACTED = "•••"


def redact(value: Any) -> Any:
    """One value, safe to write. Recurses into dicts and lists."""
    if isinstance(value, dict):
        return {
            key: (REDACTED if _private(key) else redact(item))
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [redact(item) for item in value]
    if isinstance(value, str) and (_PHONE_SHAPED.search(value) or _LID_SHAPED.search(value)):
        return REDACTED
    return value


def _private(key: str) -> bool:
    return any(private in key.lower() for private in _PRIVATE_KEYS)


class AuditTrail:
    """Append-only, bounded, redacted.

    A trail that cannot be written — a read-only `/data`, a full disk — is a
    degraded trail, not a broken application: the failure is logged once and the
    change still goes through. Refusing to manage the house because the diary is
    full would be the wrong trade.
    """

    def __init__(self, path: Path | None, *, max_bytes: int = MAX_BYTES) -> None:
        self._path = path
        self._max_bytes = max_bytes
        self._warned = False
        if path is not None:
            try:
                path.parent.mkdir(parents=True, exist_ok=True)
            except OSError as exc:  # pragma: no cover - depends on the filesystem
                logger.warning("audit trail directory unavailable (%s); keeping memory only", exc)
                self._path = None

    @property
    def path(self) -> Path | None:
        return self._path

    def append(self, entry: AuditEntry) -> None:
        if self._path is None:
            return
        line = json.dumps(redact(entry.model_dump()), ensure_ascii=False)
        try:
            self._rotate_if_needed()
            with self._path.open("a", encoding="utf-8") as handle:
                handle.write(line + "\n")
                handle.flush()
                # The trail is worth an fsync: it exists precisely for the case
                # where something went wrong right after a change.
                os.fsync(handle.fileno())
        except OSError as exc:
            # Once per process. A disk that cannot be written will not start
            # working because it was told about it five hundred times.
            if not self._warned:
                logger.warning("cannot write the audit trail (%s); keeping memory only", exc)
                self._warned = True

    def _rotate_if_needed(self) -> None:
        if self._path is None or not self._path.exists():
            return
        if self._path.stat().st_size < self._max_bytes:
            return
        previous = self._path.with_suffix(self._path.suffix + ".1")
        # Replace, not append: exactly one older generation is kept, so the
        # space this takes has a ceiling rather than a slope.
        self._path.replace(previous)

    def read(self, limit: int) -> list[AuditEntry]:
        """The newest lines, newest first. Unreadable lines are skipped.

        Both generations are read so a rotation does not make the recent past
        vanish from the screen mid-week.
        """
        if self._path is None:
            return []
        lines: list[str] = []
        for path in (self._path.with_suffix(self._path.suffix + ".1"), self._path):
            try:
                if path.exists():
                    lines.extend(path.read_text("utf-8").splitlines())
            except OSError as exc:  # pragma: no cover - depends on the filesystem
                logger.warning("cannot read the audit trail (%s)", exc)

        entries: list[AuditEntry] = []
        for line in reversed(lines):
            if len(entries) >= min(limit, MAX_RECORDS):
                break
            try:
                entries.append(AuditEntry.model_validate(json.loads(line)))
            except (ValueError, TypeError):
                # A half-written last line, or a line from an older shape. One
                # bad line must not cost the whole history.
                continue
        return entries


def build_trail(data_dir: str | os.PathLike[str] | None) -> AuditTrail:
    """The trail for this install, or a memory-only one when there is no `/data`.

    Outside Home Assistant — a developer's laptop, a test — `/data` does not
    exist and must not be created at the filesystem root. A temporary directory
    keeps the code path identical without leaving anything behind.
    """
    if not data_dir:
        return AuditTrail(None)
    path = Path(data_dir)
    if not path.exists() and path == Path("/data"):
        return AuditTrail(Path(tempfile.gettempdir()) / "bobi-cc" / "audit.jsonl")
    return AuditTrail(path / "audit.jsonl")
