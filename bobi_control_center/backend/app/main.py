"""Application factory.

Owns adapter selection at startup, structured error handling, security headers,
and serving the compiled frontend so the app is one container behind Ingress.
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.api import router as bobi_router
from app.api.deps import build_adapter, build_management
from app.api.manage import router as manage_router
from app.config import Settings, get_settings
from app.errors import INTERNAL, BobiError
from app.version import APP_NAME, APP_VERSION

logger = logging.getLogger("bobi")

#: Where the compiled SPA is copied during the Docker build.
STATIC_DIR = Path(__file__).parent / "static"


def _configure_logging(settings: Settings) -> None:
    logging.basicConfig(
        level=getattr(logging, settings.log_level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)-8s %(name)s %(message)s",
    )


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    _configure_logging(settings)

    adapter = build_adapter(settings)
    management = build_management(adapter)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        logger.info(
            "Bobi Control Center %s starting — adapter=%s writes_enabled=%s",
            APP_VERSION,
            adapter.name,
            adapter.writes_enabled,
        )
        try:
            yield
        finally:
            await adapter.aclose()

    app = FastAPI(
        title="Bobi Control Center API",
        description=(
            "ממשק הניהול של בובי. שלב 2 — קריאה בלבד דרך גשר bobi_cc_* "
            "של Home Assistant."
        ),
        version=APP_VERSION,
        lifespan=lifespan,
        docs_url="/api/docs",
        openapi_url="/api/openapi.json",
    )
    app.state.settings = settings
    app.state.adapter = adapter
    app.state.management = management

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=False,
        allow_methods=["GET", "POST", "OPTIONS"],
        allow_headers=["Content-Type"],
    )

    _register_errors(app)
    _register_security_headers(app)
    app.include_router(bobi_router)
    app.include_router(manage_router)

    @app.get("/health", tags=["system"], summary="Health check")
    async def health() -> dict[str, object]:
        """Used by the Docker healthcheck and the Supervisor watchdog."""
        return {
            "ok": True,
            "app": APP_NAME,
            "version": APP_VERSION,
            "adapter": adapter.name,
            "writes_enabled": adapter.writes_enabled,
        }

    _mount_frontend(app)
    return app


def _register_security_headers(app: FastAPI) -> None:
    @app.middleware("http")
    async def security_headers(request: Request, call_next):
        response = await call_next(request)
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("Referrer-Policy", "no-referrer")
        response.headers.setdefault(
            "Permissions-Policy", "geolocation=(), microphone=(), camera=()"
        )
        # Ingress serves the app inside a Home Assistant iframe, so framing must
        # be allowed for same-origin ancestors rather than denied outright.
        response.headers.setdefault(
            "Content-Security-Policy",
            "default-src 'self'; img-src 'self' data:; style-src 'self' 'unsafe-inline'; "
            "script-src 'self'; connect-src 'self'; frame-ancestors 'self'",
        )
        return response


def _register_errors(app: FastAPI) -> None:
    """Convert everything into the `{code, message, details}` envelope.

    Home Assistant failures are surfaced with their own code and a Hebrew
    message — never swallowed, and never as a traceback.
    """

    @app.exception_handler(BobiError)
    async def handle_bobi_error(_: Request, exc: BobiError) -> JSONResponse:
        logger.warning("Bobi error: %s (%s) %s", exc.code, exc.status_code, exc.details)
        return JSONResponse(status_code=exc.status_code, content=exc.to_dict())

    @app.exception_handler(RequestValidationError)
    async def handle_validation(_: Request, exc: RequestValidationError) -> JSONResponse:
        return JSONResponse(
            status_code=422,
            content={
                "code": "validation_error",
                "message": "חלק מהפרטים שנשלחו אינם תקינים",
                "details": {"fields": [".".join(str(p) for p in e["loc"]) for e in exc.errors()]},
            },
        )

    @app.exception_handler(StarletteHTTPException)
    async def handle_http(_: Request, exc: StarletteHTTPException) -> JSONResponse:
        messages = {404: "לא מצאתי את מה שחיפשת", 405: "הפעולה הזו לא נתמכת כאן"}
        return JSONResponse(
            status_code=exc.status_code,
            content={
                "code": f"http_{exc.status_code}",
                "message": messages.get(exc.status_code, "הבקשה נכשלה"),
                "details": {},
            },
        )

    @app.exception_handler(Exception)
    async def handle_unexpected(request: Request, exc: Exception) -> JSONResponse:
        # Logged in full server-side; never returned to the client.
        logger.exception("Unhandled error on %s %s", request.method, request.url.path)
        return JSONResponse(status_code=500, content=INTERNAL)


def _mount_frontend(app: FastAPI) -> None:
    """Serve the built SPA when present.

    Absent in development, where Vite serves the UI and proxies `/api` here, so
    a missing directory is not an error.

    Ingress note: the frontend uses a HashRouter and relative asset paths, so
    every real path served here is either `/` or a real file. There is no
    client-side path routing to fall back for, but the fallback is kept so a
    stale bookmark still lands on the app rather than a 404.
    """
    if not STATIC_DIR.is_dir():
        logger.info("No built frontend at %s — serving API only.", STATIC_DIR)
        return

    assets = STATIC_DIR / "assets"
    if assets.is_dir():
        app.mount("/assets", StaticFiles(directory=assets), name="assets")

    index = STATIC_DIR / "index.html"

    @app.get("/{full_path:path}", include_in_schema=False)
    async def spa(full_path: str) -> FileResponse:
        candidate = (STATIC_DIR / full_path).resolve()
        if (
            full_path
            and candidate.is_file()
            and candidate.is_relative_to(STATIC_DIR.resolve())
        ):
            return FileResponse(candidate)
        return FileResponse(index)


app = create_app()
