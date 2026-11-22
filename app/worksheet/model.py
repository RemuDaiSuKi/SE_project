"""學習單解析結果的資料結構。"""

from __future__ import annotations

from dataclasses import dataclass

UNLABELED_SOURCE_NO = "（未標示）"


@dataclass(frozen=True)
class Labels:
    no: str
    question: str
    answer: str


@dataclass(frozen=True)
class Question:
    no: int                  # 系統題號 1..N
    sheet_name: str
    sheet_part: str          # zip 內的工作表 XML 路徑，例如 xl/worksheets/sheet1.xml
    cell_ref: str            # 填空格（合併時為左上角），例如 G5
    row: int
    source_no: str | None    # 學習單原始題號；沒有內容時為 None
    sub_label: str | None
    group_no: int | None

    @property
    def source_no_display(self) -> str:
        return self.source_no if self.source_no else UNLABELED_SOURCE_NO

    @property
    def location(self) -> str:
        return f"{self.sheet_name}!{self.cell_ref}"

    def identity(self) -> tuple:
        """寫回前一致性比對用的欄位。"""
        return (self.no, self.sheet_name, self.sheet_part, self.cell_ref, self.row,
                self.source_no, self.sub_label, self.group_no)


@dataclass(frozen=True)
class QuestionGroup:
    group_no: int
    source_no: str | None
    sheet_name: str
    range_ref: str           # 題號欄的合併範圍，例如 B5:B6
    question_nos: tuple[int, ...]

    @property
    def source_no_display(self) -> str:
        return self.source_no if self.source_no else UNLABELED_SOURCE_NO


@dataclass(frozen=True)
class ParsedWorksheet:
    labels: Labels
    questions: tuple[Question, ...]
    groups: tuple[QuestionGroup, ...]

    @property
    def question_count(self) -> int:
        return len(self.questions)

    @property
    def group_count(self) -> int:
        return len(self.groups)


@dataclass(frozen=True)
class ImportIssue:
    message: str
    sheet: str | None = None
    location: str | None = None


class ImportRejected(Exception):
    """學習單被整份拒絕。"""

    def __init__(self, issues: list[ImportIssue], *, too_large: bool = False,
                 total: int | None = None) -> None:
        super().__init__(issues[0].message if issues else "")
        self.issues = issues
        self.too_large = too_large
        self.total = total if total is not None else len(issues)

    @property
    def summary(self) -> str:
        if self.total == 1:
            return self.issues[0].message
        return f"學習單有 {self.total} 處問題，未匯入"
