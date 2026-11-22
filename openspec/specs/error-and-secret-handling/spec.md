# error-and-secret-handling Specification

## Purpose

確保系統對使用者呈現的所有訊息都是繁體中文且不洩漏內部細節，並保護密碼、Token 與組別代碼不出現在 log、程式碼、文件、測試資料或 repo 中。

## Requirements

### Requirement: 繁體中文訊息
所有 UI 文字與錯誤訊息 SHALL 使用繁體中文，包含請求格式錯誤、找不到資源、權限不足與上限超過等框架層級的錯誤。

#### Scenario: 請求格式錯誤
- **WHEN** 一個 API 請求缺少必要欄位或欄位型別錯誤
- **THEN** 回應的錯誤訊息為繁體中文（例如「請求格式不正確」），不含框架預設的英文驗證訊息

#### Scenario: 不存在的路徑
- **WHEN** 請求一個不存在的 API 路徑
- **THEN** 回應繁體中文的「找不到資源」

### Requirement: 統一錯誤回應格式
API 錯誤回應 SHALL 使用一致的結構，包含錯誤代碼、繁中訊息，以及（適用時）逐項錯誤明細；每項明細 SHALL 能標示位置（例如工作表名稱與列號或儲存格）。

#### Scenario: 含多項明細的錯誤
- **WHEN** 匯入的學習單有 3 處錯誤
- **THEN** 回應包含一個整體訊息與 3 筆明細，每筆明細有位置與繁中說明

### Requirement: 不洩漏內部細節
系統 MUST NOT 在回應或畫面中顯示堆疊追蹤、例外類別名稱、檔案系統路徑、SQL 或其他內部細節。未預期的錯誤 SHALL 回應「系統發生錯誤，請稍後再試」。

#### Scenario: 未預期例外
- **WHEN** 處理請求時發生未預期的例外
- **THEN** 回應只含「系統發生錯誤，請稍後再試」，不含堆疊、路徑或例外名稱

### Requirement: 機敏資料不進入 log
老師密碼、身分 Token 與組別代碼 MUST NOT 出現在任何 log 中。系統 MUST NOT 記錄請求內容或含查詢字串的完整 URL；機敏值 MUST NOT 透過 URL 查詢字串傳遞。

#### Scenario: 完整流程後檢查 log
- **WHEN** 執行登入、登入失敗、匯入、確認、寫回與匯出的完整流程後，檢查所有 log 輸出
- **THEN** log 中找不到該次使用的密碼與任何 Token 字串

### Requirement: 機敏資料不進入 repo
程式碼、文件與測試資料 MUST NOT 含真實的密碼、Token 或組別代碼；測試所需的密碼 SHALL 在測試執行時產生。repo SHALL 提供只含佔位值的 `.env.example`，且 `.env` 與資料目錄 SHALL 列入 `.gitignore`。

#### Scenario: 檢查 repo 內容
- **WHEN** 檢查 repo 中被版本控制的檔案
- **THEN** 存在 `.env.example` 且其中密碼為佔位值；`.gitignore` 含 `.env` 與資料目錄；沒有任何 `.env` 檔被版本控制
