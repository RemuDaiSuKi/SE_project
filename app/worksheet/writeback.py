"""把答案寫回原學習單（design.md D9）。

只修改含填空格的工作表 XML，其餘 zip 項目原樣複製；不使用 openpyxl 整份重存。
"""

from __future__ import annotations

import io
import re
import zipfile
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from lxml import etree
from openpyxl.utils.cell import column_index_from_string, coordinate_from_string

from .model import Labels, ParsedWorksheet, Question
from .parser import ImportLimits, parse_xlsx
from .model import ImportRejected
from .store import sha256_hex

_NS = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
_XML_SPACE = "{http://www.w3.org/XML/1998/namespace}space"

# XML 1.0 不允許的字元
_ILLEGAL_XML = re.compile("[^\u0009\u000a\u000d -퟿-�\U00010000-\U0010ffff]")


class StructureMismatch(Exception):
    def __init__(self, problems: list[str]) -> None:
        super().__init__("; ".join(problems))
        self.problems = problems


def strip_illegal_xml(text: str) -> str:
    return _ILLEGAL_XML.sub("", text)


# ---------------------------------------------------------------- consistency

def verify_structure(data: bytes, expected_sha256: str, expected: ParsedWorksheet,
                     labels: Labels) -> None:
    """原始檔必須與匯入時一致：雜湊值相同，且重新解析後每題都相同。"""
    problems: list[str] = []
    if sha256_hex(data) != expected_sha256:
        problems.append("原始檔案內容已在匯入後被修改")
    try:
        current = parse_xlsx(data, labels, ImportLimits())
    except ImportRejected as exc:
        problems.append("重新解析學習單失敗：" + exc.summary)
        raise StructureMismatch(problems) from None
    if current.question_count != expected.question_count:
        problems.append(f"題數不一致（匯入時 {expected.question_count} 題，"
                        f"現在 {current.question_count} 題）")
    for old, new in zip(expected.questions, current.questions):
        if old.identity() != new.identity():
            problems.append(f"第 {old.no} 題的位置或題組不一致（匯入時 {old.location}，"
                            f"現在 {new.location}）")
    old_groups = [(g.group_no, g.question_nos) for g in expected.groups]
    new_groups = [(g.group_no, g.question_nos) for g in current.groups]
    if old_groups != new_groups:
        problems.append("題組結構不一致")
    if problems:
        raise StructureMismatch(problems[:50])


# ---------------------------------------------------------------- sheet XML

def _split_ref(ref: str) -> tuple[int, int]:
    letters, row = coordinate_from_string(ref)
    return row, column_index_from_string(letters)


def _declaration(raw: bytes) -> bytes:
    if raw.startswith(b"<?xml"):
        end = raw.find(b"?>")
        if end != -1:
            return raw[: end + 2]
    return b'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'


def _indexed(children: Sequence[etree._Element], attr_to_index) -> list[tuple[int, etree._Element]]:  # noqa: ANN001
    """為列或儲存格算出索引；缺少 r 屬性時依前一個 +1（OOXML 的隱含規則）。"""
    result: list[tuple[int, etree._Element]] = []
    previous = 0
    for child in children:
        ref = child.get("r")
        index = attr_to_index(ref) if ref else previous + 1
        result.append((index, child))
        previous = index
    return result


def _find_or_create_row(sheet_data: etree._Element, row_index: int) -> etree._Element:
    rows = _indexed(sheet_data.findall(f"{{{_NS}}}row"), int)
    for index, row in rows:
        if index == row_index:
            return row
    new_row = etree.Element(f"{{{_NS}}}row", r=str(row_index))
    for index, row in rows:
        if index > row_index:
            row.addprevious(new_row)
            return new_row
    sheet_data.append(new_row)
    return new_row


def _find_or_create_cell(row: etree._Element, ref: str, col_index: int) -> etree._Element:
    cells = _indexed(row.findall(f"{{{_NS}}}c"), lambda r: _split_ref(r)[1])
    for index, cell in cells:
        if index == col_index:
            return cell
    new_cell = etree.Element(f"{{{_NS}}}c", r=ref)
    for index, cell in cells:
        if index > col_index:
            cell.addprevious(new_cell)
            break
    else:
        row.append(new_cell)
    spans = row.get("spans")
    if spans and ":" in spans:
        low, _, high = spans.partition(":")
        if low.isdigit() and high.isdigit():
            row.set("spans", f"{min(int(low), col_index)}:{max(int(high), col_index)}")
    return new_cell


def set_cell_texts(sheet_xml: bytes, values: Mapping[str, str]) -> bytes:
    """把文字寫入指定儲存格（inlineStr），保留樣式與其他所有內容。"""
    parser = etree.XMLParser(resolve_entities=False, no_network=True, huge_tree=False,
                             remove_blank_text=False)
    root = etree.fromstring(sheet_xml, parser)
    sheet_data = root.find(f"{{{_NS}}}sheetData")
    if sheet_data is None:
        raise ValueError("worksheet has no sheetData")
    for ref, text in values.items():
        row_index, col_index = _split_ref(ref)
        cell = _find_or_create_cell(_find_or_create_row(sheet_data, row_index), ref, col_index)
        for child in list(cell):
            cell.remove(child)
        cell.set("t", "inlineStr")
        inline = etree.SubElement(cell, f"{{{_NS}}}is")
        text_el = etree.SubElement(inline, f"{{{_NS}}}t")
        text_el.set(_XML_SPACE, "preserve")
        text_el.text = strip_illegal_xml(text)
    body = etree.tostring(root, encoding="UTF-8", xml_declaration=False)
    return _declaration(sheet_xml) + body


# ---------------------------------------------------------------- zip

def rebuild_zip(original: bytes, replacements: Mapping[str, bytes]) -> bytes:
    """依原順序重建 zip；未替換的項目內容原樣複製，沿用名稱、時間與壓縮方式。"""
    source = zipfile.ZipFile(io.BytesIO(original))
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w") as target:
        for info in source.infolist():
            data = replacements.get(info.filename)
            if data is None:
                data = source.read(info)
            copy = zipfile.ZipInfo(info.filename, date_time=info.date_time)
            copy.compress_type = info.compress_type
            copy.external_attr = info.external_attr
            copy.create_system = info.create_system
            copy.comment = info.comment
            copy.extra = info.extra
            target.writestr(copy, data)
    return output.getvalue()


@dataclass(frozen=True)
class WritebackOutput:
    content: bytes
    empty_question_nos: tuple[int, ...]


def build_writeback(original: bytes, questions: Sequence[Question],
                    answers: Mapping[int, str]) -> WritebackOutput:
    by_part: dict[str, dict[str, str]] = {}
    for question in questions:
        if question.no in answers:
            by_part.setdefault(question.sheet_part, {})[question.cell_ref] = answers[question.no]
    source = zipfile.ZipFile(io.BytesIO(original))
    replacements = {
        part: set_cell_texts(source.read(part), values) for part, values in by_part.items()
    }
    empty = tuple(q.no for q in questions if q.no not in answers)
    return WritebackOutput(rebuild_zip(original, replacements), empty)
