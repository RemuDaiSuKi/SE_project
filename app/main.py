"""FastAPI app 工廠。"""

from __future__ import annotations

import time
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from . import realtime
from .activity.errors import ActivityError
from .activity.join_limiter import JoinLimiter
from .activity.registry import ActivityRegistry
from .activity.results import SqliteResultSource
from .api import activities, outputs, student, teacher, worksheets
from .config import MISSING_PASSWORD_MESSAGE, Settings, StartupError
from .db import Database
from .errors import error_response, install_error_handlers
from .google.auth import GoogleAuth
from .google.errors import SheetsError, sheets_error_handler
from .google.gateway import GoogleSheetsGateway, SheetsGateway
from .results.contract import FinalResultSource
from .security import Clock, LoginLimiter, SessionStore, WindowRegistry
from .state import AppState
from .worksheet.store import PreviewStore, WorksheetStore

STATIC_DIR = Path(__file__).parent / "static"


async def _activity_error_handler(_: Request, exc: ActivityError) -> JSONResponse:
    return error_response(exc.status, exc.code, exc.message, extra=exc.extra or None,
                          headers=exc.headers or None)


def create_app(settings: Settings, *, clock: Clock = time.monotonic,
               result_source: FinalResultSource | None = None,
               gateway: SheetsGateway | None = None) -> FastAPI:
    if not settings.has_teacher_password():
        raise StartupError(MISSING_PASSWORD_MESSAGE)

    data_dir = Path(settings.data_dir)
    data_dir.mkdir(parents=True, exist_ok=True)
    db = Database(data_dir / "buzzer.db")
    if gateway is None:
        auth = GoogleAuth(settings.google_client_secrets_path, settings.google_token_path)
        gateway = GoogleSheetsGateway(auth, timeout_seconds=settings.google_timeout_seconds)
    worksheet_store = WorksheetStore(db)
    registry = ActivityRegistry(db, worksheet_store, settings, clock=clock)
    registry.startup()  # 未結束的活動改為已中斷
    state = AppState(
        settings=settings,
        clock=clock,
        db=db,
        windows=WindowRegistry(settings.lockout_max_failures, settings.lockout_seconds, clock),
        login_limiter=LoginLimiter(settings.login_max_failures, settings.login_lock_seconds, clock),
        sessions=SessionStore(settings.token_ttl_seconds, clock),
        previews=PreviewStore(db),
        worksheets=worksheet_store,
        result_source=result_source or SqliteResultSource(registry.repo, worksheet_store),
        gateway=gateway,
        activities=registry,
        join_limiter=JoinLimiter(settings.lockout_max_failures, settings.lockout_seconds,
                                 settings.join_global_max_failures, clock),
        hub=realtime.Hub(registry),
    )

    app = FastAPI(title="課堂搶答系統", docs_url=None, redoc_url=None, openapi_url=None)
    app.state.buzzer = state
    install_error_handlers(app)
    app.add_exception_handler(SheetsError, sheets_error_handler)  # type: ignore[arg-type]
    app.add_exception_handler(ActivityError, _activity_error_handler)  # type: ignore[arg-type]
    app.include_router(teacher.router)
    app.include_router(worksheets.router)
    app.include_router(outputs.router)
    app.include_router(activities.router)
    app.include_router(student.router)
    app.include_router(realtime.router)

    @app.middleware("http")
    async def _security_headers(request: Request, call_next):  # noqa: ANN001, ANN202
        response = await call_next(request)
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        if request.url.path.startswith("/api/"):
            response.headers.setdefault("Cache-Control", "no-store")
        return response

    @app.get("/", include_in_schema=False)
    def _index() -> FileResponse:
        return FileResponse(STATIC_DIR / "index.html")

    @app.get("/teacher", include_in_schema=False)
    def _teacher() -> FileResponse:
        return FileResponse(STATIC_DIR / "teacher.html")

    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
    return app
