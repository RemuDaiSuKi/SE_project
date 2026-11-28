# server-runtime Specification

## Purpose

規範課堂搶答系統伺服器的啟動條件、可設定參數與網路邊界，確保系統只在單一電腦上以本機連線運作，所有可調整的數值都透過設定提供而不寫死在程式中，且伺服器以單一程序保存全部記憶體狀態。

## Requirements

### Requirement: 缺少老師密碼時拒絕啟動
伺服器啟動時若老師密碼環境變數未設定或為空字串（含只有空白），系統 SHALL 拒絕啟動，以繁體中文說明缺少的設定名稱並以非零結束碼結束，訊息 MUST NOT 含任何機敏值。

#### Scenario: 未設定密碼
- **WHEN** 未設定老師密碼環境變數就啟動伺服器
- **THEN** 伺服器不開始監聽，輸出「未設定老師密碼（BUZZER_TEACHER_PASSWORD），伺服器無法啟動」並以非零結束碼結束

#### Scenario: 密碼為空白
- **WHEN** 老師密碼環境變數只含空白字元
- **THEN** 伺服器同樣拒絕啟動

### Requirement: 參數可設定
系統的可調參數 SHALL 透過環境變數（或 `.env` 檔）設定且各有預設值，MUST NOT 寫死在程式中。至少包含：
- 監聽位址（預設 127.0.0.1）與 port
- 資料目錄
- 題數上限（預設 500）
- 三個表頭標籤（預設「題號」「題目」「作答」）
- 老師登入失敗次數（預設 5）與鎖定秒數（預設 300）
- 視窗失敗鎖定次數（預設 5）與鎖定秒數（預設 60）
- Token 有效時數（預設 8）
- Google OAuth 用戶端設定檔路徑（預設為資料目錄下的 `google-client-secret.json`）
- Google 授權檔路徑（預設為資料目錄下的 `google-token.json`）
- Google API 逾時秒數（預設 10）

設定值不合法時伺服器 SHALL 拒絕啟動，並以繁中說明哪個設定有誤。

#### Scenario: 覆寫題數上限
- **WHEN** 以題數上限 10 啟動伺服器，並匯入 11 題的學習單
- **THEN** 匯入因超過題數上限被拒絕

#### Scenario: 設定值不合法
- **WHEN** 以 port 設為「abc」啟動伺服器
- **THEN** 伺服器拒絕啟動，訊息指出 port 設定不合法

#### Scenario: 自訂 Google 設定檔位置
- **WHEN** 以 `BUZZER_GOOGLE_CLIENT_SECRETS` 指定另一個 OAuth 用戶端設定檔路徑後執行登入指令
- **THEN** 登入指令使用該路徑的設定檔

### Requirement: 單一程序執行
伺服器 SHALL 以單一程序執行，所有請求共用同一份記憶體狀態；啟動方式 MUST NOT 允許多個 worker。

#### Scenario: 啟動方式
- **WHEN** 依文件的啟動指令啟動伺服器
- **THEN** 只有一個伺服器程序處理所有請求

### Requirement: 監聽位址可設定
伺服器 SHALL 監聽 `BUZZER_HOST` 指定的位址（預設 127.0.0.1）與設定的 port；系統不檢查請求的 Host 標頭。

#### Scenario: 預設位址
- **WHEN** 未設定 `BUZZER_HOST` 時啟動伺服器
- **THEN** 伺服器只在 127.0.0.1 上的設定 port 接受連線

#### Scenario: 自訂位址
- **WHEN** 以 `BUZZER_HOST=0.0.0.0` 啟動伺服器
- **THEN** 伺服器監聽 0.0.0.0

### Requirement: 搶答活動參數可設定
搶答活動的可調參數 SHALL 透過環境變數（或 `.env` 檔）設定且各有預設值：
- 全體每分鐘輸錯組別代碼的上限（預設 60）
- 組數上限（預設 20）與組名長度上限（預設 20 字）
- 答案長度上限（預設 200 字）
- 是否啟用冷卻（預設啟用）、冷卻秒數 N（預設 10，範圍 1–600）、領先題數 K（預設 2，範圍 1–100）
- WebSocket 驗證逾時秒數（預設 5，範圍 0.1–60）

輸入組別代碼時的視窗鎖定沿用既有的視窗失敗鎖定設定。設定值不合法時伺服器 SHALL 拒絕啟動，並以繁中說明哪個設定有誤。

#### Scenario: 冷卻秒數超出範圍
- **WHEN** 以 `BUZZER_COOLDOWN_SECONDS=601` 啟動伺服器
- **THEN** 伺服器拒絕啟動，訊息指出 `BUZZER_COOLDOWN_SECONDS` 不合法

#### Scenario: 覆寫答案長度上限
- **WHEN** 以 `BUZZER_MAX_ANSWER_LENGTH=5` 啟動伺服器，學生在搶答中送出 6 個字的答案
- **THEN** 送出被拒絕，訊息為「第 1 題的答案超過 5 字」

### Requirement: 頁面與靜態檔每次確認新版
頁面（`/`、`/teacher`）與 `/static/` 下的檔案回應 SHALL 帶有 `Cache-Control: no-cache`，讓瀏覽器每次使用快取前都先向伺服器確認有沒有新版。`/static/` 的檔案 SHALL 提供 `ETag`，瀏覽器帶著相同的 `If-None-Match` 再次請求且檔案未變更時，伺服器回應 304 且不重送內容。API 回應 MUST 維持 `Cache-Control: no-store`。

#### Scenario: 頁面要求重新確認
- **WHEN** 瀏覽器請求 `/teacher`
- **THEN** 回應帶有 `Cache-Control: no-cache`

#### Scenario: 靜態檔要求重新確認
- **WHEN** 瀏覽器請求 `/static/js/teacher.js` 或 `/static/css/app.css`
- **THEN** 回應帶有 `Cache-Control: no-cache` 與 `ETag`

#### Scenario: 檔案未變更
- **WHEN** 瀏覽器以上一次取得的 `ETag` 作為 `If-None-Match` 再次請求 `/static/js/teacher.js`，而檔案沒有變更
- **THEN** 伺服器回應 304，不重送檔案內容

#### Scenario: 程式更新後
- **WHEN** `teacher.js` 更新並重新啟動伺服器後，老師重新整理頁面
- **THEN** 瀏覽器取得新版的 `teacher.js`，不需要強制重新整理

#### Scenario: API 不受影響
- **WHEN** 呼叫任何 `/api/` 端點
- **THEN** 回應仍帶有 `Cache-Control: no-store`
