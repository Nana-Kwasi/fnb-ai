const defaultBase = "http://localhost:8000";
const defaultCore = "http://localhost:8001";
const defaultGateway = "http://localhost:8002";

export async function request(apiKey, baseUrl, path, options = {}) {
  const url = `${(baseUrl || defaultBase).replace(/\/$/, "")}${path}`;
  const headers = {
    "Content-Type": "application/json",
    ...(apiKey ? { "X-API-Key": apiKey } : {}),
    ...options.headers,
  };
  const res = await fetch(url, { ...options, headers });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) {
    const d = data.detail;
    const msg = Array.isArray(d) ? (d[0]?.msg || d[0]) : d;
    throw new Error(msg || data.message || res.statusText);
  }
  return data;
}

export async function fraudScore(apiKey, baseUrl, body) {
  return request(apiKey, baseUrl, "/api/v1/fraud/score", {
    method: "POST",
    body: JSON.stringify(body),
  });
}

export async function listTransactions(apiKey, baseUrl, { account_id, limit = 50 } = {}) {
  const params = new URLSearchParams();
  if (account_id) params.set("account_id", account_id);
  if (limit) params.set("limit", String(limit));
  const qs = params.toString() ? `?${params.toString()}` : "";
  return request(apiKey, baseUrl, `/api/v1/fraud/transactions${qs}`);
}

export async function careChat(apiKey, baseUrl, body, { careToken } = {}) {
  return request(apiKey, baseUrl, "/api/v1/care/chat", {
    method: "POST",
    headers: careToken ? { Authorization: `Bearer ${careToken}` } : {},
    body: JSON.stringify(body),
  });
}

export function makeBasicAuth(username, password) {
  const s = `${username}:${password}`;
  if (typeof Buffer !== "undefined") return `Basic ${Buffer.from(s, "utf8").toString("base64")}`;
  if (typeof btoa !== "undefined") return `Basic ${btoa(unescape(encodeURIComponent(s)))}`;
  const chars = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/";
  let out = "";
  for (let i = 0; i < s.length; i += 3) {
    const a = s.charCodeAt(i);
    const b = i + 1 < s.length ? s.charCodeAt(i + 1) : 0;
    const c = i + 2 < s.length ? s.charCodeAt(i + 2) : 0;
    out += chars[a >> 2] + chars[((a & 3) << 4) | (b >> 4)] + (i + 1 < s.length ? chars[((b & 15) << 2) | (c >> 6)] : "=") + (i + 2 < s.length ? chars[c & 63] : "=");
  }
  return `Basic ${out}`;
}

function coreBase() {
  return defaultCore;
}

function gwBase() {
  return defaultGateway;
}

export async function coreRequest(authHeader, path, options = {}) {
  const url = `${coreBase().replace(/\/$/, "")}${path}`;
  const headers = {
    "Content-Type": "application/json",
    ...(authHeader ? { Authorization: authHeader } : {}),
    ...options.headers,
  };
  const res = await fetch(url, { ...options, headers });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) {
    const d = data.detail;
    const msg = Array.isArray(d) ? (d[0]?.msg || d[0]) : d;
    throw new Error(msg || data.message || res.statusText);
  }
  return data;
}

export async function gwRequest(path, options = {}) {
  const url = `${gwBase().replace(/\/$/, "")}${path}`;
  const headers = { "Content-Type": "application/json", ...options.headers };
  const res = await fetch(url, { ...options, headers });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) {
    const d = data.detail;
    const msg = Array.isArray(d) ? (d[0]?.msg || d[0]) : d;
    throw new Error(msg || data.message || res.statusText);
  }
  return data;
}

export async function registerUser(body) {
  return coreRequest(null, "/api/auth/register", {
    method: "POST",
    body: JSON.stringify(body),
  });
}

export async function loginUser(authHeader) {
  return coreRequest(authHeader, "/api/auth/login", { method: "POST" });
}

export async function getMyAccounts(authHeader) {
  const data = await coreRequest(authHeader, "/api/me/accounts");
  return data.accounts || [];
}

export async function deposit(authHeader, { account_id, amount, currency = "USD" }) {
  return coreRequest(authHeader, "/api/deposit", {
    method: "POST",
    body: JSON.stringify({ account_id, amount, currency }),
  });
}

export async function updateLimit(authHeader, { account_id, daily_transfer_limit }) {
  return coreRequest(authHeader, "/api/account-settings/limits", {
    method: "PATCH",
    body: JSON.stringify({ account_id, daily_transfer_limit: daily_transfer_limit ?? null }),
  });
}

export async function payViaGateway(body) {
  return gwRequest("/api/pay", {
    method: "POST",
    body: JSON.stringify(body),
  });
}

export async function transferViaGateway(body) {
  return gwRequest("/api/transfers", {
    method: "POST",
    body: JSON.stringify(body),
  });
}

export async function getBalance(accountId) {
  return gwRequest(`/api/balance?account_id=${encodeURIComponent(accountId)}`);
}

export async function getTransactions(accountId, limit = 50) {
  const data = await gwRequest(`/api/transactions?account_id=${encodeURIComponent(accountId)}&limit=${limit}`);
  return data.transactions || [];
}
