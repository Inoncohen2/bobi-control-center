"""Structured errors.

The API contract is that a client always receives::

    {"code": "...", "message": "<Hebrew, for a human>", "details": {}}

Stack traces never leave the process. ``main.py`` installs handlers that turn
anything unexpected into a generic :data:`INTERNAL` envelope.
"""

from __future__ import annotations

from typing import Any


class BobiError(Exception):
    """Base class for every error the API is allowed to surface."""

    status_code: int = 400
    code: str = "bobi_error"
    #: Hebrew. Shown directly to the user, so it must never contain a traceback.
    message: str = "משהו השתבש"

    def __init__(
        self,
        message: str | None = None,
        *,
        code: str | None = None,
        details: dict[str, Any] | None = None,
        status_code: int | None = None,
    ) -> None:
        self.message = message or self.message
        self.code = code or self.code
        self.details: dict[str, Any] = details or {}
        if status_code is not None:
            self.status_code = status_code
        super().__init__(self.message)

    def to_dict(self) -> dict[str, Any]:
        return {"code": self.code, "message": self.message, "details": self.details}


class NotFoundError(BobiError):
    status_code = 404
    code = "not_found"
    message = "לא מצאתי את מה שחיפשת"


class ValidationError(BobiError):
    status_code = 422
    code = "validation_error"
    message = "חלק מהפרטים אינם תקינים"


class ReadOnlyError(BobiError):
    """Raised when a write is attempted while the mock adapter is active."""

    status_code = 409
    code = "read_only"
    message = "בשלב זה לא ניתן לבצע שינוי אמיתי במערכת הבית"


class PreviewRequiredError(BobiError):
    """Raised when a confirm arrives without a matching preview token."""

    status_code = 409
    code = "preview_required"
    message = "צריך לאשר את התצוגה המקדימה לפני ביצוע השינוי"


class UpstreamError(BobiError):
    status_code = 502
    code = "upstream_unavailable"
    message = "לא הצלחתי להתחבר למערכת הבית"


INTERNAL = {
    "code": "internal_error",
    "message": "משהו השתבש אצלי. נסה שוב בעוד רגע.",
    "details": {},
}
