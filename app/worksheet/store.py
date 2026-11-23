"""匯入預覽與已確認學習單（皆存在 SQLite）。"""

from __future__ import annotations

import json
import secrets
import threading
from collections.abc import Callable
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import TypeVar

from ..db import Database
from .model import Labels, ParsedWorksheet, Question, QuestionGroup

T = TypeVar("T")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def parsed_to_json(parsed: ParsedWorksheet) -> str:
    return json.dumps({"labels": asdict(parsed.labels),
                       "questions": [asdict(q) for q in parsed.questions],
                       "groups": [asdict(g) for g in parsed.groups]}, ensure_ascii=False)


def parsed_from_json(text: str) -> ParsedWorksheet:
    data = json.loads(text)
    return ParsedWorksheet(
        labels=Labels(**data["labels"]),
        questions=tuple(Question(**q) for q in data["questions"]),
        groups=tuple(QuestionGroup(**{**g, "question_nos": tuple(g["question_nos"])})
                     for g in data["groups"]),
    )


@dataclass(frozen=True)
class Preview:
    preview_id: str
    spreadsheet_id: str
    spreadsheet_url: str
    title: str
    parsed: ParsedWorksheet


class PreviewStore:
    """未確認的匯入預覽：保存在資料庫、沒有有效期限，伺服器重啟後仍可確認。

    每份預覽只能從「待確認」變成「已確認」或「已取消」一次（與 SpecKit 組一致）。
    """

    def __init__(self, db: Database) -> None:
        self._db = db
        self._lock = threading.Lock()

    def add(self, spreadsheet_id: str, spreadsheet_url: str, title: str,
            parsed: ParsedWorksheet) -> Preview:
        preview = Preview(secrets.token_urlsafe(16), spreadsheet_id, spreadsheet_url, title, parsed)
        with self._db.transaction() as conn:
            conn.execute(
                "INSERT INTO worksheet_previews (preview_id, spreadsheet_id, spreadsheet_url,"
                " title, parsed_json, status, created_at) VALUES (?,?,?,?,?,'pending',?)",
                (preview.preview_id, spreadsheet_id, spreadsheet_url, title,
                 parsed_to_json(parsed), _now()),
            )
        return preview

    def _pending(self, preview_id: str) -> Preview | None:
        with self._db.read() as conn:
            row = conn.execute(
                "SELECT * FROM worksheet_previews WHERE preview_id = ? AND status = 'pending'",
                (preview_id,)).fetchone()
        if row is None:
            return None
        return Preview(row["preview_id"], row["spreadsheet_id"], row["spreadsheet_url"],
                       row["title"], parsed_from_json(row["parsed_json"]))

    def _mark(self, preview_id: str, status: str) -> None:
        with self._db.transaction() as conn:
            conn.execute("UPDATE worksheet_previews SET status = ? WHERE preview_id = ?",
                         (status, preview_id))

    def confirm(self, preview_id: str, save: Callable[[Preview], T]) -> T | None:
        """待確認的預覽交給 save 建立學習單並標為已確認；不存在、已確認或已取消時為 None。"""
        with self._lock:
            preview = self._pending(preview_id)
            if preview is None:
                return None
            result = save(preview)
            self._mark(preview_id, "confirmed")
            return result

    def cancel(self, preview_id: str) -> bool:
        """待確認的預覽標為已取消；不存在、已確認或已取消時為 False。"""
        with self._lock:
            if self._pending(preview_id) is None:
                return False
            self._mark(preview_id, "cancelled")
            return True


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
        confirmed_at = _now()
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
