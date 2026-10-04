"""Local-first onboarding, users and provider configuration for Bobi Next.

The setup database replaces Bobi-specific Home Assistant helpers used as
configuration storage.  It deliberately keeps provider credentials out of the
configuration model: provider rows hold only a ``secret_ref`` that can later be
resolved by a dedicated secret backend.

External messaging identities are not stored in plaintext.  They are mapped to
stable Bobi users through a per-installation salted fingerprint, so changing a
phone number/provider does not change the user's Bobi identity or memory.
"""

from __future__ import annotations

import hashlib
import json
import secrets
import sqlite3
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .authorization import RiskLevel, UserPolicy


@dataclass(slots=True, frozen=True)
class SetupStatus:
    completed: bool
    ready: bool
    missing_steps: tuple[str, ...]
    enabled_providers: int
    enabled_users: int
    linked_identities: int


@dataclass(slots=True, frozen=True)
class MessagingProvider:
    provider_key: str
    provider_type: str
    display_name: str
    enabled: bool
    endpoint: str
    session: str
    engine: str
    secret_ref: str
    config: dict[str, Any]


@dataclass(slots=True, frozen=True)
class BobiUser:
    user_key: str
    display_name: str
    role: str
    enabled: bool
    policy: UserPolicy


@dataclass(slots=True, frozen=True)
class IdentityLink:
    provider_key: str
    user_key: str
    identity_label: str
    created_ts: int


_ALLOWED_ROLES = frozenset({"owner", "admin", "member", "guest"})


def _json_object(raw: str) -> dict[str, Any]:
    try:
        value = json.loads(raw or "{}")
    except (TypeError, ValueError):
        return {}
    return value if isinstance(value, dict) else {}


def _string_set(value: Any, default: frozenset[str] = frozenset()) -> frozenset[str]:
    if not isinstance(value, list):
        return default
    return frozenset(str(item) for item in value if str(item).strip())


def _risk_from_value(value: Any) -> RiskLevel:
    try:
        return RiskLevel(int(value))
    except (TypeError, ValueError):
        return RiskLevel.MEDIUM


def policy_to_dict(policy: UserPolicy) -> dict[str, Any]:
    return {
        "allowed_capabilities": sorted(policy.allowed_capabilities),
        "denied_capabilities": sorted(policy.denied_capabilities),
        "allowed_domains": sorted(policy.allowed_domains),
        "denied_actions": sorted(policy.denied_actions),
        "max_without_approval": int(policy.max_without_approval),
        "can_approve": bool(policy.can_approve),
    }


def policy_from_dict(user_key: str, value: dict[str, Any]) -> UserPolicy:
    return UserPolicy(
        user_key=user_key,
        allowed_capabilities=_string_set(
            value.get("allowed_capabilities"), frozenset({"*"})
        ),
        denied_capabilities=_string_set(value.get("denied_capabilities")),
        allowed_domains=_string_set(value.get("allowed_domains"), frozenset({"*"})),
        denied_actions=_string_set(value.get("denied_actions")),
        max_without_approval=_risk_from_value(value.get("max_without_approval")),
        can_approve=bool(value.get("can_approve", True)),
    )


def default_policy(user_key: str, role: str) -> UserPolicy:
    """Conservative defaults; setup can narrow or expand them explicitly."""

    normalized = role.strip().lower()
    if normalized not in _ALLOWED_ROLES:
        raise ValueError("invalid_user_role")
    if normalized == "guest":
        return UserPolicy(
            user_key=user_key,
            allowed_capabilities=frozenset({
                "power",
                "brightness",
                "temperature",
                "hvac_mode",
                "fan_mode",
                "swing_mode",
                "preset_mode",
                "position",
                "tilt_position",
                "volume",
            }),
            allowed_domains=frozenset({
                "light",
                "switch",
                "climate",
                "fan",
                "media_player",
                "cover",
            }),
            max_without_approval=RiskLevel.LOW,
            can_approve=False,
        )
    return UserPolicy(
        user_key=user_key,
        max_without_approval=RiskLevel.MEDIUM,
        can_approve=normalized in {"owner", "admin"},
    )


class SetupStore:
    """Durable installation/setup state backed by local SQLite."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._db = sqlite3.connect(self.path)
        self._db.row_factory = sqlite3.Row
        self._db.execute("PRAGMA journal_mode=WAL")
        self._db.execute("PRAGMA foreign_keys=ON")
        self._migrate()
        self._ensure_installation()

    def close(self) -> None:
        self._db.close()

    def _migrate(self) -> None:
        self._db.executescript(
            """
            CREATE TABLE IF NOT EXISTS installation (
                singleton INTEGER PRIMARY KEY CHECK(singleton=1),
                installation_id TEXT NOT NULL,
                identity_salt TEXT NOT NULL,
                setup_completed INTEGER NOT NULL DEFAULT 0,
                settings_json TEXT NOT NULL DEFAULT '{}',
                created_ts INTEGER NOT NULL,
                updated_ts INTEGER NOT NULL
            );

            CREATE TABLE IF NOT EXISTS messaging_providers (
                provider_key TEXT PRIMARY KEY,
                provider_type TEXT NOT NULL,
                display_name TEXT NOT NULL,
                enabled INTEGER NOT NULL DEFAULT 1,
                endpoint TEXT NOT NULL DEFAULT '',
                session TEXT NOT NULL DEFAULT '',
                engine TEXT NOT NULL DEFAULT '',
                secret_ref TEXT NOT NULL DEFAULT '',
                config_json TEXT NOT NULL DEFAULT '{}',
                created_ts INTEGER NOT NULL,
                updated_ts INTEGER NOT NULL
            );

            CREATE TABLE IF NOT EXISTS users (
                user_key TEXT PRIMARY KEY,
                display_name TEXT NOT NULL,
                role TEXT NOT NULL,
                enabled INTEGER NOT NULL DEFAULT 1,
                policy_json TEXT NOT NULL,
                created_ts INTEGER NOT NULL,
                updated_ts INTEGER NOT NULL
            );

            CREATE TABLE IF NOT EXISTS user_identities (
                provider_key TEXT NOT NULL,
                identity_hash TEXT NOT NULL,
                user_key TEXT NOT NULL,
                identity_label TEXT NOT NULL DEFAULT '',
                created_ts INTEGER NOT NULL,
                PRIMARY KEY(provider_key, identity_hash),
                FOREIGN KEY(provider_key) REFERENCES messaging_providers(provider_key)
                    ON DELETE CASCADE,
                FOREIGN KEY(user_key) REFERENCES users(user_key)
                    ON DELETE CASCADE
            );
            CREATE INDEX IF NOT EXISTS ix_user_identities_user
                ON user_identities(user_key, provider_key);
            """
        )
        self._db.commit()

    def _ensure_installation(self) -> None:
        row = self._db.execute("SELECT 1 FROM installation WHERE singleton=1").fetchone()
        if row is not None:
            return
        now = int(time.time())
        with self._db:
            self._db.execute(
                """
                INSERT INTO installation(
                    singleton,installation_id,identity_salt,setup_completed,
                    settings_json,created_ts,updated_ts
                ) VALUES(1,?,?,0,'{}',?,?)
                """,
                (str(uuid.uuid4()), secrets.token_hex(32), now, now),
            )

    def installation_id(self) -> str:
        row = self._db.execute(
            "SELECT installation_id FROM installation WHERE singleton=1"
        ).fetchone()
        if row is None:
            raise RuntimeError("installation_missing")
        return str(row["installation_id"])

    def settings(self) -> dict[str, Any]:
        row = self._db.execute(
            "SELECT settings_json FROM installation WHERE singleton=1"
        ).fetchone()
        if row is None:
            raise RuntimeError("installation_missing")
        return _json_object(str(row["settings_json"]))

    def update_settings(
        self,
        values: dict[str, Any],
        *,
        now_ts: int | None = None,
    ) -> dict[str, Any]:
        if not isinstance(values, dict):
            raise TypeError("settings_must_be_object")
        current = self.settings()
        current.update(values)
        now = int(now_ts or time.time())
        encoded = json.dumps(current, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        with self._db:
            self._db.execute(
                "UPDATE installation SET settings_json=?, updated_ts=? WHERE singleton=1",
                (encoded, now),
            )
        return current

    def upsert_provider(
        self,
        *,
        provider_key: str,
        provider_type: str,
        display_name: str,
        enabled: bool = True,
        endpoint: str = "",
        session: str = "",
        engine: str = "",
        secret_ref: str = "",
        config: dict[str, Any] | None = None,
        now_ts: int | None = None,
    ) -> MessagingProvider:
        key = provider_key.strip()
        kind = provider_type.strip().lower()
        if not key or not kind:
            raise ValueError("provider_identity_required")
        if not display_name.strip():
            raise ValueError("provider_display_name_required")
        now = int(now_ts or time.time())
        config_value = config or {}
        if not isinstance(config_value, dict):
            raise TypeError("provider_config_must_be_object")
        encoded = json.dumps(
            config_value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        with self._db:
            self._db.execute(
                """
                INSERT INTO messaging_providers(
                    provider_key,provider_type,display_name,enabled,endpoint,
                    session,engine,secret_ref,config_json,created_ts,updated_ts
                ) VALUES(?,?,?,?,?,?,?,?,?,?,?)
                ON CONFLICT(provider_key) DO UPDATE SET
                    provider_type=excluded.provider_type,
                    display_name=excluded.display_name,
                    enabled=excluded.enabled,
                    endpoint=excluded.endpoint,
                    session=excluded.session,
                    engine=excluded.engine,
                    secret_ref=excluded.secret_ref,
                    config_json=excluded.config_json,
                    updated_ts=excluded.updated_ts
                """,
                (
                    key,
                    kind,
                    display_name.strip(),
                    int(enabled),
                    endpoint.strip(),
                    session.strip(),
                    engine.strip().upper(),
                    secret_ref.strip(),
                    encoded,
                    now,
                    now,
                ),
            )
        provider = self.get_provider(key)
        if provider is None:
            raise RuntimeError("provider_not_persisted")
        return provider

    def get_provider(self, provider_key: str) -> MessagingProvider | None:
        row = self._db.execute(
            "SELECT * FROM messaging_providers WHERE provider_key=?",
            (provider_key,),
        ).fetchone()
        if row is None:
            return None
        return MessagingProvider(
            provider_key=str(row["provider_key"]),
            provider_type=str(row["provider_type"]),
            display_name=str(row["display_name"]),
            enabled=bool(row["enabled"]),
            endpoint=str(row["endpoint"]),
            session=str(row["session"]),
            engine=str(row["engine"]),
            secret_ref=str(row["secret_ref"]),
            config=_json_object(str(row["config_json"])),
        )

    def list_providers(self, *, enabled_only: bool = False) -> tuple[MessagingProvider, ...]:
        where = "WHERE enabled=1" if enabled_only else ""
        rows = self._db.execute(
            f"SELECT provider_key FROM messaging_providers {where} ORDER BY provider_key"
        ).fetchall()
        return tuple(
            provider
            for row in rows
            if (provider := self.get_provider(str(row["provider_key"]))) is not None
        )

    def create_user(
        self,
        *,
        display_name: str,
        role: str = "member",
        user_key: str = "",
        enabled: bool = True,
        policy: UserPolicy | None = None,
        now_ts: int | None = None,
    ) -> BobiUser:
        normalized_role = role.strip().lower()
        if normalized_role not in _ALLOWED_ROLES:
            raise ValueError("invalid_user_role")
        if not display_name.strip():
            raise ValueError("display_name_required")
        key = user_key.strip() or f"usr_{uuid.uuid4().hex}"
        selected_policy = policy or default_policy(key, normalized_role)
        if selected_policy.user_key != key:
            raise ValueError("policy_user_mismatch")
        now = int(now_ts or time.time())
        encoded = json.dumps(
            policy_to_dict(selected_policy),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        try:
            with self._db:
                self._db.execute(
                    """
                    INSERT INTO users(
                        user_key,display_name,role,enabled,policy_json,created_ts,updated_ts
                    ) VALUES(?,?,?,?,?,?,?)
                    """,
                    (
                        key,
                        display_name.strip(),
                        normalized_role,
                        int(enabled),
                        encoded,
                        now,
                        now,
                    ),
                )
        except sqlite3.IntegrityError as exc:
            raise ValueError("duplicate_user_key") from exc
        user = self.get_user(key)
        if user is None:
            raise RuntimeError("user_not_persisted")
        return user

    def get_user(self, user_key: str) -> BobiUser | None:
        row = self._db.execute(
            "SELECT * FROM users WHERE user_key=?",
            (user_key,),
        ).fetchone()
        if row is None:
            return None
        key = str(row["user_key"])
        return BobiUser(
            user_key=key,
            display_name=str(row["display_name"]),
            role=str(row["role"]),
            enabled=bool(row["enabled"]),
            policy=policy_from_dict(key, _json_object(str(row["policy_json"]))),
        )

    def list_users(self, *, enabled_only: bool = False) -> tuple[BobiUser, ...]:
        where = "WHERE enabled=1" if enabled_only else ""
        rows = self._db.execute(
            f"SELECT user_key FROM users {where} ORDER BY created_ts,user_key"
        ).fetchall()
        return tuple(
            user
            for row in rows
            if (user := self.get_user(str(row["user_key"]))) is not None
        )

    def update_user_policy(
        self,
        user_key: str,
        policy: UserPolicy,
        *,
        now_ts: int | None = None,
    ) -> BobiUser:
        if policy.user_key != user_key:
            raise ValueError("policy_user_mismatch")
        if self.get_user(user_key) is None:
            raise KeyError("user_not_found")
        now = int(now_ts or time.time())
        encoded = json.dumps(
            policy_to_dict(policy),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        with self._db:
            self._db.execute(
                "UPDATE users SET policy_json=?, updated_ts=? WHERE user_key=?",
                (encoded, now, user_key),
            )
        updated = self.get_user(user_key)
        if updated is None:
            raise RuntimeError("user_disappeared")
        return updated

    def set_user_enabled(
        self,
        user_key: str,
        enabled: bool,
        *,
        now_ts: int | None = None,
    ) -> BobiUser:
        now = int(now_ts or time.time())
        with self._db:
            result = self._db.execute(
                "UPDATE users SET enabled=?, updated_ts=? WHERE user_key=?",
                (int(enabled), now, user_key),
            )
        if result.rowcount != 1:
            raise KeyError("user_not_found")
        updated = self.get_user(user_key)
        if updated is None:
            raise RuntimeError("user_disappeared")
        return updated

    def _identity_salt(self) -> str:
        row = self._db.execute(
            "SELECT identity_salt FROM installation WHERE singleton=1"
        ).fetchone()
        if row is None:
            raise RuntimeError("installation_missing")
        return str(row["identity_salt"])

    def _identity_hash(self, provider_key: str, external_id: str) -> str:
        normalized = external_id.strip().lower()
        if not normalized:
            raise ValueError("external_identity_required")
        raw = f"{self._identity_salt()}\0{provider_key.strip()}\0{normalized}"
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()

    def link_identity(
        self,
        *,
        provider_key: str,
        external_id: str,
        user_key: str,
        identity_label: str = "",
        now_ts: int | None = None,
    ) -> IdentityLink:
        provider = self.get_provider(provider_key)
        if provider is None:
            raise KeyError("provider_not_found")
        user = self.get_user(user_key)
        if user is None:
            raise KeyError("user_not_found")
        identity_hash = self._identity_hash(provider_key, external_id)
        now = int(now_ts or time.time())
        try:
            with self._db:
                self._db.execute(
                    """
                    INSERT INTO user_identities(
                        provider_key,identity_hash,user_key,identity_label,created_ts
                    ) VALUES(?,?,?,?,?)
                    """,
                    (
                        provider_key,
                        identity_hash,
                        user_key,
                        identity_label.strip(),
                        now,
                    ),
                )
        except sqlite3.IntegrityError as exc:
            raise ValueError("identity_already_linked") from exc
        return IdentityLink(provider_key, user_key, identity_label.strip(), now)

    def resolve_user(self, provider_key: str, external_id: str) -> BobiUser | None:
        identity_hash = self._identity_hash(provider_key, external_id)
        row = self._db.execute(
            """
            SELECT u.user_key
            FROM user_identities i
            JOIN users u ON u.user_key=i.user_key
            JOIN messaging_providers p ON p.provider_key=i.provider_key
            WHERE i.provider_key=? AND i.identity_hash=?
              AND u.enabled=1 AND p.enabled=1
            """,
            (provider_key, identity_hash),
        ).fetchone()
        if row is None:
            return None
        return self.get_user(str(row["user_key"]))

    def unlink_identity(self, *, provider_key: str, external_id: str) -> bool:
        identity_hash = self._identity_hash(provider_key, external_id)
        with self._db:
            result = self._db.execute(
                "DELETE FROM user_identities WHERE provider_key=? AND identity_hash=?",
                (provider_key, identity_hash),
            )
        return result.rowcount == 1

    def status(self) -> SetupStatus:
        row = self._db.execute(
            "SELECT setup_completed FROM installation WHERE singleton=1"
        ).fetchone()
        completed = bool(row["setup_completed"]) if row is not None else False
        enabled_providers = int(
            self._db.execute(
                "SELECT COUNT(*) AS n FROM messaging_providers WHERE enabled=1"
            ).fetchone()["n"]
        )
        enabled_users = int(
            self._db.execute("SELECT COUNT(*) AS n FROM users WHERE enabled=1").fetchone()["n"]
        )
        linked_identities = int(
            self._db.execute(
                """
                SELECT COUNT(*) AS n
                FROM user_identities i
                JOIN users u ON u.user_key=i.user_key
                JOIN messaging_providers p ON p.provider_key=i.provider_key
                WHERE u.enabled=1 AND p.enabled=1
                """
            ).fetchone()["n"]
        )
        missing: list[str] = []
        if enabled_providers < 1:
            missing.append("messaging_provider")
        if enabled_users < 1:
            missing.append("user")
        if linked_identities < 1:
            missing.append("user_identity")
        ready = not missing
        return SetupStatus(
            completed=completed,
            ready=ready,
            missing_steps=tuple(missing),
            enabled_providers=enabled_providers,
            enabled_users=enabled_users,
            linked_identities=linked_identities,
        )

    def mark_completed(self, *, now_ts: int | None = None) -> SetupStatus:
        status = self.status()
        if not status.ready:
            raise RuntimeError(f"setup_incomplete:{','.join(status.missing_steps)}")
        now = int(now_ts or time.time())
        with self._db:
            self._db.execute(
                "UPDATE installation SET setup_completed=1, updated_ts=? WHERE singleton=1",
                (now,),
            )
        return self.status()

    def safe_snapshot(self) -> dict[str, Any]:
        """Diagnostics-safe setup snapshot with no external IDs or secret refs."""

        status = self.status()
        return {
            "installation_id": self.installation_id(),
            "setup": {
                "completed": status.completed,
                "ready": status.ready,
                "missing_steps": list(status.missing_steps),
            },
            "providers": [
                {
                    "provider_key": provider.provider_key,
                    "provider_type": provider.provider_type,
                    "display_name": provider.display_name,
                    "enabled": provider.enabled,
                    "session": provider.session,
                    "engine": provider.engine,
                    "has_secret_ref": bool(provider.secret_ref),
                }
                for provider in self.list_providers()
            ],
            "users": [
                {
                    "user_key": user.user_key,
                    "display_name": user.display_name,
                    "role": user.role,
                    "enabled": user.enabled,
                    "policy": policy_to_dict(user.policy),
                }
                for user in self.list_users()
            ],
            "linked_identities": status.linked_identities,
        }
