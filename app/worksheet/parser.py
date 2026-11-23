"""把試算表格子資料解析成題目結構（design.md D1；規則見 worksheet-import spec）。

只依表頭標籤與儲存格結構判斷，不依賴試算表名稱、工作表名、儲存格位置或題數。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, time

from .grid import Pos, SheetGrid, SpreadsheetGrid, cell_ref
from .model import ImportIssue, ImportRejected, Labels, ParsedWorksheet, Question, QuestionGroup

def is_blank(value: object) -> bool:
    """沒有值，或只有空白字元（含全形空白）。公式與數值都算非空白。"""
    return value is None or (isinstance(value, str) and value.strip() == "")


def format_value(value: object) -> str:
    if isinstance(value, bool):
        return "TRUE" if value else "FALSE"
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    if isinstance(value, (datetime, date, time)):
        return value.isoformat()
    return str(value).strip()


def _reject(message: str) -> ImportRejected:
    return ImportRejected([ImportIssue(message)])


@dataclass(frozen=True)
class _Header:
    row: int
    no_span: tuple[int, int]
    question_span: tuple[int, int]
    answer_span: tuple[int, int]


def _in(span: tuple[int, int], col: int) -> bool:
    return span[0] <= col <= span[1]


@dataclass
class _RowResult:
    row: int
    cell: Pos
    source_no: str | None
    sub_label: str | None


@dataclass
class _GroupResult:
    rows: list[int]
    range_ref: str
    source_no: str | None


@dataclass
class _SheetResult:
    rows: list[_RowResult] = field(default_factory=list)
    groups: list[_GroupResult] = field(default_factory=list)


class _SheetView:
    def __init__(self, sheet: SheetGrid) -> None:
        self.sheet = sheet
        self.title = sheet.title
        self.values = sheet.values
        self.max_row = sheet.max_row
        self.anchor: dict[Pos, Pos] = {}
        self.bounds: dict[Pos, tuple[int, int, int, int]] = {}
        for r0, c0, r1, c1 in sheet.merges:
            top_left = (r0, c0)
            self.bounds[top_left] = (r0, c0, r1, c1)
            for r in range(r0, r1 + 1):
                for c in range(c0, c1 + 1):
                    self.anchor[(r, c)] = top_left

    def anchor_of(self, pos: Pos) -> Pos:
        return self.anchor.get(pos, pos)

    def value(self, pos: Pos) -> object:
        # 合併範圍中非左上角的儲存格一律視為沒有值
        if self.anchor_of(pos) != pos:
            return None
        return self.values.get(pos)

    def col_span(self, pos: Pos) -> tuple[int, int]:
        bounds = self.bounds.get(pos)
        return (bounds[1], bounds[3]) if bounds else (pos[1], pos[1])

    def find_header(self, labels: Labels) -> _Header | None:
        wanted = {labels.no: "no", labels.question: "question", labels.answer: "answer"}
        rows: dict[int, dict[str, tuple[int, int]]] = {}
        for pos in sorted(self.values):  # 依 (列, 欄) 排序，同列最左邊的先出現
            if self.anchor_of(pos) != pos:
                continue
            value = self.value(pos)
            if not isinstance(value, str):
                continue
            key = wanted.get(value.strip())
            if key is None:
                continue
            found = rows.setdefault(pos[0], {})
            found.setdefault(key, self.col_span(pos))
        for row in sorted(rows):
            found = rows[row]
            if len(found) == 3:
                return _Header(row, found["no"], found["question"], found["answer"])
        return None

    def _row_value(self, row: int, span: tuple[int, int]) -> object:
        """這一列在 span 內第一個有內容的儲存格值。

        只看位在這一列本身的儲存格：被上方合併範圍覆蓋的格子不算（縱向合併只屬於最上面那列）。
        """
        for col in range(span[0], span[1] + 1):
            pos = (row, col)
            if self.anchor_of(pos) == pos:
                value = self.value(pos)
                if not is_blank(value):
                    return value
        return None

    def is_question_row(self, row: int, header: _Header) -> bool:
        return self._row_value(row, header.question_span) is not None

    def answer_cells(self, row: int, header: _Header) -> list[Pos]:
        """作答範圍內屬於這一列的儲存格，依欄順序；合併範圍算一格，以左上角代表。"""
        cells: list[Pos] = []
        for col in range(header.answer_span[0], header.answer_span[1] + 1):
            pos = (row, col)
            if self.anchor_of(pos) == pos:
                cells.append(pos)
        return cells

    def parse(self, header: _Header, issues: list[ImportIssue]) -> _SheetResult:
        result = _SheetResult()
        question_rows = [
            r for r in range(header.row + 1, self.max_row + 1) if self.is_question_row(r, header)
        ]
        question_row_set = set(question_rows)

        for row in question_rows:
            cells = self.answer_cells(row, header)
            # 相鄰的空白儲存格視為同一個填空區段，以最左邊的儲存格代表（與 SpecKit 組一致）
            segments: list[Pos] = []
            previous_blank = False
            for pos in cells:
                blank = is_blank(self.value(pos))
                if blank and not previous_blank:
                    segments.append(pos)
                previous_blank = blank
            if len(segments) != 1:
                if not segments:
                    message = f"工作表「{self.title}」第 {row} 列：作答欄沒有空白填空格"
                else:
                    refs = "、".join(cell_ref(p) for p in segments)
                    message = (f"工作表「{self.title}」第 {row} 列：作答欄有 {len(segments)} 個"
                               f"互不相連的空白區（{refs}），每個題目列只能有一個填空格")
                issues.append(ImportIssue(message, self.title, f"第 {row} 列"))
                continue
            source = self._row_value(row, header.no_span)
            # 子題標籤：作答範圍內第一個有內容的儲存格
            label = next((self.value(p) for p in cells if not is_blank(self.value(p))), None)
            result.rows.append(_RowResult(
                row=row,
                cell=segments[0],
                source_no=format_value(source) if source is not None else None,
                sub_label=format_value(label) if label is not None else None,
            ))

        for top_left, (r0, c0, r1, c1) in sorted(self.bounds.items()):
            if not _in(header.no_span, c0) or r0 <= header.row or r1 == r0:
                continue
            # 題號欄縱向合併的每一列都必須是題目列，否則整份拒絕（與 SpecKit 組一致）
            covered = list(range(r0, r1 + 1))
            grouped = [r for r in covered if r in question_row_set]
            range_ref = f"{cell_ref((r0, c0))}:{cell_ref((r1, c1))}"
            missing = [r for r in covered if r not in question_row_set]
            if missing:
                # 每個非題目列各算一處問題（與 SpecKit 組一致）
                for r in missing:
                    issues.append(ImportIssue(
                        f"工作表「{self.title}」題組範圍 {range_ref} 的第 {r} 列不是題目列，"
                        "題組的每一列都必須是題目列",
                        self.title, range_ref))
                continue
            value = self.value(top_left)
            result.groups.append(_GroupResult(
                rows=grouped,
                range_ref=range_ref,
                source_no=None if is_blank(value) else format_value(value),
            ))
        return result


def parse_grid(grid: SpreadsheetGrid, labels: Labels,
               max_questions: int | None = None) -> ParsedWorksheet:
    """解析學習單；任何問題都會以 ImportRejected 整份拒絕。"""
    views = [_SheetView(sheet) for sheet in grid.sheets]
    issues: list[ImportIssue] = []
    parsed: list[tuple[_SheetView, _SheetResult]] = []
    for view in views:
        header = view.find_header(labels)
        if header is None:
            continue
        parsed.append((view, view.parse(header, issues)))

    # 檢查順序與 SpecKit 組一致：表頭 → 逐列問題（一次全部列出）→ 沒有題目列 → 題數上限
    if not parsed:
        raise _reject(f"找不到同時包含『{labels.no}』『{labels.question}』『{labels.answer}』的表頭列")

    if issues:
        raise ImportRejected(issues)

    if not any(result.rows for _, result in parsed):
        names = "、".join(f"「{view.title}」" for view, _ in parsed)
        raise _reject(f"找不到任何題目列（已找到表頭的工作表：{names}）")

    total = sum(len(result.rows) for _, result in parsed)
    if max_questions is not None and total > max_questions:
        raise _reject(f"題目數 {total} 超過上限 {max_questions}")

    questions: list[Question] = []
    groups: list[QuestionGroup] = []
    for view, result in parsed:
        group_of_row: dict[int, _GroupResult] = {}
        for group in result.groups:
            for row in group.rows:
                group_of_row[row] = group
        group_numbers: dict[int, int] = {}
        group_members: dict[int, list[int]] = {}
        for row_result in result.rows:
            no = len(questions) + 1
            group = group_of_row.get(row_result.row)
            group_no = None
            if group is not None:
                key = id(group)
                if key not in group_numbers:
                    group_numbers[key] = len(groups) + len(group_numbers) + 1
                    group_members[key] = []
                group_no = group_numbers[key]
                group_members[key].append(no)
            questions.append(Question(
                no=no,
                sheet_id=view.sheet.sheet_id,
                sheet_name=view.title,
                cell_ref=cell_ref(row_result.cell),
                row=row_result.row,
                source_no=group.source_no if group is not None else row_result.source_no,
                sub_label=row_result.sub_label,
                group_no=group_no,
            ))
        for group in sorted(result.groups, key=lambda g: g.rows[0]):
            key = id(group)
            groups.append(QuestionGroup(
                group_no=group_numbers[key],
                source_no=group.source_no,
                sheet_id=view.sheet.sheet_id,
                sheet_name=view.title,
                range_ref=group.range_ref,
                question_nos=tuple(group_members[key]),
            ))

    return ParsedWorksheet(labels=labels, questions=tuple(questions),
                           groups=tuple(sorted(groups, key=lambda g: g.group_no)))
