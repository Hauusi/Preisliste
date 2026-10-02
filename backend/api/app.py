from __future__ import annotations

from urllib.parse import urlsplit

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, PlainTextResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException

import logging

from backend.ai.provider import cached_status
from backend.api.deps import LoginRequired
from backend.api.templating import templates
from backend.config import PROJECT_ROOT, Settings, get_settings
from backend.database import engine as db_engine
from backend.database.migrate import upgrade

log = logging.getLogger("preisliste")
NO_TELEMETRY = {"tracing": False, "metrics": False, "logs": False, "operation_spans": False, "auto_configure": False}

CSP = (
    "default-src 'self'; img-src 'self' data:; style-src 'self'; script-src 'self'; "
    "frame-ancestors 'none'; form-action 'self'; base-uri 'none'; object-src 'none'"
)


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    settings.upload_dir.mkdir(parents=True, exist_ok=True)
    db_url = f"sqlite:///{settings.db_path}"
    upgrade(db_url)
    db_engine.configure(db_url)

    # Keine Telemetrie: FastAPIs eingebaute OpenTelemetry-Anbindung vollständig aus
    app = FastAPI(title="Preisliste", docs_url=None, redoc_url=None, openapi_url=None, telemetry=NO_TELEMETRY)
    app.dependency_overrides[get_settings] = lambda: settings
    app.mount("/static", StaticFiles(directory=PROJECT_ROOT / "frontend/static"), name="static")

    @app.middleware("http")
    async def security(request: Request, call_next):
        if request.method not in ("GET", "HEAD", "OPTIONS"):
            origin = request.headers.get("origin") or request.headers.get("referer")
            if origin and origin != "null" and urlsplit(origin).netloc != request.headers.get("host"):
                return PlainTextResponse("Fremde Herkunft abgelehnt", status_code=403)
        response = await call_next(request)
        response.headers["Content-Security-Policy"] = CSP
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "same-origin"
        response.headers.setdefault("Cache-Control", "no-store")
        return response

    @app.exception_handler(LoginRequired)
    async def _login_required(request: Request, _exc):
        if request.url.path.startswith("/api/"):
            return JSONResponse({"detail": "Nicht angemeldet"}, status_code=401)
        return RedirectResponse("/login", status_code=303)

    @app.exception_handler(StarletteHTTPException)
    async def _http_error(request: Request, exc: StarletteHTTPException):
        if request.url.path.startswith("/api/"):
            return JSONResponse({"detail": exc.detail}, status_code=exc.status_code)
        return templates.TemplateResponse(
            request, "error.html", {"status": exc.status_code, "detail": exc.detail},
            status_code=exc.status_code,
        )

    from backend.api import (
        routes_api, routes_auth, routes_compare, routes_imports, routes_jobs, routes_lists, routes_rules,
        routes_updates, routes_users,
    )

    for module in (routes_auth, routes_imports, routes_lists, routes_users, routes_rules, routes_compare,
                   routes_jobs, routes_updates, routes_api):
        app.include_router(module.router)

    if settings.start_worker:
        from backend.jobs.runner import recover_after_restart, start_worker

        recover_after_restart()
        start_worker(settings)
        status = cached_status(settings, max_age=0)
        log.info("KI: %s (%s, %s)", "aktiv" if status.active else "inaktiv", status.provider, status.message)
    return app
