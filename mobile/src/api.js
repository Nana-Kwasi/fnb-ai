const defaultBase = "http://localhost:8000";

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

export async function careChat(apiKey, baseUrl, body) {
  return request(apiKey, baseUrl, "/api/v1/care/chat", {
    method: "POST",
    body: JSON.stringify(body),
  });
}
