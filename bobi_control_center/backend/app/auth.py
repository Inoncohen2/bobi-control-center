"""Authentication for the dedicated external Cloudflare hostname.

Home Assistant Ingress is already authenticated by Home Assistant and reaches
the app under HA's own host.  The external Cloudflare hostname reaches this
container directly, so it gets a separate, short-lived server-side session.
No Home Assistant credential is involved and no secret is sent to the SPA.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import logging
import secrets
import time
from collections import defaultdict
from dataclasses import dataclass

from fastapi import APIRouter, FastAPI, Request, Response
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from app.config import Settings
from app.services.roles import ANONYMOUS, LABELS, Actor, Role

logger = logging.getLogger("bobi.auth")

COOKIE_NAME = "__Host-bobi_session"
SESSION_SECONDS = 12 * 60 * 60
FAILURE_WINDOW_SECONDS = 15 * 60
MAX_FAILURES = 5
_SCRYPT_N = 2**14
_SCRYPT_R = 8
_SCRYPT_P = 1


def hash_external_password(password: str, *, salt: bytes | None = None) -> str:
    """Return the only password representation accepted by the app."""
    salt = salt or secrets.token_bytes(16)
    digest = hashlib.scrypt(
        password.encode("utf-8"), salt=salt, n=_SCRYPT_N, r=_SCRYPT_R, p=_SCRYPT_P
    )
    encoded_salt = base64.urlsafe_b64encode(salt).decode("ascii").rstrip("=")
    encoded_digest = base64.urlsafe_b64encode(digest).decode("ascii").rstrip("=")
    return f"scrypt${_SCRYPT_N}${_SCRYPT_R}${_SCRYPT_P}${encoded_salt}${encoded_digest}"


def verify_external_password(password: str, encoded: str) -> bool:
    """Constant-time verification; malformed option values fail closed."""
    try:
        algorithm, n, r, p, encoded_salt, encoded_digest = encoded.split("$", 5)
        if algorithm != "scrypt":
            return False
        if (int(n), int(r), int(p)) != (_SCRYPT_N, _SCRYPT_R, _SCRYPT_P):
            return False
        salt = base64.urlsafe_b64decode(encoded_salt + "=" * (-len(encoded_salt) % 4))
        expected = base64.urlsafe_b64decode(
            encoded_digest + "=" * (-len(encoded_digest) % 4)
        )
        actual = hashlib.scrypt(
            password.encode("utf-8"), salt=salt, n=int(n), r=int(r), p=int(p)
        )
    except (ValueError, TypeError):
        return False
    return hmac.compare_digest(actual, expected)


def is_external_request(request: Request, settings: Settings) -> bool:
    """Recognize the dedicated hostname even when cloudflared rewrites Host.

    The add-on has no published port, so an unauthenticated Internet request
    can reach it only through Cloudflare.  HA Ingress remains authenticated by
    Home Assistant; if an authenticated HA user supplies Cloudflare-looking
    headers they merely opt into the stricter second login.
    """
    if not settings.normalized_external_hostname:
        return False

    forwarded_host = request.headers.get("x-forwarded-host", "").split(",", 1)[0]
    for candidate in (request.headers.get("host", ""), forwarded_host):
        host = candidate.strip().lower().split(":", 1)[0]
        if hmac.compare_digest(host, settings.normalized_external_hostname):
            return True

    # Cloudflare overwrites CF-Connecting-IP and creates CF-Ray at its edge.
    # Requiring both also avoids classifying ordinary reverse-proxy traffic as
    # external when the origin Host is the add-on's internal Docker hostname.
    return bool(
        request.headers.get("cf-connecting-ip") and request.headers.get("cf-ray")
    )


@dataclass(frozen=True)
class Session:
    expires_at: float
    #: Decided when the session is created and read from here afterwards.
    #: Nothing in a payload, a header or a query string can raise it.
    role: Role = Role.ADMIN


class ExternalAuth:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._sessions: dict[str, Session] = {}
        self._failures: defaultdict[str, list[float]] = defaultdict(list)

    @property
    def role(self) -> Role:
        """The role a successful external login is granted.

        Read from the add-on options, and an unrecognised value falls to
        `viewer` rather than to the configured intention — a typo in a role
        name should cost reading, never grant writing.
        """
        try:
            return Role(str(self.settings.external_role).strip().lower())
        except ValueError:
            logger.warning(
                "external_role %r is not a known role; treating this session as viewer",
                self.settings.external_role,
            )
            return Role.VIEWER

    def _clean(self, now: float) -> None:
        self._sessions = {
            token: session
            for token, session in self._sessions.items()
            if session.expires_at > now
        }

    def authenticate(self, token: str | None) -> Session | None:
        now = time.time()
        self._clean(now)
        if not token:
            return None
        session = self._sessions.get(token)
        if session is None or session.expires_at <= now:
            return None
        return session

    def login(self, password: str, client_key: str) -> tuple[str, Session] | None:
        now = time.time()
        failures = [
            timestamp
            for timestamp in self._failures[client_key]
            if timestamp > now - FAILURE_WINDOW_SECONDS
        ]
        self._failures[client_key] = failures
        if len(failures) >= MAX_FAILURES:
            raise TooManyAttempts

        if not verify_external_password(password, self.settings.external_password_hash):
            failures.append(now)
            logger.warning("Rejected external Bobi login from %s", client_key)
            return None

        self._failures.pop(client_key, None)
        token = secrets.token_urlsafe(32)
        session = Session(expires_at=now + SESSION_SECONDS, role=self.role)
        self._sessions[token] = session
        return token, session

    def logout(self, token: str | None) -> None:
        if token:
            self._sessions.pop(token, None)


class TooManyAttempts(Exception):
    pass


class LoginBody(BaseModel):
    password: str = Field(min_length=1, max_length=512)


def _client_key(request: Request) -> str:
    # Cloudflare overwrites CF-Connecting-IP at the edge.  It is used only for
    # throttling, never as an authentication decision.
    return request.headers.get("cf-connecting-ip") or (
        request.client.host if request.client else "unknown"
    )


def _same_origin(request: Request, settings: Settings) -> bool:
    return request.headers.get("origin") == f"https://{settings.normalized_external_hostname}"


def actor_for(request: Request) -> Actor:
    """Who this request is, for the permission check and the audit line.

    Ingress means Home Assistant already authenticated an administrator — the
    manifest restricts the panel to them — so it is `owner`. The public
    hostname carries whatever role its session was created with. A request that
    somehow reached a route without either is a viewer: the failure mode of a
    gap in this function is reading, never writing.
    """
    settings: Settings = request.app.state.settings
    if not is_external_request(request, settings):
        return Actor(role=Role.OWNER, source="ingress")

    auth: ExternalAuth | None = getattr(request.app.state, "external_auth", None)
    session = auth.authenticate(request.cookies.get(COOKIE_NAME)) if auth else None
    if session is None:
        return ANONYMOUS
    return Actor(role=session.role, source="external")


def _error(status: int, code: str, message: str) -> JSONResponse:
    return JSONResponse(
        status_code=status,
        content={"code": code, "message": message, "details": {}},
    )


router = APIRouter(prefix="/api/auth", tags=["authentication"])


@router.get("/session", response_model=None)
async def session_status(request: Request) -> dict[str, object] | JSONResponse:
    settings: Settings = request.app.state.settings
    if not is_external_request(request, settings):
        return {
            "authenticated": True,
            "mode": "home_assistant",
            "role": Role.OWNER.value,
            "role_label": LABELS[Role.OWNER],
        }
    if not settings.external_auth_configured:
        return _error(503, "external_auth_unconfigured", "הגישה החיצונית עדיין לא הוגדרה")

    session = request.app.state.external_auth.authenticate(request.cookies.get(COOKIE_NAME))
    if session is None:
        return _error(401, "authentication_required", "נדרשת התחברות לבובי")
    return {
        "authenticated": True,
        "mode": "external",
        "expires_in_seconds": max(0, int(session.expires_at - time.time())),
        "role": session.role.value,
        "role_label": LABELS[session.role],
    }


@router.post("/login", response_model=None)
async def login(
    request: Request, body: LoginBody, response: Response
) -> dict[str, object] | JSONResponse:
    settings: Settings = request.app.state.settings
    if not is_external_request(request, settings):
        return {"authenticated": True, "mode": "home_assistant"}
    if not settings.external_auth_configured:
        return _error(503, "external_auth_unconfigured", "הגישה החיצונית עדיין לא הוגדרה")
    if not _same_origin(request, settings):
        return _error(403, "origin_rejected", "הבקשה נחסמה מטעמי אבטחה")

    try:
        result = request.app.state.external_auth.login(body.password, _client_key(request))
    except TooManyAttempts:
        limited = _error(429, "too_many_attempts", "יותר מדי ניסיונות. נסי שוב בעוד 15 דקות")
        limited.headers["Retry-After"] = str(FAILURE_WINDOW_SECONDS)
        return limited
    if result is None:
        return _error(401, "invalid_password", "הסיסמה אינה נכונה")

    token, session = result
    response.set_cookie(
        COOKIE_NAME,
        token,
        max_age=SESSION_SECONDS,
        expires=SESSION_SECONDS,
        path="/",
        secure=True,
        httponly=True,
        samesite="strict",
    )
    return {
        "authenticated": True,
        "mode": "external",
        "expires_in_seconds": int(session.expires_at - time.time()),
        "role": session.role.value,
        "role_label": LABELS[session.role],
    }


@router.post("/logout", response_model=None)
async def logout(request: Request, response: Response) -> dict[str, object] | JSONResponse:
    settings: Settings = request.app.state.settings
    if not is_external_request(request, settings):
        return {"authenticated": True, "mode": "home_assistant"}
    if not _same_origin(request, settings):
        return _error(403, "origin_rejected", "הבקשה נחסמה מטעמי אבטחה")
    request.app.state.external_auth.logout(request.cookies.get(COOKIE_NAME))
    response.delete_cookie(
        COOKIE_NAME, path="/", secure=True, httponly=True, samesite="strict"
    )
    return {"authenticated": False, "mode": "external"}


def register_external_auth_middleware(app: FastAPI) -> None:
    """Protect every API route on the dedicated public hostname."""

    @app.middleware("http")
    async def external_authentication(request: Request, call_next):
        settings: Settings = request.app.state.settings
        if not is_external_request(request, settings):
            return await call_next(request)

        # The compiled login screen and its static assets contain no household
        # data.  Authentication endpoints decide their own exact requirements.
        if not request.url.path.startswith("/api/") or request.url.path.startswith(
            "/api/auth/"
        ):
            return await call_next(request)

        if not settings.external_auth_configured:
            return _error(503, "external_auth_unconfigured", "הגישה החיצונית עדיין לא הוגדרה")
        session = request.app.state.external_auth.authenticate(
            request.cookies.get(COOKIE_NAME)
        )
        if session is None:
            return _error(401, "authentication_required", "נדרשת התחברות לבובי")
        if request.method not in {"GET", "HEAD", "OPTIONS"} and not _same_origin(
            request, settings
        ):
            return _error(403, "origin_rejected", "הבקשה נחסמה מטעמי אבטחה")
        return await call_next(request)
