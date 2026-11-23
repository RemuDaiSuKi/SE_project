"""解析規則測試：每個情境都經由「活頁簿 → Sheets API JSON → 格子資料 → parse_grid」。"""

from __future__ import annotations

import openpyxl
import pytest

from app.google.convert import grid_from_sheets_api
from app.worksheet.model import ImportRejected, Labels
from app.worksheet.parser import format_value, is_blank, parse_grid

from . import builders
from .conftest import FIXTURES
from .sheets_json import workbook_to_sheets_json

LABELS = Labels("題號", "題目", "作答")


def grid_of(source):
    workbook = openpyxl.load_workbook(source) if not hasattr(source, "worksheets") else source
    return grid_from_sheets_api(workbook_to_sheets_json(workbook))


def parse(source, labels: Labels = LABELS, max_questions: int | None = 500):
    return parse_grid(grid_of(source), labels, max_questions)


def rejected(source, **kwargs) -> ImportRejected:
    with pytest.raises(ImportRejected) as info:
        parse(source, **kwargs)
    return info.value


def summary(parsed):
    return [(q.no, q.sheet_name, q.cell_ref, q.source_no, q.sub_label, q.group_no)
            for q in parsed.questions]


EXPECTED_A = [(i, "學習單", f"G{row}", str(i), None, None)
              for i, row in enumerate((5, 7, 9, 11, 13, 15), start=1)]
EXPECTED_B = [
    (1, "學習單", "H5", "1", "（1）", 1),
    (2, "學習單", "H6", "1", "（2）", 1),
    (3, "學習單", "H8", "2", "（1）", 2),
    (4, "學習單", "H9", "2", "（2）", 2),
    (5, "學習單", "G11", "3", None, None),
    (6, "學習單", "G13", "4", None, None),
]


# ---------------------------------------------------------------- helpers


@pytest.mark.parametrize("value,blank", [
    (None, True), ("", True), ("  ", True), ("　　", True), ("\t\n", True),
    ("a", False), (0, False), (1.5, False), ('=""', False), (False, False),
])
def test_is_blank(value, blank):
    assert is_blank(value) is blank


def test_format_value():
    assert format_value(3.0) == "3"
    assert format_value(3) == "3"
    assert format_value(2.5) == "2.5"
    assert format_value(" 3 ") == "3"


# ---------------------------------------------------------------- real samples


def test_real_sample_a():
    parsed = parse(FIXTURES / "sample_a.xlsx")
    assert summary(parsed) == EXPECTED_A
    assert parsed.group_count == 0
    assert {q.sheet_id for q in parsed.questions} == {0}


def test_real_sample_b():
    parsed = parse(FIXTURES / "sample_b.xlsx")
    assert summary(parsed) == EXPECTED_B
    assert [(g.group_no, g.range_ref, g.source_no, g.question_nos) for g in parsed.groups] == [
        (1, "B5:B6", "1", (1, 2)), (2, "B8:B9", "2", (3, 4))]


def test_equivalent_builders_match_real_samples():
    assert summary(parse(builders.sample_a())) == summary(parse(FIXTURES / "sample_a.xlsx"))
    assert summary(parse(builders.sample_b())) == summary(parse(FIXTURES / "sample_b.xlsx"))


# ---------------------------------------------------------------- layouts


def test_alt_layout():
    # 作答範圍內有兩段文字時，子題標籤只取第一個（與 SpecKit 組一致）
    parsed = parse(builders.alt_layout())
    assert [(q.no, q.cell_ref, q.source_no, q.sub_label) for q in parsed.questions] == [
        (1, "E3", "1", "答："), (2, "E5", "2", "答："), (3, "E7", "3", "答：")]


def test_multi_sheet_skips_sheet_without_header_and_numbers_across_sheets():
    parsed = parse(builders.multi_sheet())
    assert [(q.no, q.sheet_name, q.cell_ref) for q in parsed.questions] == [
        (1, "第一節", "G5"), (2, "第一節", "G6"), (3, "第一節", "G7"), (4, "第一節", "G8"),
        (5, "第二節", "C3"), (6, "第二節", "C4"), (7, "第二節", "C5")]
    # 工作表以 Google 工作表 ID 識別
    assert parsed.questions[0].sheet_id == 111 and parsed.questions[4].sheet_id == 222


def test_custom_labels():
    parsed = parse(builders.custom_labels(), labels=Labels("編號", "問題", "回答"))
    assert parsed.question_count == 6


def test_padded_labels():
    assert parse(builders.padded_labels()).question_count == 6


def test_whitespace_only_answer_is_blank():
    assert parse(builders.whitespace_answer()).questions[0].cell_ref == "G5"


def test_vertical_question_merge_counts_only_top_row():
    # 縱向合併的題目儲存格只屬於最上面那列，所以第 6 列不是題目列，題組範圍不完整
    error = rejected(builders.vertical_question_merge())
    assert error.summary == ("工作表「學習單」題組範圍 B5:B6 的第 6 列不是題目列，"
                             "題組的每一列都必須是題目列")


def test_section_title_merge_is_not_a_question_row():
    assert parse(builders.section_title_row()).question_count == 6


def test_number_merge_covering_spacer_row_rejected():
    # 題號欄縱向合併的每一列都必須是題目列，即使只涵蓋一個題目列也一樣（與 SpecKit 組一致）
    error = rejected(builders.merge_covering_spacer())
    assert error.summary == ("工作表「學習單」題組範圍 B5:B6 的第 6 列不是題目列，"
                             "題組的每一列都必須是題目列")


def test_unlabeled_source_number():
    workbook = builders.sample_a()
    workbook.active["B5"] = None
    question = parse(workbook).questions[0]
    assert question.source_no is None and question.source_no_display == "（未標示）"


# ---------------------------------------------------------------- errors


def test_blank_spreadsheet_reports_missing_header():
    assert rejected(builders.blank_workbook()).summary == \
        "找不到同時包含『題號』『題目』『作答』的表頭列"


def test_no_header():
    assert rejected(builders.no_header()).summary == "找不到同時包含『題號』『題目』『作答』的表頭列"


def test_header_only():
    assert rejected(builders.header_only()).summary == "找不到任何題目列（已找到表頭的工作表：「學習單」）"


def test_prefilled_answer():
    error = rejected(builders.prefilled())
    assert error.summary == "工作表「學習單」第 7 列：作答欄沒有空白填空格"
    assert (error.issues[0].sheet, error.issues[0].location) == ("學習單", "第 7 列")


def test_real_prefilled_sample():
    assert rejected(FIXTURES / "sample_a_wrong.xlsx").summary == \
        "工作表「學習單」第 5 列：作答欄沒有空白填空格"


def test_adjacent_blank_cells_are_one_blank():
    # 相鄰的空白儲存格算同一個填空格，以最左邊的儲存格代表（與 SpecKit 組一致）
    parsed = parse(builders.two_blanks())
    assert [(q.no, q.cell_ref) for q in parsed.questions] == [(1, "G5"), (2, "G9")]


def test_separated_blank_cells_rejected():
    error = rejected(builders.split_blanks())
    assert error.summary == ("工作表「學習單」第 9 列：作答欄有 2 個互不相連的空白區（G9、I9），"
                             "每個題目列只能有一個填空格")


def test_formula_showing_empty_text_is_blank():
    # 以顯示值判斷：公式 =""  顯示為空白，所以是填空格（與 SpecKit 組一致）
    assert parse(builders.formula_answer()).questions[0].cell_ref == "G5"


def test_vertical_answer_merge_rejected():
    error = rejected(builders.vertical_answer_merge())
    assert error.summary == "工作表「學習單」第 6 列：作答欄沒有空白填空格"


def test_group_with_non_question_row():
    error = rejected(builders.group_with_blank_row())
    assert error.summary == ("工作表「學習單」題組範圍 B5:B7 的第 7 列不是題目列，"
                             "題組的每一列都必須是題目列")
    assert error.issues[0].location == "B5:B7"


def test_each_non_question_row_in_group_is_one_issue():
    workbook = builders.group_with_blank_row()
    ws = workbook.active
    ws.unmerge_cells("B5:B7")
    ws.merge_cells("B5:B8")
    error = rejected(workbook)
    assert error.total == 2
    assert [i.message for i in error.issues] == [
        "工作表「學習單」題組範圍 B5:B8 的第 7 列不是題目列，題組的每一列都必須是題目列",
        "工作表「學習單」題組範圍 B5:B8 的第 8 列不是題目列，題組的每一列都必須是題目列"]


def test_question_limit():
    error = rejected(builders.many_questions(501))
    assert error.summary == "題目數 501 超過上限 500"
    assert parse(builders.many_questions(500)).question_count == 500


def test_question_limit_configurable():
    error = rejected(builders.many_questions(11), max_questions=10)
    assert error.summary == "題目數 11 超過上限 10"


def test_multiple_errors_reported_together():
    error = rejected(builders.multiple_errors())
    assert error.total == 2
    assert error.summary == "學習單有 2 處問題，未匯入"
    assert [i.location for i in error.issues] == ["第 7 列", "第 9 列"]


def test_all_errors_reported():
    workbook = builders.many_questions(80)
    ws = workbook.active
    for row in range(2, 82):
        ws[f"C{row}"] = "已填"
    error = rejected(workbook)
    assert error.total == 80 and len(error.issues) == 80


def test_row_errors_take_precedence_over_question_limit():
    # 檢查順序與 SpecKit 組一致：先回報逐列問題，沒有問題才檢查題數上限
    workbook = builders.many_questions(11)
    workbook.active["C2"] = "已填"
    error = rejected(workbook, max_questions=10)
    assert error.summary == "工作表「學習單」第 2 列：作答欄沒有空白填空格"
