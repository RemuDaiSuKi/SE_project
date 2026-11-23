"""搶答活動的 API、WebSocket 與端到端測試（handoff 第 4 節的驗收情境）。

TestClient 以 `with` 進入，讓 HTTP 請求與 WebSocket 共用同一個事件迴圈（引擎的 asyncio.Lock
與推播都需要同一個迴圈）。
"""

from __future__ import annotations

import logging
from contextlib import contextmanager

import pytest
from starlette.websockets import WebSocketDisconnect

from app.activity import codes

from .conftest import FIXTURES, import_worksheet, login


@pytest.fixture
def app(make_client, password, gateway):
    """回傳 (client, 老師標頭, 範例 A 的學習單 ID, 範例 B 的學習單 ID)。"""
    with make_client(activity_results=True) as client:
        teacher = login(client, password)
        ws_a = import_worksheet(client, teacher, gateway, FIXTURES / "sample_a.xlsx", "範例 A")
        ws_b = import_worksheet(client, teacher, gateway, FIXTURES / "sample_b.xlsx", "範例 B")
        yield client, teacher, ws_a, ws_b


def create(client, teacher, worksheet_id, teams=("A 組", "B 組", "C 組"), **extra):
    response = client.post("/api/activities", headers=teacher,
                           json={"worksheetId": worksheet_id, "teams": list(teams), **extra})
    assert response.status_code == 201, response.text
    return response.json()


def start(client, teacher, activity):
    response = client.post(f"/api/activities/{activity['id']}/start", headers=teacher)
    assert response.status_code == 200, response.text


def end(client, teacher, activity):
    response = client.post(f"/api/activities/{activity['id']}/end", headers=teacher)
    assert response.status_code == 200, response.text


def join(client, code, window="w1"):
    response = client.post("/api/join", json={"code": code}, headers={"X-Window-Id": window})
    assert response.status_code == 200, response.text
    return {"Authorization": f"Bearer {response.json()['token']}"}


def code_of(activity, team_index):
    return activity["teams"][team_index]["code"]


def submit(client, headers, key, answers):
    return client.post("/api/submissions", headers=headers,
                       json={"unitKey": key, "answers": {str(k): v for k, v in answers.items()}})


def error(response):
    return response.json()["error"]["message"]


def running(client, teacher, worksheet_id, teams=("A 組", "B 組", "C 組"), **extra):
    """建立並開始活動，各組各用一個視窗加入；回傳 (活動, [各組標頭])。"""
    activity = create(client, teacher, worksheet_id, teams, **extra)
    start(client, teacher, activity)
    heads = [join(client, code_of(activity, i), f"w{i}") for i in range(len(teams))]
    return activity, heads


@contextmanager
def socket(client, token_headers):
    token = token_headers["Authorization"].split(" ", 1)[1]
    with client.websocket_connect("/ws") as ws:
        ws.send_json({"type": "auth", "token": token})
        snapshot = ws.receive_json()
        assert snapshot["type"] == "snapshot"
        yield ws, snapshot


# ---------- 活動與代碼 ----------

def test_create_activity(app):
    client, teacher, ws_a, _ = app
    activity = create(client, teacher, ws_a)
    assert activity["phase"] == "preparing"
    assert [u["key"] for u in activity["units"]] == [f"Q{i}" for i in range(1, 7)]
    team_codes = [t["code"] for t in activity["teams"]]
    assert len(set(team_codes)) == 3 and all(codes.is_well_formed(c) for c in team_codes)
    assert activity["fairness"] == {"enabled": True, "cooldownSeconds": 10, "cooldownLead": 2}


def test_single_live_activity(app):
    client, teacher, ws_a, _ = app
    create(client, teacher, ws_a)
    response = client.post("/api/activities", headers=teacher, json={"worksheetId": ws_a, "teams": ["甲"]})
    assert response.status_code == 409
    assert error(response) == "已有一場準備中或搶答中的活動，請先結束它再建立新活動"


@pytest.mark.parametrize("teams,message", [
    (["甲", "乙", "甲"], "組名不可重複：甲"),
    (["甲", "  "], "第 2 組的組名不可為空白"),
    ([str(i) for i in range(21)], "組數必須是 1–20 組"),
])
def test_team_validation(app, teams, message):
    client, teacher, ws_a, _ = app
    response = client.post("/api/activities", headers=teacher, json={"worksheetId": ws_a, "teams": teams})
    assert response.status_code == 400 and error(response) == message
    assert client.get("/api/activities", headers=teacher).json()["activities"] == []


def test_create_rejects_unknown_fields_and_out_of_range(app):
    client, teacher, ws_a, _ = app
    for body in ({"worksheetId": ws_a, "teams": ["甲"], "extra": 1},
                 {"worksheetId": ws_a, "teams": ["甲"], "cooldownSeconds": 601},
                 {"worksheetId": ws_a, "teams": ["甲"], "cooldownLead": 0}):
        assert client.post("/api/activities", headers=teacher, json=body).status_code == 400
    response = client.post("/api/activities", headers=teacher, json={"worksheetId": 999, "teams": ["甲"]})
    assert response.status_code == 404 and error(response) == "找不到學習單"


def test_override_cooldown(app):
    client, teacher, ws_a, _ = app
    activity = create(client, teacher, ws_a, cooldownSeconds=5, cooldownLead=3, fairnessEnabled=False)
    assert activity["fairness"] == {"enabled": False, "cooldownSeconds": 5, "cooldownLead": 3}


# ---------- 加入 ----------

def test_join_normalizes_code(app):
    client, teacher, ws_a, _ = app
    activity = create(client, teacher, ws_a)
    code = code_of(activity, 1)
    response = client.post("/api/join", json={"code": f" {code[:3].lower()} {code[3:].lower()} "},
                           headers={"X-Window-Id": "w"})
    assert response.status_code == 200
    body = response.json()
    assert body["team"] == {"id": 2, "name": "B 組"} and body["phase"] == "preparing"
    assert body["activityId"] == activity["id"] and code not in response.text


def test_join_format_errors_not_counted_and_lockout(app, clock):
    client, teacher, ws_a, _ = app
    activity = create(client, teacher, ws_a)
    for _ in range(10):
        response = client.post("/api/join", json={"code": "12345"}, headers={"X-Window-Id": "w1"})
        assert response.status_code == 400 and error(response) == "組別代碼格式不正確（6 碼英數字）"
    wrong = "ZZZZZZ" if "ZZZZZZ" not in [t["code"] for t in activity["teams"]] else "YYYYYY"
    for _ in range(5):
        response = client.post("/api/join", json={"code": wrong}, headers={"X-Window-Id": "w1"})
        assert response.status_code == 400 and error(response) == "組別代碼錯誤"
        assert "A 組" not in response.text
    locked = client.post("/api/join", json={"code": code_of(activity, 0)}, headers={"X-Window-Id": "w1"})
    assert locked.status_code == 429
    assert error(locked) == "代碼輸入錯誤次數過多，請於 60 秒後再試"
    assert locked.headers["Retry-After"] == "60" and locked.json()["error"]["retryAfterSeconds"] == 60
    join(client, code_of(activity, 0), "w2")  # 其他視窗不受影響
    clock.advance(60)
    join(client, code_of(activity, 0), "w1")


def test_join_global_limit(make_client, password, gateway, settings, clock):
    override = settings.model_copy(update={"join_global_max_failures": 3})
    with make_client(settings_override=override, activity_results=True) as client:
        teacher = login(client, password)
        ws_a = import_worksheet(client, teacher, gateway, FIXTURES / "sample_a.xlsx")
        activity = create(client, teacher, ws_a)
        wrong = next(c for c in ("ZZZZZZ", "YYYYYY") if c not in [t["code"] for t in activity["teams"]])
        for i in range(3):
            client.post("/api/join", json={"code": wrong}, headers={"X-Window-Id": f"x{i}"})
            clock.advance(10)
        response = client.post("/api/join", json={"code": code_of(activity, 0)},
                               headers={"X-Window-Id": "fresh"})
        assert response.status_code == 429 and response.json()["error"]["retryAfterSeconds"] == 30
        clock.advance(30)
        join(client, code_of(activity, 0), "fresh")


def test_codes_only_join_live_activity(app):
    client, teacher, ws_a, _ = app
    activity = create(client, teacher, ws_a)
    start(client, teacher, activity)
    end(client, teacher, activity)
    response = client.post("/api/join", json={"code": code_of(activity, 0)}, headers={"X-Window-Id": "w"})
    assert response.status_code == 400 and error(response) == "組別代碼錯誤"
    teams = client.get(f"/api/activities/{activity['id']}", headers=teacher).json()["teams"]
    assert all(t["code"] is None for t in teams)


def test_regenerate_code(app):
    client, teacher, ws_a, _ = app
    activity, heads = running(client, teacher, ws_a)
    assert submit(client, heads[0], "Q1", {1: "答"}).status_code == 200
    old = code_of(activity, 0)
    with socket(client, heads[0]) as (ws, _):
        response = client.post(f"/api/activities/{activity['id']}/teams/1/regenerate-code", headers=teacher)
        assert response.status_code == 200
        new = response.json()["code"]
        assert ws.receive_json()["type"] == "sessionRevoked"
        with pytest.raises(WebSocketDisconnect) as closed:
            ws.receive_json()
        assert closed.value.code == 4403
    me = client.get("/api/me", headers=heads[0])
    assert me.status_code == 401 and error(me) == "組別身分無效或已失效，請重新輸入組別代碼"
    assert client.post("/api/join", json={"code": old}, headers={"X-Window-Id": "z"}).status_code == 400
    again = join(client, new, "z")
    mine = client.get("/api/me", headers=again).json()["mySubmissions"]
    assert [(m["unitKey"], m["outcome"]) for m in mine] == [("Q1", "success")]
    assert client.get("/api/me", headers=heads[1]).status_code == 200  # 其他組不受影響


# ---------- 階段 ----------

def test_phase_moves_forward_only(app):
    client, teacher, ws_a, _ = app
    activity = create(client, teacher, ws_a)
    response = client.post(f"/api/activities/{activity['id']}/end", headers=teacher)
    assert response.status_code == 409 and error(response) == "只有搶答中的活動可以結束"
    start(client, teacher, activity)
    end(client, teacher, activity)
    response = client.post(f"/api/activities/{activity['id']}/start", headers=teacher)
    assert response.status_code == 409 and error(response) == "只有準備中的活動可以開始搶答"


def test_student_cannot_manage(app):
    client, teacher, ws_a, _ = app
    activity, heads = running(client, teacher, ws_a)
    aid = activity["id"]
    for method, path in [("POST", "/api/activities"), ("GET", "/api/activities"),
                         ("GET", f"/api/activities/{aid}"), ("POST", f"/api/activities/{aid}/end"),
                         ("POST", f"/api/activities/{aid}/teams/1/regenerate-code"),
                         ("POST", f"/api/activities/{aid}/units/Q1/invalidate")]:
        response = client.request(method, path, headers=heads[0],
                                  json={"worksheetId": ws_a, "teams": ["x"]})
        assert response.status_code == 403 and error(response) == "無權限執行此操作", path
    assert client.get(f"/api/activities/{aid}", headers=teacher).json()["phase"] == "running"


# ---------- 送出 ----------

def test_submissions(app):
    client, teacher, ws_a, _ = app
    activity, heads = running(client, teacher, ws_a)
    first = submit(client, heads[0], "Q5", {5: "  甲  "})
    assert first.json() == {"unitKey": "Q5", "rank": 1, "outcome": "success", "message": "搶答成功！"}
    second = submit(client, heads[1], "Q5", {5: "乙"})
    assert second.json()["message"] == "未搶到，第 2 順位"
    again = submit(client, heads[0], "Q5", {5: "再一次"})
    assert again.status_code == 409 and error(again) == "本組已作答此題"
    assert submit(client, heads[2], "Q4", {4: "   "}).json()["error"]["message"] == "第 4 題的答案不可為空白"
    assert error(submit(client, heads[2], "Q4", {4: "字" * 201})) == "第 4 題的答案超過 200 字"
    assert submit(client, heads[2], "Q4", {4: "字" * 200}).json()["rank"] == 1
    assert error(submit(client, heads[2], "Q99", {99: "x"})) == "找不到這個搶答單位"
    assert error(submit(client, heads[2], "Q6", {"x": "a"})) == "答案的題號必須是數字"
    view = client.get(f"/api/activities/{activity['id']}", headers=teacher).json()
    q5 = next(u for u in view["units"] if u["key"] == "Q5")
    assert [(s["teamName"], s["answers"], s["rank"], s["outcome"]) for s in q5["submissions"]] == [
        ("A 組", {"5": "甲"}, 1, "success"), ("B 組", {"5": "乙"}, 2, "lost")]


def test_extra_fields_rejected(app):
    client, teacher, ws_a, _ = app
    activity, heads = running(client, teacher, ws_a)
    response = client.post("/api/submissions", headers=heads[0],
                           json={"unitKey": "Q1", "answers": {"1": "a"}, "timestamp": 0, "result": "success"})
    assert response.status_code == 400
    view = client.get(f"/api/activities/{activity['id']}", headers=teacher).json()
    assert view["units"][0]["submissions"] == []


def test_not_running(app):
    client, teacher, ws_a, _ = app
    activity = create(client, teacher, ws_a)
    head = join(client, code_of(activity, 0))
    assert error(submit(client, head, "Q1", {1: "a"})) == "目前不在搶答時間"
    start(client, teacher, activity)
    end(client, teacher, activity)
    response = submit(client, head, "Q1", {1: "a"})
    assert response.status_code == 409 and error(response) == "目前不在搶答時間"


def test_group_units(app):
    client, teacher, _, ws_b = app
    activity, heads = running(client, teacher, ws_b)
    assert [u["key"] for u in activity["units"]] == ["G1", "G2", "Q5", "Q6"]
    assert error(submit(client, heads[0], "G1", {1: "甲"})) == "題組必須一次送出全部題目的答案。缺少第 2 題"
    assert error(submit(client, heads[0], "Q1", {1: "甲"})) == "找不到這個搶答單位"
    ok = submit(client, heads[0], "G1", {1: "甲", 2: "乙"})
    assert ok.json()["outcome"] == "success"
    teams = client.get(f"/api/activities/{activity['id']}", headers=teacher).json()["teams"]
    assert teams[0]["wins"] == 1


# ---------- 冷卻 ----------

def test_cooldown(app, clock):
    client, teacher, ws_a, _ = app
    activity, heads = running(client, teacher, ws_a)
    submit(client, heads[0], "Q1", {1: "a"})
    submit(client, heads[0], "Q2", {2: "a"})       # 2 − 0 = 2：冷卻 10 秒
    clock.advance(3.5)
    blocked = submit(client, heads[0], "Q3", {3: "a"})
    assert blocked.status_code == 409
    assert error(blocked) == "本組領先其他組別，冷卻中，請在 7 秒後再送出"
    assert blocked.json()["error"]["retryAfterSeconds"] == 7
    assert submit(client, heads[1], "Q3", {3: "b"}).json()["rank"] == 1
    assert client.get("/api/me", headers=heads[0]).json()["cooldownRemaining"] == 7
    assert client.get("/api/me", headers=heads[1]).json()["cooldownRemaining"] == 0
    teacher_view = client.get(f"/api/activities/{activity['id']}", headers=teacher).json()
    assert [t["cooldownRemaining"] for t in teacher_view["teams"]] == [7, 0, 0]
    clock.advance(7)
    assert submit(client, heads[0], "Q3", {3: "a"}).json()["rank"] == 2


# ---------- 判定無效 ----------

def test_invalidate_promote_and_notify(app):
    client, teacher, ws_a, _ = app
    activity, heads = running(client, teacher, ws_a, fairnessEnabled=False)
    aid = activity["id"]
    display = activity["units"][4]["display"]
    submit(client, heads[0], "Q5", {5: "甲"})
    submit(client, heads[1], "Q5", {5: "乙"})
    with socket(client, heads[0]) as (wa, _), socket(client, heads[1]) as (wb, _), \
            socket(client, heads[2]) as (wc, _):
        response = client.post(f"/api/activities/{aid}/units/Q5/invalidate", headers=teacher)
        assert response.json() == {"unitKey": "Q5", "invalidatedTeamId": 1, "promotedTeamId": 2,
                                   "unitStatus": "won"}
        a_msg = wa.receive_json()
        assert a_msg == {"type": "invalidated", "unitKey": "Q5",
                         "message": f"{display}的答案已被老師判定無效"}
        b_msg = wb.receive_json()
        assert b_msg == {"type": "promoted", "unitKey": "Q5", "message": f"{display}遞補為搶答成功"}
        # C 組沒有收到通知：它的下一則訊息是自己的送出結果
        submit(client, heads[2], "Q6", {6: "丙"})
        assert wc.receive_json()["type"] == "teamSubmission"
    # 沒有成功者時拒絕
    response = client.post(f"/api/activities/{aid}/units/Q1/invalidate", headers=teacher)
    assert response.status_code == 409 and error(response) == "這個搶答單位目前沒有成功者，無法判定無效"


def test_invalidate_reopens(app):
    client, teacher, ws_a, _ = app
    activity, heads = running(client, teacher, ws_a, fairnessEnabled=False)
    submit(client, heads[0], "Q5", {5: "甲"})
    result = client.post(f"/api/activities/{activity['id']}/units/Q5/invalidate", headers=teacher).json()
    assert result["promotedTeamId"] is None and result["unitStatus"] == "open"
    assert error(submit(client, heads[0], "Q5", {5: "再"})) == "本組已作答此題"
    reopened = submit(client, heads[2], "Q5", {5: "丙"}).json()
    assert (reopened["rank"], reopened["outcome"]) == (2, "success")


# ---------- 隔離、檢視與結果 ----------

def test_isolation_before_end(app):
    client, teacher, ws_a, _ = app
    activity, heads = running(client, teacher, ws_a)
    submit(client, heads[1], "Q5", {5: "B 組的答案"})
    me = client.get("/api/me", headers=heads[0])
    assert "B 組的答案" not in me.text and "status" not in me.text
    assert me.json()["results"] is None
    results = client.get(f"/api/activities/{activity['id']}/results", headers=heads[0])
    assert results.status_code == 409 and error(results) == "活動尚未結束，結束後才能檢視結果"


def test_results_after_end(app):
    client, teacher, ws_a, _ = app
    activity, heads = running(client, teacher, ws_a)
    aid = activity["id"]
    submit(client, heads[0], "Q5", {5: "甲"})
    submit(client, heads[1], "Q5", {5: "乙"})
    end(client, teacher, activity)
    student = client.get(f"/api/activities/{aid}/results", headers=heads[2]).json()
    q5 = next(u for u in student["units"] if u["key"] == "Q5")
    assert q5["winner"] == {"teamId": 1, "teamName": "A 組", "answers": {"5": "甲"}}
    assert "乙" not in str(student)
    assert next(u for u in student["units"] if u["key"] == "Q1")["status"] == "no_winner"
    assert [t["wins"] for t in student["teams"]] == [1, 0, 0]
    full = client.get(f"/api/activities/{aid}/results", headers=teacher).json()
    assert len(next(u for u in full["units"] if u["key"] == "Q5")["submissions"]) == 2
    assert client.get(f"/api/activities/{aid}/results").status_code == 403
    me = client.get("/api/me", headers=heads[1]).json()
    assert me["results"]["units"][4]["winner"]["teamId"] == 1
    assert client.get(f"/api/activities/{aid}/phase").json() == {"phase": "ended"}


# ---------- WebSocket ----------

def test_websocket_auth(make_client, password, settings):
    override = settings.model_copy(update={"ws_auth_timeout_seconds": 0.1})
    with make_client(settings_override=override, activity_results=True) as client:
        with client.websocket_connect("/ws") as ws:
            with pytest.raises(WebSocketDisconnect) as closed:
                ws.receive_json()
            assert closed.value.code == 4401
        with client.websocket_connect("/ws") as ws:
            ws.send_json({"type": "auth", "token": "not-a-token"})
            with pytest.raises(WebSocketDisconnect) as closed:
                ws.receive_json()
            assert closed.value.code == 4401
        teacher = login(client, password)
        with socket(client, teacher) as (_, snapshot):
            assert snapshot == {"type": "snapshot", "activity": None}


def test_websocket_sync(app):
    client, teacher, ws_a, _ = app
    activity = create(client, teacher, ws_a)
    a1 = join(client, code_of(activity, 0), "a1")
    a2 = join(client, code_of(activity, 0), "a2")
    b = join(client, code_of(activity, 1), "b")
    with socket(client, teacher) as (wt, snap_t), socket(client, a1) as (w1, snap_1), \
            socket(client, a2) as (w2, _), socket(client, b) as (wb, snap_b):
        assert snap_t["activity"]["id"] == activity["id"]
        assert snap_1["team"]["name"] == "A 組" and snap_b["team"]["name"] == "B 組"
        start(client, teacher, activity)
        for ws in (wt, w1, w2, wb):
            assert ws.receive_json() == {"type": "phaseChanged", "phase": "running"}
        submit(client, a1, "Q5", {5: "甲"})
        for ws in (w1, w2):
            assert ws.receive_json() == {"type": "teamSubmission", "unitKey": "Q5", "rank": 1,
                                         "outcome": "success"}
        teacher_msg = wt.receive_json()
        assert teacher_msg["type"] == "submission" and teacher_msg["answers"] == {"5": "甲"}
        submit(client, b, "Q5", {5: "乙"})
        # B 組的下一則訊息是自己的結果，沒有收到 A 組的送出
        assert wb.receive_json() == {"type": "teamSubmission", "unitKey": "Q5", "rank": 2,
                                     "outcome": "lost"}
        end(client, teacher, activity)
        assert wb.receive_json() == {"type": "phaseChanged", "phase": "ended"}
        final = wb.receive_json()
        assert final["type"] == "snapshot" and final["results"]["units"][4]["winner"]["teamId"] == 1


def test_reconnect_gets_snapshot(app, clock):
    client, teacher, ws_a, _ = app
    activity, heads = running(client, teacher, ws_a)
    submit(client, heads[0], "Q1", {1: "a"})
    submit(client, heads[0], "Q2", {2: "a"})
    with socket(client, heads[0]) as (_, snapshot):
        assert snapshot["phase"] == "running" and snapshot["cooldownRemaining"] == 10
        assert [m["unitKey"] for m in snapshot["mySubmissions"]] == ["Q1", "Q2"]
    late = join(client, code_of(activity, 0), "late")
    assert len(client.get("/api/me", headers=late).json()["mySubmissions"]) == 2


# ---------- 保存與重啟 ----------

def test_end_persist_failure(app, monkeypatch):
    client, teacher, ws_a, _ = app
    activity, heads = running(client, teacher, ws_a)
    repo = client.app.state.buzzer.activities.repo

    def broken(*_args, **_kwargs):
        raise OSError("disk full")

    monkeypatch.setattr(repo, "persist_results", broken)
    response = client.post(f"/api/activities/{activity['id']}/end", headers=teacher)
    assert response.status_code == 500
    assert error(response) == "結果保存失敗，活動仍在進行中，請再試一次"
    assert client.get(f"/api/activities/{activity['id']}/phase").json() == {"phase": "running"}
    assert submit(client, heads[0], "Q1", {1: "a"}).status_code == 200


def test_restart(make_client, password, gateway):
    with make_client(activity_results=True) as client:
        teacher = login(client, password)
        ws_b = import_worksheet(client, teacher, gateway, FIXTURES / "sample_b.xlsx")
        ended, heads = running(client, teacher, ws_b)
        submit(client, heads[0], "Q5", {5: "甲"})
        submit(client, heads[1], "Q5", {5: "乙"})
        end(client, teacher, ended)
        live, live_heads = running(client, teacher, ws_b)
        csv_before = client.get(f"/api/activities/{ended['id']}/results.csv", headers=teacher).content
    with make_client(activity_results=True) as client:   # 重新啟動
        teacher = login(client, password)
        assert client.get(f"/api/activities/{live['id']}/phase").json() == {"phase": "interrupted"}
        response = client.get(f"/api/activities/{live['id']}", headers=teacher)
        assert response.status_code == 409
        assert error(response) == "活動已中斷（伺服器曾重新啟動），請老師重新建立活動"
        assert client.get("/api/me", headers=live_heads[0]).status_code == 401
        assert client.post(f"/api/activities/{live['id']}/writeback", headers=teacher).status_code == 409
        assert client.get(f"/api/activities/{ended['id']}/results.csv", headers=teacher).content == csv_before
        # 重啟後判定無效：遞補並保存
        result = client.post(f"/api/activities/{ended['id']}/units/Q5/invalidate", headers=teacher).json()
        assert result["promotedTeamId"] == 2
        create(client, teacher, ws_b)  # 可以建立新活動
    with make_client(activity_results=True) as client:
        teacher = login(client, password)
        results = client.get(f"/api/activities/{ended['id']}/results", headers=teacher).json()
        q5 = next(u for u in results["units"] if u["key"] == "Q5")
        assert q5["winner"]["teamId"] == 2


# ---------- 端到端：寫回與 CSV ----------

def test_end_to_end_writeback_and_csv(app, gateway):
    client, teacher, _, ws_b = app
    activity, heads = running(client, teacher, ws_b, fairnessEnabled=False)
    aid = activity["id"]
    submit(client, heads[0], "G1", {1: "甲", 2: "乙"})
    submit(client, heads[1], "G1", {1: "丙", 2: "丁"})
    submit(client, heads[2], "Q5", {5: "戊"})
    submit(client, heads[1], "Q6", {6: "己"})
    assert client.post(f"/api/activities/{aid}/writeback", headers=teacher).status_code == 409
    end(client, teacher, activity)
    client.post(f"/api/activities/{aid}/units/Q6/invalidate", headers=teacher)
    writeback = client.post(f"/api/activities/{aid}/writeback", headers=teacher)
    assert writeback.status_code == 200, writeback.text
    assert writeback.json()["written"] == [1, 2, 5] and writeback.json()["empty"] == [3, 4, 6]
    written = {w.cell_ref: w.text for w in gateway.writes[-1][1]}
    assert written == {"H5": "甲", "H6": "乙", "G11": "戊"}
    csv_response = client.get(f"/api/activities/{aid}/results.csv", headers=teacher)
    assert csv_response.headers["X-Record-Count"] == "4"
    lines = csv_response.content.decode("utf-8-sig").splitlines()
    assert lines[0] == "題號,組別,答案,搶答順位,結果"
    assert lines[1:] == ["1,A 組,甲,1,成功", "1,B 組,丙,2,未搶到", "2,A 組,乙,1,成功",
                         "2,B 組,丁,2,未搶到", "5,C 組,戊,1,成功", "6,B 組,己,1,無效"]
    student = client.get(f"/api/activities/{aid}/results", headers=heads[2]).json()
    winners = {u["key"]: u["winner"] and u["winner"]["teamId"] for u in student["units"]}
    assert winners == {"G1": 1, "G2": None, "Q5": 3, "Q6": None}


# ---------- log ----------

def test_activity_flow_never_logs_secrets(app, password, caplog, capsys):
    caplog.set_level(logging.DEBUG)
    client, teacher, ws_a, _ = app
    activity, heads = running(client, teacher, ws_a)
    submit(client, heads[0], "Q1", {1: "a"})
    new_code = client.post(f"/api/activities/{activity['id']}/teams/2/regenerate-code",
                           headers=teacher).json()["code"]
    end(client, teacher, activity)
    captured = capsys.readouterr()
    everything = caplog.text + captured.out + captured.err
    assert "開始搶答" in caplog.text
    secrets_used = [password, teacher["Authorization"].split()[1], new_code,
                    *[t["code"] for t in activity["teams"]],
                    *[h["Authorization"].split()[1] for h in heads]]
    for secret in secrets_used:
        assert secret not in everything
