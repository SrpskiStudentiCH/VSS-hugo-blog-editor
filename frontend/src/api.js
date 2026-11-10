// API client wrapper: attaches the admin session token and normalizes errors.
const API_URL = process.env.REACT_APP_API_URL || "";

let token = localStorage.getItem("admin_token") || "";

export function setToken(t) {
  token = t || "";
  if (t) localStorage.setItem("admin_token", t);
  else localStorage.removeItem("admin_token");
}

export function getToken() {
  return token;
}

// Absolute URL for assets/endpoints (safe for <img src> which cannot send headers).
export function apiUrl(path) {
  return `${API_URL}${path}`;
}

// URL of a repo image served through the authenticated backend proxy.
export function imageUrl(repoPath) {
  return apiUrl(`/api/image?path=${encodeURIComponent(repoPath)}`);
}

export async function api(path, options = {}) {
  const headers = { ...(options.headers || {}) };
  if (token) headers["X-Admin-Token"] = token;
  let body;
  if (options.json !== undefined) {
    headers["Content-Type"] = "application/json";
    body = JSON.stringify(options.json);
  }
  const res = await fetch(`${API_URL}${path}`, {
    method: options.method || "GET",
    headers,
    body,
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) {
    const err = new Error(data.error || `HTTP ${res.status}`);
    err.status = res.status;
    err.conflict = !!data.conflict;
    err.details = data;
    throw err;
  }
  return data;
}

export async function login(username, password) {
  return api("/login", { method: "POST", json: { username, password } });
}

// Convert a File to a raw base64 string (no data: prefix).
export function fileToBase64(file) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(String(reader.result).split(",")[1] || "");
    reader.onerror = () => reject(new Error("Ne mogu da pročitam fajl."));
    reader.readAsDataURL(file);
  });
}

// Notify the app shell that the pending changes count may have changed.
export function notifyPendingChanged() {
  window.dispatchEvent(new CustomEvent("pending-changed"));
}

export function onPendingChanged(callback) {
  const handler = () => callback();
  window.addEventListener("pending-changed", handler);
  return () => window.removeEventListener("pending-changed", handler);
}
