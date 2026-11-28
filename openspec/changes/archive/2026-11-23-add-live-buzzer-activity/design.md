# Design

## Context

前兩個 change 已完成老師端：登入、匯入、寫回、CSV 匯出、Google 授權。寫回與 CSV 只讀取 `app/results/contract.py` 的 `ActivityResult`，而預設的結果來源 `NoActivitiesSource` 對任何活動都回答「找不到活動」。

SpecKit 組已完成並驗證他們的 002（`silverwind63/SEFinal` 的 `main`，2026-11-23）。期末要求兩組的基本功能一致，所以本 change 的**操作結果以對方的程式為準**，包括：
- 回應是成功還是拒絕，被拒絕時的原因
- 順位與結果
- 成功數與冷卻
- 可見範圍
- 保存時機

對方的規格或 research 與程式不一致時，以程式為準。例如 research 寫代碼字元 31 個，程式實際是 32 個。

交接文件 `docs/handoff-add-live-buzzer-activity.md` 第 3 節的預設中，與 SpecKit 程式不同的項目已改成對方的做法（見 D12）。

## Goals / Non-Goals

**Goals：**
- 規則 A2–A4、C11–C22 的完整流程：建立活動、代碼、加入、即時搶答、冷卻、判定無效、結束保存、重啟。
- 與 SpecKit 組的引擎逐步一致，以差異測試驗證（D11）。
- 寫回與 CSV 改由真正的活動結果驅動，兩個端點本身不改。

**Non-Goals：**
- 不支援多台電腦連線。仍只在單一電腦上以多個視窗運作，監聽位址由 `BUZZER_HOST` 決定。
- 不提供取消活動、復原判定無效、刪除活動。
- 搶答中的送出不寫入資料庫，重啟後無法恢復進行中的活動。

## Decisions

### D1. 模組結構

```
app/activity/
  codes.py        代碼產生、正規化、格式檢查、SHA-256
  units.py        由 ParsedWorksheet 推導搶答單位與標示
  errors.py       領域例外，不依賴 FastAPI
  engine.py       ActivityEngine：一場活動的判定核心，純邏輯，只依賴 asyncio
  repository.py   SQLite repository
  registry.py     ActivityRegistry：目前的活動、已載入的引擎、重啟標記
  results.py      SqliteResultSource：實作 FinalResultSource
  join_limiter.py JoinLimiter：視窗鎖定加上全體每分鐘上限
app/api/activities.py  老師端與共用端點
app/api/student.py     加入、送出、本組檢視
app/realtime.py        WebSocket 端點與推播中心 Hub
```

引擎不處理 HTTP 或 WebSocket，只回傳結果與事件清單，所以不安裝 FastAPI 也能直接測試，差異測試也可以直接 import 兩邊的引擎。

### D2. 並行：每場活動一把 asyncio.Lock

活動相關端點全部是 `async def`，每場活動一把 `asyncio.Lock`。所有會改變狀態的操作在鎖內依序執行，「伺服器處理順序」就是取得鎖的順序。這和 SpecKit 組相同，也滿足 G9。

- 推播在鎖釋放後才送出，避免慢的連線拖住判定。
- SQLite 寫入是同步呼叫，在鎖內直接執行。
- 伺服器固定單一 worker，所以不需要跨程序的鎖。

既有的匯入、寫回端點仍是同步 `def`，與搶答狀態沒有共用資料，不受影響。

### D3. 判定一律使用結果契約

引擎內的每筆送出只記錄：
- `id`、單位、組別、順位、答案、`invalidated`、送出時間

成功與否不另存，一律用 `contract.winner_of` 推導：順位最小且未被判無效的那筆。

在 SpecKit 組的程式中，遞補選的是順位最小的「未搶到」紀錄，重新開放後的新送出直接成功，所以對方明確保存的 outcome 永遠等於這個推導結果，兩邊等價。差異測試也逐步比對了結果（D11）。

成功數與寫回、CSV 共用 `success_counts` 和 `winning_answers`，不會出現兩套判定。

### D4. 送出檢查順序與冷卻

送出檢查的順序與 SpecKit 的 `ActivityEngine.submit` 相同：
1. 階段
2. 代碼版本
3. 冷卻
4. 單位
5. 題號集合
6. 依單位題號順序檢查答案
7. 本組已送出

冷卻：
- 只在即時送出成功時檢查。
- 公式為 `wins[team] - min(wins.values()) >= K`，`wins` 包含所有組。
- 冷卻記住觸發它的送出 ID，被判無效的正好是這筆時立即解除。
- 剩餘秒數以 `ceil(until - now)` 計算，到期時在讀取時移除。
- 時鐘使用 `app.security.Clock`（單調時鐘），測試以 `FakeClock` 控制。

### D5. 代碼與加入

代碼與 SpecKit 組相同：
- 字元集 `23456789ABCDEFGHJKLMNPQRSTUVWXYZ`，6 碼，以 `secrets.choice` 產生。
- 正規化為 `"".join(raw.split()).upper()`，`split()` 會去掉所有 Unicode 空白。
- 資料庫只存 `sha256(code)`，明文只在引擎的記憶體中。
- 代碼只在目前進行中的活動裡比對。

`JoinLimiter` 以視窗為單位，每個視窗的鎖定直接沿用既有設定：
- `BUZZER_LOCKOUT_MAX_FAILURES`、`BUZZER_LOCKOUT_SECONDS`（5 次／60 秒）
- 鎖定時計數歸零，成功一次也歸零。

另外記錄全體最近 60 秒內的失敗時間，達到 `BUZZER_JOIN_GLOBAL_MAX_FAILURES`（預設 60）時拒絕所有視窗。

檢查順序為：視窗鎖定 → 全體上限 → 格式 → 比對，與對方的 `check_allowed` 相同。

視窗 ID 與 SpecKit 組相同：
- 由學生頁自己產生（`crypto.randomUUID()`），存在 sessionStorage。
- 放在 `X-Window-Id` 標頭，最多 128 字，不需要先向伺服器註冊。
- 沒有帶標頭時視為同一個「unknown-window」。

老師登入仍使用既有的 `POST /api/windows` 註冊機制，兩者互不影響。

### D6. 學生身分

加入成功時以 `SessionStore.issue("group", window_id, group_id=..., activity_id=..., code_version=...)` 發 Token，沿用權限測試已經使用的 role 名稱。

新增 `require_group` 依賴，Token 無效、過期或不是組別身分時回應：
- 401 `GROUP_SESSION_INVALID`
- 訊息「組別身分無效或已失效，請重新輸入組別代碼」

重新產生代碼時：
1. 以 `revoke_where` 撤銷該組所有 Token。
2. 由 Hub 送出撤銷事件。
3. 以 4403 關閉該組的連線。

老師端點收到組別 Token 時，沿用 `require_teacher`，回應「無權限執行此操作」。

### D7. 保存與重啟

schema 第 4 版只新增資料表，不動既有資料：

| 資料表 | 內容 |
|---|---|
| `activities` | id、worksheet_id、phase、冷卻設定、建立／開始／結束時間 |
| `activity_teams` | 組別編號、組名、代碼雜湊、代碼版本；組名在活動內唯一 |
| `activity_submissions` | 送出 ID、單位、組別、順位、invalidated、送出與判無效時間；`(單位, 組別)` 與 `(單位, 順位)` 都唯一 |
| `activity_answers` | 每筆送出的「題號 → 答案」 |

保存時機：

| 時機 | 寫入內容 |
|---|---|
| 建立 | 活動與組別 |
| 開始 | 階段 |
| 結束 | 一筆交易寫入全部送出並改階段；成功後才改記憶體、清除冷卻、推播 |
| 已結束後判定無效 | 先更新資料庫，再更新記憶體 |

`create_app` 啟動時把準備中、搶答中的活動改為已中斷。`ActivityRegistry.get`：
- 記憶體中沒有、但資料庫中是已結束的活動：從資料庫載入。
- 已中斷：回應 409。

`SqliteResultSource.lookup` 從資料庫組出 `ActivityResult`。所有單位都列出，沒有紀錄的單位 records 為空。它取代 `NoActivitiesSource`，成為 `create_app` 的預設結果來源；測試仍可注入假的結果來源。

### D8. 檢視與推播

引擎提供 `view_for_teacher`、`view_for_team`、`results_view`，內容與 SpecKit 組相同，JSON 欄位改用本組的 camelCase。

結果值使用契約的 `success`、`lost`、`invalid`。單位狀態使用 `no_submission`、`won`、`open`、`no_winner`。

事件與對象：

| 事件 | 對象 |
|---|---|
| `phaseChanged`、`snapshot` | 老師與該活動所有學生 |
| `submission`（含答案） | 老師 |
| `teamSubmission`（只有本組的順位與結果） | 該組 |
| `cooldown` | 該組與老師 |
| `invalidated`、`promoted` | 相關組別（含通知文字）與老師 |
| `sessionRevoked` | 撤銷該組 |

`snapshot` 事件會依每條連線的身分各自產生快照。活動結束時送出 `snapshot`，讓學生拿到完整結果。

WebSocket 的第一則訊息必須是 `{"type": "auth", "token": ...}`，逾時為 `BUZZER_WS_AUTH_TIMEOUT_SECONDS`（預設 5）。與 SpecKit 組相同，不檢查 `Origin`。

### D9. API

| 方法 | 路徑 | 身分 | 說明 |
|---|---|---|---|
| POST | `/api/activities` | 老師 | 建立：`worksheetId`、`teams`、`fairnessEnabled?`、`cooldownSeconds?`、`cooldownLead?`，多餘欄位拒絕 |
| GET | `/api/activities` | 老師 | 活動清單 |
| GET | `/api/activities/{id}` | 老師 | 監看畫面 |
| POST | `/api/activities/{id}/start` | 老師 | 開始 |
| POST | `/api/activities/{id}/end` | 老師 | 結束並保存 |
| POST | `/api/activities/{id}/teams/{teamId}/regenerate-code` | 老師 | 重新產生代碼 |
| POST | `/api/activities/{id}/units/{unitKey}/invalidate` | 老師 | 判定無效 |
| GET | `/api/activities/{id}/results` | 老師或該活動的學生 | 結果 |
| GET | `/api/activities/{id}/phase` | 公開 | 只回傳階段 |
| POST | `/api/join` | 任何視窗 | body `code`、標頭 `X-Window-Id`，多餘欄位拒絕 |
| POST | `/api/submissions` | 學生 | `unitKey`、`answers`，多餘欄位拒絕 |
| GET | `/api/me` | 學生 | 本組畫面 |
| WS | `/ws` | 老師或學生 | 即時同步 |

錯誤沿用 `AppError` 與 `{"error": {...}}` 格式。訊息文字與 SpecKit 組相同，但依本組慣例省略句尾的句號，例如「目前不在搶答時間」。

狀態碼：

| 狀態碼 | 情況 |
|---|---|
| 400 | 格式錯誤、組別設定錯誤、代碼格式錯誤、代碼錯誤、答案不合法、題組缺漏 |
| 401 | 組別身分失效 |
| 403 | 無權限 |
| 404 | 找不到活動、學習單、組別、單位 |
| 409 | 階段不允許、已有進行中的活動、已中斷、冷卻中、已作答、尚未結束 |
| 429 | 代碼輸錯過多，附 `Retry-After` 與 `retryAfterSeconds` |
| 500 | 結果保存失敗 |

### D10. 頁面

**學生頁 `index.html` + `student.js`：**
- 輸入代碼加入。
- 以 WebSocket 接收快照與事件，斷線後 1 秒重連。
- 冷卻倒數。
- 送出時一次送出單位內所有題目。
- 結束後顯示完整結果。
- Token 失效時以公開的階段查詢判斷：已中斷顯示「活動已中斷，請老師重新建立」，其他情況顯示「組別身分已失效，請重新輸入組別代碼」。

**老師頁 `teacher.html` + `teacher.js`：**
- 從已確認的學習單建立活動，可覆寫冷卻設定。
- 顯示代碼並可重新產生。
- 開始、結束。
- 即時監看各單位狀態與送出，可判定無效。
- 各組成功數與冷卻。
- 活動清單。
- 結束後提供「寫回答案」「下載 CSV」。

### D11. 以差異測試驗證

SpecKit 組的 `ActivityEngine` 是純邏輯、時鐘可注入，可以直接 import，不需要替身模組。

比對方式：
1. 用亂數產生操作序列，同時餵給兩邊的引擎，逐步比對。
2. 操作包括送出、判定無效、時鐘前進、開始、結束、重新產生代碼。
3. 每一步比對：
   - 回應是成功還是拒絕，被拒絕時的原因（對方的 reject code 對應本組的錯誤代碼）
   - 順位與結果
   - 各組成功數、冷卻剩餘秒數
   - 單位狀態
   - 最後保存的送出

比對程式放在 repo 外面，與 `align-teacher-side-with-speckit` 的做法相同，結果記在這一節。repo 內的 `tests/test_activity_engine.py` 以固定情境涵蓋規格中的每一條規則。

**結果（2026-11-23，對照 `silverwind63/SEFinal` 的 `main`，commit `136667a`）：**

| 比對項目 | 規模 | 結果 |
|---|---|---|
| 判定引擎 | 3 組亂數種子 × 2,000 個操作序列，共約 48 萬步 | 全部一致 |
| 搶答單位與標示 | 每個序列一份隨機學習單（1–10 題，隨機題組、原始題號、子題標籤） | 全部一致 |
| 輸錯限制 | 3,000 個隨機序列（隨機上限、鎖定秒數、視窗數、時間） | 全部一致 |
| 代碼正規化、格式檢查、雜湊 | 20 萬個隨機字串（含全形空白、ß、é、小寫） | 全部一致 |

每個引擎序列：
- 1–5 組，單題與題組混合。
- 冷卻設定、答案上限隨機。
- 約 2 成的「結束」注入保存失敗。

引擎序列的每一步都比對：
- 回應是成功還是拒絕，被拒絕時的原因與訊息（去掉句尾句號後）
- 順位、結果、事件的對象與種類、冷卻事件的秒數、通知文字
- 各組成功數、冷卻剩餘秒數、單位狀態、全部送出
- 本組畫面、結束後的完整結果、老師畫面的代碼與成功數

最後還比對保存的送出。為了確認比對程式真的能抓到差異，故意把本組冷卻條件的 `<` 改成 `<=`，比對程式在第一個序列就回報不一致。

### D12. 與交接文件預設不同的地方（改成 SpecKit 組的做法）

| 項目 | 交接文件 | 本 change |
|---|---|---|
| G5 已結束活動的代碼 | 重啟後仍可加入並唯讀檢視 | 結束後就無法加入 |
| G12 多工作表的標示 | 加工作表名 | 不加 |
| 代碼字元集 | 31 字（不含 L） | 32 字（含 L） |
| 輸錯代碼的限制 | 只限每個視窗 | 每個視窗 5 次／60 秒，加上全體每分鐘 60 次 |
| 代碼格式錯誤 | 未定義 | 「格式不正確」，不算失敗次數 |
| 多餘欄位（SUB-09） | 忽略 | 以格式錯誤拒絕 |
| 答案中的控制字元 | 允許換行、拒絕其他控制字元 | 不檢查 |
| 判定無效的對象 | 指定成功的那筆紀錄，對未搶到的紀錄判無效要拒絕（INV-07） | 指定單位，判定它目前的成功者 |
| N 的範圍 | 1–300 秒 | 1–600 秒，K 為 1–100 |
| 結束後老師畫面的代碼 | 重啟後無法顯示 | 結束後一律不顯示 |
| WebSocket Origin 檢查 | 要檢查 | 不檢查 |

兩邊相同、照做的項目：
- G3：沒有取消，也不能從準備中直接結束
- G7：冷卻公式
- 單場限制
- 單位鍵值 `Q<n>` 與 `G<n>`
- 重啟後未結束的活動標為已中斷
- 結束後才保存結果
- 寫回與 CSV 的判定規則：順位最小且未被判無效的那筆為成功
- 不合法的送出不留紀錄、不佔順位

### D13. 設計圖

本 change 新增或修改的圖：

| 圖檔 | 內容 | 新增或修改 |
|---|---|---|
| `diagrams/component.puml` | 加入 activity 套件、Hub、新 API 與結果來源 | 修改 |
| `diagrams/class.puml` | 加入 ActivityEngine、ActivityRegistry、JoinLimiter、SqliteResultSource 等類別 | 修改 |
| `diagrams/state-activity.puml` | 活動狀態圖 | 新增 |
| `diagrams/sequence-join.puml` | 加入組別（代碼驗證與鎖定） | 新增 |
| `diagrams/sequence-submit.puml` | 送出與判定（含冷卻） | 新增 |
| `diagrams/sequence-invalidate.puml` | 判定無效與遞補 | 新增 |
| `diagrams/sequence-end.puml` | 結束保存與重啟 | 新增 |

設計圖只保留 PlantUML 原始檔，不提交 PNG：作業只要求 SpecKit 組畫圖，本組以 Demo 影片展示流程，而且過時的 PNG 會和 `.puml` 不一致（2026-11-23 組內決定）。原本提交的 PNG 已刪除，`openspec/config.yaml` 的規則也一併修改。需要看圖時，可以用 README「設計圖」的指令自行轉檔。

> **後續（2026-11-28）：** 為了讓 GitHub 上閱讀 design.md 的人直接看得到圖，改回提交 PNG。所有 `.puml` 都重新轉出同名 PNG，`openspec/config.yaml` 恢復「轉成 PNG 並一起提交」的規則，README 也一併更新。

## Risks / Trade-offs

- **鎖內同步寫 SQLite 會短暫擋住事件迴圈。** 結束時一次寫入全部送出，課堂規模下最多數百筆，可以接受；SpecKit 組也是這樣做。
- **鎖定以視窗為單位，可以繞過。** 重開視窗或重新註冊視窗就能繞過（G10）。全體每分鐘上限加上 32⁶ ≈ 10.7 億種組合，才是主要防線。
- **組別 Token 在活動結束後仍有效，直到時效到期或重啟。** 學生因此可以在結束後查看結果，與 SpecKit 組相同。
- **寫回後才判定無效時，舊答案會留在試算表。** 已有內容不覆蓋，老師要先手動清掉那格，兩組相同。
- **老師的 WebSocket 快照只含本次啟動後建立的活動。** 重啟後要看已結束的活動，由老師頁以活動清單與 HTTP 讀取。

## Migration Plan

- schema 由第 3 版升到第 4 版只新增資料表，既有學習單與預覽保留。
- 新設定都有預設值，既有 `.env` 不用修改。

## Open Questions

無。規則與預設都已依 SpecKit 組的程式確定。
