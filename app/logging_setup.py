"""應用程式 log：只記錄事件與識別碼，不記錄請求內容、標頭或查詢字串。"""

from __future__ import annotations

import logging

LOGGER_NAME = "buzzer"


def setup_logging(level: int = logging.INFO) -> None:
    logger = logging.getLogger(LOGGER_NAME)
    if not logger.handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s"))
        logger.addHandler(handler)
    logger.setLevel(level)
    # 不使用 uvicorn 的 access log（會記錄完整 URL）
    logging.getLogger("uvicorn.access").disabled = True
