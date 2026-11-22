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
系統的可調參數 SHALL 透過環境變數（或 `.env` 檔）設定且各有預設值，MUST NOT 寫死在程式中。至少包含：port、資料目錄、題數上限（預設 500）、三個表頭標籤（預設「題號」「題目」「作答」）、視窗失敗鎖定次數（預設 5）與鎖定秒數（預設 60）、Token 有效時數（預設 12）、Google OAuth 用戶端設定檔路徑（預設為資料目錄下的 `google-client-secret.json`）、Google 授權檔路徑（預設為資料目錄下的 `google-token.json`）與 Google API 逾時秒數（預設 20）。設定值不合法時伺服器 SHALL 拒絕啟動並以繁中說明哪個設定有誤。

#### Scenario: 覆寫題數上限
- **WHEN** 以題數上限 10 啟動伺服器，並匯入 11 題的學習單
- **THEN** 匯入因超過題數上限被拒絕

#### Scenario: 設定值不合法
- **WHEN** 以 port 設為「abc」啟動伺服器
- **THEN** 伺服器拒絕啟動，訊息指出 port 設定不合法

#### Scenario: 自訂 Google 設定檔位置
- **WHEN** 以 `BUZZER_GOOGLE_CLIENT_SECRETS` 指定另一個 OAuth 用戶端設定檔路徑後執行登入指令
- **THEN** 登入指令使用該路徑的設定檔

### Requirement: 只監聽本機
伺服器 SHALL 只監聽 127.0.0.1，此位址 MUST NOT 可被設定為其他值；port 可設定。

#### Scenario: 監聽位址
- **WHEN** 伺服器啟動完成
- **THEN** 只有 127.0.0.1 上的設定 port 接受連線，其他網路介面無法連線

### Requirement: Host 標頭檢查
系統 SHALL 只接受 Host 標頭為 `127.0.0.1:<port>` 或 `localhost:<port>` 的請求，其他 Host SHALL 被拒絕並回應「不允許的連線來源」。

#### Scenario: 非本機 Host
- **WHEN** 一個請求的 Host 標頭為 `evil.example:8000`
- **THEN** 系統拒絕該請求，不執行任何操作

### Requirement: 單一程序執行
伺服器 SHALL 以單一程序執行，所有請求共用同一份記憶體狀態；啟動方式 MUST NOT 允許多個 worker。

#### Scenario: 啟動方式
- **WHEN** 依文件的啟動指令啟動伺服器
- **THEN** 只有一個伺服器程序處理所有請求
