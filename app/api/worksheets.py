"""學習單匯入預覽、確認、取消與查詢。"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, Request
from starlette.concurrency import run_in_threadpool
from starlette.datastructures import UploadFile

from ..errors import AppError, ErrorDetail, not_found
from ..security import Session
from ..state import AppState, get_state, require_teacher
from ..worksheet.model import ImportRejected, Labels, ParsedWorksheet, Question, QuestionGroup
from ..worksheet.parser import ImportLimits, parse_xlsx
from ..worksheet.store import StoredWorksheet, safe_filename

logger = logging.getLogger("buzzer")
router = APIRouter(prefix="/api/worksheets")

_MULTIPART_OVERHEAD = 1024 * 1024


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
    return {"id": ws.id, "filename": ws.original_filename, "questionCount": ws.question_count,
            "groupCount": ws.group_count, "confirmedAt": ws.confirmed_at}


def _rejected(exc: ImportRejected) -> AppError:
    details = [ErrorDetail(i.message, i.sheet, i.location) for i in exc.issues]
    return AppError(413 if exc.too_large else 400, "IMPORT_INVALID", exc.summary, details=details)


@router.post("/previews", status_code=201)
async def create_preview(request: Request, _: Session = Depends(require_teacher),
                         state: AppState = Depends(get_state)) -> dict:
    settings = state.settings
    limits = ImportLimits(settings.max_upload_bytes, settings.max_uncompressed_bytes,
                          settings.max_questions)
    too_large = AppError(413, "IMPORT_INVALID",
                         f"檔案超過大小上限（{settings.max_upload_mb} MB）")
    length = request.headers.get("content-length")
    if length and length.isdigit() and int(length) > settings.max_upload_bytes + _MULTIPART_OVERHEAD:
        raise too_large
    try:
        form = await request.form(max_files=1, max_fields=5)
    except Exception:
        raise AppError(400, "BAD_REQUEST", "請求格式不正確") from None
    upload = form.get("file")
    if not isinstance(upload, UploadFile):
        raise AppError(400, "NO_FILE", "請選擇要上傳的檔案")
    data = await upload.read(settings.max_upload_bytes + 1)
    filename = safe_filename(upload.filename)
    await upload.close()
    labels = Labels(settings.label_no, settings.label_question, settings.label_answer)
    try:
        parsed = await run_in_threadpool(parse_xlsx, data, labels, limits)
    except ImportRejected as exc:
        raise _rejected(exc) from None
    preview = state.previews.add(filename, data, parsed)
    return {"previewId": preview.preview_id, "filename": filename, **parsed_json(parsed)}


@router.post("/previews/{preview_id}/confirm", status_code=201)
def confirm_preview(preview_id: str, _: Session = Depends(require_teacher),
                    state: AppState = Depends(get_state)) -> dict:
    preview = state.previews.take(preview_id)
    if preview is None:
        raise AppError(409, "PREVIEW_EXPIRED", "預覽已失效，請重新上傳")
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
