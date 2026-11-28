# Spec Delta

## ADDED Requirements

### Requirement: 頁面與靜態檔每次確認新版
頁面（`/`、`/teacher`）與 `/static/` 下的檔案回應 SHALL 帶有 `Cache-Control: no-cache`，讓瀏覽器每次使用快取前都先向伺服器確認有沒有新版。`/static/` 的檔案 SHALL 提供 `ETag`，瀏覽器帶著相同的 `If-None-Match` 再次請求且檔案未變更時，伺服器回應 304 且不重送內容。API 回應 MUST 維持 `Cache-Control: no-store`。

#### Scenario: 頁面要求重新確認
- **WHEN** 瀏覽器請求 `/teacher`
- **THEN** 回應帶有 `Cache-Control: no-cache`

#### Scenario: 靜態檔要求重新確認
- **WHEN** 瀏覽器請求 `/static/js/teacher.js` 或 `/static/css/app.css`
- **THEN** 回應帶有 `Cache-Control: no-cache` 與 `ETag`

#### Scenario: 檔案未變更
- **WHEN** 瀏覽器以上一次取得的 `ETag` 作為 `If-None-Match` 再次請求 `/static/js/teacher.js`，而檔案沒有變更
- **THEN** 伺服器回應 304，不重送檔案內容

#### Scenario: 程式更新後
- **WHEN** `teacher.js` 更新並重新啟動伺服器後，老師重新整理頁面
- **THEN** 瀏覽器取得新版的 `teacher.js`，不需要強制重新整理

#### Scenario: API 不受影響
- **WHEN** 呼叫任何 `/api/` 端點
- **THEN** 回應仍帶有 `Cache-Control: no-store`
