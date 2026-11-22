# Proposal

## Why

助教 11/17 公告要求系統直接讀寫雲端的 Google 試算表，而不是下載成 .xlsx 在本地端離線處理；期末專題說明也要求把搶答成功的答案寫入「原」Guided Notes 的填空格。上一個 change（已封存的 `add-worksheet-import-and-export`）採用 .xlsx 上傳與產生新檔，因此匯入來源與寫回方式都必須改變。

同一系統由 SpecKit 小組平行實作，本 change 的行為已與對方對齊：直接寫入原試算表、以 OAuth 取得 Google 存取權、不保留 .xlsx 上傳路徑。

## What Changes

- **BREAKING** 移除 .xlsx 上傳匯入：老師改為輸入 Google 試算表網址，系統以授權的 Google 帳號直接讀取儲存格內容與合併範圍。辨識表頭、題目列、填空格、題組的規則完全不變。
- **BREAKING** 寫回改為直接寫入原 Google 試算表，不再產生新的 .xlsx：
  - 只寫入目前空白的填空格，其他儲存格的內容與所有格式都不碰。
  - 已有內容的填空格不覆蓋，完成訊息列出這些題號。
  - 寫回前重新讀取試算表並驗證結構與匯入時一致，不一致就整批拒絕。
  - 需要還原時使用 Google 試算表內建的版本記錄。
- 新增 Google OAuth 授權：老師在本機執行一次登入指令完成授權，系統保存授權資料並自動更新；伺服器可在未授權時啟動，但匯入與寫回會提示先完成授權。老師頁面顯示目前授權的 Google 帳號。
- 新增 Google 存取失敗時的繁中訊息（網址無效、找不到試算表、沒有權限、授權失效、網路或服務異常）。
- 設定調整：移除上傳與解壓大小上限，新增 OAuth 用戶端設定檔、授權檔路徑與 Google API 逾時設定；OAuth 用戶端設定檔與授權檔列為機敏資料。
- 新增 PlantUML 設計圖（元件圖、類別圖、時序圖）於 `./diagrams/`，並在 `openspec/config.yaml` 規定之後的 change 都要附圖。
- 資料庫中舊版（.xlsx）的學習單資料不再可用，升級時捨棄。

## Capabilities

### New Capabilities

- `google-sheets-access`: 以 OAuth 取得與保存 Google 授權、授權狀態查詢、授權自動更新與失效處理，以及讀寫 Google 試算表失敗時的繁中訊息。

### Modified Capabilities

- `worksheet-import`: 匯入來源由上傳 .xlsx 改為 Google 試算表網址；移除檔案格式與大小相關需求；確認、取消、保存與清單改以試算表識別表示。
- `answer-writeback`: 改為直接寫入原試算表的空白填空格、不覆蓋已有內容、寫回前重新讀取驗證結構；移除「產生新檔且原檔不變」。
- `server-runtime`: 可設定參數改為 Google 相關設定，移除上傳與解壓大小上限。
- `error-and-secret-handling`: 機敏資料範圍加入 Google OAuth 用戶端密鑰與授權檔。
- `teacher-auth`: 老師專屬操作加入查看 Google 授權狀態。

## Impact

- 程式：解析器改為吃與資料來源無關的格子資料；新增 Google 試算表存取層與 OAuth 登入指令；移除 .xlsx 上傳、zip 檢查與 lxml 寫回。
- API：`POST /api/worksheets/previews` 改收試算表網址（JSON）；寫回回傳 JSON 結果而非檔案；新增 `GET /api/google/status`。
- 相依套件：新增 google-auth、google-auth-oauthlib、requests；移除 lxml、python-multipart；openpyxl 只留在測試。
- 執行環境：匯入與寫回需要對外連線到 Google；搶答過程本身不需要連網。使用前需在 Google Cloud 建立 OAuth 用戶端（Desktop app）並啟用 Google Sheets API。
- 資料：SQLite schema 升級到第 2 版，舊的學習單資料表與 `data/worksheets/` 中的 .xlsx 不再使用。
- 不受影響：老師密碼登入、視窗身分、錯誤格式、CSV 匯出、ActivityResult 契約，以及之後的搶答活動 change。
