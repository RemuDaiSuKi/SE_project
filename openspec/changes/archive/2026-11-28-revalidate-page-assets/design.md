# Design

## Context

伺服器原本只對 `/api/` 的回應加上 `Cache-Control: no-store`。頁面（`/`、`/teacher`）與 `/static/` 下的 JS、CSS 沒有任何快取指示，要不要沿用快取由瀏覽器自行判斷。

實測與 Demo 前常常更新程式並重啟伺服器，結果瀏覽器仍沿用舊的 `teacher.js` 或 `app.css`：畫面和伺服器的行為不一致，老師要按 Ctrl+F5 才看得到新版，容易誤判成功能沒改好。SpecKit 組遇到同樣的問題，也做了相同的修正，兩組行為一致。

## Goals / Non-Goals

**Goals：**
- 程式更新並重啟伺服器後，一般重新整理（F5）就拿到新版頁面、JS 與 CSS。
- 檔案沒變時不重新傳送內容，維持載入速度。
- API 的快取行為不變。

**Non-Goals：**
- 不在檔名或網址加上版本號，例如 `app.css?v=…`。
- 不改 API、判定引擎、資料庫或頁面內容。

## Decisions

### D1 頁面與靜態檔使用 `Cache-Control: no-cache`

`no-cache` 的意思是「可以存快取，但每次使用前都要先向伺服器確認」，不是禁止快取：

| 回應 | `Cache-Control` | 理由 |
|---|---|---|
| `/api/` | `no-store`（不變） | API 內容含 Token 相關的狀態與即時資料，不該留在快取 |
| `/`、`/teacher` | `no-cache` | 頁面很小，每次確認也不影響速度 |
| `/static/` 下的 JS、CSS | `no-cache` | 搭配 D2 的 304，檔案沒變時幾乎不花傳輸量 |

考慮過的做法：
- **`no-store`：** 每次都要重新下載全部檔案，沒有必要。
- **在網址加版本號：** 每次改檔都要同步更新 HTML 裡的引用，容易漏改；本機單機系統也不需要長時間快取。

### D2 沿用 StaticFiles 的 `ETag` 與 304

Starlette 的 `StaticFiles` 已經會為每個檔案提供 `ETag` 與 `Last-Modified`。瀏覽器帶著 `If-None-Match` 再次請求、且檔案沒有變更時，會直接回應 304。本 change 不需要自己計算 ETag。

### D3 在既有的 middleware 中設定

標頭加在 `app/main.py` 既有的 `_security_headers` middleware，依路徑決定：
- `/api/` 開頭：`no-store`。
- `/`、`/teacher`，或 `/static/` 開頭：`no-cache`。

沿用 `setdefault`，個別端點若已自行設定 `Cache-Control`，就不覆蓋。

### D4 測試

在 `tests/test_errors_and_host.py` 驗證：
- 頁面與靜態檔帶有 `no-cache`。
- 靜態檔帶有 `ETag`，用相同的 `If-None-Match` 再次請求時回應 304。
- API 仍為 `no-store`。

## 設計圖

本 change 只在既有的 middleware 中加上回應標頭，沒有新增或改變元件、類別與互動流程，所以不新增也不修改 `./diagrams` 中的圖。

## Risks / Trade-offs

- **每次載入頁面都多一次確認請求：** 只在本機傳輸，檔案沒變時回應 304、沒有內容，影響可以忽略。
- **已經存了舊快取的瀏覽器：** 舊快取沒有 `no-cache` 指示，第一次仍可能沿用舊檔。改版後第一次載入可能需要強制重新整理一次，之後就不會再發生。
