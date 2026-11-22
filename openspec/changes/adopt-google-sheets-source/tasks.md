# Tasks

## 1. 相依套件與設定

- [ ] 1.1 更新 `pyproject.toml`（新增 google-auth、google-auth-oauthlib、requests；移除 lxml、python-multipart；openpyxl 移到開發相依）並重新安裝，確認 `pip install -e .[dev]` 成功且 `python -c "import google_auth_oauthlib"` 可執行
- [ ] 1.2 更新 Settings：移除上傳與解壓大小上限，新增 Google 用戶端設定檔、授權檔路徑（預設在資料目錄下）與 API 逾時秒數；更新 `.env.example` 與 `.gitignore`（`client_secret*.json`、`google-client-secret*.json`、`google-token*.json`）；以單元測試驗證預設路徑、覆寫與不合法值，並以 `git check-ignore` 確認憑證檔名被忽略

## 2. 與資料來源無關的解析

- [ ] 2.1 新增 `SheetGrid`／`SpreadsheetGrid`，把解析器改為 `parse_grid(grid, labels, max_questions)`，`Question.sheet_part` 改為 `sheet_id`，移除 zip 與 openpyxl 載入程式；以既有的解析情境驗證規則不變
- [ ] 2.2 實作 Sheets API JSON → 格子資料的轉換（0 起算轉 1 起算、合併範圍不含尾端轉含尾端、`userEnteredValue` 各型別、略過圖表工作表、隱藏工作表照常處理），並在 tests 提供 openpyxl 活頁簿 → Sheets API JSON 的轉換工具；以範例 A、B 真實檔轉成的 JSON 驗證解析結果與預期完全相同
- [ ] 2.3 把所有解析測試改為經由「活頁簿 → API JSON → 格子資料 → parse_grid」的路徑執行，新增空白試算表訊息「試算表沒有任何內容」的測試，移除只適用於檔案的測試（檔案格式、大小、zip），確認解析測試全部通過

## 3. Google 存取層（google-sheets-access）

- [ ] 3.1 實作試算表網址解析（編輯網址、純 ID、發布到網路的連結、無效輸入）與網址正規化，以單元測試涵蓋各種輸入
- [ ] 3.2 實作 `GoogleAuth`（載入授權檔、過期自動更新並以原子性方式保存、更新失敗轉為 `auth_expired`、`status()`），以假的憑證物件測試未授權、正常、更新成功、更新失敗與授權檔損毀
- [ ] 3.3 實作 `GoogleSheetsGateway.fetch` 與 `write_cells`（fields 參數、`valueInputOption=RAW`、單一批次、工作表名稱引號、逾時、錯誤分類含 `api_disabled`），以假的 HTTP session 驗證請求內容與每一種錯誤分類，並確認錯誤訊息不含權杖或 Google 原始回應
- [ ] 3.4 實作登入指令 `python -m app google-login`（缺少用戶端設定檔、授權完成、授權未完成時原授權檔不變、回呼只綁 127.0.0.1），以假的 flow 測試三種情況與結束碼
- [ ] 3.5 實作 `GET /api/google/status`（老師專屬），以 API 測試驗證三種狀態與未登入者被拒絕且不透露授權資訊

## 4. 以網址匯入（worksheet-import）

- [ ] 4.1 SQLite schema 升級到第 2 版（試算表 ID、網址、標題、工作表 ID），第 1 版資料表捨棄重建；以測試驗證全新建立與從第 1 版升級兩種情況
- [ ] 4.2 更新預覽與學習單儲存（不再保存檔案位元組），以測試驗證保存後重新建立 app 結構不變、同一試算表可匯入兩次
- [ ] 4.3 更新匯入 API：`POST /api/worksheets/previews` 改收 `{url}`，加入試算表標題與網址；清單與詳細資料改用試算表標題與連結；以 API 測試驗證範例 A、B 確認畫面資料、無效網址、未授權、各種 Google 錯誤訊息、確認、取消、預覽失效訊息「預覽已失效，請重新讀取試算表」

## 5. 直接寫回原試算表（answer-writeback）

- [ ] 5.1 實作寫回前的結構驗證（重新讀取、清空預期填空格後重新解析、逐題比對、工作表被刪除、改名不算差異），以測試驗證插入一列、子題標籤被改、題目被刪除時拒絕，填空格已有內容與工作表改名時通過
- [ ] 5.2 實作 `write_back` 服務（依結果取答案、只寫空白填空格、跳過已有內容、單一批次、無需寫入時不呼叫 API、回傳三種題號清單），以假的 gateway 驗證範例 A 全部寫入、範例 B 題組寫入、部分空白、第二次寫回全部跳過、判定無效後再寫回保留舊答案、寫入失敗後重試
- [ ] 5.3 更新寫回 API 為 JSON 回應與 spec 規定的完成訊息，移除 .xlsx 寫回程式；以 API 測試驗證完成訊息格式、未結束與不存在的活動、結構不一致、缺少編輯權限，並以假的 gateway 比對寫回前後只有填空格的值改變

## 6. 老師頁面

- [ ] 6.1 老師頁面加入 Google 授權狀態區塊、改為輸入試算表網址匯入、學習單清單顯示試算表標題與連結；在瀏覽器手動驗證未授權狀態的提示與無效網址的錯誤訊息

## 7. 文件與設計圖

- [ ] 7.1 更新 README：Google Cloud 專案與 OAuth 用戶端的建立步驟、`google-login` 用法、Testing 模式 7 天失效、試算表需共用給授權帳號、寫回後以版本記錄還原；依 README 步驟檢查每個指令都存在
- [ ] 7.2 比對 `diagrams/*.puml` 與最終實作（元件名稱、類別欄位、時序），有出入就更新
- [ ] 7.3 把 `diagrams/*.puml` 轉成同名 PNG，確認每個 .puml 都有對應且內容最新的 PNG

## 8. 整合檢查

- [ ] 8.1 conftest 加上禁止真實網路請求的防護，擴充「全流程 log 不含機敏值」測試涵蓋假的 Google 存取權杖、更新權杖與用戶端密鑰，並更新權限矩陣加入 `/api/google/status`
- [ ] 8.2 確認程式中已無 `parse_xlsx`、lxml、multipart 上傳的殘留引用，執行完整 `pytest` 全部通過，並執行 `openspec validate adopt-google-sheets-source --strict` 通過
- [ ] 8.3 撰寫 `scripts/google_writeback_check.py` 手動驗證工具，並由使用者以真實 Google 帳號完成：`google-login`、以網址匯入範例 A、B 的副本、執行工具寫回後在 Google 試算表確認答案、格式與第 2 題空白，再執行一次確認已有內容不被覆蓋

## Workflow follow-up

- 封存本 change 時，直接修改 `openspec/specs/worksheet-import/spec.md` 與 `openspec/specs/answer-writeback/spec.md` 的 Purpose，把「上傳 .xlsx」「產生新的 .xlsx」改為以 Google 試算表為來源與寫回目標。
- 把 design.md Risks 中「與 SpecKit 組可能不一致的細節」列給 SpecKit 組確認。
- 搶答活動 change（`add-live-buzzer-activity`）的結果頁面加入寫回與 CSV 匯出按鈕，並以資料庫實作取代預設的 FinalResultSource。
