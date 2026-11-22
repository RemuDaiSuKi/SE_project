# teacher-auth Specification

## Purpose

讓老師以密碼取得只屬於單一瀏覽器視窗的身分，並確保只有老師能執行管理類操作，學生與未登入者一律被拒絕。

## Requirements

### Requirement: 老師密碼來源
系統 SHALL 只從環境變數取得老師密碼，程式碼、設定檔範本與測試資料中 MUST NOT 含有真實密碼。登入時系統 SHALL 以固定時間比對方式比對密碼。

#### Scenario: 密碼正確
- **WHEN** 老師在登入畫面輸入與環境變數相同的密碼
- **THEN** 系統核發一個老師 Token，該視窗進入老師畫面

#### Scenario: 密碼錯誤
- **WHEN** 老師輸入錯誤的密碼
- **THEN** 系統拒絕登入並顯示「密碼錯誤」，不核發 Token，並把該視窗的連續失敗次數加 1

### Requirement: 視窗獨立身分
每個瀏覽器視窗 SHALL 持有自己的視窗識別與身分 Token，身分資料 MUST 只存在該視窗的 sessionStorage，系統 MUST NOT 以 Cookie 傳遞身分。同一瀏覽器的不同視窗 SHALL 可以分別是老師或其他身分而互不覆蓋。

#### Scenario: 同一瀏覽器兩個視窗
- **WHEN** 視窗 1 以老師登入，同一瀏覽器的視窗 2 沒有登入
- **THEN** 視窗 2 仍是未登入狀態，呼叫老師功能被拒絕；視窗 1 不受影響

#### Scenario: 重新整理視窗
- **WHEN** 已登入的老師視窗重新整理頁面
- **THEN** 該視窗仍保有老師身分，不需重新登入

#### Scenario: 登出
- **WHEN** 老師在某視窗按「登出」
- **THEN** 該視窗的 Token 立即失效並從 sessionStorage 清除，其他老師視窗的登入不受影響

### Requirement: 登入失敗鎖定
同一視窗連續登入失敗達設定次數（預設 5 次）時，系統 SHALL 暫時鎖定該視窗的登入（預設 60 秒），鎖定期間連正確密碼也拒絕並告知剩餘秒數。鎖定 MUST 以視窗為單位，MUST NOT 影響其他視窗。登入成功時失敗次數 SHALL 歸零。

#### Scenario: 達到失敗上限
- **WHEN** 視窗 W1 連續輸錯密碼 5 次
- **THEN** W1 在 60 秒內的任何登入嘗試（包含正確密碼）都被拒絕，訊息顯示剩餘秒數

#### Scenario: 其他視窗不受影響
- **WHEN** W1 處於鎖定中，同一台電腦的 W2 輸入正確密碼
- **THEN** W2 登入成功

#### Scenario: 鎖定解除
- **WHEN** W1 的鎖定時間已過，並輸入正確密碼
- **THEN** W1 登入成功，失敗次數歸零

### Requirement: Token 有效期限
老師 Token SHALL 在設定的時間後失效（預設 12 小時），且伺服器重啟後所有 Token SHALL 失效。持失效 Token 的請求 SHALL 被視為未登入。

#### Scenario: 伺服器重啟後
- **WHEN** 伺服器重啟後，老師視窗以舊 Token 呼叫老師功能
- **THEN** 系統回應「登入已失效，請重新登入」，畫面回到登入頁

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
