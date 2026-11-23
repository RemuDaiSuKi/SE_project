# Spec Delta

## ADDED Requirements

### Requirement: 搶答活動參數可設定
搶答活動的可調參數 SHALL 透過環境變數（或 `.env` 檔）設定且各有預設值：
- 全體每分鐘輸錯組別代碼的上限（預設 60）
- 組數上限（預設 20）與組名長度上限（預設 20 字）
- 答案長度上限（預設 200 字）
- 是否啟用冷卻（預設啟用）、冷卻秒數 N（預設 10，範圍 1–600）、領先題數 K（預設 2，範圍 1–100）
- WebSocket 驗證逾時秒數（預設 5，範圍 0.1–60）

輸入組別代碼時的視窗鎖定沿用既有的視窗失敗鎖定設定。設定值不合法時伺服器 SHALL 拒絕啟動，並以繁中說明哪個設定有誤。

#### Scenario: 冷卻秒數超出範圍
- **WHEN** 以 `BUZZER_COOLDOWN_SECONDS=601` 啟動伺服器
- **THEN** 伺服器拒絕啟動，訊息指出 `BUZZER_COOLDOWN_SECONDS` 不合法

#### Scenario: 覆寫答案長度上限
- **WHEN** 以 `BUZZER_MAX_ANSWER_LENGTH=5` 啟動伺服器，學生在搶答中送出 6 個字的答案
- **THEN** 送出被拒絕，訊息為「第 1 題的答案超過 5 字」
