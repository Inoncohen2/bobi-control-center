"""Stable privacy-preserving cloud subject identifiers for Bobi Next."""

from __future__ import annotations

import hashlib


def cloud_subject(installation_id: str, user_key: str) -> str:
    installation = str(installation_id or "").strip()
    user = str(user_key or "").strip()
    if not installation or not user:
        raise ValueError("cloud_subject_identity_required")
    digest = hashlib.sha256(f"{installation}\0{user}".encode()).hexdigest()
    return f"bobi2_{digest[:48]}"
