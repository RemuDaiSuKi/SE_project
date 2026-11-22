"""學習單匯入預覽、確認、取消與查詢。"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from starlette.concurrency import run_in_threadpool

from ..errors import AppError, ErrorDetail, not_found
from ..google.urls import canonical_url, parse_spreadsheet_id
from ..security import Session
from ..state import AppState, get_state, require_teacher
from ..worksheet.model import ImportRejected, Labels, ParsedWorksheet, Question, QuestionGroup
from ..worksheet.parser import parse_grid
from ..worksheet.store import StoredWorksheet

logger = logging.getLogger("buzzer")
router = APIRouter(prefix="/api/worksheets")

INVALID_URL_MESSAGE = "請輸入有效的 Google 試算表網址"


class PreviewBody(BaseModel):
    url: str = Field(max_length=2000)


def question_json(q: Question) -> dict:
    return {"no": q.no, "sourceNo": q.source_no_display, "subLabel": q.sub_label,
            "sheet": q.sheet_name, "cell": q.cell_ref, "location": q.location,
            "groupNo": q.group_no}


def group_json(g: QuestionGroup) -> dict:
    return {"groupNo": g.group_no, "sourceNo": g.source_no_display, "sheet": g.sheet_name,
            "range": g.range_ref, "questionNos": list(g.question_nos)}


def parsed_json(parsed: ParsedWorksheet) -> dict:
    return {"questionCount": parsed.question_count, "groupCount": parsed.group_count,
            "questions": [question_json(q) for q in parsed.questions],
            "groups": [group_json(g) for g in parsed.groups]}


def worksheet_summary(ws: StoredWorksheet) -> dict:
    return {"id": ws.id, "title": ws.title, "spreadsheetUrl": ws.spreadsheet_url,
            "questionCount": ws.question_count, "groupCount": ws.group_count,
            "confirmedAt": ws.confirmed_at}


def _rejected(exc: ImportRejected) -> AppError:
    details = [ErrorDetail(i.message, i.sheet, i.location) for i in exc.issues]
    return AppError(400, "IMPORT_INVALID", exc.summary, details=details)


@router.post("/previews", status_code=201)
async def create_preview(body: PreviewBody, _: Session = Depends(require_teacher),
                         state: AppState = Depends(get_state)) -> dict:
    spreadsheet_id = parse_spreadsheet_id(body.url)
    if spreadsheet_id is None:
        raise AppError(400, "INVALID_URL", INVALID_URL_MESSAGE)
    settings = state.settings
    labels = Labels(settings.label_no, settings.label_question, settings.label_answer)
    grid = await run_in_threadpool(state.gateway.fetch, spreadsheet_id)  # SheetsError 由例外處理器轉換
    try:
        parsed = parse_grid(grid, labels, settings.max_questions)
    except ImportRejected as exc:
        raise _rejected(exc) from None
    url = canonical_url(spreadsheet_id)
    preview = state.previews.add(spreadsheet_id, url, grid.title, parsed)
    return {"previewId": preview.preview_id, "spreadsheetTitle": grid.title,
            "spreadsheetUrl": url, **parsed_json(parsed)}


@router.post("/previews/{preview_id}/confirm", status_code=201)
def confirm_preview(preview_id: str, _: Session = Depends(require_teacher),
                    state: AppState = Depends(get_state)) -> dict:
    preview = state.previews.take(preview_id)
    if preview is None:
        raise AppError(409, "PREVIEW_EXPIRED", "預覽已失效，請重新讀取試算表")
    stored = state.worksheets.save(preview)
    logger.info("學習單已確認 id=%s 題數=%s 題組數=%s", stored.id, stored.question_count,
                stored.group_count)
    return worksheet_summary(stored)


@router.delete("/previews/{preview_id}")
def cancel_preview(preview_id: str, _: Session = Depends(require_teacher),
                   state: AppState = Depends(get_state)) -> dict:
    state.previews.discard(preview_id)
    return {"ok": True}


@router.get("")
def list_worksheets(_: Session = Depends(require_teacher),
                    state: AppState = Depends(get_state)) -> dict:
    return {"worksheets": [worksheet_summary(ws) for ws in state.worksheets.list()]}


@router.get("/{worksheet_id}")
def get_worksheet(worksheet_id: int, _: Session = Depends(require_teacher),
                  state: AppState = Depends(get_state)) -> dict:
    stored = state.worksheets.get(worksheet_id)
    if stored is None:
        raise not_found("找不到學習單")
    return {**worksheet_summary(stored), **parsed_json(stored.parsed)}
