"""每個 app 實例共用的狀態與 FastAPI 依賴。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from fastapi import Request

from .activity.join_limiter import JoinLimiter
from .activity.registry import ActivityRegistry
from .config import Settings
from .db import Database
from .errors import AppError, forbidden, session_expired
from .google.gateway import SheetsGateway
from .results.contract import FinalResultSource
from .security import (
    ROLE_TEACHER,
    Clock,
    LoginLimiter,
    Session,
    SessionStore,
    WindowRegistry,
    bearer_token,
)
from .worksheet.store import PreviewStore, WorksheetStore

ROLE_GROUP = "group"
GROUP_SESSION_INVALID_MESSAGE = "組別身分無效或已失效，請重新輸入組別代碼"


@dataclass
class AppState:
    settings: Settings
    clock: Clock
    db: Database
    windows: WindowRegistry
    login_limiter: LoginLimiter
    sessions: SessionStore
    previews: PreviewStore
    worksheets: WorksheetStore
    result_source: FinalResultSource
    gateway: SheetsGateway
    activities: ActivityRegistry
    join_limiter: JoinLimiter
    hub: Any  # app.realtime.Hub（避免循環 import）


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


def group_session_invalid() -> AppError:
    return AppError(401, "GROUP_SESSION_INVALID", GROUP_SESSION_INVALID_MESSAGE)


def require_group(request: Request) -> Session:
    """學生功能：Token 無效、過期或不是組別身分時回應 401。"""
    token = bearer_token(request.headers.get("authorization"))
    session = get_state(request).sessions.resolve(token) if token else None
    if session is None or session.role != ROLE_GROUP:
        raise group_session_invalid()
    return session
