"""WebSocket 連線管理與推播（design.md D8）。

- Token 放在連線後的第一則訊息，不放在網址上，避免出現在存取紀錄。
- 推播在引擎的鎖釋放後才進行；送出失敗的連線自動移除。
- 與 SpecKit 組相同，不檢查 Origin。
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from typing import Any

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from .activity.engine import ActivityEngine, Event
from .activity.errors import ActivityError
from .activity.registry import ActivityRegistry
from .security import ROLE_TEACHER

logger = logging.getLogger("buzzer")
router = APIRouter()

CLOSE_UNAUTHORIZED = 4401
CLOSE_REVOKED = 4403
ROLE_GROUP = "group"


@dataclass(eq=False)
class Connection:
    ws: Any
    role: str                       # teacher | group
    activity_id: int | None = None
    team_id: int | None = None


def targets(event: Event, engine: ActivityEngine, connections: list[Connection]) -> list[Connection]:
    """teacher → 所有老師連線；team／revoke → 該活動該組；all → 老師與該活動所有學生。"""
    students = [c for c in connections if c.role == ROLE_GROUP and c.activity_id == engine.id]
    teachers = [c for c in connections if c.role == ROLE_TEACHER]
    if event.audience == "teacher":
        return teachers
    if event.audience in ("team", "revoke"):
        return [c for c in students if c.team_id == event.team_id]
    return teachers + students


class Hub:
    def __init__(self, registry: ActivityRegistry) -> None:
        self.registry = registry
        self.connections: list[Connection] = []

    def snapshot_for(self, conn: Connection) -> dict[str, Any]:
        if conn.role == ROLE_TEACHER:
            engine = self.registry.latest
            return {"type": "snapshot", "activity": engine.view_for_teacher() if engine else None}
        engine = self.registry.get(conn.activity_id)  # type: ignore[arg-type]
        return {"type": "snapshot", **engine.view_for_team(conn.team_id)}  # type: ignore[arg-type]

    async def send(self, conn: Connection, message: dict[str, Any]) -> None:
        try:
            await conn.ws.send_json(message)
        except Exception:  # noqa: BLE001 - 連線已斷
            self.remove(conn)

    def remove(self, conn: Connection) -> None:
        if conn in self.connections:
            self.connections.remove(conn)

    async def dispatch(self, engine: ActivityEngine, events: list[Event]) -> None:
        for event in events:
            for conn in targets(event, engine, list(self.connections)):
                if event.payload.get("type") == "snapshot":
                    try:
                        message = self.snapshot_for(conn)
                    except ActivityError:
                        continue
                    await self.send(conn, message)
                else:
                    await self.send(conn, event.payload)
                if event.audience == "revoke":
                    self.remove(conn)
                    try:
                        await conn.ws.close(code=CLOSE_REVOKED)
                    except Exception:  # noqa: BLE001
                        pass

    async def broadcast_teacher_snapshot(self) -> None:
        for conn in [c for c in self.connections if c.role == ROLE_TEACHER]:
            await self.send(conn, self.snapshot_for(conn))


def identify(state: Any, token: object) -> Connection | None:
    """Token 對應的身分；無效、過期，或組別代碼已重新產生時為 None。"""
    if not isinstance(token, str) or not token:
        return None
    session = state.sessions.resolve(token)
    if session is None:
        return None
    if session.role == ROLE_TEACHER:
        return Connection(ws=None, role=ROLE_TEACHER)
    if session.role != ROLE_GROUP:
        return None
    activity_id, team_id = session.attrs.get("activity_id"), session.attrs.get("group_id")
    try:
        engine = state.activities.get(activity_id)
    except ActivityError:
        return None
    team = engine.teams.get(team_id)
    if team is None or team.code_version != session.attrs.get("code_version"):
        return None
    return Connection(ws=None, role=ROLE_GROUP, activity_id=activity_id, team_id=team_id)


@router.websocket("/ws")
async def websocket_endpoint(ws: WebSocket) -> None:
    state = ws.app.state.buzzer
    await ws.accept()
    try:
        message = await asyncio.wait_for(ws.receive_json(),
                                         timeout=state.settings.ws_auth_timeout_seconds)
        conn = (identify(state, message.get("token"))
                if isinstance(message, dict) and message.get("type") == "auth" else None)
    except (asyncio.TimeoutError, WebSocketDisconnect, ValueError, KeyError, TypeError):
        conn = None
    if conn is None:
        try:
            await ws.close(code=CLOSE_UNAUTHORIZED)
        except Exception:  # noqa: BLE001
            pass
        return
    conn.ws = ws
    hub: Hub = state.hub
    hub.connections.append(conn)
    try:
        await hub.send(conn, hub.snapshot_for(conn))
        while True:
            await ws.receive_text()  # 客戶端不需要送任何指令；保持連線直到斷線
    except WebSocketDisconnect:
        pass
    except Exception:  # noqa: BLE001
        pass
    finally:
        hub.remove(conn)
