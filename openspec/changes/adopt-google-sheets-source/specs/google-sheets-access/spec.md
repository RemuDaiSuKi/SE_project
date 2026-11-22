# Spec Delta

## Purpose

讓伺服器以老師在本機授權的 Google 帳號（OAuth）讀取與寫入 Google 試算表，保存並自動更新授權，且在授權或存取失敗時以繁體中文說明原因與處理方式。

## ADDED Requirements

### Requirement: Google 授權指令
系統 SHALL 提供登入指令（`python -m app google-login`），以設定的 OAuth 用戶端設定檔在瀏覽器完成 Google 授權，並把授權資料保存到設定的授權檔。授權範圍 MUST 只包含讀寫 Google 試算表與取得帳號 email。授權過程中的本機回呼 MUST 只監聽 127.0.0.1。

#### Scenario: 完成授權
- **WHEN** 老師執行登入指令並在瀏覽器同意授權
- **THEN** 授權資料被保存到授權檔，指令顯示「已完成 Google 授權：<帳號 email>」並以結束碼 0 結束

#### Scenario: 缺少 OAuth 用戶端設定檔
- **WHEN** 設定的 OAuth 用戶端設定檔不存在時執行登入指令
- **THEN** 指令顯示「找不到 Google OAuth 用戶端設定檔（BUZZER_GOOGLE_CLIENT_SECRETS）」與設定說明，以非零結束碼結束，不開啟瀏覽器

#### Scenario: 授權未完成
- **WHEN** 老師在瀏覽器拒絕授權或關閉授權頁面
- **THEN** 指令顯示「Google 授權未完成」並以非零結束碼結束，原有的授權檔保持不變

### Requirement: 授權狀態
老師 SHALL 能在老師頁面看到 Google 授權狀態：尚未設定 OAuth 用戶端、尚未授權，或已授權（顯示授權的帳號 email）。

#### Scenario: 已授權
- **WHEN** 已完成授權的老師開啟老師頁面
- **THEN** 頁面顯示「已授權 Google 帳號：<帳號 email>」

#### Scenario: 尚未授權
- **WHEN** 授權檔不存在時老師開啟老師頁面
- **THEN** 頁面顯示「尚未完成 Google 授權」與登入指令的使用說明

### Requirement: 未授權時仍可啟動
伺服器 SHALL 能在尚未完成 Google 授權時啟動；此時讀取或寫入 Google 試算表的操作 SHALL 被拒絕並顯示「尚未完成 Google 授權，請先執行 python -m app google-login」。

#### Scenario: 未授權時匯入
- **WHEN** 尚未授權時老師輸入試算表網址匯入
- **THEN** 系統拒絕並顯示「尚未完成 Google 授權，請先執行 python -m app google-login」

### Requirement: 授權自動更新與失效
存取權杖過期時系統 SHALL 自動以更新權杖取得新的存取權杖並保存。更新失敗（例如授權被撤銷或更新權杖過期）時，系統 SHALL 拒絕該操作並顯示「Google 授權已失效，請重新執行 python -m app google-login」。

#### Scenario: 存取權杖過期
- **WHEN** 存取權杖已過期、更新權杖仍有效時老師匯入試算表
- **THEN** 系統自動更新權杖並完成匯入，授權檔中的權杖被更新

#### Scenario: 更新權杖失效
- **WHEN** 更新權杖已失效時老師匯入試算表
- **THEN** 系統拒絕並顯示「Google 授權已失效，請重新執行 python -m app google-login」

### Requirement: Google 存取錯誤訊息
讀寫 Google 試算表失敗時，系統 SHALL 依原因顯示繁中訊息，且訊息 MUST NOT 含權杖、內部錯誤細節或 Google 回傳的原始內容：找不到試算表時顯示「找不到試算表，請確認網址是否正確」；沒有權限時顯示「目前授權的 Google 帳號沒有這份試算表的讀取或編輯權限，請確認試算表已共用給該帳號」；無法連線時顯示「無法連線到 Google，請確認網路連線後再試」；Google Cloud 專案尚未啟用 Google Sheets API 時顯示「Google Cloud 專案尚未啟用 Google Sheets API，請依 README 啟用後再試」；Google 服務異常或流量受限時顯示「Google 服務暫時無法使用，請稍後再試」。

#### Scenario: 沒有權限
- **WHEN** 老師匯入一份沒有共用給授權帳號的試算表
- **THEN** 系統顯示沒有權限的訊息，不建立任何資料

#### Scenario: 網路中斷
- **WHEN** 匯入時無法連線到 Google
- **THEN** 系統顯示「無法連線到 Google，請確認網路連線後再試」

#### Scenario: 未啟用 Sheets API
- **WHEN** OAuth 用戶端所屬的 Google Cloud 專案沒有啟用 Google Sheets API 時匯入
- **THEN** 系統顯示「Google Cloud 專案尚未啟用 Google Sheets API，請依 README 啟用後再試」，而不是沒有權限的訊息
