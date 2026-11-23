# Proposal

## Why

同一系統由 SpecKit 組平行實作（`silverwind63/SEFinal`），期末要求兩組的基本功能一致。2026-11-23 逐項比對兩邊的老師端功能（登入、學習單匯入解析、寫回、Google 授權與啟動）後，發現多處行為不同。組內決議：以 SpecKit 組已完成的版本為準，只修改本 repo，對方的程式不動。

比對方式：
- 把同一批學習單同時餵給兩邊的解析器：兩份範例學習單、18 種特殊排版，加上 15,000 份隨機產生的學習單。修改後，接受或拒絕、填空格位置、原始題號、子題標籤與題組全部相同。
- 用 7 種「匯入後試算表被修改」的情境比對寫回前的結構檢查，修改後結果相同。

## What Changes

**老師登入（`teacher-auth`）**
- **BREAKING** 密碼輸錯鎖定改為所有視窗共用一個計數，預設連續 5 次鎖定 300 秒（原本以視窗為單位、鎖定 60 秒）。新增 `BUZZER_LOGIN_MAX_FAILURES`、`BUZZER_LOGIN_LOCK_SECONDS`。以視窗為單位的鎖定設定保留，給之後的組別代碼使用。
- 老師 Token 預設有效時數由 12 改為 8 小時。
- 登出維持不變：SpecKit 組的頁面也有登出按鈕，老師看到的行為相同。

**學習單匯入（`worksheet-import`）**
- **BREAKING** 儲存格改讀顯示值（`formattedValue`），公式以計算結果判斷，例如 `=""` 視為空白。
- **BREAKING** 作答範圍內相鄰的空白儲存格算同一個填空格，以最左邊的儲存格代表；只有互不相連的空白才算多個。
- **BREAKING** 題號欄的縱向合併只要涵蓋到非題目列就拒絕，即使只涵蓋一個題目列也一樣；每個非題目列各算一處問題。
- **BREAKING** 縱向合併的題目儲存格只屬於最上面那列。
- 子題標籤只取作答範圍內第一個有內容的儲存格。
- 錯誤一次全部列出，取消 50 筆上限。檢查順序改為：表頭 → 逐列問題 → 沒有題目列 → 題數上限。
- 移除「試算表沒有任何內容」，空白試算表改回報找不到表頭列。
- **BREAKING** 網址規則改為：只接受 `https://docs.google.com/spreadsheets/d/` 開頭的網址或純 ID，ID 長度 20–100，輸入上限 2048 字。
- **BREAKING** 未確認的預覽改存資料庫，沒有期限、重啟後仍可確認。已確認或已取消的預覽不能再確認或取消。

**答案寫回（`answer-writeback`）**
- **BREAKING** 寫回前的結構檢查只比對題數，以及每題的工作表 ID、工作表名稱、填空格與題組；子題標籤與原始題號不再比對。
- **BREAKING** 工作表改名視為結構不一致而拒絕寫回。
- 重新解析時使用目前設定的表頭標籤與題數上限。
- 遇到第一個差異就停止，只回報一項。

**Google 授權與啟動（`google-sheets-access`、`server-runtime`）**
- **BREAKING** 缺少 OAuth 用戶端設定檔或尚未完成授權時，伺服器拒絕啟動。
- 移除老師頁面的 Google 授權狀態與 `GET /api/google/status`。
- **BREAKING** 錯誤分類改為：401 授權失效、403 沒有權限、404 找不到，其他（含無法連線）一律為暫時無法使用。沒有權限的訊息會列出授權帳號的 email。
- 移除「不是 Google 試算表格式」與「未啟用 Sheets API」兩條專屬訊息。
- Google API 逾時預設改為 10 秒。
- **BREAKING** 監聽位址可用 `BUZZER_HOST` 設定（預設 127.0.0.1），並移除 Host 標頭檢查。

## Capabilities

### New Capabilities

（無）

### Modified Capabilities

- `teacher-auth`: 鎖定改為全體共用、5 次鎖 300 秒；Token 預設 8 小時；老師專屬操作移除查看 Google 授權狀態。
- `worksheet-import`: 讀取顯示值，並更新填空格、題組、題目列、子題標籤、錯誤順序、網址與預覽保存的規則。
- `answer-writeback`: 結構比對的欄位與標籤來源改變，工作表改名改為拒絕。
- `google-sheets-access`: 未授權時拒絕啟動、移除授權狀態、錯誤分類與訊息改變。
- `server-runtime`: 監聽位址可設定、移除 Host 檢查、參數預設值改變。

## Impact

- **程式：**
  - `app/worksheet/parser.py`、`store.py`、`writeback.py`
  - `app/google/convert.py`、`gateway.py`、`errors.py`、`auth.py`、`urls.py`
  - `app/security.py`、`app/config.py`、`app/main.py`、`app/__main__.py`、`app/state.py`、`app/db.py`
  - 刪除 `app/middleware.py`、`app/api/google.py`
- **API：**
  - 移除 `GET /api/google/status`。
  - 確認或取消已結束的預覽時回 409 `PREVIEW_CLOSED`。
  - 錯誤代碼 `GOOGLE_NETWORK`、`GOOGLE_API_DISABLED`、`GOOGLE_NOT_SPREADSHEET` 不再出現。
- **資料庫：** schema 升到第 3 版，只新增 `worksheet_previews`，既有學習單保留。
- **設定：**
  - 新增 `BUZZER_HOST`、`BUZZER_LOGIN_MAX_FAILURES`、`BUZZER_LOGIN_LOCK_SECONDS`。
  - `BUZZER_TOKEN_TTL_HOURS` 預設改為 8，`BUZZER_GOOGLE_TIMEOUT_SECONDS` 預設改為 10。
- **畫面：** 老師頁面移除「Google 授權」區塊。
- **與 SpecKit 組刻意保留的差異：**
  - 環境變數名稱、指令名稱、API 路徑與錯誤訊息的用字不同。
  - 寫回完成訊息附原試算表連結。
  - 授權過期時不需要重新啟動伺服器（本 repo 會重新讀取授權檔）。
  - 這些都不影響操作結果。
