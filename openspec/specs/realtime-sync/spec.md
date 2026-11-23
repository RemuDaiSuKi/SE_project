# realtime-sync Specification

## Purpose

讓老師與各組視窗在不重新整理頁面的情況下，透過 WebSocket 即時看到階段變化、送出結果、冷卻與判定無效，且每條連線只收到該身分可以看到的資料。

## Requirements

### Requirement: WebSocket 驗證
系統 SHALL 在 `/ws` 提供 WebSocket。連線後的第一則訊息 MUST 是 `{"type": "auth", "token": <Token>}`。以下情況 SHALL 以關閉代碼 4401 關閉連線：
- 在驗證逾時秒數（預設 5）內沒有送出
- 格式不對
- Token 無效
- 組別代碼已重新產生

Token MUST NOT 放在網址中。系統不檢查 `Origin` 標頭。

#### Scenario: 沒有驗證
- **WHEN** 連上 `/ws` 後 5 秒內沒有送出驗證訊息
- **THEN** 連線以 4401 關閉

#### Scenario: Token 無效
- **WHEN** 第一則訊息帶的是已登出的老師 Token
- **THEN** 連線以 4401 關閉

### Requirement: 快照與增量事件
驗證成功後，系統 SHALL 先送一份依身分產生的完整快照：
- 老師：本次啟動後最近建立的活動的監看畫面；沒有活動時為空。
- 學生：本組畫面。

之後系統 SHALL 推送增量事件。事件依對象分成四種：
- 老師
- 某一組
- 該活動的所有連線
- 撤銷某一組

推播 SHALL 在狀態更新完成、鎖釋放之後才送出。斷線重連時 SHALL 重新收到完整快照。

#### Scenario: 開始搶答
- **WHEN** 老師按「開始」
- **THEN** 所有已連線的老師與學生視窗收到階段變為搶答中的事件

#### Scenario: 同組同步
- **WHEN** A 組在視窗 1 送出
- **THEN** A 組的視窗 2 收到這筆送出的順位與結果，B 組沒有收到

#### Scenario: 斷線重連
- **WHEN** A 組的視窗在搶答中斷線後重連
- **THEN** 立即收到目前階段、A 組的紀錄與冷卻剩餘秒數

#### Scenario: 活動結束
- **WHEN** 老師結束活動
- **THEN** 所有連線收到階段變為已結束的事件，接著各自收到新的快照，學生的快照含完整結果

### Requirement: 撤銷連線
老師重新產生某組代碼時，系統 SHALL 送出撤銷事件給該組的所有連線，接著以關閉代碼 4403 關閉它們。

#### Scenario: 重新產生代碼
- **WHEN** 老師重新產生 A 組代碼
- **THEN** A 組的所有 WebSocket 收到撤銷事件後以 4403 關閉，B 組的連線不受影響
