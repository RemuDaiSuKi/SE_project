"""學生端：加入組別、送出、本組檢視（design.md D5、D6、D9）。"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, Header
from pydantic import BaseModel, ConfigDict, Field

from ..activity import codes
from ..activity.engine import ActivityEngine
from ..activity.errors import InvalidCode, InvalidCodeFormat, InvalidInput, RejectReason, SubmissionRejected
from ..security import Session
from ..state import ROLE_GROUP, AppState, get_state, require_group

logger = logging.getLogger("buzzer")
router = APIRouter(prefix="/api")

UNKNOWN_WINDOW = "unknown-window"


class JoinBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    code: str = Field(min_length=1, max_length=32)


class SubmitBody(BaseModel):
    model_config = ConfigDict(extra="forbid")  # 客戶端的時間或結果欄位一律拒絕
    unitKey: str = Field(min_length=1, max_length=16)
    answers: dict[str, str] = Field(min_length=1, max_length=500)


@router.post("/join")
async def join(body: JoinBody, state: AppState = Depends(get_state),
               x_window_id: str = Header(default="", max_length=128)) -> dict:
    window = x_window_id or UNKNOWN_WINDOW
    state.join_limiter.check_allowed(window)
    code = codes.normalize(body.code)
    if not codes.is_well_formed(code):
        raise InvalidCodeFormat()          # 格式錯誤不算輸錯次數
    found = state.activities.find_team_by_code(code)
    if found is None:
        state.join_limiter.record_failure(window)
        logger.info("輸入組別代碼失敗")
        raise InvalidCode()
    engine, team = found
    state.join_limiter.record_success(window)
    token = state.sessions.issue(ROLE_GROUP, window, group_id=team.id, activity_id=engine.id,
                                 code_version=team.code_version)
    logger.info("活動 %s：組別 %d 有視窗加入", engine.id, team.id)
    return {"token": token, "role": ROLE_GROUP, "activityId": engine.id,
            "team": {"id": team.id, "name": team.name}, "phase": engine.phase}


def _engine_for(state: AppState, session: Session) -> ActivityEngine:
    engine = state.activities.get(session.attrs["activity_id"])
    team = engine.teams.get(session.attrs["group_id"])
    if team is None or team.code_version != session.attrs.get("code_version"):
        raise SubmissionRejected(RejectReason.CODE_OUTDATED)
    return engine


@router.post("/submissions")
async def submit(body: SubmitBody, session: Session = Depends(require_group),
                 state: AppState = Depends(get_state)) -> dict:
    engine = _engine_for(state, session)
    try:
        answers = {int(k): v for k, v in body.answers.items()}
    except ValueError:
        raise InvalidInput("答案的題號必須是數字") from None
    result, events = await engine.submit(session.attrs["group_id"], session.attrs["code_version"],
                                         body.unitKey, answers)
    await state.hub.dispatch(engine, events)
    return result


@router.get("/me")
async def me(session: Session = Depends(require_group),
             state: AppState = Depends(get_state)) -> dict:
    return _engine_for(state, session).view_for_team(session.attrs["group_id"])
