// 每個視窗的身分只存在自己的 sessionStorage；所有 API 以 Authorization 標頭傳遞 Token。

const KEY_WINDOW = "buzzer.windowId";
const KEY_TOKEN = "buzzer.token";
const KEY_ROLE = "buzzer.role";

function storage() {
  try {
    return window.sessionStorage;
  } catch {
    return null;
  }
}

function getItem(key) {
  try {
    return storage()?.getItem(key) ?? null;
  } catch {
    return null;
  }
}

function setItem(key, value) {
  try {
    if (value === null) storage()?.removeItem(key);
    else storage()?.setItem(key, value);
  } catch {
    /* sessionStorage 無法使用時只在記憶體中保存 */
  }
}

export class ApiError extends Error {
  constructor(status, code, message, details = [], extra = {}) {
    super(message);
    this.status = status;
    this.code = code;
    this.details = details;
    this.extra = extra;
  }
}

let memoryToken = null;

export function token() {
  return getItem(KEY_TOKEN) ?? memoryToken;
}

export function role() {
  return getItem(KEY_ROLE);
}

export function setSession(newToken, newRole) {
  memoryToken = newToken;
  setItem(KEY_TOKEN, newToken);
  setItem(KEY_ROLE, newRole);
}

export function clearSession() {
  setSession(null, null);
}

async function parseError(response) {
  let body = null;
  try {
    body = await response.json();
  } catch {
    /* 非 JSON 回應 */
  }
  const error = body?.error ?? {};
  const { code = "ERROR", message = "系統發生錯誤，請稍後再試", details = [], ...extra } = error;
  return new ApiError(response.status, code, message, details, extra);
}

export async function request(method, path, { json, form, raw = false } = {}) {
  const headers = {};
  const current = token();
  if (current) headers.Authorization = `Bearer ${current}`;
  let body;
  if (json !== undefined) {
    headers["Content-Type"] = "application/json";
    body = JSON.stringify(json);
  } else if (form !== undefined) {
    body = form;
  }
  let response;
  try {
    response = await fetch(path, { method, headers, body, credentials: "omit" });
  } catch {
    throw new ApiError(0, "NETWORK", "無法連線到伺服器，請確認伺服器是否啟動");
  }
  if (!response.ok) {
    const error = await parseError(response);
    if (error.code === "SESSION_EXPIRED") {
      clearSession();
      window.dispatchEvent(new CustomEvent("buzzer:session-expired", { detail: error }));
    }
    throw error;
  }
  if (raw) return response;
  if (response.status === 204) return null;
  return response.json();
}

export async function windowId({ renew = false } = {}) {
  let id = renew ? null : getItem(KEY_WINDOW);
  if (!id) {
    const data = await request("POST", "/api/windows");
    id = data.windowId;
    setItem(KEY_WINDOW, id);
  }
  return id;
}

export async function loginTeacher(password) {
  const attempt = async (renew) =>
    request("POST", "/api/teacher/login", {
      json: { windowId: await windowId({ renew }), password },
    });
  let data;
  try {
    data = await attempt(false);
  } catch (error) {
    if (error.code !== "WINDOW_UNKNOWN") throw error;
    data = await attempt(true); // 伺服器重啟後視窗識別失效：重新註冊一次
  }
  setSession(data.token, data.role);
  return data;
}

export async function logout() {
  try {
    await request("POST", "/api/teacher/logout");
  } finally {
    clearSession();
  }
}

export function filenameFrom(response, fallback) {
  const header = response.headers.get("Content-Disposition") || "";
  const match = header.match(/filename\*=UTF-8''([^;]+)/i);
  if (match) {
    try {
      return decodeURIComponent(match[1]);
    } catch {
      /* 使用預設檔名 */
    }
  }
  return fallback;
}

export async function saveResponse(response, fallbackName) {
  const blob = await response.blob();
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = filenameFrom(response, fallbackName);
  document.body.appendChild(link);
  link.click();
  link.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}
