"""Google 授權狀態（老師專屬）。"""

from __future__ import annotations

from fastapi import APIRouter, Depends

from ..google.errors import LOGIN_HINT
from ..security import Session
from ..state import AppState, get_state, require_teacher

router = APIRouter(prefix="/api/google")


@router.get("/status")
def google_status(_: Session = Depends(require_teacher),
                  state: AppState = Depends(get_state)) -> dict:
    status = state.google_auth.status()
    return {"configured": status.configured, "authorized": status.authorized,
            "account": status.account, "loginCommand": LOGIN_HINT}
