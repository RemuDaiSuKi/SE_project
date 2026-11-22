# Spec Delta

## MODIFIED Requirements

### Requirement: 老師專屬操作
匯入學習單、確認或取消匯入、查看學習單、查看 Google 授權狀態、建立活動、切換活動階段、判定無效、重新產生組別代碼、寫回答案與匯出 CSV SHALL 只允許持有效老師 Token 的請求。其他請求 MUST 被拒絕並回應「無權限執行此操作」，且 MUST NOT 產生任何副作用。

#### Scenario: 未登入者呼叫老師功能
- **WHEN** 沒有 Token 的請求呼叫學習單匯入、寫回或 CSV 匯出
- **THEN** 系統回應「無權限執行此操作」，不建立、不修改、不回傳任何資料

#### Scenario: 非老師身分呼叫老師功能
- **WHEN** 持非老師 Token（例如學生 Token）的請求呼叫任何老師專屬操作
- **THEN** 系統回應「無權限執行此操作」，不產生任何副作用

#### Scenario: 未登入者查看 Google 授權狀態
- **WHEN** 沒有 Token 的請求查詢 Google 授權狀態
- **THEN** 系統回應「無權限執行此操作」，不透露是否已授權或授權帳號
