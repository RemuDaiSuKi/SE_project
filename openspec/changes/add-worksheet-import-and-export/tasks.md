# Tasks

## 1. 專案骨架

- [x] 1.1 建立 `pyproject.toml`（Python 3.12；相依 fastapi、uvicorn、openpyxl、lxml、pydantic-settings、python-multipart；開發相依 pytest、httpx）與 `app/`、`tests/` 套件，確認 `pip install -e .[dev]` 成功且 `pytest` 可執行
- [x] 1.2 新增 `.gitignore`（含 `.env`、資料目錄、`__pycache__`）與只含佔位值的 `.env.example`，以 `git check-ignore .env data/` 確認兩者都被忽略
- [x] 1.3 請使用者從 Google Sheets 下載範例 A、B 的 .xlsx 放入 `tests/fixtures/`，用 openpyxl 讀出表頭、題號、題目、作答欄的合併範圍，記錄在 `tests/fixtures/README.md`，確認與 design.md D6 的解析假設一致（尤其是範例 B 題目欄是否縱向合併）

## 2. 設定與伺服器啟動（server-runtime）

- [x] 2.1 實作 `app/config.py` 的 Settings（`BUZZER_` 前綴、design D2 的預設值與範圍驗證），以單元測試驗證預設值、環境變數覆寫與不合法值的錯誤
- [x] 2.2 實作 `app/__main__.py`：密碼未設定或只含空白、設定不合法時，輸出繁中訊息（只列設定名稱）並以結束碼 1 離開；以 subprocess 測試驗證結束碼與訊息，且輸出不含任何設定值
- [x] 2.3 啟動 uvicorn 時固定 host `127.0.0.1`、`workers=1`、`access_log=False`，以單元測試檢查建立出的 uvicorn 設定
- [x] 2.4 實作 Host 標頭檢查 middleware，以 API 測試驗證 `127.0.0.1:<port>`、`localhost:<port>` 可通過，`evil.example:8000` 被拒絕
- [x] 2.5 在 `README.md` 撰寫安裝、設定 `.env` 與啟動步驟，依文件指令實際啟動一次確認可連線

## 3. 錯誤格式與 log（error-and-secret-handling）

- [x] 3.1 實作 `app/errors.py`：AppError、錯誤代碼、統一回應格式（design D4），覆寫 422、404、405 與未預期例外的處理器；以 API 測試驗證回應為繁中、結構一致，且 500 回應不含堆疊、路徑或例外名稱
- [x] 3.2 設定應用程式 logging（不記錄請求內容、標頭與查詢字串），並在 `tests/` 提供共用的 log 收集 fixture，以測試驗證一個帶 Authorization 標頭的請求不會讓 Token 出現在 log 中

## 4. 資料庫

- [x] 4.1 實作 `app/db.py`：在資料目錄建立 SQLite（WAL、foreign_keys、`user_version`）與 design D7 的學習單資料表；以測試驗證全新資料目錄啟動後資料表存在，且重複啟動不會出錯

## 5. 視窗身分與老師登入（teacher-auth）

- [x] 5.1 實作視窗註冊與以視窗為單位的失敗鎖定（可注入時鐘）；以單元測試驗證連續 5 次失敗後鎖定 60 秒、鎖定期間正確密碼也被拒絕、其他視窗不受影響、到期後可再登入、成功後失敗次數歸零
- [x] 5.2 實作 Token 簽發（只保存 SHA-256）、有效期限與登出；以單元測試驗證過期、登出後失效，以及重新建立 app 後舊 Token 失效
- [x] 5.3 實作 `POST /api/windows`、`/api/teacher/login`、`/api/teacher/logout` 與 `require_teacher` 依賴（固定時間比對密碼）；以 API 測試驗證登入成功與失敗、鎖定時回應 429 與剩餘秒數、無 Token 與非老師 Token 都回應「無權限執行此操作」
- [x] 5.4 實作前端 `static/js/api.js`（windowId 與 Token 只存在 sessionStorage、以 Authorization 標頭傳遞、視窗識別失效時自動重新註冊一次、登入失效時回到登入頁）與老師登入頁；在瀏覽器手動驗證同一瀏覽器兩個視窗的身分互不覆蓋、重新整理後仍保持登入、登出只影響該視窗

## 6. 學習單解析（worksheet-import）

- [x] 6.1 實作 `tests/builders.py`，以程式產生範例 A、範例 B 的等價檔案、排版不同的檔案（表頭在第 2 列、題號 A、題目 B、作答 D:F）、多工作表檔案（含無表頭的「說明」與隱藏工作表），以及各種錯誤檔；以測試確認每個產生的檔案都能被 openpyxl 開啟
- [x] 6.2 實作檔案層級檢查（大小上限、zip 與 `xl/workbook.xml`、含巨集、解壓大小只讀中央目錄、0 位元組與無內容）；以測試驗證文字檔、截斷檔、.xlsm、超過 10 MB、解壓過大、空檔分別得到 spec 中的訊息
- [x] 6.3 實作合併對照、視覺值與空白判斷（None、半形與全形空白、公式為非空白）；以單元測試涵蓋各種組合
- [x] 6.4 實作表頭列辨識（標籤去空白後完全相等、取第一個符合的列、欄範圍含合併、同一標籤重複時取最左邊）；以測試驗證範例 A 的欄範圍、前後空白的標籤、自訂標籤與找不到表頭
- [x] 6.5 實作題目列、作答欄邏輯儲存格、填空格與子題標籤辨識，以及 0 個或 2 個以上填空格、作答欄縱向合併跨列的錯誤；以測試驗證空白分隔列被忽略、題目欄縱向合併的兩列都是題目列，以及錯誤訊息的工作表、列號與儲存格
- [x] 6.6 實作題組辨識（題號欄縱向合併 2 列以上，範圍內全為題目列）與「題組範圍包含非題目列」錯誤；以測試驗證範例 B 的題組 1、2 與 B5:B7 含空白列的錯誤
- [x] 6.7 實作系統題號編號、跨工作表連續、原始題號轉換（3.0 → 「3」、空白 → 「（未標示）」）、工作表 XML 路徑對照、題數上限與錯誤彙整（最多 50 筆）；以測試驗證範例 A、B、排版不同與多工作表檔案的完整解析結果，與 spec 確認畫面情境的資料逐欄一致
- [x] 6.8 加入以 `tests/fixtures/` 中真實範例 A、B 匯出檔執行的解析測試，確認結果與 6.7 的等價檔案相同（依賴 1.3）

## 7. 匯入預覽、確認與保存（worksheet-import）

- [x] 7.1 實作記憶體中的預覽暫存（30 分鐘、最多 10 份、淘汰最舊的、確認或取消後移除，可注入時鐘）；以單元測試驗證到期、上限淘汰與確認後不可重複使用
- [x] 7.2 實作已確認學習單的保存（先以隨機檔名寫入原始檔，再於同一 transaction 寫入資料表；transaction 失敗時刪除檔案）與讀取；以測試驗證保存後原始檔雜湊值不變、以同一資料目錄重新建立 app 後學習單仍在，以及注入 transaction 失敗時不留下檔案
- [x] 7.3 實作預覽上傳、確認、取消、清單與詳細資料 API（design D11）；以 API 測試驗證錯誤時整份拒絕且不建立資料、確認後出現在清單、取消後無法確認、重複確認被拒、伺服器重啟後確認顯示「預覽已失效，請重新上傳」、同一檔案可匯入兩次
- [x] 7.4 實作老師的匯入畫面（選檔上傳、錯誤清單含位置、確認畫面顯示題數、題組數與每題的系統題號、原始題號、子題標籤、填空格位置、所屬題組，確認與取消按鈕）與學習單清單；在瀏覽器以範例 A、B 與一個錯誤檔手動驗證，並確認畫面沒有任何題目敘述

## 8. 活動結果契約

- [x] 8.1 實作 `app/results/contract.py`（ResultGroup、ResultRecord、ResultUnit、ActivityResult、`winner_of`、`outcome_of`、`success_counts`、契約驗證）；以單元測試驗證一般成功、遞補後成功、搶答中重新開放後新送出成功、全部無效時無人成功、題組成功數計 1，以及違反順位連續性時驗證失敗
- [x] 8.2 實作 FinalResultSource 介面、預設一律回傳 `not_found` 的實作，以及以 FastAPI 依賴注入的方式提供；在 tests 提供假的結果來源 fixture，以 API 測試驗證預設情況下寫回與匯出都回應「找不到活動」

## 9. 答案寫回（answer-writeback）

- [x] 9.1 實作寫回前的一致性驗證（SHA-256、以匯入時的標籤重新解析並逐題比對、填空格仍為空白）；以測試驗證竄改原始檔時被拒絕並列出不一致項目，以及改變伺服器標籤設定後仍能寫回
- [x] 9.2 以 lxml 實作工作表 XML 的儲存格寫入（保留 `s` 屬性、設為 inlineStr、`xml:space="preserve"`、補上缺少的 `<c>` 或 `<row>` 並維持順序、保留 XML 宣告、移除 XML 不允許的控制字元）；以單元測試涵蓋自閉合儲存格、缺少儲存格、缺少列、`<` `&` 引號換行，以及以 `=` 開頭的答案
- [x] 9.3 實作 zip 重新打包（依原順序、未修改項目沿用原 ZipInfo 並複製內容）；以測試驗證除目標工作表外所有項目內容逐位元組相同、目標工作表只有填空格不同，並以 openpyxl 讀回新檔確認答案、合併範圍與子題標籤
- [x] 9.4 實作 `POST /api/activities/{id}/writeback`（活動狀態檢查、只依結果來源取答案、忽略請求中的答案、RFC 5987 中文檔名、`X-Empty-Questions` 標頭）；以 API 測試驗證範例 A 全部有答案、部分空白、範例 B 題組寫回、結束後判定無效的遞補答案、未結束與不存在的活動，以及寫回兩次後原檔雜湊值不變
- [x] 9.5 Spike：把 9.4 產生的範例 A、B 寫回檔手動上傳到 Google Sheets，確認答案與格式正確，結果記錄在 `tests/fixtures/README.md`；若 inlineStr 不被支援，改為修改 `sharedStrings.xml` 並更新 design.md D9

## 10. CSV 匯出（result-csv-export）

- [x] 10.1 實作 `app/results/csv_export.py`（5 欄標題、題組展開、依題號與順位排序、`utf-8-sig`、CRLF、QUOTE_MINIMAL、答案不加前綴）；以單元測試驗證含逗號、雙引號、換行的答案可被 `csv` 模組完整讀回、檔案開頭為 BOM、成功／未搶到／無效三種結果與原順位、題組展開成多列、沒有送出的題目不輸出，以及沒有紀錄時只有標題列
- [x] 10.2 實作 `GET /api/activities/{id}/results.csv`（活動狀態檢查、`X-Record-Count` 標頭、中文檔名）；以 API 測試驗證未結束與不存在的活動被拒，以及沒有紀錄時 `X-Record-Count` 為 0

## 11. 整合檢查

- [x] 11.1 撰寫端到端測試：以執行時產生的隨機密碼走過登入失敗、登入、匯入、確認、寫回、匯出（以假的結果來源提供已結束活動），驗證全程 log 中沒有密碼與任何 Token
- [x] 11.2 撰寫權限矩陣測試：對每個老師專屬 API，分別以無 Token、過期 Token、非老師 Token 呼叫，驗證都被拒絕且沒有副作用（資料庫與資料目錄沒有變化）
- [x] 11.3 執行完整 `pytest` 全部通過，並執行 `openspec validate add-worksheet-import-and-export --strict` 通過

## Workflow follow-up

- 第二個 change `add-live-buzzer-activity` 以資料庫實作取代預設的 FinalResultSource，並在活動結果頁面加入寫回與 CSV 匯出的操作入口。
- 與 SpecKit 小組對齊：隱藏工作表照常處理、CSV 不加公式注入防護前綴、題組內題目欄縱向合併採視覺語意。
- 實作與驗證完成後，依專案審查流程封存此 change。
