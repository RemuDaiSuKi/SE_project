"""視窗註冊與老師登入／登出。"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field

from ..errors import AppError
from ..security import ROLE_TEACHER, Session, bearer_token, password_matches
from ..state import AppState, get_state, require_teacher

logger = logging.getLogger("buzzer")
router = APIRouter(prefix="/api")


class LoginBody(BaseModel):
    windowId: str = Field(min_length=1, max_length=64)
    password: str = Field(max_length=1024)


@router.post("/windows", status_code=201)
def register_window(state: AppState = Depends(get_state)) -> dict:
    return {"windowId": state.windows.register()}


@router.post("/teacher/login")
def login(body: LoginBody, state: AppState = Depends(get_state)) -> dict:
    window_id = body.windowId
    if not state.windows.exists(window_id):
        raise AppError(400, "WINDOW_UNKNOWN", "視窗識別已失效，請重新整理頁面")
    remaining = state.login_limiter.lock_remaining()
    if remaining:
        raise AppError(429, "LOCKED", f"密碼錯誤次數過多，請於 {remaining} 秒後再試",
                       headers={"Retry-After": str(remaining)},
                       extra={"retryAfterSeconds": remaining})
    expected = state.settings.teacher_password
    assert expected is not None  # create_app 已檢查
    if not password_matches(body.password, expected.get_secret_value()):
        state.login_limiter.record_failure()
        logger.info("老師登入失敗")
        raise AppError(400, "INVALID_PASSWORD", "密碼錯誤")
    state.login_limiter.record_success()
    token = state.sessions.issue(ROLE_TEACHER, window_id)
    logger.info("老師登入成功")
    return {"token": token, "role": ROLE_TEACHER,
            "expiresInSeconds": state.settings.token_ttl_seconds}


@router.get("/teacher/me")
def me(_: Session = Depends(require_teacher)) -> dict:
    return {"role": ROLE_TEACHER}


@router.post("/teacher/logout")
def logout(request: Request, _: Session = Depends(require_teacher),
           state: AppState = Depends(get_state)) -> dict:
    token = bearer_token(request.headers.get("authorization"))
    if token:
        state.sessions.revoke(token)
    logger.info("老師登出")
    return {"ok": True}
