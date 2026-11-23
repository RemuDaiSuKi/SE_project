# google-sheets-access Specification

## Purpose

讓伺服器以老師在本機授權的 Google 帳號（OAuth）讀取與寫入 Google 試算表，保存並自動更新授權，且在授權或存取失敗時以繁體中文說明原因與處理方式。

## Requirements

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

### Requirement: 授權自動更新與失效
存取權杖過期時系統 SHALL 自動以更新權杖取得新的存取權杖並保存。更新失敗（例如授權被撤銷或更新權杖過期）時，系統 SHALL 拒絕該操作並顯示「Google 授權已失效，請重新執行 python -m app google-login」。

#### Scenario: 存取權杖過期
- **WHEN** 存取權杖已過期、更新權杖仍有效時老師匯入試算表
- **THEN** 系統自動更新權杖並完成匯入，授權檔中的權杖被更新

#### Scenario: 更新權杖失效
- **WHEN** 更新權杖已失效時老師匯入試算表
- **THEN** 系統拒絕並顯示「Google 授權已失效，請重新執行 python -m app google-login」

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
