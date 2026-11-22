"""手動驗證：以真實 Google 帳號把測試答案寫回已確認的學習單（design.md D12）。

只用於驗證，請對學習單的「副本」執行，因為答案會直接寫入原試算表。

用法（在專案根目錄）：
    .venv\\Scripts\\python scripts\\google_writeback_check.py --list
    .venv\\Scripts\\python scripts\\google_writeback_check.py <學習單編號>

寫入內容為「測試答案 N」，並刻意讓第 2 題所屬的搶答單位沒有成功答案（保持空白）。
"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.config import Settings  # noqa: E402
from app.db import Database  # noqa: E402
from app.google.auth import GoogleAuth  # noqa: E402
from app.google.errors import SheetsError  # noqa: E402
from app.google.gateway import GoogleSheetsGateway  # noqa: E402
from app.results.contract import ActivityResult, ResultGroup, ResultRecord, ResultUnit  # noqa: E402
from app.worksheet.store import StoredWorksheet, WorksheetStore  # noqa: E402
from app.worksheet.writeback import StructureMismatch, write_back, writeback_message  # noqa: E402

SKIPPED_QUESTION = 2


def build_result(worksheet: StoredWorksheet) -> ActivityResult:
    units: list[ResultUnit] = []
    grouped = {no for g in worksheet.parsed.groups for no in g.question_nos}
    candidates = [(f"G{g.group_no}", g.question_nos) for g in worksheet.parsed.groups]
    candidates += [(f"Q{q.no}", (q.no,)) for q in worksheet.parsed.questions if q.no not in grouped]
    for unit_id, nos in sorted(candidates, key=lambda c: c[1][0]):
        records: tuple[ResultRecord, ...] = ()
        if SKIPPED_QUESTION not in nos:
            records = (ResultRecord(1, 1, {no: f"測試答案 {no}" for no in nos}),)
        units.append(ResultUnit(unit_id, tuple(nos), records))
    return ActivityResult(0, worksheet.id, datetime.now(timezone.utc),
                          (ResultGroup(1, "測試組"),), tuple(units))


def main() -> int:
    parser = argparse.ArgumentParser(description="手動驗證 Google 試算表寫回")
    parser.add_argument("worksheet_id", nargs="?", type=int, help="已確認學習單的編號")
    parser.add_argument("--list", action="store_true", help="列出已確認的學習單")
    args = parser.parse_args()

    settings = Settings()
    db = Database(Path(settings.data_dir) / "buzzer.db")
    store = WorksheetStore(db)
    if args.list or args.worksheet_id is None:
        for ws in store.list():
            print(f"{ws.id}\t{ws.title}\t{ws.question_count} 題\t{ws.spreadsheet_url}")
        return 0

    worksheet = store.get(args.worksheet_id)
    if worksheet is None:
        print("找不到學習單", file=sys.stderr)
        return 1
    auth = GoogleAuth(settings.google_client_secrets_path, settings.google_token_path)
    gateway = GoogleSheetsGateway(auth, timeout_seconds=settings.google_timeout_seconds)
    try:
        report = write_back(build_result(worksheet), worksheet, gateway)
    except SheetsError as exc:
        print(exc.message, file=sys.stderr)
        return 1
    except StructureMismatch as exc:
        print("學習單結構與匯入時不一致，無法寫回：", file=sys.stderr)
        for problem in exc.problems:
            print(f"  - {problem}", file=sys.stderr)
        return 1
    print(writeback_message(report))
    print(f"請開啟試算表確認：{worksheet.spreadsheet_url}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
