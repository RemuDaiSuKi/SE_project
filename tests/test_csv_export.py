from __future__ import annotations

import csv
import io
from urllib.parse import unquote

from app.results.csv_export import CSV_HEADER, build_csv

from .results_helpers import group, rec, result, single
from .conftest import FIXTURES, import_worksheet


def rows_of(content: bytes) -> list[list[str]]:
    assert content.startswith(b"\xef\xbb\xbf")
    return list(csv.reader(io.StringIO(content.decode("utf-8-sig"), newline="")))


def test_header_and_three_outcomes():
    res = result(1, single(1, rec(1, 1, {1: "a"}, True), rec(2, 2, {1: "b"}), rec(3, 3, {1: "c"})))
    out = build_csv(res)
    assert out.record_count == 3
    assert rows_of(out.content) == [
        list(CSV_HEADER),
        ["1", "第一組", "a", "1", "無效"],
        ["1", "第二組", "b", "2", "成功"],
        ["1", "第三組", "c", "3", "未搶到"],
    ]


def test_group_expanded_per_question():
    res = result(1, group(1, (1, 2), rec(1, 1, {1: "甲", 2: "乙"})))
    assert rows_of(build_csv(res).content)[1:] == [
        ["1", "第一組", "甲", "1", "成功"], ["2", "第一組", "乙", "1", "成功"]]


def test_sorted_by_question_then_rank_and_empty_units_skipped():
    res = result(1, single(3, rec(2, 1, {3: "x"}), rec(1, 2, {3: "y"})), single(2),
                 single(1, rec(1, 3, {1: "z"})))
    assert [(r[0], r[3]) for r in rows_of(build_csv(res).content)[1:]] == [
        ("1", "1"), ("3", "1"), ("3", "2")]


def test_special_characters_round_trip_and_crlf():
    answer = '他說"好",然後\n下一行'
    out = build_csv(result(1, single(1, rec(1, 1, {1: answer}))))
    text = out.content.decode("utf-8-sig")
    assert text.startswith("題號,組別,答案,搶答順位,結果\r\n")
    assert '"他說""好"",然後\n下一行"' in text
    assert rows_of(out.content)[1][2] == answer


def test_formula_like_answer_not_altered():
    out = build_csv(result(1, single(1, rec(1, 1, {1: "=SUM(1)"}))))
    assert rows_of(out.content)[1][2] == "=SUM(1)"


def test_no_records_only_header():
    out = build_csv(result(1, single(1), single(2)))
    assert out.record_count == 0
    assert out.content == "﻿題號,組別,答案,搶答順位,結果\r\n".encode("utf-8")


# ---------------------------------------------------------------- API


def test_csv_endpoint(client, teacher, results, gateway):
    ws_id = import_worksheet(client, teacher, gateway, FIXTURES / "sample_b.xlsx")
    results.results[7] = result(ws_id, group(1, (1, 2), rec(1, 2, {1: "甲", 2: "乙"})),
                                group(2, (3, 4)), single(5), single(6), activity_id=7)
    response = client.get("/api/activities/7/results.csv", headers=teacher)
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/csv")
    assert response.headers["x-record-count"] == "1"
    name = unquote(response.headers["content-disposition"].split("filename*=UTF-8''")[1])
    assert name == "活動7_搶答結果.csv"
    assert rows_of(response.content)[1:] == [["1", "第二組", "甲", "1", "成功"],
                                             ["2", "第二組", "乙", "1", "成功"]]


def test_csv_endpoint_empty(client, teacher, results, gateway):
    ws_id = import_worksheet(client, teacher, gateway, FIXTURES / "sample_a.xlsx")
    results.results[1] = result(ws_id, *[single(n) for n in range(1, 7)])
    response = client.get("/api/activities/1/results.csv", headers=teacher)
    assert response.headers["x-record-count"] == "0"
    assert rows_of(response.content) == [list(CSV_HEADER)]


def test_csv_requires_ended_activity(client, teacher, results):
    assert client.get("/api/activities/5/results.csv", headers=teacher).status_code == 404
    results.not_ended.add(5)
    response = client.get("/api/activities/5/results.csv", headers=teacher)
    assert response.status_code == 409
    assert response.json()["error"]["message"] == "只能匯出已結束活動的結果"
