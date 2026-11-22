"""已結束活動的答案寫回與 CSV 匯出。"""

from __future__ import annotations

import logging
from pathlib import PurePath
from urllib.parse import quote

from fastapi import APIRouter, Depends
from fastapi.responses import Response

from ..errors import AppError, ErrorDetail, not_found
from ..results.contract import ActivityResult, ContractViolation, validate_result, winning_answers
from ..results.csv_export import build_csv
from ..security import Session
from ..state import AppState, get_state, require_teacher
from ..worksheet.store import StoredWorksheet
from ..worksheet.writeback import StructureMismatch, build_writeback, verify_structure

logger = logging.getLogger("buzzer")
router = APIRouter(prefix="/api/activities")

XLSX_MEDIA_TYPE = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def attachment(filename: str, fallback: str) -> str:
    return f"attachment; filename=\"{fallback}\"; filename*=UTF-8''{quote(filename)}"


def _ended_result(state: AppState, activity_id: int, not_ended_message: str) -> ActivityResult:
    lookup = state.result_source.lookup(activity_id)
    if lookup.status == "not_found":
        raise not_found("找不到活動")
    if lookup.status != "ended" or lookup.result is None:
        raise AppError(409, "ACTIVITY_NOT_ENDED", not_ended_message)
    validate_result(lookup.result)
    return lookup.result


def _worksheet_for(state: AppState, result: ActivityResult) -> StoredWorksheet:
    worksheet = state.worksheets.get(result.worksheet_id)
    if worksheet is None:
        raise AppError(409, "WORKSHEET_MISSING", "找不到活動所使用的學習單")
    known = {q.no for q in worksheet.parsed.questions}
    if any(no not in known for unit in result.units for no in unit.question_nos):
        raise ContractViolation("result refers to unknown questions")
    return worksheet


@router.post("/{activity_id}/writeback")
def writeback(activity_id: int, _: Session = Depends(require_teacher),
              state: AppState = Depends(get_state)) -> Response:
    result = _ended_result(state, activity_id, "只能對已結束的活動寫回答案")
    worksheet = _worksheet_for(state, result)
    original = state.worksheets.read_file(worksheet)
    try:
        verify_structure(original, worksheet.file_sha256, worksheet.parsed,
                         worksheet.parsed.labels)
    except StructureMismatch as exc:
        raise AppError(409, "STRUCTURE_MISMATCH", "學習單結構與匯入時不一致，無法寫回",
                       details=[ErrorDetail(p) for p in exc.problems]) from None
    output = build_writeback(original, worksheet.parsed.questions, winning_answers(result))
    stem = PurePath(worksheet.original_filename).stem or "學習單"
    logger.info("答案寫回 activity=%s 空白題數=%s", activity_id, len(output.empty_question_nos))
    return Response(
        content=output.content,
        media_type=XLSX_MEDIA_TYPE,
        headers={
            "Content-Disposition": attachment(f"{stem}_搶答結果.xlsx",
                                              f"worksheet-{activity_id}-result.xlsx"),
            "X-Empty-Questions": ",".join(str(no) for no in output.empty_question_nos),
        },
    )


@router.get("/{activity_id}/results.csv")
def export_csv(activity_id: int, _: Session = Depends(require_teacher),
               state: AppState = Depends(get_state)) -> Response:
    result = _ended_result(state, activity_id, "只能匯出已結束活動的結果")
    _worksheet_for(state, result)
    output = build_csv(result)
    logger.info("匯出 CSV activity=%s 紀錄數=%s", activity_id, output.record_count)
    return Response(
        content=output.content,
        media_type="text/csv; charset=utf-8",
        headers={
            "Content-Disposition": attachment(f"活動{activity_id}_搶答結果.csv",
                                              f"activity-{activity_id}-results.csv"),
            "X-Record-Count": str(output.record_count),
        },
    )
