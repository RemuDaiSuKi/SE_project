# Spec Delta

## MODIFIED Requirements

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
