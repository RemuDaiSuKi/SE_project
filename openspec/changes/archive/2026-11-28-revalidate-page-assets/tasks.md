# Tasks

## 1. 實作

- [x] 1.1 `app/main.py` 的 `_security_headers` middleware：對 `/`、`/teacher` 與 `/static/` 的回應加上 `Cache-Control: no-cache`，`/api/` 維持 `no-store`
- [x] 1.2 `tests/test_errors_and_host.py`：驗證頁面與靜態檔的 `Cache-Control: no-cache`、靜態檔的 `ETag`、`If-None-Match` 命中時回應 304，以及 API 仍為 `no-store`

## 2. 驗證

- [x] 2.1 在已安裝相依套件的環境執行 `python -m pytest`，確認全部通過
- [x] 2.2 執行 `openspec validate revalidate-page-assets --strict`
- [x] 2.3 手動確認：開啟老師頁後修改 `app/static/css/app.css` 的任一顏色並重啟伺服器，一般重新整理（F5）就看得到新樣式；在瀏覽器開發者工具的 Network 分頁看到 `app.css` 未變更時為 304
- [x] 2.4 封存本 change（`openspec archive revalidate-page-assets`）
