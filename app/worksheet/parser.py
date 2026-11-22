"""把 .xlsx 學習單解析成題目結構（design.md D6）。

只依表頭標籤與儲存格結構判斷，不依賴檔名、工作表名、儲存格位置或題數。
"""

from __future__ import annotations

import io
import posixpath
import warnings
import zipfile
from dataclasses import dataclass, field
from datetime import date, datetime, time

import openpyxl
from lxml import etree
from openpyxl.cell.cell import MergedCell
from openpyxl.utils import get_column_letter

from .model import ImportIssue, ImportRejected, Labels, ParsedWorksheet, Question, QuestionGroup

MAX_REPORTED_ISSUES = 50

INVALID_FILE_MESSAGE = "檔案不是有效的 .xlsx 試算表或已損毀"
EMPTY_FILE_MESSAGE = "檔案是空的"
TOO_BIG_UNCOMPRESSED_MESSAGE = "檔案損毀或過大"

_NS_MAIN = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
_NS_REL = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
_NS_PKG_REL = "http://schemas.openxmlformats.org/package/2006/relationships"

Pos = tuple[int, int]  # (row, column)，皆從 1 起算


@dataclass(frozen=True)
class ImportLimits:
    max_bytes: int | None = None
    max_uncompressed_bytes: int | None = None
    max_questions: int | None = None


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


def _reject(message: str, **kwargs: object) -> ImportRejected:
    return ImportRejected([ImportIssue(message)], **kwargs)  # type: ignore[arg-type]


def _format_mb(num_bytes: int) -> str:
    mb = num_bytes / (1024 * 1024)
    return str(int(mb)) if mb.is_integer() else f"{mb:.1f}"


# ---------------------------------------------------------------- container

def check_container(data: bytes, limits: ImportLimits) -> zipfile.ZipFile:
    if len(data) == 0:
        raise _reject(EMPTY_FILE_MESSAGE)
    if limits.max_bytes is not None and len(data) > limits.max_bytes:
        raise _reject(f"檔案超過大小上限（{_format_mb(limits.max_bytes)} MB）", too_large=True)
    try:
        archive = zipfile.ZipFile(io.BytesIO(data))
        infos = archive.infolist()
    except (zipfile.BadZipFile, zipfile.LargeZipFile, ValueError, OSError, EOFError):
        raise _reject(INVALID_FILE_MESSAGE) from None
    names = {info.filename for info in infos}
    if "xl/workbook.xml" not in names:
        raise _reject(INVALID_FILE_MESSAGE)
    if any(name.lower().endswith("vbaproject.bin") for name in names):
        raise _reject(INVALID_FILE_MESSAGE)
    if any(info.flag_bits & 0x1 for info in infos):  # 加密項目
        raise _reject(INVALID_FILE_MESSAGE)
    total = sum(info.file_size for info in infos)
    if limits.max_uncompressed_bytes is not None and total > limits.max_uncompressed_bytes:
        raise _reject(TOO_BIG_UNCOMPRESSED_MESSAGE)
    return archive


def _safe_xml(raw: bytes) -> etree._Element:
    parser = etree.XMLParser(resolve_entities=False, no_network=True, huge_tree=False)
    return etree.fromstring(raw, parser)


def sheet_parts(archive: zipfile.ZipFile) -> dict[str, str]:
    """工作表名稱 → zip 內的工作表 XML 路徑。"""
    try:
        workbook = _safe_xml(archive.read("xl/workbook.xml"))
        rels = _safe_xml(archive.read("xl/_rels/workbook.xml.rels"))
    except (KeyError, etree.XMLSyntaxError, zipfile.BadZipFile, OSError):
        raise _reject(INVALID_FILE_MESSAGE) from None
    targets = {
        rel.get("Id"): rel.get("Target", "")
        for rel in rels.iter(f"{{{_NS_PKG_REL}}}Relationship")
    }
    result: dict[str, str] = {}
    for sheet in workbook.iter(f"{{{_NS_MAIN}}}sheet"):
        target = targets.get(sheet.get(f"{{{_NS_REL}}}id"))
        if not target:
            continue
        if target.startswith("/"):
            part = target.lstrip("/")
        else:
            part = posixpath.normpath(posixpath.join("xl", target))
        result[sheet.get("name", "")] = part
    return result


def _load_workbook(data: bytes) -> openpyxl.Workbook:
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            return openpyxl.load_workbook(io.BytesIO(data), read_only=False,
                                          data_only=False, keep_links=False, keep_vba=False)
    except Exception:  # openpyxl 對損毀檔案會丟出各種例外
        raise _reject(INVALID_FILE_MESSAGE) from None


# ---------------------------------------------------------------- sheet view

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
    def __init__(self, ws) -> None:  # noqa: ANN001 - openpyxl Worksheet
        self.title: str = ws.title
        self.values: dict[Pos, object] = {}
        for row in ws.iter_rows():
            for cell in row:
                if cell.value is not None and not isinstance(cell, MergedCell):
                    self.values[(cell.row, cell.column)] = cell.value
        self.max_row: int = ws.max_row
        self.anchor: dict[Pos, Pos] = {}
        self.bounds: dict[Pos, tuple[int, int, int, int]] = {}
        for merged in ws.merged_cells.ranges:
            top_left = (merged.min_row, merged.min_col)
            self.bounds[top_left] = (merged.min_row, merged.min_col, merged.max_row, merged.max_col)
            for r in range(merged.min_row, merged.max_row + 1):
                for c in range(merged.min_col, merged.max_col + 1):
                    self.anchor[(r, c)] = top_left

    def anchor_of(self, pos: Pos) -> Pos:
        return self.anchor.get(pos, pos)

    def value(self, pos: Pos) -> object:
        return self.values.get(pos)

    def col_span(self, pos: Pos) -> tuple[int, int]:
        bounds = self.bounds.get(pos)
        return (bounds[1], bounds[3]) if bounds else (pos[1], pos[1])

    def has_content(self) -> bool:
        return any(not is_blank(v) for v in self.values.values())

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

    def _field_value(self, row: int, span: tuple[int, int]) -> object:
        """span 內第一個非空白的視覺值；合併儲存格只歸屬於左上角所在的欄範圍。"""
        for col in range(span[0], span[1] + 1):
            top_left = self.anchor_of((row, col))
            if _in(span, top_left[1]):
                value = self.value(top_left)
                if not is_blank(value):
                    return value
        return None

    def is_question_row(self, row: int, header: _Header) -> bool:
        return self._field_value(row, header.question_span) is not None

    def answer_cells(self, row: int, header: _Header) -> list[Pos]:
        cells: list[Pos] = []
        seen: set[Pos] = set()
        for col in range(header.answer_span[0], header.answer_span[1] + 1):
            top_left = self.anchor_of((row, col))
            if top_left in seen:
                continue
            seen.add(top_left)
            if top_left[0] == row and _in(header.answer_span, top_left[1]):
                cells.append(top_left)
        return cells

    def parse(self, header: _Header, issues: list[ImportIssue]) -> _SheetResult:
        result = _SheetResult()
        question_rows = [
            r for r in range(header.row + 1, self.max_row + 1) if self.is_question_row(r, header)
        ]
        question_row_set = set(question_rows)

        for row in question_rows:
            cells = self.answer_cells(row, header)
            blanks = [p for p in cells if is_blank(self.value(p))]
            labelled = [p for p in cells if not is_blank(self.value(p))]
            if len(blanks) != 1:
                if not blanks:
                    message = f"工作表「{self.title}」第 {row} 列：作答欄沒有空白填空格"
                else:
                    refs = "、".join(_ref(p) for p in blanks)
                    message = (f"工作表「{self.title}」第 {row} 列：作答欄有 {len(blanks)} 個"
                               f"填空格（{refs}）")
                issues.append(ImportIssue(message, self.title, f"第 {row} 列"))
                continue
            source = self._field_value(row, header.no_span)
            sub_label = " ".join(format_value(self.value(p)) for p in labelled) or None
            result.rows.append(_RowResult(
                row=row,
                cell=blanks[0],
                source_no=format_value(source) if source is not None else None,
                sub_label=sub_label,
            ))

        for top_left, (r0, c0, r1, c1) in sorted(self.bounds.items()):
            if not _in(header.no_span, c0) or r0 <= header.row or r1 == r0:
                continue
            covered = list(range(r0, r1 + 1))
            grouped = [r for r in covered if r in question_row_set]
            if len(grouped) < 2:
                continue  # 只跨一個題目列：不是題組
            range_ref = f"{_ref((r0, c0))}:{_ref((r1, c1))}"
            missing = [r for r in covered if r not in question_row_set]
            if missing:
                rows_text = "、".join(f"第 {r} 列" for r in missing)
                issues.append(ImportIssue(
                    f"工作表「{self.title}」題組範圍 {range_ref} 包含非題目列（{rows_text}）",
                    self.title, range_ref))
                continue
            value = self.value(top_left)
            result.groups.append(_GroupResult(
                rows=grouped,
                range_ref=range_ref,
                source_no=None if is_blank(value) else format_value(value),
            ))
        return result


def _ref(pos: Pos) -> str:
    return f"{get_column_letter(pos[1])}{pos[0]}"


# ---------------------------------------------------------------- entry point

def parse_xlsx(data: bytes, labels: Labels, limits: ImportLimits) -> ParsedWorksheet:
    """解析學習單；任何問題都會以 ImportRejected 整份拒絕。"""
    archive = check_container(data, limits)
    parts = sheet_parts(archive)
    workbook = _load_workbook(data)

    views = [_SheetView(ws) for ws in workbook.worksheets]
    if not any(view.has_content() for view in views):
        raise _reject(EMPTY_FILE_MESSAGE)

    issues: list[ImportIssue] = []
    parsed: list[tuple[_SheetView, _SheetResult]] = []
    for view in views:
        header = view.find_header(labels)
        if header is None:
            continue
        if view.title not in parts:
            raise _reject(INVALID_FILE_MESSAGE)
        parsed.append((view, view.parse(header, issues)))

    if not parsed:
        raise _reject(f"找不到同時包含『{labels.no}』『{labels.question}』『{labels.answer}』的表頭列")

    if not issues and not any(result.rows for _, result in parsed):
        names = "、".join(f"「{view.title}」" for view, _ in parsed)
        raise _reject(f"找不到任何題目列（已找到表頭的工作表：{names}）")

    total = sum(len(result.rows) for _, result in parsed)
    if limits.max_questions is not None and total > limits.max_questions:
        issues.append(ImportIssue(f"題目數 {total} 超過上限 {limits.max_questions}"))

    if issues:
        raise ImportRejected(issues[:MAX_REPORTED_ISSUES], total=len(issues))

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
                sheet_name=view.title,
                sheet_part=parts[view.title],
                cell_ref=_ref(row_result.cell),
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
                sheet_name=view.title,
                range_ref=group.range_ref,
                question_nos=tuple(group_members[key]),
            ))

    return ParsedWorksheet(labels=labels, questions=tuple(questions),
                           groups=tuple(sorted(groups, key=lambda g: g.group_no)))
