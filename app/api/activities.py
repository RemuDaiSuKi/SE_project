"""搶答活動：老師端操作、結果與公開的階段查詢（design.md D9）。

會改變或讀取搶答狀態的端點都是 async，在事件迴圈上依序執行（design.md D2）。
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, ConfigDict, Field

from ..errors import forbidden
from ..security import ROLE_TEACHER, Session, bearer_token
from ..state import ROLE_GROUP, AppState, get_state, require_teacher

logger = logging.getLogger("buzzer")
router = APIRouter(prefix="/api/activities")


class CreateActivityBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    worksheetId: int = Field(ge=1)
    teams: list[str] = Field(min_length=1, max_length=1000)
    fairnessEnabled: bool | None = None
    cooldownSeconds: int | None = Field(default=None, ge=1, le=600)
    cooldownLead: int | None = Field(default=None, ge=1, le=100)


@router.post("", status_code=201)
async def create_activity(body: CreateActivityBody, _: Session = Depends(require_teacher),
                          state: AppState = Depends(get_state)) -> dict:
    engine = state.activities.create(body.worksheetId, body.teams, body.fairnessEnabled,
                                     body.cooldownSeconds, body.cooldownLead)
    await state.hub.broadcast_teacher_snapshot()
    return engine.view_for_teacher()


@router.get("")
async def list_activities(_: Session = Depends(require_teacher),
                          state: AppState = Depends(get_state)) -> dict:
    return {"activities": state.activities.list()}


@router.get("/{activity_id}")
async def get_activity(activity_id: int, _: Session = Depends(require_teacher),
                       state: AppState = Depends(get_state)) -> dict:
    return state.activities.get(activity_id).view_for_teacher()


@router.post("/{activity_id}/start")
async def start(activity_id: int, _: Session = Depends(require_teacher),
                state: AppState = Depends(get_state)) -> dict:
    engine = state.activities.get(activity_id)
    events = await engine.start()
    await state.hub.dispatch(engine, events)
    return {"phase": engine.phase}


@router.post("/{activity_id}/end")
async def end(activity_id: int, _: Session = Depends(require_teacher),
              state: AppState = Depends(get_state)) -> dict:
    engine = state.activities.get(activity_id)
    events = await engine.end()
    await state.hub.dispatch(engine, events)
    return {"phase": engine.phase}


@router.post("/{activity_id}/teams/{team_id}/regenerate-code")
async def regenerate_code(activity_id: int, team_id: int, _: Session = Depends(require_teacher),
                          state: AppState = Depends(get_state)) -> dict:
    engine = state.activities.get(activity_id)
    code, events = await engine.regenerate_code(team_id)
    state.sessions.revoke_where(lambda s: s.role == ROLE_GROUP
                                and s.attrs.get("activity_id") == engine.id
                                and s.attrs.get("group_id") == team_id)
    await state.hub.dispatch(engine, events)
    return {"teamId": team_id, "code": code}


@router.post("/{activity_id}/units/{unit_key}/invalidate")
async def invalidate(activity_id: int, unit_key: str, _: Session = Depends(require_teacher),
                     state: AppState = Depends(get_state)) -> dict:
    engine = state.activities.get(activity_id)
    result, events = await engine.invalidate(unit_key)
    await state.hub.dispatch(engine, events)
    return result


@router.get("/{activity_id}/results")
async def results(activity_id: int, request: Request,
                  state: AppState = Depends(get_state)) -> dict:
    """老師看到全部送出；屬於這場活動的學生只看到成功者；其他請求無權限。"""
    token = bearer_token(request.headers.get("authorization"))
    session = state.sessions.resolve(token) if token else None
    if session is not None and session.role == ROLE_TEACHER:
        return state.activities.get(activity_id).results_view(include_all=True)
    if session is None or session.role != ROLE_GROUP or session.attrs.get("activity_id") != activity_id:
        raise forbidden()
    return state.activities.get(activity_id).results_view(include_all=False)


@router.get("/{activity_id}/phase")
async def phase(activity_id: int, state: AppState = Depends(get_state)) -> dict:
    """公開端點，只回傳階段；重啟後學生頁以此判斷活動是否已中斷。"""
    return {"phase": state.activities.phase_of(activity_id)}
