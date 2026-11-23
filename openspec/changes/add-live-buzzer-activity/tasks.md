# Tasks

## 1. 設定與資料庫

- [x] 1.1 `app/config.py` 新增設定，更新 `.env.example`、README 的設定表與 `tests/test_config_and_startup.py`：
  - `max_teams`、`team_name_max`、`max_answer_length`
  - `fairness_enabled`、`cooldown_seconds`（1–600）、`cooldown_lead`（1–100）
  - `join_global_max_failures`
  - `ws_auth_timeout_seconds`（0.1–60）
- [x] 1.2 `app/db.py` 升到 schema 第 4 版，只新增 `activities`、`activity_teams`、`activity_submissions`、`activity_answers`。更新 `tests/test_db.py`，驗證 v3 升級到 v4 會保留學習單與預覽

## 2. 判定引擎（不依賴 FastAPI）

- [x] 2.1 `app/activity/codes.py`、`units.py`、`errors.py`：代碼產生、正規化與格式檢查，單位推導與標示。以單元測試驗證字元集、唯一性，以及範例 B 的單位與標示（含「?」與省略括號）
- [x] 2.2 `app/activity/engine.py`：開始、結束（保存失敗時維持搶答中）、送出（D4 的檢查順序）、冷卻、判定無效與遞補、重新產生代碼、三種檢視。成功判定一律使用結果契約。以 `tests/test_activity_engine.py` 涵蓋規格中的每一條情境
- [x] 2.3 `app/activity/join_limiter.py`：視窗鎖定加上全體每分鐘上限。以單元測試驗證鎖定、歸零與全體上限的剩餘秒數

## 3. 保存與結果來源

- [x] 3.1 `app/activity/repository.py`：建立、階段、結束保存、已結束後判定無效、代碼更新、載入、啟動時標記已中斷
- [x] 3.2 `app/activity/registry.py`：單場限制、組別設定檢查、建立、取得（已結束從資料庫載入，已中斷回應 409）、以代碼找組別
- [x] 3.3 `app/activity/results.py`：`SqliteResultSource`，取代 `create_app` 預設的 `NoActivitiesSource`。以測試驗證三種狀態與 `validate_result` 通過

## 4. API 與即時同步

- [x] 4.1 `app/state.py` 新增 `require_group`；`app/api/activities.py` 實作老師端與共用端點；`app/api/student.py` 實作加入、送出、本組檢視
- [x] 4.2 `app/realtime.py`：`/ws` 驗證、快照、依對象推播、撤銷關閉 4403
- [x] 4.3 `app/main.py`：註冊 router 與 WebSocket，啟動時標記已中斷
- [x] 4.4 `tests/test_activity_api.py`：
  - 驗收情境 ACT、JOIN、PH、SUB、GRP、ISO、MON、RES、INV、COOL、PER、E2E
  - WebSocket 以 `TestClient.websocket_connect` 測試
  - 結束保存失敗以替換 repository 注入錯誤
- [x] 4.5 `tests/test_integration.py`：
  - `TEACHER_ENDPOINTS` 加入本 change 的老師端點
  - 新增搶答全流程的 log 掃描，掃描內容含密碼、老師 Token、組別 Token 與組別代碼

## 5. 頁面

- [x] 5.1 學生頁 `index.html`、`student.js`：加入、本組畫面、送出、冷卻倒數、通知、重連、結束後結果、Token 失效時的訊息
- [x] 5.2 老師頁 `teacher.html`、`teacher.js`：
  - 建立活動、代碼與重新產生、開始與結束
  - 監看與判定無效、成功數與冷卻
  - 活動清單、寫回與 CSV 下載

## 6. 設計圖

- [x] 6.1 修改 `diagrams/component.puml`、`class.puml`，新增 `state-activity.puml`、`sequence-join.puml`、`sequence-submit.puml`、`sequence-invalidate.puml`、`sequence-end.puml`

## 7. 文件

- [x] 7.1 更新 README：搶答流程、學生加入方式、新設定
- [x] 7.2 在交接文件第 7 節勾選已對齊的項目，並記錄 D12 的差異

## 8. 驗證

- [x] 8.1 在已安裝相依套件的環境執行 `python -m pytest`，確認全部通過
- [ ] 8.2 以 PlantUML 把 6.1 的 7 個 .puml 轉成 PNG，確認 PNG 已更新（見 README「設計圖」）
- [x] 8.3 執行 `openspec validate add-live-buzzer-activity --strict`
- [ ] 8.4 手動操作：一個老師視窗加三個學生視窗走完整個流程。確認以下項目後，寫回範例 B 並下載 CSV：
  - 同步在 2 秒內
  - 冷卻倒數
  - 判定無效的通知
  - 重新產生代碼後被踢出

## 9. 與 SpecKit 組比對

- [x] 9.1 以 design D11 的方法執行差異測試，把結果記在 design.md D11
- [ ] 9.2 封存本 change（`/openspec-archive-change`），把 delta spec 同步進主 spec
