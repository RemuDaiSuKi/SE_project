# Spec Delta

## MODIFIED Requirements

### Requirement: 登入失敗鎖定
所有視窗共用一個老師登入失敗計數。連續登入失敗達設定次數（預設 5 次）時，系統 SHALL 暫時鎖定老師登入（預設 300 秒），鎖定期間任何視窗連正確密碼也拒絕，並告知剩餘秒數。達到上限而鎖定時失敗次數 SHALL 歸零；登入成功時失敗次數 SHALL 歸零。

#### Scenario: 達到失敗上限
- **WHEN** 視窗 W1 輸錯密碼 3 次、視窗 W2 輸錯 2 次
- **THEN** 300 秒內任何視窗的登入嘗試（包含正確密碼）都被拒絕，訊息為「密碼錯誤次數過多，請於 300 秒後再試」

#### Scenario: 鎖定解除
- **WHEN** 鎖定時間已過，任一視窗輸入正確密碼
- **THEN** 登入成功，失敗次數歸零

#### Scenario: 次數與秒數可設定
- **WHEN** 以 `BUZZER_LOGIN_MAX_FAILURES=2`、`BUZZER_LOGIN_LOCK_SECONDS=30` 啟動並連續輸錯 2 次
- **THEN** 之後的登入被拒絕，剩餘秒數為 30

### Requirement: Token 有效期限
老師 Token SHALL 在設定的時間後失效（預設 8 小時），且伺服器重啟後所有 Token SHALL 失效。持失效 Token 的請求 SHALL 被視為未登入。

#### Scenario: 伺服器重啟後
- **WHEN** 伺服器重啟後，老師視窗以舊 Token 呼叫老師功能
- **THEN** 系統回應「登入已失效，請重新登入」，畫面回到登入頁

### Requirement: 老師專屬操作
匯入學習單、確認或取消匯入、查看學習單、建立活動、切換活動階段、判定無效、重新產生組別代碼、寫回答案與匯出 CSV SHALL 只允許持有效老師 Token 的請求。其他請求 MUST 被拒絕並回應「無權限執行此操作」，且 MUST NOT 產生任何副作用。

#### Scenario: 未登入者呼叫老師功能
- **WHEN** 沒有 Token 的請求呼叫學習單匯入、寫回或 CSV 匯出
- **THEN** 系統回應「無權限執行此操作」，不建立、不修改、不回傳任何資料

#### Scenario: 非老師身分呼叫老師功能
- **WHEN** 持非老師 Token（例如學生 Token）的請求呼叫任何老師專屬操作
- **THEN** 系統回應「無權限執行此操作」，不產生任何副作用
