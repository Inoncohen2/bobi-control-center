"""The Preview → Confirm half of the safety model.

A preview is stored under an opaque token. ``confirm`` refuses to run unless it
is handed a token that was issued for *this exact payload*, which makes it
impossible for a client to skip the preview step or to confirm something other
than what the user saw.
"""

from __future__ import annotations

import hashlib
import json
import secrets
import time
from dataclasses import dataclass, field
from typing import Any

from app.errors import PreviewRequiredError
from app.models import ChangePreview, PreviewLine

#: Previews older than this are discarded, so a stale tab cannot confirm.
TOKEN_TTL_SECONDS = 15 * 60


def _fingerprint(payload: Any) -> str:
    """Stable hash of a payload, independent of key ordering."""
    encoded = json.dumps(payload, sort_keys=True, ensure_ascii=False, default=str)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


@dataclass
class _StoredPreview:
    operation: str
    fingerprint: str
    payload: Any
    created_at: float = field(default_factory=time.monotonic)


class PreviewStore:
    """In-memory preview registry.

    Process-local on purpose: previews are short-lived UI state, not data worth
    persisting, and Phase 1 runs as a single process.
    """

    def __init__(self) -> None:
        self._items: dict[str, _StoredPreview] = {}

    def issue(self, operation: str, payload: Any) -> str:
        self._evict_expired()
        token = secrets.token_urlsafe(16)
        self._items[token] = _StoredPreview(
            operation=operation,
            fingerprint=_fingerprint(payload),
            payload=payload,
        )
        return token

    def consume(self, token: str, operation: str, payload: Any) -> None:
        """Validate and burn a token. Raises when it does not match."""
        self._evict_expired()
        stored = self._items.pop(token, None)
        if stored is None:
            raise PreviewRequiredError(
                "התצוגה המקדימה פגה. אפשר לנסות שוב.",
                details={"operation": operation},
            )
        if stored.operation != operation:
            raise PreviewRequiredError(details={"operation": operation})
        if stored.fingerprint != _fingerprint(payload):
            raise PreviewRequiredError(
                "מה שאושר שונה ממה שהוצג בתצוגה המקדימה.",
                details={"operation": operation},
            )

    def _evict_expired(self) -> None:
        cutoff = time.monotonic() - TOKEN_TTL_SECONDS
        for token in [t for t, item in self._items.items() if item.created_at < cutoff]:
            self._items.pop(token, None)

    def clear(self) -> None:
        self._items.clear()


def build_preview(
    store: PreviewStore,
    *,
    operation: str,
    payload: Any,
    summary: str,
    lines: list[PreviewLine] | None = None,
    warnings: list[str] | None = None,
    destructive: bool = False,
) -> ChangePreview:
    """Create a preview and register its token in one step."""
    token = store.issue(operation, payload)
    return ChangePreview(
        summary=summary,
        lines=lines or [],
        warnings=warnings or [],
        requires_confirmation=True,
        destructive=destructive,
        token=token,
    )
