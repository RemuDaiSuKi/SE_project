# Spec Delta

## MODIFIED Requirements

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

## ADDED Requirements

### Requirement: 監聽位址可設定
伺服器 SHALL 監聽 `BUZZER_HOST` 指定的位址（預設 127.0.0.1）與設定的 port；系統不檢查請求的 Host 標頭。

#### Scenario: 預設位址
- **WHEN** 未設定 `BUZZER_HOST` 時啟動伺服器
- **THEN** 伺服器只在 127.0.0.1 上的設定 port 接受連線

#### Scenario: 自訂位址
- **WHEN** 以 `BUZZER_HOST=0.0.0.0` 啟動伺服器
- **THEN** 伺服器監聽 0.0.0.0

## REMOVED Requirements

### Requirement: 只監聽本機
**Reason**: 與 SpecKit 組一致，監聽位址改為可設定（預設仍為 127.0.0.1）。
**Migration**: 不設定 `BUZZER_HOST` 時行為不變。

### Requirement: Host 標頭檢查
**Reason**: 與 SpecKit 組一致，不檢查 Host 標頭。
**Migration**: 無；連線範圍由監聽位址決定。
