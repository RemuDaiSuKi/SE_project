// 學生頁：Token、活動 ID、視窗 ID 都存在本視窗的 sessionStorage，每個視窗是獨立的身分。
// 畫面上的資料全部來自伺服器依本組身分過濾後的內容。
import * as api from "./api.js";

const $ = (id) => document.getElementById(id);
const KEY_WINDOW = "buzzer.studentWindowId";
const KEY_ACTIVITY = "buzzer.activityId";
const ROLE = "group";
const PHASE = { preparing: "準備中（等待老師開始）", running: "搶答中", ended: "已結束", interrupted: "已中斷" };
const OUTCOME = { success: "搶答成功！", invalid: "已被老師判定無效" };

let socket = null;
let view = null;
let countdown = null;

function store(key, value) {
  try {
    if (value === null) sessionStorage.removeItem(key);
    else sessionStorage.setItem(key, value);
  } catch {
    /* sessionStorage 無法使用 */
  }
}

function load(key) {
  try {
    return sessionStorage.getItem(key);
  } catch {
    return null;
  }
}

function windowId() {
  let id = load(KEY_WINDOW);
  if (!id) {
    id = crypto.randomUUID ? crypto.randomUUID() : `${Date.now()}-${Math.random().toString(36).slice(2)}`;
    store(KEY_WINDOW, id);
  }
  return id;
}

function show(element, visible) {
  element.classList.toggle("hidden", !visible);
}

function showMessage(text, kind = "ok") {
  const box = $("message");
  box.className = `message ${kind}`;
  box.textContent = text;
}

function hideMessage() {
  show($("message"), false);
}

function leave(message) {
  api.clearSession();
  if (socket) {
    socket.onclose = null;
    socket.close();
    socket = null;
  }
  view = null;
  show($("group-view"), false);
  show($("team-name"), false);
  show($("join-view"), true);
  showMessage(message, "error");
}

function renderCooldown() {
  const seconds = view ? view.cooldownRemaining : 0;
  show($("cooldown"), seconds > 0);
  $("cooldown").textContent = `本組領先其他組別，冷卻中：${seconds} 秒後才能再送出。`;
}

function tickCooldown() {
  clearInterval(countdown);
  countdown = null;
  if (!view || !view.cooldownRemaining) return;
  countdown = setInterval(() => {
    view.cooldownRemaining = Math.max(0, view.cooldownRemaining - 1);
    renderCooldown();
    if (!view.cooldownRemaining) {
      clearInterval(countdown);
      countdown = null;
      refresh();
    }
  }, 1000);
}

function statusText(mine) {
  if (mine.outcome === "lost") return `未搶到，第 ${mine.rank} 順位`;
  return OUTCOME[mine.outcome];
}

function renderUnits(v) {
  const mine = Object.fromEntries(v.mySubmissions.map((s) => [s.unitKey, s]));
  const forms = v.units.map((u) => {
    const form = document.createElement("form");
    form.className = "unit";
    const title = document.createElement("h3");
    title.textContent = u.display;
    form.appendChild(title);
    const done = mine[u.key];
    for (const no of u.questionNos) {
      const label = document.createElement("label");
      label.textContent = `第 ${no} 題`;
      const input = document.createElement("input");
      input.type = "text";
      input.name = `q${no}`;
      input.autocomplete = "off";
      input.disabled = Boolean(done) || v.phase !== "running";
      if (done) input.value = done.answers[String(no)] ?? "";
      label.appendChild(input);
      form.appendChild(label);
    }
    const row = document.createElement("div");
    row.className = "row";
    if (done) {
      const status = document.createElement("span");
      status.className = done.outcome === "success" ? "status-ok" : "status-warn";
      status.textContent = statusText(done);
      row.appendChild(status);
    } else {
      const button = document.createElement("button");
      button.type = "submit";
      button.className = "primary";
      button.textContent = "送出";
      button.disabled = v.phase !== "running";
      row.appendChild(button);
    }
    form.appendChild(row);
    form.addEventListener("submit", (event) => {
      event.preventDefault();
      send(u, form);
    });
    return form;
  });
  $("units").replaceChildren(...forms);
}

function renderResults(results) {
  show($("results"), Boolean(results));
  if (!results) return;
  const rows = results.units.map((u) => {
    const tr = document.createElement("tr");
    const answers = u.winner
      ? Object.entries(u.winner.answers).map(([no, a]) => `第 ${no} 題：${a}`).join("；")
      : "—";
    for (const text of [u.display, u.winner ? u.winner.teamName : "無人搶答", answers]) {
      const td = document.createElement("td");
      td.className = "wrap";
      td.textContent = text;
      tr.appendChild(td);
    }
    return tr;
  });
  $("result-rows").replaceChildren(...rows);
  $("team-wins").replaceChildren(...results.teams.map((t) => {
    const li = document.createElement("li");
    li.textContent = `${t.name}：${t.wins} 題`;
    return li;
  }));
}

function render(v) {
  // 正在輸入的答案在重新繪製後保留
  const typed = {};
  for (const input of $("units").querySelectorAll("input")) {
    if (!input.disabled && input.value) typed[input.name] = input.value;
  }
  view = v;
  show($("join-view"), false);
  show($("group-view"), true);
  $("team-name").textContent = v.team.name;
  show($("team-name"), true);
  $("phase").textContent = PHASE[v.phase] ?? v.phase;
  renderCooldown();
  tickCooldown();
  renderUnits(v);
  for (const [name, value] of Object.entries(typed)) {
    const input = $("units").querySelector(`input[name="${name}"]`);
    if (input && !input.disabled) input.value = value;
  }
  renderResults(v.results);
}

async function send(unit, form) {
  const answers = {};
  for (const no of unit.questionNos) answers[String(no)] = form.querySelector(`input[name="q${no}"]`).value;
  try {
    const result = await api.request("POST", "/api/submissions", { json: { unitKey: unit.key, answers } });
    showMessage(result.message, result.outcome === "success" ? "ok" : "error");
  } catch (error) {
    if (error.status === 401) return checkInterrupted();
    showMessage(error.message, "error");
  }
  refresh();
}

async function refresh() {
  try {
    render(await api.request("GET", "/api/me"));
  } catch (error) {
    if (error.status === 401 || error.code === "ACTIVITY_INTERRUPTED") return checkInterrupted();
    showMessage(error.message, "error");
  }
}

async function checkInterrupted() {
  const id = load(KEY_ACTIVITY);
  if (id) {
    try {
      const body = await api.request("GET", `/api/activities/${encodeURIComponent(id)}/phase`);
      if (body.phase === "interrupted") return leave("活動已中斷，請老師重新建立。");
    } catch {
      /* 活動不存在時顯示一般訊息 */
    }
  }
  leave("組別身分已失效，請重新輸入組別代碼。");
}

function connect() {
  const scheme = location.protocol === "https:" ? "wss" : "ws";
  socket = new WebSocket(`${scheme}://${location.host}/ws`);
  socket.onopen = () => socket.send(JSON.stringify({ type: "auth", token: api.token() }));
  socket.onmessage = (event) => {
    const msg = JSON.parse(event.data);
    if (msg.type === "snapshot") return render(msg);
    if (msg.type === "sessionRevoked") return leave("老師已重新產生本組代碼，請向老師取得新代碼後重新加入。");
    if (msg.type === "invalidated") showMessage(msg.message, "error");
    if (msg.type === "promoted") showMessage(msg.message, "ok");
    refresh();
  };
  socket.onclose = (event) => {
    socket = null;
    if (event.code === 4401 || event.code === 4403) return checkInterrupted();
    setTimeout(() => {
      if (api.token() && api.role() === ROLE) connect(); // 斷線自動重連，重連後重新收到完整快照
    }, 1000);
  };
}

$("join-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  hideMessage();
  try {
    const body = await api.request("POST", "/api/join", {
      json: { code: $("code").value },
      headers: { "X-Window-Id": windowId() },
    });
    api.setSession(body.token, ROLE);
    store(KEY_ACTIVITY, String(body.activityId));
    $("code").value = "";
    showMessage(`已加入「${body.team.name}」。`);
    await refresh();
    connect();
  } catch (error) {
    showMessage(error.message, "error");
  }
});

if (api.token() && api.role() === ROLE) {
  refresh().then(() => {
    if (api.token() && api.role() === ROLE) connect();
  });
}
