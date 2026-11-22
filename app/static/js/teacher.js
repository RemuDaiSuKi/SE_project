import * as api from "./api.js";

const $ = (id) => document.getElementById(id);

let currentPreview = null;

function show(element, visible) {
  element.classList.toggle("hidden", !visible);
}

function cell(text) {
  const td = document.createElement("td");
  td.textContent = text ?? "";
  return td;
}

function showMessage(box, kind, message, details = []) {
  box.className = `message ${kind}`;
  box.replaceChildren(document.createTextNode(message));
  if (details.length) {
    const list = document.createElement("ul");
    for (const detail of details) {
      const item = document.createElement("li");
      item.textContent = detail.message;
      list.appendChild(item);
    }
    box.appendChild(list);
  }
}

function linkCell(text, href) {
  const td = document.createElement("td");
  const link = document.createElement("a");
  link.href = href;
  link.target = "_blank";
  link.rel = "noopener noreferrer";
  link.textContent = text;
  td.appendChild(link);
  return td;
}

async function refreshGoogleStatus() {
  const text = $("google-status");
  try {
    const status = await api.request("GET", "/api/google/status");
    $("google-command").textContent = status.loginCommand;
    text.replaceChildren();
    const strong = document.createElement("span");
    if (status.authorized) {
      strong.className = "status-ok";
      strong.textContent = `已授權 Google 帳號：${status.account ?? "（無法取得帳號 email）"}`;
    } else if (!status.configured) {
      strong.className = "status-warn";
      strong.textContent = "尚未設定 Google OAuth 用戶端，請依 README 建立用戶端設定檔後執行登入指令。";
    } else {
      strong.className = "status-warn";
      strong.textContent = "尚未完成 Google 授權";
    }
    text.appendChild(strong);
    show($("google-help"), !status.authorized);
  } catch (error) {
    text.textContent = error.message;
  }
}

function showLogin() {
  show($("login-view"), true);
  show($("dashboard"), false);
  show($("logout"), false);
  $("password").value = "";
  $("password").focus();
}

async function showDashboard() {
  show($("login-view"), false);
  show($("dashboard"), true);
  show($("logout"), true);
  await Promise.all([refreshGoogleStatus(), refreshWorksheets()]);
}

function groupText(question) {
  return question.groupNo ? `題組 ${question.groupNo}` : "—";
}

function renderPreview(preview) {
  currentPreview = preview;
  $("preview-filename").textContent = preview.spreadsheetTitle;
  $("preview-count").textContent = `共 ${preview.questionCount} 題`;
  $("preview-groups").textContent = `${preview.groupCount} 個題組`;
  const rows = preview.questions.map((q) => {
    const tr = document.createElement("tr");
    tr.append(cell(`第 ${q.no} 題`), cell(q.sourceNo), cell(q.subLabel ?? "—"),
      cell(q.location), cell(groupText(q)));
    return tr;
  });
  $("preview-rows").replaceChildren(...rows);
  show($("preview"), true);
  $("confirm").focus();
}

function clearPreview() {
  currentPreview = null;
  show($("preview"), false);
  $("preview-rows").replaceChildren();
}

async function refreshWorksheets() {
  const data = await api.request("GET", "/api/worksheets");
  const rows = data.worksheets.map((ws) => {
    const tr = document.createElement("tr");
    const confirmed = new Date(ws.confirmedAt).toLocaleString("zh-TW");
    tr.append(cell(ws.id), linkCell(ws.title, ws.spreadsheetUrl), cell(ws.questionCount),
      cell(ws.groupCount), cell(confirmed));
    return tr;
  });
  $("worksheets-rows").replaceChildren(...rows);
  show($("worksheets-table"), rows.length > 0);
  show($("worksheets-empty"), rows.length === 0);
}

$("login-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const box = $("login-message");
  show(box, false);
  try {
    await api.loginTeacher($("password").value);
    await showDashboard();
  } catch (error) {
    showMessage(box, "error", error.message);
  }
});

$("logout").addEventListener("click", async () => {
  try {
    await api.logout();
  } catch {
    /* 已失效也直接回到登入頁 */
  }
  clearPreview();
  showLogin();
});

$("upload-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const box = $("upload-message");
  show(box, false);
  clearPreview();
  const url = $("sheet-url").value.trim();
  if (!url) {
    showMessage(box, "error", "請輸入有效的 Google 試算表網址");
    return;
  }
  $("upload-button").disabled = true;
  try {
    renderPreview(await api.request("POST", "/api/worksheets/previews", { json: { url } }));
  } catch (error) {
    showMessage(box, "error", error.message, error.details);
  } finally {
    $("upload-button").disabled = false;
  }
});

$("confirm").addEventListener("click", async () => {
  if (!currentPreview) return;
  const box = $("upload-message");
  try {
    const ws = await api.request("POST",
      `/api/worksheets/previews/${encodeURIComponent(currentPreview.previewId)}/confirm`);
    showMessage(box, "ok", `已匯入「${ws.title}」，共 ${ws.questionCount} 題。`);
    clearPreview();
    $("upload-form").reset();
    await refreshWorksheets();
  } catch (error) {
    showMessage(box, "error", error.message, error.details);
    clearPreview();
  }
});

$("cancel").addEventListener("click", async () => {
  if (!currentPreview) return;
  const id = currentPreview.previewId;
  clearPreview();
  $("upload-form").reset();
  show($("upload-message"), false);
  try {
    await api.request("DELETE", `/api/worksheets/previews/${encodeURIComponent(id)}`);
  } catch {
    /* 預覽已失效時不需要額外處理 */
  }
  $("sheet-url").focus();
});

$("google-refresh").addEventListener("click", refreshGoogleStatus);

window.addEventListener("buzzer:session-expired", (event) => {
  clearPreview();
  showLogin();
  showMessage($("login-message"), "error", event.detail.message);
});

async function start() {
  if (api.token() && api.role() === "teacher") {
    try {
      await api.request("GET", "/api/teacher/me");
      await showDashboard();
      return;
    } catch {
      /* Token 失效時回到登入頁 */
    }
  }
  showLogin();
}

start();
