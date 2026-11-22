"""每個 app 實例共用的狀態與 FastAPI 依賴。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from fastapi import Request

from .config import Settings
from .db import Database
from .errors import forbidden, session_expired
from .google.auth import AuthStatus
from .google.gateway import SheetsGateway
from .results.contract import FinalResultSource
from .security import ROLE_TEACHER, Clock, Session, SessionStore, WindowRegistry, bearer_token
from .worksheet.store import PreviewStore, WorksheetStore


class AuthStatusSource(Protocol):
    def status(self) -> AuthStatus: ...


@dataclass
class AppState:
    settings: Settings
    clock: Clock
    db: Database
    windows: WindowRegistry
    sessions: SessionStore
    previews: PreviewStore
    worksheets: WorksheetStore
    result_source: FinalResultSource
    gateway: SheetsGateway
    google_auth: AuthStatusSource


def get_state(request: Request) -> AppState:
    return request.app.state.buzzer


def current_session(request: Request) -> Session | None:
    """沒有 Token 時為 None；Token 無效或過期時視為登入失效。"""
    token = bearer_token(request.headers.get("authorization"))
    if token is None:
        return None
    session = get_state(request).sessions.resolve(token)
    if session is None:
        raise session_expired()
    return session


def require_teacher(request: Request) -> Session:
    session = current_session(request)
    if session is None or session.role != ROLE_TEACHER:
        raise forbidden()
    return session
