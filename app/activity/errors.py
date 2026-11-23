"""搶答活動的領域例外。不依賴 FastAPI；API 層轉成 AppError（design.md D9）。

訊息文字與 SpecKit 組相同，依本組慣例省略句尾的句號。
"""

from __future__ import annotations

from enum import Enum
from typing import Any


class ActivityError(Exception):
    status = 400
    code = "ERROR"

    def __init__(self, message: str, *, extra: dict[str, Any] | None = None,
                 headers: dict[str, str] | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.extra = extra or {}
        self.headers = headers or {}


class InvalidState(ActivityError):
    status = 409
    code = "INVALID_STATE"


class NotFound(ActivityError):
    status = 404
    code = "NOT_FOUND"


class InvalidInput(ActivityError):
    status = 400
    code = "INVALID_INPUT"


class ActivityInProgress(ActivityError):
    status = 409
    code = "ACTIVITY_IN_PROGRESS"

    def __init__(self) -> None:
        super().__init__("已有一場準備中或搶答中的活動，請先結束它再建立新活動")


class ActivityInterrupted(ActivityError):
    status = 409
    code = "ACTIVITY_INTERRUPTED"

    def __init__(self, message: str = "活動已中斷（伺服器曾重新啟動），請老師重新建立活動") -> None:
        super().__init__(message)


class NotEnded(ActivityError):
    status = 409
    code = "NOT_ENDED"

    def __init__(self) -> None:
        super().__init__("活動尚未結束，結束後才能檢視結果")


class PersistFailed(ActivityError):
    status = 500
    code = "PERSIST_FAILED"

    def __init__(self) -> None:
        super().__init__("結果保存失敗，活動仍在進行中，請再試一次")


class InvalidCodeFormat(ActivityError):
    status = 400
    code = "INVALID_CODE_FORMAT"

    def __init__(self) -> None:
        super().__init__("組別代碼格式不正確（6 碼英數字）")


class InvalidCode(ActivityError):
    status = 400
    code = "INVALID_CODE"

    def __init__(self) -> None:
        super().__init__("組別代碼錯誤")


class TooManyAttempts(ActivityError):
    status = 429
    code = "LOCKED"

    def __init__(self, remaining_seconds: int) -> None:
        super().__init__(f"代碼輸入錯誤次數過多，請於 {remaining_seconds} 秒後再試",
                         extra={"retryAfterSeconds": remaining_seconds},
                         headers={"Retry-After": str(remaining_seconds)})
        self.remaining_seconds = remaining_seconds


class RejectReason(str, Enum):
    NOT_RUNNING = "NOT_RUNNING"
    CODE_OUTDATED = "CODE_OUTDATED"
    COOLDOWN = "COOLDOWN"
    UNKNOWN_UNIT = "UNKNOWN_UNIT"
    INCOMPLETE_GROUP = "INCOMPLETE_GROUP"
    INVALID_ANSWER = "INVALID_ANSWER"
    ALREADY_SUBMITTED = "ALREADY_SUBMITTED"


_REJECT_STATUS = {
    RejectReason.NOT_RUNNING: 409,
    RejectReason.CODE_OUTDATED: 401,
    RejectReason.COOLDOWN: 409,
    RejectReason.UNKNOWN_UNIT: 404,
    RejectReason.INCOMPLETE_GROUP: 400,
    RejectReason.INVALID_ANSWER: 400,
    RejectReason.ALREADY_SUBMITTED: 409,
}


class SubmissionRejected(ActivityError):
    """送出被拒絕：不留紀錄、不佔順位。"""

    def __init__(self, reason: RejectReason, *, seconds: int = 0,
                 missing: list[int] | None = None, unexpected: list[int] | None = None,
                 question_no: int = 0, problem: str = "") -> None:
        self.reason = reason
        self.status = _REJECT_STATUS[reason]
        self.code = reason.value
        extra: dict[str, Any] = {}
        headers: dict[str, str] = {}
        if reason is RejectReason.NOT_RUNNING:
            message = "目前不在搶答時間"
        elif reason is RejectReason.CODE_OUTDATED:
            message = "組別身分已失效（代碼可能已重新產生），請重新輸入組別代碼"
        elif reason is RejectReason.COOLDOWN:
            message = f"本組領先其他組別，冷卻中，請在 {seconds} 秒後再送出"
            extra["retryAfterSeconds"] = seconds
            headers["Retry-After"] = str(seconds)
        elif reason is RejectReason.UNKNOWN_UNIT:
            message = "找不到這個搶答單位"
        elif reason is RejectReason.INCOMPLETE_GROUP:
            missing, unexpected = missing or [], unexpected or []
            parts = []
            if missing:
                parts.append("缺少第 " + "、".join(map(str, missing)) + " 題")
            if unexpected:
                parts.append("第 " + "、".join(map(str, unexpected)) + " 題不屬於這個單位")
            message = "題組必須一次送出全部題目的答案。" + "；".join(parts)
            extra.update(missing=missing, unexpected=unexpected)
        elif reason is RejectReason.INVALID_ANSWER:
            message = f"第 {question_no} 題的答案{problem}"
            extra["questionNo"] = question_no
        else:
            message = "本組已作答此題"
        super().__init__(message, extra=extra, headers=headers)
