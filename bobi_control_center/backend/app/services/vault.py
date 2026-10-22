"""Encrypted, fail-closed local secret store for Bobi Guardian.

The encryption key must be provisioned separately as BOBI_VAULT_KEY. It is
never generated automatically, stored beside the ciphertext, returned by an
API, or logged. A missing key leaves the vault locked.
"""
from __future__ import annotations

import contextlib
import json
import os
import re
import tempfile
import threading
from pathlib import Path
from typing import Any

from cryptography.fernet import Fernet, InvalidToken

_NAME_RE = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9_.:@/-]{0,127}$")
_LOCK = threading.RLock()


class VaultError(RuntimeError):
    """Safe-to-display vault error without secret values."""


class VaultNotConfigured(VaultError):
    """The external encryption key is unavailable or invalid."""


class VaultCorrupt(VaultError):
    """The ciphertext cannot be authenticated or parsed."""


class EncryptedVault:
    """Authenticated encrypted storage; listing never returns secret values."""

    def __init__(self, path: str | Path, *, key: str | bytes | None = None) -> None:
        self.path = Path(path)
        configured = key if key is not None else os.environ.get("BOBI_VAULT_KEY")
        if isinstance(configured, str):
            configured = configured.encode("ascii", errors="ignore")
        if not configured:
            raise VaultNotConfigured(
                "Vault is locked: BOBI_VAULT_KEY has not been provisioned."
            )
        try:
            self._fernet = Fernet(configured)
        except (TypeError, ValueError) as exc:
            raise VaultNotConfigured(
                "Vault is locked: the configured encryption key is invalid."
            ) from exc

    @staticmethod
    def _validate_name(name: str) -> str:
        if not isinstance(name, str) or not _NAME_RE.fullmatch(name):
            raise ValueError("Invalid secret name.")
        if ".." in name or name.startswith("/") or "\\" in name:
            raise ValueError("Invalid secret name.")
        return name

    def _read_all(self) -> dict[str, dict[str, Any]]:
        if not self.path.exists():
            return {}
        try:
            payload = json.loads(
                self._fernet.decrypt(self.path.read_bytes()).decode("utf-8")
            )
            if not isinstance(payload, dict) or payload.get("format") != 1:
                raise ValueError("unexpected format")
            entries = payload.get("entries")
            if not isinstance(entries, dict):
                raise ValueError("unexpected entries")
            for name, item in entries.items():
                self._validate_name(name)
                if (
                    not isinstance(item, dict)
                    or not isinstance(item.get("value"), str)
                    or not isinstance(item.get("service"), str)
                    or not isinstance(item.get("note"), str)
                ):
                    raise ValueError("unexpected entry")
            return entries
        except (
            OSError,
            InvalidToken,
            UnicodeDecodeError,
            json.JSONDecodeError,
            ValueError,
            TypeError,
        ) as exc:
            raise VaultCorrupt(
                "Vault cannot be authenticated or decoded; no changes were made."
            ) from exc

    def _write_all(self, entries: dict[str, dict[str, Any]]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd, temp_name = tempfile.mkstemp(
            prefix=".bobi-vault-", suffix=".tmp", dir=str(self.path.parent)
        )
        temp_path = Path(temp_name)
        try:
            os.fchmod(fd, 0o600)
            raw = json.dumps(
                {"format": 1, "entries": entries},
                ensure_ascii=False,
                separators=(",", ":"),
                sort_keys=True,
            ).encode("utf-8")
            ciphertext = self._fernet.encrypt(raw)
            with os.fdopen(fd, "wb") as handle:
                handle.write(ciphertext)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temp_path, self.path)
            os.chmod(self.path, 0o600)
            try:
                dir_fd = os.open(self.path.parent, os.O_RDONLY)
                try:
                    os.fsync(dir_fd)
                finally:
                    os.close(dir_fd)
            except OSError:
                pass
        except Exception:
            with contextlib.suppress(OSError):
                os.close(fd)
            with contextlib.suppress(OSError):
                temp_path.unlink(missing_ok=True)
            raise

    def put(self, name: str, value: str, *, service: str, note: str = "") -> None:
        name = self._validate_name(name)
        if not isinstance(value, str) or not value:
            raise ValueError("Secret value must not be empty.")
        if not isinstance(service, str) or not service.strip() or len(service) > 80:
            raise ValueError("A service label of at most 80 characters is required.")
        if not isinstance(note, str) or len(note) > 240:
            raise ValueError("Note must be at most 240 characters.")
        with _LOCK:
            entries = self._read_all()
            if name in entries:
                raise FileExistsError("Secret already exists; overwrite is not allowed.")
            entries[name] = {
                "value": value,
                "service": service.strip(),
                "note": note.strip(),
            }
            self._write_all(entries)

    def get(self, name: str) -> str | None:
        """Internal broker method only; no API route returns this value."""
        name = self._validate_name(name)
        with _LOCK:
            entry = self._read_all().get(name)
            return entry["value"] if entry else None

    def delete(self, name: str) -> bool:
        name = self._validate_name(name)
        with _LOCK:
            entries = self._read_all()
            if name not in entries:
                return False
            del entries[name]
            self._write_all(entries)
            return True

    def list_metadata(self) -> list[dict[str, str]]:
        with _LOCK:
            entries = self._read_all()
            return [
                {"name": name, "service": item["service"], "note": item["note"]}
                for name, item in sorted(entries.items())
            ]
