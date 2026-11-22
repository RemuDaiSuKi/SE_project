"""FastAPI app 工廠。"""

from __future__ import annotations

import time
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from .api import outputs, teacher, worksheets
from .config import MISSING_PASSWORD_MESSAGE, Settings, StartupError
from .db import Database
from .errors import install_error_handlers
from .middleware import LocalHostOnlyMiddleware
from .results.contract import FinalResultSource, NoActivitiesSource
from .security import Clock, SessionStore, WindowRegistry
from .state import AppState
from .worksheet.store import PreviewStore, WorksheetStore

STATIC_DIR = Path(__file__).parent / "static"


def create_app(settings: Settings, *, clock: Clock = time.monotonic,
               result_source: FinalResultSource | None = None) -> FastAPI:
    if not settings.has_teacher_password():
        raise StartupError(MISSING_PASSWORD_MESSAGE)

    data_dir = Path(settings.data_dir)
    data_dir.mkdir(parents=True, exist_ok=True)
    db = Database(data_dir / "buzzer.db")
    state = AppState(
        settings=settings,
        clock=clock,
        db=db,
        windows=WindowRegistry(settings.lockout_max_failures, settings.lockout_seconds, clock),
        sessions=SessionStore(settings.token_ttl_seconds, clock),
        previews=PreviewStore(clock),
        worksheets=WorksheetStore(db, data_dir),
        result_source=result_source or NoActivitiesSource(),
    )

    app = FastAPI(title="課堂搶答系統", docs_url=None, redoc_url=None, openapi_url=None)
    app.state.buzzer = state
    install_error_handlers(app)
    app.include_router(teacher.router)
    app.include_router(worksheets.router)
    app.include_router(outputs.router)

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
    app.add_middleware(LocalHostOnlyMiddleware, port=settings.port)
    return app
