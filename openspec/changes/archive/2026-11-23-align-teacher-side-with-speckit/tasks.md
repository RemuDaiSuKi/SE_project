# Tasks

## 1. 老師登入（teacher-auth）

- [x] 1.1 新增 `LoginLimiter`（全體共用計數、5 次鎖 300 秒、鎖定時歸零、成功歸零）與 `BUZZER_LOGIN_MAX_FAILURES`、`BUZZER_LOGIN_LOCK_SECONDS`；登入 API 改用它；Token 預設 8 小時
- [x] 1.2 更新測試：`LoginLimiter` 單元測試、跨視窗共用鎖定、設定可覆寫

## 2. 學習單匯入（worksheet-import）

- [x] 2.1 Sheets API 改讀 `formattedValue`，轉換只保留非空字串；測試用的活頁簿轉換工具改為輸出顯示值
- [x] 2.2 解析器：空白區段、題目列只看本列儲存格、題號欄縱向合併的每一列都必須是題目列（每列一處問題）、子題標籤取第一個、錯誤不設上限、檢查順序、移除空白試算表訊息
- [x] 2.3 網址解析改為 SpecKit 組的規則，並以兩邊的函式逐一比對
- [x] 2.4 預覽改存 SQLite（schema 第 3 版只新增資料表），確認或取消已結束的預覽回 409；測試驗證重啟後仍可確認、沒有期限、v2→v3 升級保留學習單
- [x] 2.5 差異測試：兩份範例、18 種特殊排版、15,000 份隨機學習單，與 SpecKit 組解析器的結果完全一致

## 3. 答案寫回（answer-writeback）

- [x] 3.1 結構檢查改為比對題數與 `(工作表 ID, 工作表名稱, 填空格, 題組)`，以目前設定的標籤與題數上限重新解析，只回報第一個差異；寫入使用匯入時的工作表名稱
- [x] 3.2 以 7 種情境與 SpecKit 組的結構檢查比對，結果一致；更新寫回測試（改名拒絕、子題標籤不比對、目前標籤）

## 4. Google 授權與啟動（google-sheets-access、server-runtime）

- [x] 4.1 `python -m app` 依序檢查老師密碼、OAuth 用戶端設定檔、授權，缺少時拒絕啟動
- [x] 4.2 移除 `GET /api/google/status` 與老師頁面的「Google 授權」區塊
- [x] 4.3 錯誤分類改為 401／403／404／其他，403 訊息列出授權帳號；Google API 逾時預設 10 秒
- [x] 4.4 新增 `BUZZER_HOST`，移除 Host 標頭檢查的 middleware
- [x] 4.5 更新 `.env.example`、README 與相關測試

## 5. 設計圖與驗證

- [x] 5.1 更新 `diagrams/class.puml`、`component.puml`、`sequence-import.puml`、`sequence-writeback.puml`
- [x] 5.2 以 PlantUML 把上述 4 個 .puml 轉成 PNG，確認 PNG 已更新（見 README「設計圖」）。2026-11-23 改為只保留 .puml、不提交 PNG，過時的 PNG 已刪除（見 add-live-buzzer-activity 的 design D13）
- [x] 5.3 在已安裝相依套件的環境執行 `python -m pytest`，確認全部通過
- [x] 5.4 以真實的 Google 試算表手動確認：匯入範例 A、B、寫回、未授權時無法啟動
- [x] 5.5 封存本 change（`/openspec-archive-change`），把 delta spec 同步進主 spec
