"""Application factory.

Responsibilities kept here and nowhere else: adapter selection at startup,
structured error handling, security headers, and serving the compiled frontend
so production is a single container.
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
from app.api.deps import build_service
from app.config import Settings, get_settings
from app.errors import INTERNAL, BobiError

logger = logging.getLogger("bobi")

#: Where ``npm run build`` output is copied in the production image.
STATIC_DIR = Path(__file__).parent / "static"


def _configure_logging(settings: Settings) -> None:
    logging.basicConfig(
        level=getattr(logging, settings.log_level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)-8s %(name)s %(message)s",
    )


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    _configure_logging(settings)

    # One adapter and one service for the whole process. Built eagerly rather
    # than in the lifespan so the app is usable the moment it is constructed
    # (tests, ASGI probes) and not only once startup has run.
    service = build_service(settings)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        logger.info(
            "Bobi Control Center starting — adapter=%s read_only=%s",
            service.adapter_name,
            service.read_only,
        )
        yield

    app = FastAPI(
        title="Bobi Control Center API",
        description=(
            "ממשק הניהול של בובי. בשלב זה כל הנתונים מדומים ואין גישה "
            "למערכת Home Assistant אמיתית."
        ),
        version="1.0.0",
        lifespan=lifespan,
        docs_url="/api/docs",
        openapi_url="/api/openapi.json",
    )
    app.state.settings = settings
    app.state.service = service

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=False,
        allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=["Content-Type"],
    )

    _register_errors(app)
    _register_security_headers(app)

    app.include_router(bobi_router)

    @app.get("/health", tags=["system"], summary="Health check")
    async def health() -> dict[str, str]:
        """Health endpoint used by Docker and the Home Assistant Add-on."""
        return {"status": "ok", "adapter": service.adapter_name, "version": "1.0.0"}

    _mount_frontend(app)
    return app


def _register_security_headers(app: FastAPI) -> None:
    @app.middleware("http")
    async def security_headers(request: Request, call_next):
        response = await call_next(request)
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("Referrer-Policy", "no-referrer")
        response.headers.setdefault("X-Frame-Options", "SAMEORIGIN")
        response.headers.setdefault(
            "Permissions-Policy", "geolocation=(), microphone=(), camera=()"
        )
        # Self-contained bundle: no external scripts, styles or connections.
        response.headers.setdefault(
            "Content-Security-Policy",
            "default-src 'self'; img-src 'self' data:; style-src 'self' 'unsafe-inline'; "
            "script-src 'self'; connect-src 'self'; frame-ancestors 'self'",
        )
        return response


def _register_errors(app: FastAPI) -> None:
    """Convert everything into the ``{code, message, details}`` envelope."""

    @app.exception_handler(BobiError)
    async def handle_bobi_error(_: Request, exc: BobiError) -> JSONResponse:
        return JSONResponse(status_code=exc.status_code, content=exc.to_dict())

    @app.exception_handler(RequestValidationError)
    async def handle_validation(_: Request, exc: RequestValidationError) -> JSONResponse:
        return JSONResponse(
            status_code=422,
            content={
                "code": "validation_error",
                "message": "חלק מהפרטים שנשלחו אינם תקינים",
                # Field paths only — never the raw exception text.
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
    """Serve the built SPA when it is present.

    Absent in development — the Vite dev server handles the UI and proxies
    ``/api`` here — so a missing directory is not an error.
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
        """SPA fallback: serve real files, otherwise hand back index.html."""
        candidate = (STATIC_DIR / full_path).resolve()
        if (
            full_path
            and candidate.is_file()
            and candidate.is_relative_to(STATIC_DIR.resolve())
        ):
            return FileResponse(candidate)
        return FileResponse(index)


app = create_app()
