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
  await refreshWorksheets();
  await refreshActivities();
  connectSocket();
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
  const options = data.worksheets.map((ws) => {
    const option = document.createElement("option");
    option.value = ws.id;
    option.textContent = `${ws.id}：${ws.title}（${ws.questionCount} 題）`;
    return option;
  });
  const select = $("create-worksheet");
  const previous = select.value;
  select.replaceChildren(...options.reverse());
  if (previous && [...select.options].some((o) => o.value === previous)) select.value = previous;
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
  closeSocket();
  hideActivity();
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
    /* 預覽已確認或已取消時不需要額外處理 */
  }
  $("sheet-url").focus();
});

window.addEventListener("buzzer:session-expired", (event) => {
  closeSocket();
  hideActivity();
  clearPreview();
  showLogin();
  showMessage($("login-message"), "error", event.detail.message);
});

// ---------- 搶答活動 ----------

const PHASE = { preparing: "準備中", running: "搶答中", ended: "已結束", interrupted: "已中斷" };
const STATUS = { no_submission: "尚無人搶答", won: "已搶答", open: "重新開放", no_winner: "無人搶答" };
const OUTCOME = { success: "成功", lost: "未搶到", invalid: "無效" };

let activity = null;      // 目前顯示的活動（老師監看畫面）
let socket = null;
let countdown = null;

function button(text, onClick, primary = false) {
  const b = document.createElement("button");
  b.type = "button";
  b.textContent = text;
  if (primary) b.className = "primary";
  b.addEventListener("click", onClick);
  return b;
}

function activityMessage(kind, message, details = []) {
  showMessage($("activity-message"), kind, message, details);
}

function hideActivity() {
  activity = null;
  clearInterval(countdown);
  show($("activity"), false);
}

function renderActivity(a) {
  activity = a;
  show($("activity"), true);
  $("activity-id").textContent = a.id;
  $("activity-phase").textContent = PHASE[a.phase] ?? a.phase;
  $("activity-fairness").textContent = a.fairness.enabled
    ? `冷卻：領先 ${a.fairness.cooldownLead} 題冷卻 ${a.fairness.cooldownSeconds} 秒`
    : "冷卻：停用";
  $("start").disabled = a.phase !== "preparing";
  $("end").disabled = a.phase !== "running";
  show($("writeback"), a.phase === "ended");
  show($("download-csv"), a.phase === "ended");

  const live = a.phase === "preparing" || a.phase === "running";
  $("team-rows").replaceChildren(...a.teams.map((t) => {
    const tr = document.createElement("tr");
    const code = cell(t.code ?? "—");
    code.className = "code";
    const action = document.createElement("td");
    if (live) action.appendChild(button("重新產生代碼", () => regenerate(t)));
    tr.append(cell(t.name), code, cell(t.wins),
      cell(t.cooldownRemaining ? `冷卻中 ${t.cooldownRemaining} 秒` : "—"), action);
    return tr;
  }));

  const canInvalidate = a.phase === "running" || a.phase === "ended";
  $("unit-rows").replaceChildren(...a.units.map((u) => {
    const tr = document.createElement("tr");
    const subs = document.createElement("td");
    subs.className = "wrap";
    if (!u.submissions.length) subs.textContent = "—";
    for (const s of u.submissions) {
      const line = document.createElement("div");
      const answers = Object.entries(s.answers).map(([no, text]) => `第 ${no} 題：${text}`).join("；");
      line.textContent = `第 ${s.rank} 順位　${s.teamName}　${answers}　（${OUTCOME[s.outcome] ?? s.outcome}）`;
      if (s.outcome === "success") line.className = "status-ok";
      else if (s.outcome === "invalid") line.className = "muted";
      subs.appendChild(line);
    }
    const action = document.createElement("td");
    if (canInvalidate && u.status === "won") action.appendChild(button("判定無效", () => invalidate(u)));
    const title = cell(u.display);
    title.className = "wrap";
    tr.append(title, cell(STATUS[u.status] ?? u.status), subs, action);
    return tr;
  }));

  clearInterval(countdown);
  if (a.teams.some((t) => t.cooldownRemaining > 0)) {
    countdown = setInterval(() => {
      if (!activity) return;
      for (const t of activity.teams) t.cooldownRemaining = Math.max(0, t.cooldownRemaining - 1);
      renderActivity(activity);
    }, 1000);
  }
}

async function loadActivity(id) {
  try {
    renderActivity(await api.request("GET", `/api/activities/${encodeURIComponent(id)}`));
  } catch (error) {
    hideActivity();
    showMessage($("create-message"), "error", error.message);
  }
}

async function refreshActivities() {
  const data = await api.request("GET", "/api/activities");
  const rows = data.activities.map((a) => {
    const tr = document.createElement("tr");
    const action = document.createElement("td");
    if (a.phase !== "interrupted") action.appendChild(button("檢視", () => loadActivity(a.id)));
    tr.append(cell(a.id), cell(a.worksheetId), cell(PHASE[a.phase] ?? a.phase),
      cell(new Date(a.createdAt).toLocaleString("zh-TW")),
      cell(a.endedAt ? new Date(a.endedAt).toLocaleString("zh-TW") : "—"), action);
    return tr;
  });
  $("activities-rows").replaceChildren(...rows);
  show($("activities-table"), rows.length > 0);
  show($("activities-empty"), rows.length === 0);
}

async function regenerate(team) {
  if (!activity) return;
  try {
    const data = await api.request("POST",
      `/api/activities/${activity.id}/teams/${team.id}/regenerate-code`);
    activityMessage("ok", `「${team.name}」的新代碼：${data.code}。用舊代碼加入的視窗已被登出。`);
  } catch (error) {
    activityMessage("error", error.message);
  }
  await loadActivity(activity.id);
}

async function invalidate(unit) {
  if (!activity) return;
  try {
    const result = await api.request("POST",
      `/api/activities/${activity.id}/units/${encodeURIComponent(unit.key)}/invalidate`);
    const next = result.promotedTeamId
      ? `由 ${activity.teams.find((t) => t.id === result.promotedTeamId)?.name ?? "下一順位"} 遞補`
      : "沒有可遞補的組別";
    activityMessage("ok", `${unit.display}已判定無效，${next}。`);
  } catch (error) {
    activityMessage("error", error.message);
  }
  await loadActivity(activity.id);
}

$("create-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const box = $("create-message");
  show(box, false);
  const teams = $("create-teams").value.split("\n").filter((line) => line.trim() !== "");
  const body = { worksheetId: Number($("create-worksheet").value), teams,
    fairnessEnabled: $("create-fairness").checked };
  const lead = $("create-lead").value.trim();
  const seconds = $("create-seconds").value.trim();
  if (lead) body.cooldownLead = Number(lead);
  if (seconds) body.cooldownSeconds = Number(seconds);
  if (!body.worksheetId) {
    showMessage(box, "error", "請先匯入並確認一份學習單");
    return;
  }
  $("create-button").disabled = true;
  try {
    renderActivity(await api.request("POST", "/api/activities", { json: body }));
    showMessage(box, "ok", "已建立活動。請把各組的代碼私下發給各組。");
    await refreshActivities();
  } catch (error) {
    showMessage(box, "error", error.message, error.details);
  } finally {
    $("create-button").disabled = false;
  }
});

async function changePhase(action) {
  if (!activity) return;
  show($("activity-message"), false);
  try {
    await api.request("POST", `/api/activities/${activity.id}/${action}`);
  } catch (error) {
    activityMessage("error", error.message);
  }
  await loadActivity(activity.id);
  await refreshActivities();
}

$("start").addEventListener("click", () => changePhase("start"));
$("end").addEventListener("click", () => changePhase("end"));

$("writeback").addEventListener("click", async () => {
  if (!activity) return;
  $("writeback").disabled = true;
  try {
    const data = await api.request("POST", `/api/activities/${activity.id}/writeback`);
    activityMessage("ok", data.message);
  } catch (error) {
    activityMessage("error", error.message, error.details);
  } finally {
    $("writeback").disabled = false;
  }
});

$("download-csv").addEventListener("click", async () => {
  if (!activity) return;
  try {
    const response = await api.request("GET", `/api/activities/${activity.id}/results.csv`, { raw: true });
    const count = Number(response.headers.get("X-Record-Count") ?? "0");
    await api.saveResponse(response, `activity-${activity.id}-results.csv`);
    // 沒有紀錄時仍下載只含標題列的 CSV，並在畫面提示（result-csv-export 規格）
    if (count === 0) activityMessage("ok", "此活動沒有任何送出紀錄");
    else activityMessage("ok", `已匯出 ${count} 筆紀錄。`);
  } catch (error) {
    activityMessage("error", error.message);
  }
});

function closeSocket() {
  if (socket) {
    socket.onclose = null;
    socket.close();
    socket = null;
  }
}

function connectSocket() {
  closeSocket();
  const scheme = location.protocol === "https:" ? "wss" : "ws";
  const ws = new WebSocket(`${scheme}://${location.host}/ws`);
  socket = ws;
  ws.onopen = () => ws.send(JSON.stringify({ type: "auth", token: api.token() }));
  ws.onmessage = (event) => {
    const msg = JSON.parse(event.data);
    if (msg.type === "snapshot") {
      if (msg.activity && (!activity || activity.id === msg.activity.id)) renderActivity(msg.activity);
      return;
    }
    if (activity) loadActivity(activity.id);
    if (msg.type === "phaseChanged") refreshActivities();
  };
  ws.onclose = (event) => {
    if (socket !== ws) return;
    socket = null;
    if (event.code === 4401) return; // 登入失效：下一次 API 呼叫會回到登入頁
    setTimeout(() => {
      if (!socket && api.token() && api.role() === "teacher") connectSocket();
    }, 1000);
  };
}

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
