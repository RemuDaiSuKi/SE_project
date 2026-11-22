from __future__ import annotations

import io
import zipfile

import pytest

from app.worksheet.model import ImportRejected, Labels
from app.worksheet.parser import (
    EMPTY_FILE_MESSAGE,
    INVALID_FILE_MESSAGE,
    TOO_BIG_UNCOMPRESSED_MESSAGE,
    ImportLimits,
    format_value,
    is_blank,
    parse_xlsx,
)

from . import builders
from .conftest import FIXTURES

LABELS = Labels("題號", "題目", "作答")
LIMITS = ImportLimits(10 * 1024 * 1024, 100 * 1024 * 1024, 500)


def parse(workbook_or_bytes, labels: Labels = LABELS, limits: ImportLimits = LIMITS):
    data = workbook_or_bytes if isinstance(workbook_or_bytes, bytes) else builders.to_bytes(workbook_or_bytes)
    return parse_xlsx(data, labels, limits)


def rejected(workbook_or_bytes, **kwargs) -> ImportRejected:
    with pytest.raises(ImportRejected) as info:
        parse(workbook_or_bytes, **kwargs)
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


# ---------------------------------------------------------------- real fixtures


def test_real_sample_a():
    parsed = parse((FIXTURES / "sample_a.xlsx").read_bytes())
    assert summary(parsed) == EXPECTED_A
    assert parsed.group_count == 0
    assert {q.sheet_part for q in parsed.questions} == {"xl/worksheets/sheet1.xml"}


def test_real_sample_b():
    parsed = parse((FIXTURES / "sample_b.xlsx").read_bytes())
    assert summary(parsed) == EXPECTED_B
    assert [(g.group_no, g.range_ref, g.source_no, g.question_nos) for g in parsed.groups] == [
        (1, "B5:B6", "1", (1, 2)), (2, "B8:B9", "2", (3, 4))]


def test_equivalent_builders_match_real_fixtures():
    real_a = parse((FIXTURES / "sample_a.xlsx").read_bytes())
    real_b = parse((FIXTURES / "sample_b.xlsx").read_bytes())
    assert summary(parse(builders.sample_a())) == summary(real_a)
    assert summary(parse(builders.sample_b())) == summary(real_b)


# ---------------------------------------------------------------- layouts


def test_alt_layout():
    parsed = parse(builders.alt_layout())
    assert [(q.no, q.cell_ref, q.source_no, q.sub_label) for q in parsed.questions] == [
        (1, "E3", "1", "答： 。"), (2, "E5", "2", "答： 。"), (3, "E7", "3", "答： 。")]


def test_multi_sheet_skips_sheet_without_header_and_numbers_across_sheets():
    parsed = parse(builders.multi_sheet())
    assert [(q.no, q.sheet_name, q.cell_ref) for q in parsed.questions] == [
        (1, "第一節", "G5"), (2, "第一節", "G6"), (3, "第一節", "G7"), (4, "第一節", "G8"),
        (5, "第二節", "C3"), (6, "第二節", "C4"), (7, "第二節", "C5")]
    assert parsed.questions[0].sheet_part != parsed.questions[4].sheet_part


def test_custom_labels():
    parsed = parse(builders.custom_labels(), labels=Labels("編號", "問題", "回答"))
    assert parsed.question_count == 6


def test_padded_labels():
    assert parse(builders.padded_labels()).question_count == 6


def test_whitespace_only_answer_is_blank():
    assert parse(builders.whitespace_answer()).questions[0].cell_ref == "G5"


def test_vertical_question_merge_makes_both_rows_questions():
    parsed = parse(builders.vertical_question_merge())
    assert summary(parsed)[:2] == [(1, "學習單", "H5", "1", "（1）", 1),
                                   (2, "學習單", "H6", "1", "（2）", 1)]
    assert parsed.question_count == 3


def test_section_title_merge_is_not_a_question_row():
    assert parse(builders.section_title_row()).question_count == 6


def test_merge_covering_one_question_is_not_a_group():
    parsed = parse(builders.merge_covering_spacer())
    assert parsed.group_count == 0
    assert [(q.no, q.cell_ref, q.group_no) for q in parsed.questions] == [(1, "G5", None),
                                                                          (2, "G8", None)]


def test_unlabeled_source_number():
    workbook = builders.sample_a()
    workbook.active["B5"] = None
    question = parse(workbook).questions[0]
    assert question.source_no is None and question.source_no_display == "（未標示）"


# ---------------------------------------------------------------- file errors


def test_text_file_rejected():
    assert rejected(b"just some text").summary == INVALID_FILE_MESSAGE


def test_truncated_xlsx_rejected():
    data = builders.to_bytes(builders.sample_a())
    assert rejected(data[: len(data) // 2]).summary == INVALID_FILE_MESSAGE


def test_zip_without_workbook_rejected():
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("content.xml", "<x/>")
    assert rejected(buffer.getvalue()).summary == INVALID_FILE_MESSAGE


def test_macro_workbook_rejected():
    source = zipfile.ZipFile(io.BytesIO(builders.to_bytes(builders.sample_a())))
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        for info in source.infolist():
            archive.writestr(info, source.read(info))
        archive.writestr("xl/vbaProject.bin", b"\0" * 10)
    assert rejected(buffer.getvalue()).summary == INVALID_FILE_MESSAGE


def test_empty_bytes_rejected():
    assert rejected(b"").summary == EMPTY_FILE_MESSAGE


def test_blank_workbook_rejected():
    assert rejected(builders.blank_workbook()).summary == EMPTY_FILE_MESSAGE


def test_upload_size_limit():
    data = builders.to_bytes(builders.sample_a())
    error = rejected(data, limits=ImportLimits(len(data) - 1, None, None))
    assert error.too_large
    error = rejected(b"x" * (10 * 1024 * 1024 + 1))
    assert error.summary == "檔案超過大小上限（10 MB）" and error.too_large


def test_uncompressed_size_limit_reads_only_central_directory():
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("xl/workbook.xml", "<workbook/>")
        archive.writestr("xl/huge.bin", b"\0" * (2 * 1024 * 1024))
    error = rejected(buffer.getvalue(), limits=ImportLimits(None, 1024 * 1024, None))
    assert error.summary == TOO_BIG_UNCOMPRESSED_MESSAGE


# ---------------------------------------------------------------- structure errors


def test_no_header():
    assert rejected(builders.no_header()).summary == "找不到同時包含『題號』『題目』『作答』的表頭列"


def test_header_only():
    assert rejected(builders.header_only()).summary == "找不到任何題目列（已找到表頭的工作表：「學習單」）"


def test_prefilled_answer():
    error = rejected(builders.prefilled())
    assert error.summary == "工作表「學習單」第 7 列：作答欄沒有空白填空格"
    assert (error.issues[0].sheet, error.issues[0].location) == ("學習單", "第 7 列")


def test_two_blank_cells():
    error = rejected(builders.two_blanks())
    assert error.summary == "工作表「學習單」第 9 列：作答欄有 2 個填空格（G9、H9）"


def test_formula_cell_is_not_blank():
    assert rejected(builders.formula_answer()).summary == "工作表「學習單」第 5 列：作答欄沒有空白填空格"


def test_vertical_answer_merge_rejected():
    error = rejected(builders.vertical_answer_merge())
    assert error.summary == "工作表「學習單」第 6 列：作答欄沒有空白填空格"


def test_group_with_non_question_row():
    error = rejected(builders.group_with_blank_row())
    assert error.summary == "工作表「學習單」題組範圍 B5:B7 包含非題目列（第 7 列）"
    assert error.issues[0].location == "B5:B7"


def test_question_limit():
    error = rejected(builders.many_questions(501))
    assert error.summary == "題目數 501 超過上限 500"
    assert parse(builders.many_questions(500)).question_count == 500


def test_question_limit_configurable():
    error = rejected(builders.many_questions(11), limits=ImportLimits(None, None, 10))
    assert error.summary == "題目數 11 超過上限 10"


def test_multiple_errors_reported_together():
    error = rejected(builders.multiple_errors())
    assert error.total == 2
    assert error.summary == "學習單有 2 處問題，未匯入"
    assert [i.location for i in error.issues] == ["第 7 列", "第 9 列"]


def test_error_list_capped_at_50():
    workbook = builders.many_questions(80)
    ws = workbook.active
    for row in range(2, 82):
        ws[f"C{row}"] = "已填"
    error = rejected(workbook)
    assert error.total == 80 and len(error.issues) == 50
