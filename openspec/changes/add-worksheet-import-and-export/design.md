# Design

## Context

- repo 目前只有 OpenSpec 骨架，沒有任何程式碼，本 change 同時建立專案骨架。動機見 proposal.md「Why」，行為見各 capability 的 spec。
- 同一系統由 SpecKit 小組平行實作，技術選擇沿用對方：Python 3.12、FastAPI、openpyxl、SQLite、靜態 HTML + 原生 JavaScript、pytest。
- 系統只在單一電腦運作，以多個瀏覽器視窗模擬老師與各組；同一瀏覽器的視窗共用 Cookie，因此身分只能放在各視窗的 sessionStorage。
- 本 change 的寫回與 CSV 匯出需要「已結束活動的結果」，但活動由第二個 change `add-live-buzzer-activity` 實作，因此兩者之間需要明確的資料契約。
- 兩份範例學習單（A：無題組；B：含題組）目前只有文字描述，尚未取得實際 .xlsx 匯出檔驗證合併儲存格的實際結構。

## Goals / Non-Goals

**Goals:**
- 解析器只依結構運作，能處理任意欄位位置、多工作表、合併儲存格與題組。
- 寫回時，除填空格外的所有位元組層級內容盡量不變，避免整份重存造成的格式流失。
- 定義第二個 change 可以直接沿用的基礎：視窗身分、Token、權限檢查、錯誤格式、設定、資料目錄與 ActivityResult 契約。

**Non-Goals:**
- 搶答活動、組別代碼、學生加入、即時推播：屬於第二個 change。
- 題目標示文字（例如「第 5 題（學習單第 3 題）」）的呈現規則：屬於第二個 change。
- 寫回與匯出的操作入口在活動結果頁面，由第二個 change 提供；本 change 只提供 API 與老師的登入／匯入畫面。
- 刪除學習單、編輯學習單、連接 Google 帳號。

## Decisions

### D1. 專案結構

```
app/
  __main__.py          啟動入口：檢查設定 → uvicorn（host 固定 127.0.0.1、workers=1、access_log 關閉）
  config.py            Settings（pydantic-settings，前綴 BUZZER_，讀環境變數與 .env）
  errors.py            AppError、錯誤代碼、繁中訊息、例外處理器（含 422 / 404 / 500 覆寫）
  security.py          視窗註冊、失敗鎖定、Token 簽發與驗證、require_teacher 依賴
  db.py                SQLite 連線與 schema 初始化
  worksheet/
    model.py           ParsedWorksheet、Question、QuestionGroup、ImportIssue
    parser.py          .xlsx → ParsedWorksheet | list[ImportIssue]
    store.py           已確認學習單的保存與讀取、預覽暫存
    writeback.py       寫回（lxml 修改 sheet XML + 重新打包 zip）
  results/
    contract.py        ActivityResult 契約與結果推導函式
    source.py          FinalResultSource 介面與預設實作
    csv_export.py      CSV 產生
  api/                 routes：windows、teacher、worksheets、activity_outputs
  static/              index.html、teacher.html、js/api.js、js/teacher.js、css
tests/
  builders.py          以程式產生測試用 .xlsx（含範例 A、B 的等價版本與各種錯誤檔）
  fixtures/            實際的範例 A、B 匯出檔（取得後放入）
```

替代方案：依層分（routers/services/repositories）。功能導向的分法讓第二個 change 可以新增 `app/activity/` 而不必動到既有模組，因此採用功能導向。

### D2. 設定

採用 pydantic-settings，所有設定以 `BUZZER_` 為前綴：`TEACHER_PASSWORD`、`PORT`（8000）、`DATA_DIR`（`./data`）、`MAX_UPLOAD_MB`（10）、`MAX_UNCOMPRESSED_MB`（100）、`MAX_QUESTIONS`（500）、`LABEL_NO`／`LABEL_QUESTION`／`LABEL_ANSWER`（題號／題目／作答）、`LOCKOUT_MAX_FAILURES`（5）、`LOCKOUT_SECONDS`（60）、`TOKEN_TTL_HOURS`（12）。設定驗證失敗時由 `__main__` 捕捉，輸出繁中訊息（只列設定名稱，不列值）並以結束碼 1 離開。監聽位址不是設定項目。

第二個 change 會在同一個 Settings 加入答案長度、N、K、組數上限等設定，並沿用同一組失敗鎖定設定處理組別代碼輸錯。

### D3. 視窗身分與 Token

```
 browser window                         server (memory)
 +-------------------------+            +------------------------------+
 | sessionStorage          |  POST      | windows: {window_id: lockout}|
 |   windowId  <-----------+-/windows---+ sessions: {sha256(token):    |
 |   token     <-----------+-/login-----+   role, expires_at, window}  |
 +-------------------------+            +------------------------------+
   Authorization: Bearer <token>   (每個 API 請求)
```

- 頁面載入時若 sessionStorage 沒有 `windowId`，向 `POST /api/windows` 取得一個 128 位元的隨機識別。視窗識別由伺服器發放，失敗計數與鎖定以它為單位。
- 登入請求帶 `windowId`，成功後回傳 `secrets.token_urlsafe(32)`；伺服器只保存 Token 的 SHA-256。
- 所有 API 以 `Authorization: Bearer` 傳遞 Token，不使用 Cookie，也不放在 URL 查詢字串。下載檔案時前端以 fetch 取得 blob 後觸發下載，因此下載也不需把 Token 放進網址。
- 伺服器重啟後視窗識別與 Token 全部失效；前端收到「視窗識別已失效」時自動重新註冊一次，收到「登入已失效」時回到登入頁。
- `require_teacher` 是 FastAPI 依賴：沒有 Token 或 Token 不是老師身分一律回應 `FORBIDDEN`「無權限執行此操作」；Token 過期或不存在回應 `SESSION_EXPIRED`。第二個 change 新增 `require_group` 與學生 Token，沿用同一個 sessions 表。

替代方案：簽章式 Token（JWT）。系統本來就要求重啟後失效且狀態都在記憶體，伺服器端 session 較簡單，也不需要管理簽章金鑰，因此不用 JWT。

已知限制：開新視窗即可取得新的視窗識別，繞過鎖定。單機環境無法區分視窗來源，失敗鎖定只能減緩嘗試速度；老師密碼的強度由使用者負責。

### D4. 錯誤格式

```json
{"error": {"code": "IMPORT_INVALID", "message": "學習單有 2 處問題，未匯入",
           "details": [{"sheet": "學習單", "location": "第 7 列", "message": "作答欄沒有空白填空格"}]}}
```

HTTP 狀態：400 驗證錯誤、401 `SESSION_EXPIRED`、403 `FORBIDDEN`、404 `NOT_FOUND`、409 狀態衝突（例如活動未結束、結構不一致、預覽已確認）、413 檔案過大、429 鎖定中（`retry_after_seconds`）。FastAPI 的 `RequestValidationError`、Starlette 的 404/405 與未預期的 `Exception` 都由自訂處理器轉成這個格式；未預期例外只在伺服器 log 記錄例外類型與追蹤（不含請求內容），回應固定為「系統發生錯誤，請稍後再試」。

### D5. Host 檢查與 log

- 以 middleware 檢查 `Host` 是否為 `127.0.0.1:<port>` 或 `localhost:<port>`，防止 DNS rebinding。測試的 TestClient 以 `base_url="http://127.0.0.1:<port>"` 建立。
- uvicorn `access_log=False`；應用程式 log 只記錄事件與識別碼（例如「學習單已確認 id=3 題數=6」），不記錄請求內容、標頭或 URL 查詢字串。
- 測試中以 caplog 與 capsys 收集整個流程的輸出，斷言測試產生的隨機密碼與 Token 都不出現。

### D6. 解析演算法

使用 openpyxl `load_workbook(data_only=False, read_only=False, keep_links=False)`；需要非唯讀模式才能取得 `merged_cells`，需要 `data_only=False` 才能辨識公式。載入前先以 `zipfile` 檢查：必須是 zip、含 `xl/workbook.xml`、不含 `vbaProject.bin`、所有項目的解壓大小總和不超過上限（只讀中央目錄，不實際解壓）。

每個工作表（依 `wb.worksheets` 的分頁順序，略過圖表工作表）：

1. 建立合併對照：每個被合併的座標 → 合併範圍的左上角。
2. 「視覺值」：座標在合併範圍內時取左上角的值，否則取自身的值。空白 = `None` 或 `str.strip()` 後為空字串（Python 的 `strip()` 會去除全形空白）。數值、日期、布林與公式字串都算非空白。
3. 表頭列：由上而下找第一個列，該列中「左上角位於此列」的儲存格同時含三個標籤。各欄位的欄範圍 = 該儲存格（或其合併範圍）涵蓋的欄；同一標籤出現多次時取最左邊的。
4. 題目列：表頭以下每一列，題目欄範圍內任一座標的視覺值非空白即為題目列（採視覺語意，涵蓋題目欄縱向合併的情況）。合併儲存格只在左上角的欄落在題目欄範圍內時才計入，因此範例 A 那種左上角在題號欄的 B:H 整列合併不會讓該列成為題目列。
5. 作答欄的邏輯儲存格：對作答範圍內的每個座標，取其左上角並去重；只保留「左上角位於本列且左上角的欄落在作答範圍內」的邏輯儲存格。空白者為填空格候選，非空白者為子題標籤。候選數不等於 1 時記錄錯誤。
6. 題組：題號欄範圍內、左上角在表頭以下、跨 2 列以上的合併範圍。範圍內的題目列少於 2 個時不是題組，直接略過；達 2 個以上時，範圍內每一列都必須是題目列，否則記錄錯誤；通過者成為題組，依全活頁簿出現順序編號。
7. 原始題號：題號欄範圍內第一個非空白的視覺值；整數型的 float 轉成整數字串。

全部工作表處理完才判斷「找不到表頭」「找不到題目列」與題數上限，錯誤最多收集 50 筆。另外以 `xl/workbook.xml` 與 `xl/_rels/workbook.xml.rels` 建立「工作表名稱 → 工作表 XML 路徑」的對照，記錄在每一題中，供寫回使用。

替代方案：在作答範圍內，把被縱向合併涵蓋的儲存格也算進下方的列。這樣兩個題目列會共用一個填空格，與「每個題目列恰好一個填空格」衝突，因此不採用。

### D7. 預覽與保存

- 預覽暫存在記憶體：`preview_id` → {檔案位元組、解析結果、建立時間}，存活 30 分鐘，最多同時 10 份，超過時淘汰最舊的。確認或取消後立即移除。
- 確認時，原始檔以隨機檔名寫入 `<DATA_DIR>/worksheets/`，並在同一個 SQLite transaction 中寫入：

```
worksheets(id, original_filename, stored_name, file_sha256, label_no, label_question,
           label_answer, question_count, group_count, confirmed_at)
worksheet_questions(worksheet_id, no, sheet_name, sheet_part, cell_ref, row,
                    source_no, sub_label, group_no)            -- PK(worksheet_id, no)
worksheet_groups(worksheet_id, group_no, source_no)            -- PK(worksheet_id, group_no)
```

先寫檔案、再提交 transaction；transaction 失敗時刪除已寫入的檔案。SQLite 啟用 WAL 與 `foreign_keys`。

### D8. ActivityResult 契約（與第二個 change 的介面）

```python
@dataclass(frozen=True)
class ResultGroup:   group_id: int; name: str
@dataclass(frozen=True)
class ResultRecord:  rank: int; group_id: int; answers: Mapping[int, str]; invalidated: bool
@dataclass(frozen=True)
class ResultUnit:    unit_id: str; question_nos: tuple[int, ...]; records: tuple[ResultRecord, ...]
@dataclass(frozen=True)
class ActivityResult:
    activity_id: int; worksheet_id: int; ended_at: datetime
    groups: tuple[ResultGroup, ...]; units: tuple[ResultUnit, ...]

def outcome_of(unit, record) -> Literal["success", "lost", "invalid"]
def winner_of(unit) -> ResultRecord | None      # 順位最小且未被判定無效者
def success_counts(result) -> dict[int, int]     # 以搶答單位計

class FinalResultSource(Protocol):
    def lookup(self, activity_id: int) -> FinalResultLookup   # status: not_found | not_ended | ended
```

- 搶答單位：不屬於題組的單題 `unit_id="Q<no>"`；題組 `unit_id="G<group_no>"`，`question_nos` 為該題組的系統題號。
- 結果只保存 `invalidated` 旗標，成功與否由「順位最小且未被判定無效」推導。這個推導同時涵蓋遞補（下一順位成為最小的有效紀錄）與搶答中重新開放（前面的紀錄都無效，新送出的紀錄成為唯一有效者）。第二個 change 的畫面、通知與計數也必須使用同一組函式，確保全系統只有一種判定邏輯。
- 契約驗證：每個單位的順位為 1..m 連續且不重複；每筆紀錄的 `answers` 鍵集合等於 `question_nos`；`group_id` 都存在於 `groups`。驗證失敗代表程式錯誤，回應 500。
- 本 change 的預設 `FinalResultSource` 一律回傳 `not_found`。第二個 change 以讀取 SQLite 的實作取代，並負責結果資料表的 schema。測試以假的 `FinalResultSource` 注入結果資料。

替代方案：本 change 先建立結果資料表。這會讓第一個 change 決定第二個 change 的保存設計，因此只定義讀取介面。

### D9. 寫回

```
stored original.xlsx --sha256 check--> re-parse with stored labels --compare--> ok?
        |                                                                       |
        v                                                                       v
  zip entries ------ copy unchanged parts ------------------------------> new.xlsx
        |                                                                       ^
        +-- target sheet XML --lxml parse--> set fill cells (inlineStr) ---------+
```

- 一致性驗證：重新計算 SHA-256 並與記錄比對；以記錄的表頭標籤重新解析（不套用目前的題數上限），比對每題的（題號、工作表、cell_ref、sub_label、group_no、source_no）。
- 修改方式：以 lxml（`resolve_entities=False`、`no_network=True`、`huge_tree=False`）解析目標工作表 XML，找到 `<c r="H5">`：
  - 保留 `s` 等屬性，設定 `t="inlineStr"`，移除既有子元素，放入 `<is><t xml:space="preserve">答案</t></is>`。
  - `<c>` 不存在時依欄順序插入；`<row>` 不存在時依列順序插入 `sheetData`。
  - 序列化時保留原本的 XML 宣告與 standalone 屬性。
- 使用 inlineStr 是為了只修改目標工作表一個檔案，不必動到 `sharedStrings.xml`。
- 重新打包：依原 zip 的項目順序逐一寫入，未修改的項目沿用原 `ZipInfo`（名稱、時間、壓縮方式），內容原樣複製。
- 答案在寫入前移除 XML 不允許的控制字元。第二個 change 在送出時就會拒絕這類字元，所以這只是防禦性處理。
- 回應：直接回傳 .xlsx（`Content-Disposition` 以 RFC 5987 編碼中文檔名），沒有成功答案的題號放在 `X-Empty-Questions` 標頭（逗號分隔的數字），由前端組成完成訊息。

替代方案 1：用 openpyxl 載入後整份重存。會遺失或改寫 openpyxl 不支援的內容（資料驗證擴充、條件格式擴充、圖片、主題細節等），因此不採用。
替代方案 2：用 ElementTree 修改 XML。ElementTree 會把命名空間前綴改成 `ns0` 之類的名稱，導致 `mc:Ignorable` 參照失效，Excel 會判定檔案損毀，因此改用會保留前綴的 lxml。
替代方案 3：以字串或正規表示式直接替換。不必引入新相依套件，但遇到屬性順序、自閉合標籤或缺少元素等情況時很脆弱，因此不採用。

### D10. CSV

使用 Python `csv` 模組（`QUOTE_MINIMAL`、`lineterminator="\r\n"`），以 `utf-8-sig` 編碼。資料列由 ActivityResult 展開：每筆紀錄 × 該單位的每個題號 → （題號、組名、答案、順位、`outcome_of` 對應的中文），再依（題號、順位）排序。回應標頭 `X-Record-Count` 提供送出紀錄筆數，為 0 時前端顯示提示。答案不加任何前綴（見 Risks）。

### D11. API 一覽

| 方法 | 路徑 | 權限 |
|---|---|---|
| POST | `/api/windows` | 無 |
| POST | `/api/teacher/login`、`/api/teacher/logout` | 無／老師 |
| POST | `/api/worksheets/previews`（multipart） | 老師 |
| POST | `/api/worksheets/previews/{id}/confirm` | 老師 |
| DELETE | `/api/worksheets/previews/{id}` | 老師 |
| GET | `/api/worksheets`、`/api/worksheets/{id}` | 老師 |
| POST | `/api/activities/{id}/writeback` | 老師 |
| GET | `/api/activities/{id}/results.csv` | 老師 |

上傳時先檢查 `Content-Length`，再以最多讀取「上限 + 1」位元組的方式讀取，避免超大檔案進入記憶體。

### D12. 測試策略

- `tests/builders.py` 以 openpyxl 產生測試用輸入檔（只用於產生輸入，不用於寫回），包含範例 A、B 的等價版本、排版不同與多工作表的檔案，以及各種錯誤檔。
- 取得實際的範例 A、B 匯出檔後放入 `tests/fixtures/`，增加以真實檔案驗證的測試。
- 寫回測試以 zip 層級比對：除目標工作表外所有項目的內容完全相同；目標工作表以 lxml 比對，只有填空格不同。並以 openpyxl 讀回新檔，確認答案與合併範圍。
- 並行與即時相關的測試不在本 change。

## Risks / Trade-offs

- [範例 B 的實際合併結構未驗證] 如果題目欄在題組內是逐列各自有文字，視覺語意不影響結果；如果是縱向合併，視覺語意讓它通過。兩種情況都應通過，但仍需真實檔案確認 → 第一組 task 就取得兩份實際匯出檔並加入測試。
- [Google Sheets 對 inlineStr 的支援] 若 Google Sheets 重新匯入時不顯示 inlineStr → 早期以手動上傳做 spike 驗證；如不支援，改為修改 `sharedStrings.xml`（第二個被修改的檔案），其他設計不變。
- [CSV 公式注入] 以 `=`、`+`、`-`、`@` 開頭的答案在 Excel 中可能被當成公式執行。規則要求原樣輸出，且系統只在本機課堂使用 → 不加前綴，列為已知風險並與 SpecKit 組對齊。
- [視窗鎖定可被新視窗繞過] → 在單機環境無解；主要防線是密碼強度（老師）與代碼熵（第二個 change 的學生）。
- [隱藏工作表照常處理] 老師把含表頭的工作表隱藏起來時，仍會被匯入 → 確認畫面顯示每題所屬工作表，老師可以發現並取消；需與 SpecKit 組對齊。
- [頁尾文字落在題目欄] 會被當成題目列，進而因填空格數不符而被拒絕 → 錯誤訊息指出確切列號，老師可以修正學習單。
- [記憶體中的預覽] 最多 10 份、每份最多 10 MB，記憶體上限約 100 MB → 對單機課堂使用足夠。
- [單一程序] 狀態都在記憶體，不能水平擴充 → 符合單機需求，啟動入口固定 `workers=1`。

## Migration Plan

全新專案，沒有遷移。資料目錄與 SQLite schema 在第一次啟動時建立；第二個 change 以新增資料表的方式擴充 schema（以 `user_version` 記錄 schema 版本）。

## Open Questions

- 範例 A、B 的實際 .xlsx 匯出檔需由使用者提供，用來確認測試資料與真實檔案一致；這不會改變規格（解析規則已同時涵蓋兩種可能的合併方式）。
