"""匯入預覽（記憶體）與已確認學習單（SQLite）。"""

from __future__ import annotations

import secrets
import threading
import time
from collections import OrderedDict
from dataclasses import dataclass
from datetime import datetime, timezone

from ..db import Database
from ..security import Clock
from .model import Labels, ParsedWorksheet, Question, QuestionGroup

PREVIEW_TTL_SECONDS = 30 * 60
MAX_PREVIEWS = 10


@dataclass(frozen=True)
class Preview:
    preview_id: str
    spreadsheet_id: str
    spreadsheet_url: str
    title: str
    parsed: ParsedWorksheet
    created_at: float


class PreviewStore:
    """未確認的匯入預覽：30 分鐘有效、最多 10 份，確認或取消後移除。"""

    def __init__(self, clock: Clock = time.monotonic, ttl_seconds: int = PREVIEW_TTL_SECONDS,
                 max_items: int = MAX_PREVIEWS) -> None:
        self._clock = clock
        self._ttl = ttl_seconds
        self._max = max_items
        self._items: OrderedDict[str, Preview] = OrderedDict()
        self._lock = threading.Lock()

    def _purge(self) -> None:
        now = self._clock()
        for key in [k for k, p in self._items.items() if now - p.created_at >= self._ttl]:
            del self._items[key]

    def add(self, spreadsheet_id: str, spreadsheet_url: str, title: str,
            parsed: ParsedWorksheet) -> Preview:
        preview = Preview(secrets.token_urlsafe(16), spreadsheet_id, spreadsheet_url, title,
                          parsed, self._clock())
        with self._lock:
            self._purge()
            self._items[preview.preview_id] = preview
            while len(self._items) > self._max:
                self._items.popitem(last=False)
        return preview

    def take(self, preview_id: str) -> Preview | None:
        """取出並移除；過期或不存在時為 None。"""
        with self._lock:
            self._purge()
            return self._items.pop(preview_id, None)

    def discard(self, preview_id: str) -> bool:
        with self._lock:
            self._purge()
            return self._items.pop(preview_id, None) is not None


@dataclass(frozen=True)
class StoredWorksheet:
    id: int
    spreadsheet_id: str
    spreadsheet_url: str
    title: str
    question_count: int
    group_count: int
    confirmed_at: str
    parsed: ParsedWorksheet


class WorksheetStore:
    def __init__(self, db: Database) -> None:
        self._db = db

    def save(self, preview: Preview) -> StoredWorksheet:
        parsed = preview.parsed
        confirmed_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
        with self._db.transaction() as conn:
            cursor = conn.execute(
                "INSERT INTO worksheets (spreadsheet_id, spreadsheet_url, title, label_no,"
                " label_question, label_answer, question_count, group_count, confirmed_at)"
                " VALUES (?,?,?,?,?,?,?,?,?)",
                (preview.spreadsheet_id, preview.spreadsheet_url, preview.title,
                 parsed.labels.no, parsed.labels.question, parsed.labels.answer,
                 parsed.question_count, parsed.group_count, confirmed_at),
            )
            worksheet_id = int(cursor.lastrowid)
            conn.executemany(
                "INSERT INTO worksheet_groups (worksheet_id, group_no, source_no, sheet_id,"
                " sheet_name, range_ref) VALUES (?,?,?,?,?,?)",
                [(worksheet_id, g.group_no, g.source_no, g.sheet_id, g.sheet_name, g.range_ref)
                 for g in parsed.groups],
            )
            conn.executemany(
                "INSERT INTO worksheet_questions (worksheet_id, no, sheet_id, sheet_name,"
                " cell_ref, row, source_no, sub_label, group_no) VALUES (?,?,?,?,?,?,?,?,?)",
                [(worksheet_id, q.no, q.sheet_id, q.sheet_name, q.cell_ref, q.row,
                  q.source_no, q.sub_label, q.group_no) for q in parsed.questions],
            )
        stored = self.get(worksheet_id)
        assert stored is not None
        return stored

    def list(self) -> list[StoredWorksheet]:
        with self._db.read() as conn:
            ids = [row[0] for row in conn.execute("SELECT id FROM worksheets ORDER BY id")]
        return [ws for ws in (self.get(i) for i in ids) if ws is not None]

    def get(self, worksheet_id: int) -> StoredWorksheet | None:
        with self._db.read() as conn:
            row = conn.execute("SELECT * FROM worksheets WHERE id = ?", (worksheet_id,)).fetchone()
            if row is None:
                return None
            question_rows = conn.execute(
                "SELECT * FROM worksheet_questions WHERE worksheet_id = ? ORDER BY no",
                (worksheet_id,)).fetchall()
            group_rows = conn.execute(
                "SELECT * FROM worksheet_groups WHERE worksheet_id = ? ORDER BY group_no",
                (worksheet_id,)).fetchall()
        questions = tuple(
            Question(no=q["no"], sheet_id=q["sheet_id"], sheet_name=q["sheet_name"],
                     cell_ref=q["cell_ref"], row=q["row"], source_no=q["source_no"],
                     sub_label=q["sub_label"], group_no=q["group_no"])
            for q in question_rows
        )
        groups = tuple(
            QuestionGroup(group_no=g["group_no"], source_no=g["source_no"], sheet_id=g["sheet_id"],
                          sheet_name=g["sheet_name"], range_ref=g["range_ref"],
                          question_nos=tuple(q.no for q in questions if q.group_no == g["group_no"]))
            for g in group_rows
        )
        labels = Labels(row["label_no"], row["label_question"], row["label_answer"])
        return StoredWorksheet(
            id=row["id"], spreadsheet_id=row["spreadsheet_id"],
            spreadsheet_url=row["spreadsheet_url"], title=row["title"],
            question_count=row["question_count"], group_count=row["group_count"],
            confirmed_at=row["confirmed_at"],
            parsed=ParsedWorksheet(labels=labels, questions=questions, groups=groups),
        )
