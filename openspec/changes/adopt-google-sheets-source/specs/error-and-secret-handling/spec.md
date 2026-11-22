# Spec Delta

## MODIFIED Requirements

### Requirement: 機敏資料不進入 log
老師密碼、身分 Token、組別代碼、Google OAuth 用戶端密鑰，以及 Google 存取權杖與更新權杖 MUST NOT 出現在任何 log 中。系統 MUST NOT 記錄請求內容或含查詢字串的完整 URL；機敏值 MUST NOT 透過 URL 查詢字串傳遞。

#### Scenario: 完整流程後檢查 log
- **WHEN** 執行登入、登入失敗、匯入、確認、寫回與匯出的完整流程後，檢查所有 log 輸出
- **THEN** log 中找不到該次使用的密碼與任何 Token 字串

#### Scenario: Google 權杖更新後檢查 log
- **WHEN** 匯入時 Google 存取權杖過期並被自動更新後，檢查所有 log 輸出
- **THEN** log 中找不到新舊存取權杖、更新權杖與 OAuth 用戶端密鑰

### Requirement: 機敏資料不進入 repo
程式碼、文件與測試資料 MUST NOT 含真實的密碼、Token、組別代碼、Google OAuth 用戶端設定檔或 Google 授權檔；測試所需的密碼與權杖 SHALL 在測試執行時產生。repo SHALL 提供只含佔位值的 `.env.example`，且 `.env`、資料目錄與 Google OAuth 用戶端設定檔、授權檔的常見檔名 SHALL 列入 `.gitignore`。

#### Scenario: 檢查 repo 內容
- **WHEN** 檢查 repo 中被版本控制的檔案
- **THEN** 存在 `.env.example` 且其中密碼為佔位值；`.gitignore` 含 `.env` 與資料目錄；沒有任何 `.env` 檔被版本控制

#### Scenario: Google 憑證檔不被追蹤
- **WHEN** 在 repo 根目錄放一個從 Google Cloud 下載的 `client_secret_xxx.json` 後檢查 git 狀態
- **THEN** 該檔案被 `.gitignore` 忽略，不會被加入版本控制
