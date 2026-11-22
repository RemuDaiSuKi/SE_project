# Design

## Context

- 上一個 change 已實作 .xlsx 上傳匯入與 lxml 寫回（見 `openspec/changes/archive/2026-11-22-add-worksheet-import-and-export/`）。改變的動機見 proposal.md「Why」，行為見本 change 的 delta specs。
- 解析器 `app/worksheet/parser.py` 的判斷邏輯只依賴「儲存格的值」與「合併範圍」，目前包在 openpyxl 的 `_SheetView` 裡。Google Sheets API 的 `spreadsheets.get` 一次就能取得這兩樣資料，所以解析規則可以完整保留。
- 開發環境沒有 Google 帳號與 OAuth 用戶端，自動化測試必須完全不連網；與真實 Google 的整合只能由使用者手動驗證。
- SpecKit 組的存取層也命名為 `SheetsGateway`，沿用同名以便兩組對照。

## Goals / Non-Goals

**Goals:**
- 解析規則與既有的解析測試不變，只替換資料來源。
- 所有 Google 存取集中在一個可替換的存取層，測試以假的實作取代。
- 寫回在任何失敗後都能安全地重試（只寫空白填空格）。

**Non-Goals:**
- 寫到副本、保留 .xlsx 上傳路徑（已與 SpecKit 組決定不做）。
- 在網頁上完成 Google 授權（改用本機登入指令，與 SpecKit 組一致）。
- 寫回與匯出的操作畫面：仍屬於搶答活動 change 的結果頁面。
- 讀取試算表的格式（顏色、字型）：解析不需要，也不保存。

## 設計圖

本 change 新增以下 PlantUML 圖（原始檔與轉出的 PNG 都在 repo 根目錄的 `diagrams/`）：

| 圖 | 檔案 | 內容 |
|---|---|---|
| 元件圖 | `diagrams/component.puml` / `.png` | 瀏覽器、登入指令、伺服器內部元件、SQLite、授權檔與 Google 服務的關係 |
| 類別圖 | `diagrams/class.puml` / `.png` | 格子資料、學習單模型、Google 存取層、活動結果契約 |
| 時序圖 | `diagrams/sequence-import.puml` / `.png` | 以網址匯入學習單（含確認與取消） |
| 時序圖 | `diagrams/sequence-writeback.puml` / `.png` | 寫回原試算表（重新讀取、驗證結構、單一批次寫入） |
| 時序圖 | `diagrams/sequence-google-login.puml` / `.png` | 老師在本機完成 Google 授權 |

## Decisions

### D1. 與資料來源無關的格子資料

```python
@dataclass(frozen=True)
class SheetGrid:
    sheet_id: int                      # Google 工作表 ID（gid）
    title: str
    values: Mapping[Pos, object]       # (列, 欄) 從 1 起算；只含有輸入值的儲存格
    merges: tuple[tuple[int, int, int, int], ...]   # (r0, c0, r1, c1)，含頭含尾
    max_row: int

@dataclass(frozen=True)
class SpreadsheetGrid:
    spreadsheet_id: str
    title: str
    sheets: tuple[SheetGrid, ...]      # 依分頁順序，只含一般工作表
```

`parse_grid(grid, labels, max_questions)` 取代 `parse_xlsx`。`_SheetView` 改由 `SheetGrid` 建立，其餘判斷邏輯一行不改。`Question.sheet_part`（zip 內路徑）改為 `sheet_id`，並保留 `sheet_name` 供顯示。`Question.identity()` 不含工作表名稱，所以工作表改名不算結構改變。

替代方案：直接把 Sheets API 的 JSON 丟給解析器。這會把 Google 的格式滲進解析規則，測試也得組 JSON，因此在存取層就轉成格子資料。

### D2. Sheets API JSON 轉換

- 讀取：`GET https://sheets.googleapis.com/v4/spreadsheets/{id}?includeGridData=true&fields=spreadsheetId,properties.title,sheets(properties(sheetId,title,index,sheetType),merges,data(startRow,startColumn,rowData(values(userEnteredValue))))`。只取需要的欄位以縮小回應。
- 值的對應（`userEnteredValue`）：`stringValue` → 字串；`numberValue` → float；`boolValue` → bool；`formulaValue` → 公式字串（以 `=` 開頭，必為非空白）；`errorValue` → `"#ERROR"`；沒有 `userEnteredValue` → 空白（只有格式的儲存格）。
- 座標：API 是從 0 起算，合併範圍的 `end*Index` 不含尾端；轉換時改成從 1 起算、含頭含尾，與 openpyxl 的慣例一致。
- `sheetType` 不是 `GRID` 的工作表（圖表）略過；隱藏的工作表照常處理。

### D3. SheetsGateway 與錯誤分類

```python
class SheetsGateway(Protocol):
    def fetch(self, spreadsheet_id: str) -> SpreadsheetGrid: ...
    def write_cells(self, spreadsheet_id: str, writes: Sequence[CellWrite]) -> None: ...
```

- `GoogleSheetsGateway` 以 `google.auth.transport.requests.AuthorizedSession` 呼叫 REST API，所有請求都有逾時（`BUZZER_GOOGLE_TIMEOUT_SECONDS`，預設 20 秒）。HTTP 工作階段由可注入的 factory 建立，測試以假的 session 取代。
- 寫入：`POST .../values:batchUpdate`，`valueInputOption=RAW`，所有儲存格放在同一個請求的 `data` 陣列。RAW 讓 `=1+1` 這類答案以文字儲存，且只更新值、不動格式。範圍用 `'<工作表名稱>'!H5`，名稱中的單引號改成兩個。
- 錯誤一律轉成 `SheetsError(kind)`，API 層再對應到 spec 的繁中訊息：

| 情況 | kind | HTTP（對前端） |
|---|---|---|
| 授權檔不存在 | `not_authorized` | 409 |
| 更新權杖失效、Google 回 401 | `auth_expired` | 409 |
| Google 回 404 | `not_found` | 404 |
| Google 回 403 且原因為 `SERVICE_DISABLED` / `accessNotConfigured` | `api_disabled` | 502 |
| 其他 403 | `forbidden` | 403 |
| 連線失敗、逾時 | `network` | 502 |
| 429、5xx、其他非預期回應 | `unavailable` | 502 |

Google 回傳的原始錯誤內容不放進回應，也不寫入 log（只記錄 kind 與 HTTP 狀態碼）。

替代方案：`google-api-python-client`。功能較完整但相依龐大，而且測試要 mock discovery 文件；這裡只需要兩個端點，直接呼叫 REST 較簡單。

### D4. OAuth 授權

- 範圍：`https://www.googleapis.com/auth/spreadsheets`、`openid`、`https://www.googleapis.com/auth/userinfo.email`。不用 `drive.file`，因為它只能存取由本程式建立或以 Picker 開啟的檔案，貼網址的用法行不通。
- 登入指令 `python -m app google-login`（`app/google_login.py`）：`InstalledAppFlow.from_client_secrets_file(...).run_local_server(host="localhost", bind_addr="127.0.0.1", port=0, timeout_seconds=300)`，取得憑證後呼叫 `https://openidconnect.googleapis.com/v1/userinfo` 取得 email。設定 `OAUTHLIB_RELAX_TOKEN_SCOPE=1`，避免 Google 回傳的範圍順序不同時被誤判為範圍改變。
- 授權檔格式：`{"account": "<email>", "credentials": <Credentials.to_json() 的內容>}`。先寫暫存檔再 `os.replace`，避免寫到一半損毀。授權未完成時不動原檔。
- `GoogleAuth`（伺服器端）：第一次使用時載入授權檔並快取；憑證過期就以更新權杖更新並寫回授權檔；更新失敗（`RefreshError`）轉成 `auth_expired`。以鎖保護，避免並行請求重複更新。`status()` 回傳 `configured`（用戶端設定檔存在）、`authorized`（授權檔可載入且有更新權杖）、`account`。
- 伺服器啟動不檢查 Google 授權，未授權時只有讀寫試算表的操作會失敗。

### D5. 試算表網址解析

依序嘗試：
1. `/spreadsheets/d/e/...`（發布到網路的連結）→ 無效。
2. `/spreadsheets/d/<ID>` → 取出 ID。
3. 整段輸入本身符合 `^[A-Za-z0-9_-]{20,}$` → 視為 ID。

其他情況都無效。保存的網址一律正規化為 `https://docs.google.com/spreadsheets/d/<ID>/edit`。

### D6. 匯入流程

`POST /api/worksheets/previews`，請求為 JSON `{"url": "..."}`。流程：解析網址 → `gateway.fetch`（放進 threadpool）→ `parse_grid` → 存入預覽 → 回傳試算表標題、網址與結構。預覽改存試算表 ID、網址、標題與解析結果，不再保存檔案位元組。確認、取消、清單與詳細資料 API 的路徑不變。

### D7. 寫回流程

`write_back(result, worksheet, gateway) -> WritebackReport`：

1. `gateway.fetch` 重新讀取試算表。
2. 結構驗證：複製一份格子資料，把每題預期的填空格內容清空，再以匯入時的標籤 `parse_grid`（不套用題數上限），逐題比對 `identity()` 與題組結構。工作表 ID 不存在時回報「找不到工作表（可能已被刪除）」。把填空格先清空，可以讓「老師在填空格寫了字」不被誤判為結構改變，同時重用完整的解析規則。
3. 依 `winning_answers(result)` 決定每題的答案；沒有成功答案的列入「保持空白」。有答案的題目若在步驟 1 讀到的填空格已有內容，列入「已有內容未覆蓋」，否則列入寫入清單，並以目前的工作表名稱組成範圍（依 sheet_id 查詢，支援改名）。
4. 寫入清單不為空時，以一次 `write_cells` 送出。
5. 回傳已寫入、保持空白、已有內容未覆蓋三個題號清單；API 層組成 spec 規定的完成訊息，並附上試算表網址。

驗證與寫入之間仍有極短的時間窗，期間老師若手動修改填空格可能被覆蓋；在課堂情境下可接受（見 Risks）。

### D8. 資料庫 schema 第 2 版

```
worksheets(id, spreadsheet_id, spreadsheet_url, title, label_no, label_question, label_answer,
           question_count, group_count, confirmed_at)
worksheet_groups(worksheet_id, group_no, source_no, sheet_id, sheet_name, range_ref)
worksheet_questions(worksheet_id, no, sheet_id, sheet_name, cell_ref, row,
                    source_no, sub_label, group_no)
```

從第 1 版升級時捨棄三張舊的學習單資料表再重建。舊資料只有開發期間以 .xlsx 測試匯入的紀錄，而且少了試算表 ID，無法轉換。`data/worksheets/` 中的舊 .xlsx 不再被讀取，也不會被自動刪除。

### D9. API 異動

| 方法 | 路徑 | 異動 |
|---|---|---|
| POST | `/api/worksheets/previews` | 改收 JSON `{url}`，回應加入 `spreadsheetTitle`、`spreadsheetUrl` |
| GET | `/api/worksheets`、`/api/worksheets/{id}` | `filename` 改為 `title`，加入 `spreadsheetUrl` |
| GET | `/api/google/status` | 新增，老師專屬：`{configured, authorized, account}` |
| POST | `/api/activities/{id}/writeback` | 改回傳 JSON：`{message, written, empty, skippedFilled, spreadsheetUrl}` |

### D10. 設定與相依套件

- 移除 `BUZZER_MAX_UPLOAD_MB`、`BUZZER_MAX_UNCOMPRESSED_MB`；新增 `BUZZER_GOOGLE_CLIENT_SECRETS`、`BUZZER_GOOGLE_TOKEN_FILE`（未設定時預設在資料目錄下）與 `BUZZER_GOOGLE_TIMEOUT_SECONDS`。
- `.gitignore` 加入 `client_secret*.json`、`google-client-secret*.json`、`google-token*.json`，即使檔案放在資料目錄以外也不會被追蹤。
- 執行期相依：新增 google-auth、google-auth-oauthlib、requests；移除 lxml、python-multipart。openpyxl 移到開發相依，只用來產生測試輸入。

### D11. 測試策略

- 解析測試沿用 `tests/builders.py` 產生的 openpyxl 活頁簿與兩份真實範例檔，但改經由測試工具把活頁簿轉成 Sheets API 格式的 JSON，再走正式的 JSON → 格子資料轉換與 `parse_grid`。這樣既有的解析情境全部保留，同時驗證了座標與合併範圍的轉換。
- `FakeSheetsGateway` 保存記憶體中的試算表 JSON，記錄 `write_cells` 呼叫，並能模擬各種 `SheetsError`；寫入會套用到記憶體中的內容，讓「寫回前後比對」可以測試。
- `GoogleSheetsGateway` 以假的 HTTP session 測試請求內容（fields、RAW、範圍引號）與錯誤分類；`GoogleAuth` 以假的憑證物件測試載入、更新、失效與保存；登入指令以假的 flow 測試。
- conftest 加上自動套用的防護，任何測試若真的發出網路請求就直接失敗。

### D12. 手動驗證工具

`scripts/google_writeback_check.py`：給定已確認學習單的 ID，以「測試答案 N」組成假的活動結果（刻意留空第 2 題），透過正式的 `write_back` 與 `GoogleSheetsGateway` 寫回真實試算表並印出結果。只用於手動驗證，必須對範例試算表的副本執行。

## Risks / Trade-offs

- [OAuth 同意畫面在 Testing 模式時，更新權杖 7 天就失效] → Demo 前重新執行 `google-login`；README 註明；授權失效時錯誤訊息直接指出要重新登入。
- [助教用另一份試算表測試時，授權帳號沒有權限] → 試算表必須共用給授權帳號（寫回需編輯權限），或先複製一份到該帳號；README 與錯誤訊息都說明。
- [驗證與寫入之間的時間窗] 期間若有人手動修改填空格，仍可能被寫入覆蓋 → 時間窗通常小於一秒，課堂情境可接受；需要時可用版本記錄還原。
- [values.batchUpdate 是否全有全無，官方文件沒有明確保證] → 只寫空白填空格的設計讓重試是安全的，即使部分寫入也不會重複或覆蓋。
- [直接寫入原試算表] 寫錯無法由系統復原 → 寫回前驗證結構、不覆蓋已有內容，並在 README 與 Demo 說明 Google 試算表的版本記錄。
- [Sheets API 用量限制（每位使用者每分鐘約 60 次讀取）] → 只有匯入與寫回會呼叫 API，頻率遠低於限制。
- [與 SpecKit 組可能不一致的細節] 老師頁面顯示授權帳號 email、網址欄位也接受純試算表 ID、工作表以 ID 識別（改名不影響寫回）、伺服器可在未授權時啟動、Sheets API 未啟用時的專屬訊息 → 實作完成後列給 SpecKit 組對齊。
- [舊的開發資料被捨棄] → 只影響開發期間的測試匯入，重新以網址匯入即可。

## Migration Plan

1. 安裝新相依（`uv pip install -e ".[dev]"`）。
2. 在 Google Cloud 建立專案、啟用 Google Sheets API、設定 OAuth 同意畫面（Testing，加入自己的帳號為測試使用者）、建立「桌面應用程式」OAuth 用戶端並下載 JSON 存成 `data/google-client-secret.json`。
3. 執行 `python -m app google-login` 完成授權。
4. 啟動伺服器；SQLite 第一次啟動時自動升級到第 2 版，舊學習單資料被捨棄。
5. 回復方式：切回上一個 commit 即可回到 .xlsx 版本（第 2 版資料庫無法被舊版讀取，需刪除 `data/buzzer.db`）。
