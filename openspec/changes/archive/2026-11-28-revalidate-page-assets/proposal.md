# Proposal

## Why

目前伺服器只對 `/api/` 的回應加上 `Cache-Control: no-store`，頁面（`/`、`/teacher`）與 `/static/` 下的 JS、CSS 都沒有快取指示，由瀏覽器自行決定要不要沿用快取。結果是：程式更新後重新啟動伺服器，瀏覽器仍可能繼續用舊的 `teacher.js` 或 `app.css`，畫面和伺服器的行為不一致，老師要手動按 Ctrl+F5 才看得到新版。實測與 Demo 時特別容易誤判成功能沒改好。

## What Changes

- 頁面（`/`、`/teacher`）與 `/static/` 下的所有檔案回應 `Cache-Control: no-cache`：瀏覽器可以保留快取，但每次使用前都要先向伺服器確認有沒有新版。
- `/static/` 的檔案沿用 StaticFiles 提供的 `ETag` 與 `Last-Modified`；檔案沒變時伺服器回應 304，不重新傳送內容。
- API 回應維持 `Cache-Control: no-store`，不受影響。

## Capabilities

### New Capabilities

（無）

### Modified Capabilities

- `server-runtime`: 新增「頁面與靜態檔每次確認新版」。

## Impact

- `app/main.py`：既有的 `_security_headers` middleware 加上頁面與 `/static/` 的快取標頭。
- `tests/test_errors_and_host.py`：新增快取標頭與 304 的測試。
- 不影響 API、判定引擎與資料庫。
