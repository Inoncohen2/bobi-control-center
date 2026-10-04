"""Encrypted local secret vault for Bobi Next.

Configuration databases store only opaque ``vault://`` references. Secret values
are encrypted with Fernet before they reach SQLite. The encryption key is created
once in Bobi's persistent data directory with owner-only permissions.

This protects credentials from accidental database/config exposure. A process or
host administrator that can read both the key and vault can still decrypt them,
which is the expected trust boundary for a local Home Assistant app.
"""

from __future__ import annotations

import hashlib
import os
import sqlite3
import time
from pathlib import Path
from urllib.parse import urlsplit

from cryptography.fernet import Fernet, InvalidToken


class SecretVaultError(RuntimeError):
    pass


class EncryptedSecretVault:
    def __init__(self, database_path: str | Path, key_path: str | Path) -> None:
        self.database_path = Path(database_path)
        self.key_path = Path(key_path)
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        self.key_path.parent.mkdir(parents=True, exist_ok=True)
        self._fernet = Fernet(self._load_or_create_key())
        self._db = sqlite3.connect(self.database_path)
        self._db.row_factory = sqlite3.Row
        self._db.execute("PRAGMA journal_mode=WAL")
        self._db.execute(
            """
            CREATE TABLE IF NOT EXISTS secrets (
                secret_id TEXT PRIMARY KEY,
                ciphertext BLOB NOT NULL,
                created_ts INTEGER NOT NULL,
                updated_ts INTEGER NOT NULL
            )
            """
        )
        self._db.commit()

    def close(self) -> None:
        self._db.close()

    def _load_or_create_key(self) -> bytes:
        try:
            key = self.key_path.read_bytes().strip()
        except FileNotFoundError:
            key = b""
        if key:
            try:
                Fernet(key)
            except (ValueError, TypeError) as exc:
                raise SecretVaultError("secret_vault_key_invalid") from exc
            return key

        generated = Fernet.generate_key()
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
        try:
            fd = os.open(self.key_path, flags, 0o600)
        except FileExistsError:
            key = self.key_path.read_bytes().strip()
            try:
                Fernet(key)
            except (ValueError, TypeError) as exc:
                raise SecretVaultError("secret_vault_key_invalid") from exc
            return key
        try:
            with os.fdopen(fd, "wb") as handle:
                handle.write(generated)
                handle.flush()
                os.fsync(handle.fileno())
        except Exception:
            try:
                self.key_path.unlink(missing_ok=True)
            finally:
                raise
        return generated

    @staticmethod
    def _secret_id(scope: str) -> str:
        normalized = str(scope or "").strip()
        if not normalized:
            raise ValueError("secret_scope_required")
        return hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:40]

    @staticmethod
    def _parse_ref(secret_ref: str) -> str:
        parsed = urlsplit(str(secret_ref or "").strip())
        if parsed.scheme != "vault" or parsed.netloc or parsed.query or parsed.fragment:
            raise SecretVaultError("secret_ref_invalid")
        secret_id = parsed.path.lstrip("/")
        if len(secret_id) != 40 or any(ch not in "0123456789abcdef" for ch in secret_id):
            raise SecretVaultError("secret_ref_invalid")
        return secret_id

    def put(self, scope: str, value: str, *, now_ts: int | None = None) -> str:
        plaintext = str(value or "")
        if not plaintext:
            raise ValueError("secret_value_required")
        secret_id = self._secret_id(scope)
        token = self._fernet.encrypt(plaintext.encode("utf-8"))
        now = int(now_ts or time.time())
        with self._db:
            self._db.execute(
                """
                INSERT INTO secrets(secret_id,ciphertext,created_ts,updated_ts)
                VALUES(?,?,?,?)
                ON CONFLICT(secret_id) DO UPDATE SET
                    ciphertext=excluded.ciphertext,
                    updated_ts=excluded.updated_ts
                """,
                (secret_id, token, now, now),
            )
        return f"vault:///{secret_id}"

    def resolve(self, secret_ref: str) -> str:
        secret_id = self._parse_ref(secret_ref)
        row = self._db.execute(
            "SELECT ciphertext FROM secrets WHERE secret_id=?",
            (secret_id,),
        ).fetchone()
        if row is None:
            raise SecretVaultError("secret_not_found")
        try:
            plaintext = self._fernet.decrypt(bytes(row["ciphertext"]))
            return plaintext.decode("utf-8")
        except (InvalidToken, UnicodeDecodeError) as exc:
            raise SecretVaultError("secret_decryption_failed") from exc

    def delete(self, secret_ref: str) -> bool:
        secret_id = self._parse_ref(secret_ref)
        with self._db:
            result = self._db.execute("DELETE FROM secrets WHERE secret_id=?", (secret_id,))
        return result.rowcount == 1

    def contains(self, secret_ref: str) -> bool:
        try:
            secret_id = self._parse_ref(secret_ref)
        except SecretVaultError:
            return False
        row = self._db.execute(
            "SELECT 1 FROM secrets WHERE secret_id=?",
            (secret_id,),
        ).fetchone()
        return row is not None
