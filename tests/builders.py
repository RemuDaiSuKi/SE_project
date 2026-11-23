"""以 openpyxl 產生測試用的 .xlsx 輸入檔（只用來產生輸入，不用於寫回）。"""

from __future__ import annotations

import io
from collections.abc import Iterable

from openpyxl import Workbook
from openpyxl.worksheet.worksheet import Worksheet

QUESTION_TEXT = "題目敘述"


def to_bytes(workbook: Workbook) -> bytes:
    buffer = io.BytesIO()
    workbook.save(buffer)
    return buffer.getvalue()


def _fresh(title: str = "學習單") -> tuple[Workbook, Worksheet]:
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = title
    return workbook, sheet


def write_header(ws: Worksheet, row: int = 4, labels: tuple[str, str, str] = ("題號", "題目", "作答"),
                 no_col: str = "B", question: str = "C:F", answer: str = "G:H") -> None:
    ws[f"{no_col}{row}"] = labels[0]
    q_start, q_end = question.split(":") if ":" in question else (question, question)
    a_start, a_end = answer.split(":") if ":" in answer else (answer, answer)
    ws[f"{q_start}{row}"] = labels[1]
    ws[f"{a_start}{row}"] = labels[2]
    if q_start != q_end:
        ws.merge_cells(f"{q_start}{row}:{q_end}{row}")
    if a_start != a_end:
        ws.merge_cells(f"{a_start}{row}:{a_end}{row}")


def add_single(ws: Worksheet, row: int, number: object, *, merge_answer: bool = True,
               answer_value: object = None) -> None:
    ws[f"B{row}"] = number
    ws[f"C{row}"] = f"{QUESTION_TEXT}{row}"
    ws.merge_cells(f"C{row}:F{row}")
    if answer_value is not None:
        ws[f"G{row}"] = answer_value
    if merge_answer:
        ws.merge_cells(f"G{row}:H{row}")


def sample_a(rows: Iterable[int] = (5, 7, 9, 11, 13, 15), labels=("題號", "題目", "作答")) -> Workbook:
    """與範例 A 等價：表頭第 4 列、題號 B、題目 C:F、作答 G:H，分隔列為 B:H 合併。"""
    workbook, ws = _fresh()
    ws["B2"] = "計算機概論基礎 學習單"
    ws.merge_cells("B2:H2")
    write_header(ws, labels=labels)
    rows = list(rows)
    for index, row in enumerate(rows, start=1):
        add_single(ws, row, float(index))
        if index < len(rows):
            ws.merge_cells(f"B{row + 1}:H{row + 1}")
    return workbook


def add_group(ws: Worksheet, first_row: int, number: object, size: int = 2) -> None:
    last = first_row + size - 1
    ws[f"B{first_row}"] = number
    ws.merge_cells(f"B{first_row}:B{last}")
    for offset in range(size):
        row = first_row + offset
        ws[f"C{row}"] = f"{QUESTION_TEXT}{row}"
        ws.merge_cells(f"C{row}:F{row}")
        ws[f"G{row}"] = f"（{offset + 1}）"


def sample_b() -> Workbook:
    """與範例 B 等價：B5:B6、B8:B9 題組，G 欄子題標籤、H 欄填空；G11、G13 單題。"""
    workbook, ws = _fresh()
    ws["B2"] = "計算機概論基礎 學習單"
    ws.merge_cells("B2:H2")
    write_header(ws)
    add_group(ws, 5, 1.0)
    add_group(ws, 8, 2.0)
    add_single(ws, 11, 3.0)
    add_single(ws, 13, 4.0)
    return workbook


def alt_layout() -> Workbook:
    """排版不同：表頭第 2 列、題號 A、題目 B、作答 D:F（未合併，D、F 有文字、E 空白）。"""
    workbook, ws = _fresh("練習")
    ws["A2"] = "題號"
    ws["B2"] = "題目"
    ws["D2"] = "作答"
    ws.merge_cells("D2:F2")
    for index, row in enumerate((3, 5, 7), start=1):
        ws[f"A{row}"] = index
        ws[f"B{row}"] = f"{QUESTION_TEXT}{row}"
        ws[f"D{row}"] = "答："
        ws[f"F{row}"] = "。"
    return workbook


def multi_sheet() -> Workbook:
    """「說明」（無表頭）、「第一節」4 題、隱藏的「第二節」3 題。"""
    workbook, intro = _fresh("說明")
    intro["A1"] = "本學習單共兩節。"
    first = workbook.create_sheet("第一節")
    write_header(first)
    for index, row in enumerate((5, 6, 7, 8), start=1):
        add_single(first, row, index)
    second = workbook.create_sheet("第二節")
    second.sheet_state = "hidden"
    write_header(second, row=2, no_col="A", question="B", answer="C")
    for index, row in enumerate((3, 4, 5), start=1):
        second[f"A{row}"] = index
        second[f"B{row}"] = f"{QUESTION_TEXT}{row}"
    return workbook


def many_questions(count: int) -> Workbook:
    workbook, ws = _fresh()
    write_header(ws, row=1, no_col="A", question="B", answer="C")
    for index in range(1, count + 1):
        ws[f"A{index + 1}"] = index
        ws[f"B{index + 1}"] = "題"
    return workbook


def blank_workbook() -> Workbook:
    workbook, ws = _fresh()
    ws["A1"] = "   "
    return workbook


def no_header() -> Workbook:
    workbook, ws = _fresh()
    ws["A1"] = "題號"
    ws["B2"] = "題目"
    ws["C3"] = "作答"
    return workbook


def header_only() -> Workbook:
    workbook, ws = _fresh()
    write_header(ws)
    return workbook


def prefilled() -> Workbook:
    """第 7 列的作答格已有答案。"""
    workbook = sample_a()
    workbook.active["G7"] = "已填好的答案"
    return workbook


def two_blanks() -> Workbook:
    """第 9 列的 G9、H9 未合併且都空白（相鄰，算一個填空格）。"""
    workbook, ws = _fresh()
    write_header(ws)
    add_single(ws, 5, 1)
    add_single(ws, 9, 2, merge_answer=False)
    return workbook


def _plain_question(ws: Worksheet, row: int, number: object) -> None:
    ws[f"B{row}"] = number
    ws[f"C{row}"] = f"{QUESTION_TEXT}{row}"
    ws.merge_cells(f"C{row}:F{row}")


def split_blanks() -> Workbook:
    """作答欄 G:I；第 9 列未合併，G9、I9 空白、H9 有文字（兩個互不相連的空白）。"""
    workbook, ws = _fresh()
    write_header(ws, answer="G:I")
    _plain_question(ws, 5, 1)
    ws.merge_cells("G5:I5")
    _plain_question(ws, 9, 2)
    ws["H9"] = "（1）"
    return workbook


def group_with_blank_row() -> Workbook:
    """題號 B5:B7 合併，第 5、6 列是題目列、第 7 列不是。"""
    workbook, ws = _fresh()
    write_header(ws)
    add_group(ws, 5, 1, size=2)
    ws.unmerge_cells("B5:B6")
    ws.merge_cells("B5:B7")
    return workbook


def merge_covering_spacer() -> Workbook:
    """題號 B5:B6 合併，但只有第 5 列是題目列（第 6 列為空白分隔列）。"""
    workbook, ws = _fresh()
    write_header(ws)
    add_single(ws, 5, 1)
    ws.merge_cells("B5:B6")
    add_single(ws, 8, 2)
    return workbook


def vertical_answer_merge() -> Workbook:
    """題組的作答儲存格 H5:H6 縱向合併。"""
    workbook = sample_b()
    workbook.active.merge_cells("H5:H6")
    return workbook


def vertical_question_merge() -> Workbook:
    """題組內題目儲存格 C5:F6 縱向合併（只有 C5 有文字）。"""
    workbook, ws = _fresh()
    write_header(ws)
    ws["B5"] = 1
    ws.merge_cells("B5:B6")
    ws["C5"] = QUESTION_TEXT
    ws.merge_cells("C5:F6")
    ws["G5"] = "（1）"
    ws["G6"] = "（2）"
    add_single(ws, 8, 2)
    return workbook


def section_title_row() -> Workbook:
    """表頭以下有 B:H 整列合併的段落標題（左上角在題號欄）。"""
    workbook = sample_a()
    ws = workbook.active
    ws["B10"] = "第二部分"
    return workbook


def formula_answer() -> Workbook:
    workbook, ws = _fresh()
    write_header(ws)
    add_single(ws, 5, 1)
    ws["G5"] = '=""'
    return workbook


def custom_labels() -> Workbook:
    return sample_a(labels=("編號", "問題", "回答"))


def padded_labels() -> Workbook:
    return sample_a(labels=(" 題號 ", "　題目　", "作答 "))


def whitespace_answer() -> Workbook:
    workbook = sample_a()
    workbook.active["G5"] = "　　"
    return workbook


def multiple_errors() -> Workbook:
    """第 7 列沒有填空格、第 9 列有 2 個互不相連的空白。"""
    workbook = split_blanks()
    ws = workbook.active
    _plain_question(ws, 7, 3)
    ws["G7"] = "答案"
    ws.merge_cells("G7:I7")
    return workbook
