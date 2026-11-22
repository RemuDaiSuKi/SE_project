"""統一的繁體中文錯誤回應。"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

logger = logging.getLogger("buzzer")

GENERIC_ERROR_MESSAGE = "系統發生錯誤，請稍後再試"
FORBIDDEN_MESSAGE = "無權限執行此操作"


@dataclass(frozen=True)
class ErrorDetail:
    message: str
    sheet: str | None = None
    location: str | None = None

    def to_json(self) -> dict[str, Any]:
        data: dict[str, Any] = {"message": self.message}
        if self.sheet is not None:
            data["sheet"] = self.sheet
        if self.location is not None:
            data["location"] = self.location
        return data


@dataclass
class AppError(Exception):
    status: int
    code: str
    message: str
    details: list[ErrorDetail] = field(default_factory=list)
    headers: dict[str, str] = field(default_factory=dict)
    extra: dict[str, Any] = field(default_factory=dict)

    def __str__(self) -> str:  # 避免例外字串為空
        return f"{self.code}: {self.message}"


def forbidden() -> AppError:
    return AppError(403, "FORBIDDEN", FORBIDDEN_MESSAGE)


def session_expired() -> AppError:
    return AppError(401, "SESSION_EXPIRED", "登入已失效，請重新登入")


def not_found(message: str = "找不到資源") -> AppError:
    return AppError(404, "NOT_FOUND", message)


def error_body(code: str, message: str, details: list[ErrorDetail] | None = None,
               extra: dict[str, Any] | None = None) -> dict[str, Any]:
    error: dict[str, Any] = {"code": code, "message": message}
    if details:
        error["details"] = [d.to_json() for d in details]
    if extra:
        error.update(extra)
    return {"error": error}


def error_response(status: int, code: str, message: str, **kwargs: Any) -> JSONResponse:
    headers = kwargs.pop("headers", None)
    return JSONResponse(error_body(code, message, **kwargs), status_code=status, headers=headers)


_HTTP_MESSAGES = {
    400: ("BAD_REQUEST", "請求格式不正確"),
    401: ("SESSION_EXPIRED", "登入已失效，請重新登入"),
    403: ("FORBIDDEN", FORBIDDEN_MESSAGE),
    404: ("NOT_FOUND", "找不到資源"),
    405: ("METHOD_NOT_ALLOWED", "不支援的請求方法"),
    413: ("PAYLOAD_TOO_LARGE", "上傳的資料過大"),
}


async def _app_error_handler(_: Request, exc: AppError) -> JSONResponse:
    return error_response(exc.status, exc.code, exc.message, details=exc.details,
                          extra=exc.extra, headers=exc.headers or None)


async def _validation_handler(_: Request, __: RequestValidationError) -> JSONResponse:
    return error_response(400, "BAD_REQUEST", "請求格式不正確")


async def _http_handler(_: Request, exc: StarletteHTTPException) -> JSONResponse:
    code, message = _HTTP_MESSAGES.get(exc.status_code, ("ERROR", GENERIC_ERROR_MESSAGE))
    return error_response(exc.status_code, code, message)


async def _unexpected_handler(request: Request, exc: Exception) -> JSONResponse:
    # 只記錄例外類型與追蹤，不記錄請求內容、標頭或查詢字串
    logger.error("未預期的錯誤 path=%s type=%s", request.url.path, type(exc).__name__,
                 exc_info=exc)
    return error_response(500, "INTERNAL_ERROR", GENERIC_ERROR_MESSAGE)


def install_error_handlers(app: FastAPI) -> None:
    app.add_exception_handler(AppError, _app_error_handler)  # type: ignore[arg-type]
    app.add_exception_handler(RequestValidationError, _validation_handler)  # type: ignore[arg-type]
    app.add_exception_handler(StarletteHTTPException, _http_handler)  # type: ignore[arg-type]
    app.add_exception_handler(Exception, _unexpected_handler)
