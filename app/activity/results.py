"""以 SQLite 為後端的最終結果來源，取代 NoActivitiesSource（design.md D7）。

直接從資料庫組出 ActivityResult：寫回與 CSV 端點在執行緒池中執行，不讀取引擎的記憶體狀態。
已結束活動的判定無效會先寫入資料庫，所以資料庫永遠是最新的結果。
"""

from __future__ import annotations

from ..results.contract import ActivityResult, FinalResultLookup, ResultGroup, ResultRecord, ResultUnit
from ..worksheet.store import WorksheetStore
from .engine import ENDED
from .repository import SqliteActivityRepository
from .units import build_units


class SqliteResultSource:
    def __init__(self, repo: SqliteActivityRepository, worksheets: WorksheetStore) -> None:
        self._repo = repo
        self._worksheets = worksheets

    def lookup(self, activity_id: int) -> FinalResultLookup:
        info = self._repo.get_info(activity_id)
        if info is None:
            return FinalResultLookup("not_found")
        if info.phase != ENDED or info.ended_at is None:
            return FinalResultLookup("not_ended")
        teams = self._repo.load_teams(activity_id)
        submissions = self._repo.load_submissions(activity_id)
        worksheet = self._worksheets.get(info.worksheet_id)
        if worksheet is not None:
            unit_list = [(u.key, u.question_nos) for u in build_units(worksheet.parsed)]
        else:  # 學習單不存在時由寫回／匯出端點回應 409；這裡只保留有紀錄的單位
            seen: dict[str, tuple[int, ...]] = {}
            for s in submissions:
                seen.setdefault(s.unit_key, tuple(sorted(s.answers)))
            unit_list = list(seen.items())
        units = tuple(
            ResultUnit(key, nos, tuple(
                ResultRecord(rank=s.rank, group_id=s.team_id, answers=dict(s.answers),
                             invalidated=s.invalidated)
                for s in sorted(submissions, key=lambda s: s.rank) if s.unit_key == key))
            for key, nos in unit_list)
        result = ActivityResult(activity_id=info.id, worksheet_id=info.worksheet_id,
                                ended_at=info.ended_at,
                                groups=tuple(ResultGroup(t.id, t.name) for t in teams),
                                units=units)
        return FinalResultLookup("ended", result)
