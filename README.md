# 課堂搶答系統

老師匯入存在 Google 試算表的填空式學習單（Guided Notes），各組在瀏覽器線上搶答，結束後把成功答案直接寫回原試算表的填空格。系統只在單一電腦上運作，以多個瀏覽器視窗模擬老師與各組。

目前完成的部分：
- 老師登入、以網址匯入 Google 試算表學習單、Google OAuth 授權（OpenSpec change `adopt-google-sheets-source`）。
- 答案寫回與 CSV 匯出的 API（操作畫面在搶答活動 change `add-live-buzzer-activity` 加入）。

設計圖在 [`diagrams/`](diagrams/)（PlantUML 原始檔與 PNG），規格在 [`openspec/specs/`](openspec/specs/)。

## 需求

- Python 3.12 以上
- 建議使用 [uv](https://docs.astral.sh/uv/) 建立虛擬環境（也可以用 `python -m venv`）
- 一個 Google 帳號，以及可以建立 Google Cloud 專案的權限（免費）
- 匯入與寫回時需要網路；搶答過程本身不需要連網

## 安裝

```powershell
uv venv --python 3.12 .venv
uv pip install --python .venv -e ".[dev]"
```

## 設定

複製 `.env.example` 為 `.env`，至少設定老師密碼：

```powershell
Copy-Item .env.example .env
```

接著編輯 `.env`，把 `BUZZER_TEACHER_PASSWORD` 改成自己的密碼。`.env` 已列入 `.gitignore`，不可加入版本控制。

| 設定 | 預設值 | 說明 |
|---|---|---|
| `BUZZER_TEACHER_PASSWORD` | （必填） | 老師登入密碼；未設定或空白時伺服器拒絕啟動 |
| `BUZZER_PORT` | 8000 | 伺服器 port；伺服器固定只監聽 127.0.0.1 |
| `BUZZER_DATA_DIR` | `./data` | SQLite 資料庫與 Google 授權檔的位置 |
| `BUZZER_MAX_QUESTIONS` | 500 | 題數上限 |
| `BUZZER_LABEL_NO` / `BUZZER_LABEL_QUESTION` / `BUZZER_LABEL_ANSWER` | 題號 / 題目 / 作答 | 表頭標籤 |
| `BUZZER_LOCKOUT_MAX_FAILURES` / `BUZZER_LOCKOUT_SECONDS` | 5 / 60 | 同一視窗連續失敗幾次後鎖定幾秒 |
| `BUZZER_TOKEN_TTL_HOURS` | 12 | 老師登入有效時數 |
| `BUZZER_GOOGLE_CLIENT_SECRETS` | `<資料目錄>/google-client-secret.json` | Google OAuth 用戶端設定檔 |
| `BUZZER_GOOGLE_TOKEN_FILE` | `<資料目錄>/google-token.json` | Google 授權檔（登入指令產生） |
| `BUZZER_GOOGLE_TIMEOUT_SECONDS` | 20 | 呼叫 Google API 的逾時秒數 |

## 設定 Google 存取（第一次使用前做一次）

系統以 OAuth 用你自己的 Google 帳號讀寫試算表。Google Cloud 的介面偶爾會改版，以下以功能名稱說明：

1. 到 [Google Cloud Console](https://console.cloud.google.com/) 建立一個新專案。
2. 在「API 和服務 → 程式庫」搜尋 **Google Sheets API** 並啟用。沒有啟用時，系統會顯示「Google Cloud 專案尚未啟用 Google Sheets API」。
3. 設定 **OAuth 同意畫面**（Google Auth Platform）：使用者類型選「外部」，發布狀態維持「測試」，並把你要用來登入的 Google 帳號加入「測試使用者」。
4. 在「憑證」建立 **OAuth 用戶端 ID**，應用程式類型選「**電腦版應用程式（Desktop app）**」，下載 JSON。
5. 把下載的 JSON 存成 `data/google-client-secret.json`（或用 `BUZZER_GOOGLE_CLIENT_SECRETS` 指定路徑）。這個檔案與 `client_secret*.json` 都已列入 `.gitignore`，**不要**加入版本控制。
6. 執行登入指令，瀏覽器會開啟 Google 授權頁面，登入第 3 步加入的帳號並同意授權：

```powershell
.venv\Scripts\python -m app google-login
```

完成後終端機顯示「已完成 Google 授權：<帳號 email>」，授權存在 `data/google-token.json`，老師頁面也會顯示目前授權的帳號。

**注意：** 同意畫面在「測試」狀態時，Google 會讓更新權杖在 **7 天後失效**。Demo 或上課前請重新執行一次 `google-login`。授權失效時，系統會顯示「Google 授權已失效，請重新執行 python -m app google-login」。

## 啟動

在專案根目錄執行（會讀取該目錄的 `.env`）：

```powershell
.venv\Scripts\python -m app
```

開啟 <http://127.0.0.1:8000/>。伺服器以單一程序執行，所有進行中的狀態都在記憶體中，請不要用多個 worker 啟動。尚未完成 Google 授權也能啟動，只是匯入與寫回會提示先登入。

## 匯入學習單

1. 確認試算表已**共用給授權的 Google 帳號**（匯入需要檢視權限，寫回需要編輯權限）。助教或其他老師的試算表，可以請對方共用給該帳號，或先「建立副本」到該帳號的雲端硬碟。
2. 若檔案是上傳到雲端硬碟的 Excel 檔（.xlsx），請先在 Google 試算表中選擇「檔案 → 儲存為 Google 試算表」，再使用新檔案的網址。
3. 以老師身分登入，貼上試算表網址（`https://docs.google.com/spreadsheets/d/…`）並按「讀取並檢查」。
4. 系統依表頭（同一列同時有「題號」「題目」「作答」）找出題目列、填空格與題組，並顯示確認畫面。
5. 確認無誤按「確認匯入」；按「取消」則不建立任何資料。

解析規則與錯誤訊息見 [`openspec/specs/worksheet-import/spec.md`](openspec/specs/worksheet-import/spec.md)。

## 寫回答案

寫回會**直接寫入原試算表**：
- 只寫入目前空白的填空格，其他儲存格的內容與格式都不會改變。
- 已有內容的填空格不會被覆蓋，完成訊息會列出這些題號。
- 寫回前會重新讀取試算表，若結構與匯入時不同（例如插入了列、改了子題標籤）就整批拒絕。

寫錯或想復原時，在 Google 試算表選擇「**檔案 → 版本記錄 → 查看版本記錄**」，即可還原到寫回前的版本。

手動驗證寫回時，可以用 `scripts/google_writeback_check.py`（請對學習單的**副本**執行）：

```powershell
.venv\Scripts\python scripts\google_writeback_check.py --list
```

```powershell
.venv\Scripts\python scripts\google_writeback_check.py 1
```

## 測試

```powershell
.venv\Scripts\python -m pytest
```

測試完全不連網（Google 存取以假的實作取代）。`tests/fixtures/` 內是兩份從 Google 試算表下載的範例學習單，測試會把它們轉成 Google Sheets API 的資料格式再解析，結構說明見 `tests/fixtures/README.md`。
