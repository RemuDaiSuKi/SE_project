# Spec Delta

## MODIFIED Requirements

### Requirement: Google 存取錯誤訊息
讀寫 Google 試算表失敗時，系統 SHALL 依 HTTP 狀態分類並顯示繁中訊息，且訊息 MUST NOT 含權杖、內部錯誤細節或 Google 回傳的原始內容：
- 401 或更新權杖失效：顯示「Google 授權已失效，請重新執行 python -m app google-login」。
- 404：顯示「找不到試算表，請確認網址是否正確」。
- 403：顯示「目前登入的 Google 帳號（<帳號 email>）沒有這份試算表的編輯權限，請改用有權限的帳號重新登入，或請擁有者把試算表共用給這個帳號（編輯者）」；無法取得帳號時省略括號部分。
- 其他錯誤，包含無法連線、逾時與 Google 服務異常：顯示「目前無法連線到 Google 試算表，請稍後再試」。

#### Scenario: 沒有權限
- **WHEN** 老師以 teacher@example.com 授權後，匯入一份沒有共用給該帳號的試算表
- **THEN** 系統顯示含「（teacher@example.com）」的沒有權限訊息，不建立任何資料

#### Scenario: 網路中斷
- **WHEN** 匯入時無法連線到 Google
- **THEN** 系統顯示「目前無法連線到 Google 試算表，請稍後再試」

#### Scenario: 未啟用 Sheets API
- **WHEN** OAuth 用戶端所屬的 Google Cloud 專案沒有啟用 Google Sheets API 時匯入（Google 回傳 403）
- **THEN** 系統顯示沒有權限的訊息

## ADDED Requirements

### Requirement: 未授權時拒絕啟動
`python -m app` 啟動伺服器前 SHALL 先檢查老師密碼，再檢查 Google 授權：
- OAuth 用戶端設定檔不存在時，輸出「找不到 Google OAuth 用戶端設定檔（BUZZER_GOOGLE_CLIENT_SECRETS），伺服器無法啟動。請依 README 設定後執行 python -m app google-login」。
- 授權檔不存在、無法載入或沒有更新權杖時，輸出「尚未完成 Google 授權，伺服器無法啟動。請先執行 python -m app google-login」。

兩種情況都 SHALL 以結束碼 1 結束，不開始監聽。伺服器執行期間授權檔被移除時，匯入與寫回 SHALL 顯示「尚未完成 Google 授權，請先執行 python -m app google-login」。

#### Scenario: 缺少用戶端設定檔
- **WHEN** 已設定老師密碼、但沒有 OAuth 用戶端設定檔時啟動伺服器
- **THEN** 伺服器拒絕啟動並說明缺少用戶端設定檔

#### Scenario: 尚未授權
- **WHEN** 有 OAuth 用戶端設定檔、但尚未執行登入指令時啟動伺服器
- **THEN** 伺服器拒絕啟動並提示先執行 `python -m app google-login`

## REMOVED Requirements

### Requirement: 授權狀態
**Reason**: 與 SpecKit 組一致，老師頁面不顯示 Google 授權狀態；未授權時伺服器不會啟動。
**Migration**: `GET /api/google/status` 移除。授權帳號改在沒有權限的錯誤訊息中顯示。

### Requirement: 未授權時仍可啟動
**Reason**: 與 SpecKit 組一致，改為未授權時拒絕啟動（見「未授權時拒絕啟動」）。
**Migration**: 啟動伺服器前先執行 `python -m app google-login`。
