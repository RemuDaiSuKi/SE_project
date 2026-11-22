# 課堂搶答系統

老師匯入 Google Sheets 的填空式學習單（Guided Notes），各組在瀏覽器線上搶答，結束後把成功答案寫回原學習單。系統只在單一電腦上運作，以多個瀏覽器視窗模擬老師與各組。

目前完成的部分（OpenSpec change `add-worksheet-import-and-export`）：老師登入、學習單匯入與確認、答案寫回與 CSV 匯出的 API。線上搶答活動在下一個 change `add-live-buzzer-activity` 實作。

## 需求

- Python 3.12 以上
- 建議使用 [uv](https://docs.astral.sh/uv/) 建立虛擬環境（也可以用 `python -m venv`）

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
| `BUZZER_DATA_DIR` | `./data` | SQLite 資料庫與已確認學習單原始檔的位置 |
| `BUZZER_MAX_UPLOAD_MB` | 10 | 上傳檔案大小上限 |
| `BUZZER_MAX_UNCOMPRESSED_MB` | 100 | .xlsx 解壓後大小上限 |
| `BUZZER_MAX_QUESTIONS` | 500 | 題數上限 |
| `BUZZER_LABEL_NO` / `BUZZER_LABEL_QUESTION` / `BUZZER_LABEL_ANSWER` | 題號 / 題目 / 作答 | 表頭標籤 |
| `BUZZER_LOCKOUT_MAX_FAILURES` / `BUZZER_LOCKOUT_SECONDS` | 5 / 60 | 同一視窗連續失敗幾次後鎖定幾秒 |
| `BUZZER_TOKEN_TTL_HOURS` | 12 | 老師登入有效時數 |

## 啟動

在專案根目錄執行（會讀取該目錄的 `.env`）：

```powershell
.venv\Scripts\python -m app
```

開啟 <http://127.0.0.1:8000/>。伺服器以單一程序執行，所有進行中的狀態都在記憶體中，請不要用多個 worker 啟動。

## 匯入學習單

1. 在 Google Sheets 選擇「檔案 → 下載 → Microsoft Excel (.xlsx)」。
2. 以老師身分登入，選擇下載的檔案並上傳。
3. 系統依表頭（同一列同時有「題號」「題目」「作答」）找出題目列、填空格與題組，並顯示確認畫面。
4. 確認無誤按「確認匯入」；按「取消」則不建立任何資料。

解析規則與錯誤訊息見 `openspec/changes/add-worksheet-import-and-export/specs/worksheet-import/spec.md`。

## 測試

```powershell
.venv\Scripts\python -m pytest
```

`tests/fixtures/` 內是兩份從 Google Sheets 下載的範例學習單，結構說明見 `tests/fixtures/README.md`。
