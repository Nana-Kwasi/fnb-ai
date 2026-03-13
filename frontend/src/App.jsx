import { useState } from "react";

const layers = [
  { id: "banks", label: "BANK CLIENTS", color: "#0f4c75", accent: "#1b6ca8", nodes: [{ id: "bankA", label: "Bank A", sub: "React Dashboard + API Key" }, { id: "bankB", label: "Bank B", sub: "React Dashboard + API Key" }, { id: "bankC", label: "Bank C", sub: "React Dashboard + API Key" }] },
  { id: "gateway", label: "API GATEWAY", color: "#1b4332", accent: "#2d6a4f", nodes: [{ id: "auth", label: "JWT Auth", sub: "API Key validation" }, { id: "rate", label: "Rate Limiting", sub: "Per-tenant throttle" }, { id: "router", label: "Route Resolver", sub: "Tenant resolution" }] },
  { id: "engines", label: "AI ENGINES", color: "#3d0066", accent: "#6a0dad", nodes: [{ id: "fraud", label: "Fraud Engine", sub: "LightGBM + Isolation Forest + SHAP", details: ["Receive transaction payload", "Pull velocity features from PostgreSQL", "Engineer feature vector", "LightGBM scores (0.0–1.0)", "Isolation Forest anomaly check", "SHAP explanation generated", "APPROVE / REVIEW / DECLINE", "Alert published if flagged"] }, { id: "care", label: "Customer Care Agent", sub: "DistilBERT → Phi-3 Mini → RAG", details: ["Receive customer message", "DistilBERT classifies intent", "Fetch customer context from DB", "RAG retrieves policy docs", "Phi-3 Mini generates response", "Apply tenant branding/tone", "Escalation check (sentiment)", "Return response + actions"] }] },
  { id: "data", label: "DATA LAYER — PostgreSQL", color: "#4a1942", accent: "#c9184a", nodes: [{ id: "transactions", label: "transactions", sub: "Partitioned by tenant" }, { id: "fraud_scores", label: "fraud_scores", sub: "All decisions + SHAP" }, { id: "customers", label: "customers", sub: "Profiles per bank" }, { id: "chat", label: "chat_sessions", sub: "Full conversation logs" }, { id: "knowledge", label: "knowledge_base", sub: "pgvector embeddings" }, { id: "audit", label: "audit_logs", sub: "Immutable compliance trail" }] },
];

const flowSteps = [
  { id: "fraud", label: "Fraud Detection Flow", color: "#6a0dad", steps: [{ num: "01", title: "Bank sends transaction", desc: "POST /api/v1/fraud/score with X-API-Key header" }, { num: "02", title: "Auth & Tenant Resolution", desc: "JWT validated, bank identified, model config loaded" }, { num: "03", title: "Feature Engineering", desc: "Velocity, deviation, device history pulled from PostgreSQL" }, { num: "04", title: "LightGBM Scoring", desc: "Fraud probability 0.0–1.0 computed in <50ms" }, { num: "05", title: "Anomaly Check", desc: "Isolation Forest catches unknown fraud patterns" }, { num: "06", title: "SHAP Explanation", desc: "Top 5 reason codes generated for compliance" }, { num: "07", title: "Decision Made", desc: "APPROVE / REVIEW / DECLINE + audit log written" }, { num: "08", title: "Response Returned", desc: "Score, decision, reasons, processing time in JSON" }] },
  { id: "care", label: "Customer Care Flow", color: "#c9184a", steps: [{ num: "01", title: "Customer sends message", desc: "POST /api/v1/care/chat with session & customer ID" }, { num: "02", title: "Intent Classification", desc: "DistilBERT routes: FRAUD_INQUIRY, DISPUTE, SUPPORT..." }, { num: "03", title: "Context Retrieval", desc: "Customer profile, recent transactions, fraud flags fetched" }, { num: "04", title: "RAG Knowledge Lookup", desc: "Bank policy docs retrieved via pgvector similarity search" }, { num: "05", title: "LLM Generation", desc: "Phi-3 Mini generates grounded, tenant-branded response" }, { num: "06", title: "Sentiment Analysis", desc: "Frustration or complexity triggers escalation flag" }, { num: "07", title: "Escalation Check", desc: "Route to human agent if needed, else finalize response" }, { num: "08", title: "Response Returned", desc: "Message, suggested actions, escalation status in JSON" }] },
];

const techStack = [
  { cat: "API", items: ["FastAPI", "Pydantic", "JWT/OAuth2", "OpenAPI"] },
  { cat: "ML Models", items: ["LightGBM", "Isolation Forest", "DistilBERT", "Phi-3 Mini"] },
  { cat: "AI/RAG", items: ["LangChain", "llama-cpp", "Transformers", "SHAP"] },
  { cat: "Database", items: ["PostgreSQL", "pgvector", "SQLAlchemy", "Redis"] },
  { cat: "Frontend", items: ["React", "Vite", "TailwindCSS", "Recharts"] },
  { cat: "Infra", items: ["Docker", "Nginx", "Celery", "Prometheus"] },
];

const API_BASE = import.meta.env.VITE_API_URL || "http://localhost:8000";

function OnboardTab() {
  const [name, setName] = useState("");
  const [countryCode, setCountryCode] = useState("GH");
  const [result, setResult] = useState(null);
  const [error, setError] = useState(null);
  const [loading, setLoading] = useState(false);
  const [copied, setCopied] = useState(false);

  async function handleSubmit(e) {
    e.preventDefault();
    setError(null);
    setResult(null);
    setLoading(true);
    try {
      const res = await fetch(`${API_BASE}/api/v1/admin/onboard`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ name: name.trim(), country_code: countryCode.trim() }),
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || res.statusText);
      setResult(data);
    } catch (err) {
      setError(err.message || "Request failed");
    } finally {
      setLoading(false);
    }
  }

  function copyKey() {
    if (!result?.api_key) return;
    navigator.clipboard.writeText(result.api_key);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  }

  return (
    <div className="px-10 py-8 max-w-xl">
      <p className="text-slate-500 text-xs tracking-wider mb-6 uppercase">Onboard a new bank tenant</p>
      <form onSubmit={handleSubmit} className="space-y-4">
        <div>
          <label className="block text-[11px] tracking-wider text-slate-500 uppercase mb-1.5">Bank name</label>
          <input
            type="text"
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder="e.g. Bank A"
            required
            className="w-full rounded-lg border border-slate-600 bg-slate-900 px-4 py-2.5 text-slate-200 placeholder-slate-500 focus:border-blue-500 focus:outline-none"
          />
        </div>
        <div>
          <label className="block text-[11px] tracking-wider text-slate-500 uppercase mb-1.5">Country code</label>
          <input
            type="text"
            value={countryCode}
            onChange={(e) => setCountryCode(e.target.value)}
            placeholder="e.g. GH"
            required
            maxLength={2}
            className="w-full rounded-lg border border-slate-600 bg-slate-900 px-4 py-2.5 text-slate-200 placeholder-slate-500 focus:border-blue-500 focus:outline-none uppercase"
          />
        </div>
        {error && (
          <div className="rounded-lg border border-red-500/50 bg-red-500/10 px-4 py-2 text-sm text-red-300">{error}</div>
        )}
        <button
          type="submit"
          disabled={loading}
          className="px-6 py-2.5 rounded-md border border-blue-500 bg-blue-900/50 text-blue-200 text-xs tracking-wider uppercase disabled:opacity-50"
        >
          {loading ? "Creating…" : "Onboard bank"}
        </button>
      </form>
      {result && (
        <div className="mt-8 rounded-xl border border-emerald-500/40 bg-emerald-500/10 p-5 space-y-3">
          <div className="text-[11px] tracking-wider text-emerald-400 uppercase">Created</div>
          <div>
            <div className="text-[10px] text-slate-500 uppercase mb-1">Bank ID</div>
            <code className="text-sm text-slate-200 break-all">{result.bank_id}</code>
          </div>
          <div>
            <div className="text-[10px] text-slate-500 uppercase mb-1">API Key (use in X-API-Key header)</div>
            <div className="flex items-center gap-2">
              <code className="flex-1 text-sm text-slate-200 break-all bg-slate-900/80 rounded px-2 py-1.5">
                {result.api_key}
              </code>
              <button
                type="button"
                onClick={copyKey}
                className="px-3 py-1.5 rounded border border-slate-600 text-xs text-slate-400 hover:bg-slate-800"
              >
                {copied ? "Copied" : "Copy"}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

function CareMetricsPanel() {
  const [metrics, setMetrics] = useState(null);
  const [error, setError] = useState(null);
  const [loading, setLoading] = useState(false);

  async function loadMetrics() {
    setLoading(true);
    setError(null);
    try {
      const res = await fetch(`${API_BASE}/api/v1/admin/care/metrics`);
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || res.statusText);
      setMetrics(data);
    } catch (err) {
      setError(err.message || "Failed to load metrics");
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="px-10 py-8 border-l border-slate-800">
      <div className="flex items-center justify-between mb-4">
        <div>
          <p className="text-slate-500 text-[11px] tracking-wider uppercase mb-1">Customer care health</p>
          <p className="text-slate-400 text-xs">
            Last {metrics?.window_hours ?? 24} hours — based on `care_events.log`.
          </p>
        </div>
        <button
          type="button"
          onClick={loadMetrics}
          disabled={loading}
          className="px-4 py-2 rounded-md border border-slate-600 text-xs tracking-wider uppercase text-slate-300 disabled:opacity-50"
        >
          {loading ? "Refreshing…" : metrics ? "Refresh" : "Load metrics"}
        </button>
      </div>
      {error && (
        <div className="mb-4 rounded-lg border border-red-500/50 bg-red-500/10 px-4 py-2 text-sm text-red-300">
          {error}
        </div>
      )}
      {metrics && (
        <div className="space-y-4">
          <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
            <div className="rounded-lg border border-slate-700 bg-slate-900/60 p-3">
              <div className="text-[10px] text-slate-500 uppercase tracking-wider mb-1">Total replies</div>
              <div className="text-lg font-semibold text-slate-100">{metrics.total_replies}</div>
            </div>
            <div className="rounded-lg border border-slate-700 bg-slate-900/60 p-3">
              <div className="text-[10px] text-slate-500 uppercase tracking-wider mb-1">Rule hit rate</div>
              <div className="text-lg font-semibold text-emerald-300">{(metrics.rule_hit_rate * 100).toFixed(1)}%</div>
            </div>
            <div className="rounded-lg border border-slate-700 bg-slate-900/60 p-3">
              <div className="text-[10px] text-slate-500 uppercase tracking-wider mb-1">Suggestion rate</div>
              <div className="text-lg font-semibold text-blue-300">
                {(metrics.suggestion_rate * 100).toFixed(1)}%
              </div>
            </div>
            <div className="rounded-lg border border-slate-700 bg-slate-900/60 p-3">
              <div className="text-[10px] text-slate-500 uppercase tracking-wider mb-1">Escalation rate</div>
              <div className="text-lg font-semibold text-amber-300">
                {(metrics.escalation_rate * 100).toFixed(1)}%
              </div>
            </div>
          </div>
          <div className="rounded-lg border border-slate-700 bg-slate-900/60 p-3">
            <div className="text-[10px] text-slate-500 uppercase tracking-wider mb-2">Intent counts</div>
            <div className="flex flex-wrap gap-2">
              {Object.entries(metrics.intent_counts || {}).map(([intent, count]) => (
                <div
                  key={intent}
                  className="px-3 py-1.5 rounded-full border border-slate-600 text-[11px] text-slate-300 bg-slate-800/70"
                >
                  <span className="font-mono mr-1 text-slate-500">{intent}</span>
                  <span className="font-semibold">{count}</span>
                </div>
              ))}
              {!Object.keys(metrics.intent_counts || {}).length && (
                <div className="text-xs text-slate-500">No traffic in this window.</div>
              )}
            </div>
          </div>
          {metrics.alerts?.length > 0 && (
            <div className="rounded-lg border border-amber-500/60 bg-amber-500/10 p-3">
              <div className="text-[10px] text-amber-300 uppercase tracking-wider mb-1">Alerts</div>
              <ul className="text-xs text-amber-100 list-disc list-inside space-y-0.5">
                {metrics.alerts.map((a) => (
                  <li key={a}>{a}</li>
                ))}
              </ul>
            </div>
          )}
        </div>
      )}
      {!metrics && !error && !loading && (
        <p className="text-xs text-slate-500 mt-2">Click “Load metrics” to fetch recent customer‑care stats.</p>
      )}
    </div>
  );
}

function FraudTab() {
  const [apiKey, setApiKey] = useState("");
  const [alerts, setAlerts] = useState([]);
  const [alertsLoading, setAlertsLoading] = useState(false);
  const [alertsError, setAlertsError] = useState(null);
  const [customerRisk, setCustomerRisk] = useState(null);
  const [accountId, setAccountId] = useState("");
  const [deviceCheck, setDeviceCheck] = useState(null);
  const [deviceId, setDeviceId] = useState("");

  const headers = () => ({ "X-API-Key": apiKey, "Content-Type": "application/json" });

  async function loadAlerts() {
    if (!apiKey.trim()) return;
    setAlertsLoading(true);
    setAlertsError(null);
    try {
      const res = await fetch(`${API_BASE}/api/v1/fraud/alerts`, { headers: headers() });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || res.statusText);
      setAlerts(Array.isArray(data) ? data : []);
    } catch (err) {
      setAlertsError(err.message || "Failed to load alerts");
    } finally {
      setAlertsLoading(false);
    }
  }

  async function loadCustomerRisk(e) {
    e.preventDefault();
    if (!apiKey.trim() || !accountId.trim()) return;
    try {
      const res = await fetch(`${API_BASE}/api/v1/fraud/customer-risk/${encodeURIComponent(accountId)}`, { headers: headers() });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || res.statusText);
      setCustomerRisk(data);
    } catch (err) {
      setCustomerRisk({ error: err.message });
    }
  }

  async function runDeviceCheck(e) {
    e.preventDefault();
    if (!apiKey.trim()) return;
    try {
      const res = await fetch(`${API_BASE}/api/v1/fraud/device-check`, {
        method: "POST",
        headers: headers(),
        body: JSON.stringify({ account_id: "demo", amount: 0, device_id: deviceId || undefined }),
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || res.statusText);
      setDeviceCheck(data);
    } catch (err) {
      setDeviceCheck({ risk: "ERROR", reason: err.message });
    }
  }

  return (
    <div className="px-10 py-8 space-y-8">
      <div>
        <p className="text-slate-500 text-[11px] tracking-wider mb-2 uppercase">Fraud API (X-API-Key)</p>
        <input
          type="password"
          value={apiKey}
          onChange={(e) => setApiKey(e.target.value)}
          placeholder="Paste bank API key for fraud endpoints"
          className="w-full max-w-md rounded-lg border border-slate-600 bg-slate-900 px-4 py-2 text-slate-200 placeholder-slate-500 text-sm"
        />
      </div>

      <div>
        <div className="flex items-center gap-3 mb-3">
          <h3 className="text-sm font-semibold text-slate-200">Fraud Alerts</h3>
          <button
            type="button"
            onClick={loadAlerts}
            disabled={!apiKey.trim() || alertsLoading}
            className="px-3 py-1.5 rounded border border-slate-600 text-xs text-slate-400 hover:bg-slate-800 disabled:opacity-50"
          >
            {alertsLoading ? "Loading…" : "Refresh"}
          </button>
        </div>
        {alertsError && <p className="text-xs text-red-400 mb-2">{alertsError}</p>}
        <div className="rounded-lg border border-slate-700 bg-slate-900/60 overflow-hidden">
          <table className="w-full text-left text-xs">
            <thead>
              <tr className="border-b border-slate-700 text-slate-500 uppercase tracking-wider">
                <th className="p-3">Alert ID</th>
                <th className="p-3">Transaction</th>
                <th className="p-3">Account</th>
                <th className="p-3">Type</th>
                <th className="p-3">Severity</th>
                <th className="p-3">Status</th>
                <th className="p-3">Created</th>
              </tr>
            </thead>
            <tbody>
              {alerts.length === 0 && !alertsLoading && (
                <tr><td colSpan={7} className="p-4 text-slate-500">No alerts. Use API key and click Refresh.</td></tr>
              )}
              {alerts.map((a) => (
                <tr key={a.alert_id} className="border-b border-slate-800">
                  <td className="p-3 font-mono text-slate-400">{String(a.alert_id).slice(0, 8)}…</td>
                  <td className="p-3 font-mono">{String(a.transaction_id).slice(0, 8)}…</td>
                  <td className="p-3">{a.account_id ?? "—"}</td>
                  <td className="p-3">{a.alert_type}</td>
                  <td className="p-3">{a.severity}</td>
                  <td className="p-3">{a.status}</td>
                  <td className="p-3 text-slate-500">{a.created_at ? new Date(a.created_at).toLocaleString() : "—"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      <div>
        <h3 className="text-sm font-semibold text-slate-200 mb-3">Customer Risk Profile</h3>
        <form onSubmit={loadCustomerRisk} className="flex gap-2 mb-2">
          <input
            type="text"
            value={accountId}
            onChange={(e) => setAccountId(e.target.value)}
            placeholder="Account ID"
            className="rounded-lg border border-slate-600 bg-slate-900 px-3 py-2 text-slate-200 text-sm w-48"
          />
          <button type="submit" disabled={!apiKey.trim()} className="px-4 py-2 rounded border border-slate-600 text-xs uppercase text-slate-300 disabled:opacity-50">Lookup</button>
        </form>
        {customerRisk && !customerRisk.error && (
          <div className="rounded-lg border border-slate-700 bg-slate-900/60 p-4 text-xs space-y-1">
            <p><span className="text-slate-500">Risk score:</span> {customerRisk.risk_score}</p>
            <p><span className="text-slate-500">Avg transaction:</span> {customerRisk.avg_transaction ?? "—"}</p>
            <p><span className="text-slate-500">Max transaction:</span> {customerRisk.max_transaction ?? "—"}</p>
            <p><span className="text-slate-500">Usual location:</span> {customerRisk.usual_location ?? "—"}</p>
          </div>
        )}
        {customerRisk?.error && <p className="text-red-400 text-xs">{customerRisk.error}</p>}
      </div>

      <div>
        <h3 className="text-sm font-semibold text-slate-200 mb-3">Device Check</h3>
        <form onSubmit={runDeviceCheck} className="flex gap-2 mb-2">
          <input
            type="text"
            value={deviceId}
            onChange={(e) => setDeviceId(e.target.value)}
            placeholder="Device ID"
            className="rounded-lg border border-slate-600 bg-slate-900 px-3 py-2 text-slate-200 text-sm w-48"
          />
          <button type="submit" disabled={!apiKey.trim()} className="px-4 py-2 rounded border border-slate-600 text-xs uppercase text-slate-300 disabled:opacity-50">Check</button>
        </form>
        {deviceCheck && (
          <div className="rounded-lg border border-slate-700 bg-slate-900/60 p-4 text-xs">
            <p><span className="text-slate-500">Risk:</span> {deviceCheck.risk}</p>
            <p><span className="text-slate-500">Known:</span> {deviceCheck.is_known ? "Yes" : "No"}</p>
            {deviceCheck.reason && <p className="text-slate-400">{deviceCheck.reason}</p>}
          </div>
        )}
      </div>

      <div className="rounded-lg border border-slate-700 border-dashed p-6 text-center text-slate-500 text-xs">
        Transaction Monitor (live stream) and Fraud Analytics charts — connect to WebSocket or polling API when ready.
      </div>
    </div>
  );
}

function Header({ activeTab, setActiveTab }) {
  return (
    <div className="border-b border-slate-700 bg-gradient-to-br from-slate-900 via-slate-800 to-slate-900 px-10 py-7 flex items-center justify-between">
      <div>
        <div className="flex items-center gap-3 mb-1.5">
          <div className="w-2.5 h-2.5 rounded-full bg-emerald-400 shadow-[0_0_8px] shadow-emerald-400 animate-pulse" />
          <span className="text-slate-500 text-[11px] tracking-widest uppercase">Architecture Blueprint</span>
        </div>
        <h1 className="m-0 text-2xl font-bold tracking-tight text-slate-100">BankAI Platform</h1>
        <p className="mt-1 text-slate-500 text-sm">White-label Fraud Detection + Customer Care API</p>
      </div>
      <div className="flex gap-2">
        {["architecture", "flow", "stack", "admin", "fraud"].map((tab) => (
          <button
            key={tab}
            onClick={() => setActiveTab(tab)}
            className={`px-5 py-2 rounded-md border text-xs tracking-wider uppercase transition-all ${
              activeTab === tab ? "border-blue-500 bg-blue-900/50 text-blue-200" : "border-slate-600 text-slate-500"
            }`}
          >
            {tab}
          </button>
        ))}
      </div>
    </div>
  );
}

function ArchitectureTab({ activeEngine, setActiveEngine }) {
  return (
    <div className="px-10 py-8">
      <p className="text-slate-500 text-xs tracking-wider mb-6 uppercase">Click on AI Engines to explore internals</p>
      {layers.map((layer, li) => (
        <div key={layer.id} className="mb-3">
          <div className="text-[10px] tracking-widest text-slate-500 uppercase mb-2 pl-1">{`0${li + 1}`} — {layer.label}</div>
          <div className={`flex gap-3 flex-wrap rounded-xl p-4 border bg-[${layer.color}22] border-[${layer.accent}44]`} style={{ background: `${layer.color}22`, borderColor: `${layer.accent}44` }}>
            {layer.nodes.map((node) => {
              const isEngine = layer.id === "engines";
              const isActive = activeEngine === node.id;
              return (
                <div
                  key={node.id}
                  onClick={() => isEngine && setActiveEngine(isActive ? null : node.id)}
                  className="flex-1 min-w-[160px] rounded-lg p-4 border cursor-default transition-all"
                  style={{
                    background: isActive ? `${layer.accent}44` : `${layer.accent}22`,
                    borderColor: isActive ? layer.accent : layer.accent + "66",
                    cursor: isEngine ? "pointer" : "default",
                    boxShadow: isActive ? `0 0 16px ${layer.accent}44` : "none",
                  }}
                >
                  <div className="text-sm font-semibold text-slate-200 mb-1">{node.label}</div>
                  <div className="text-[11px] text-slate-500">{node.sub}</div>
                  {isEngine && (
                    <div className={`mt-2 text-[10px] tracking-wide ${isActive ? "text-blue-200" : "text-slate-500"}`}>
                      {isActive ? "▲ COLLAPSE" : "▼ EXPAND"}
                    </div>
                  )}
                </div>
              );
            })}
          </div>
          {layer.id === "engines" && layer.nodes.map((node) =>
            activeEngine === node.id && node.details ? (
              <div key={`detail-${node.id}`} className="bg-slate-900 border border-slate-600 border-t-0 rounded-b-xl p-5 -mt-2">
                <div className="text-[11px] tracking-wider text-slate-500 uppercase mb-3">{node.label} — Process Steps</div>
                <div className="flex gap-2 flex-wrap">
                  {node.details.map((step, i) => (
                    <div key={i} className="flex items-start gap-2 bg-slate-800 border border-slate-600 rounded-md p-3 min-w-[200px] flex-1">
                      <span className="text-[11px] font-bold text-purple-400 min-w-[20px]">{String(i + 1).padStart(2, "0")}</span>
                      <span className="text-xs text-slate-300">{step}</span>
                    </div>
                  ))}
                </div>
              </div>
            ) : null
          )}
          {li < layers.length - 1 && <div className="text-center py-1 text-slate-600 text-lg">↓</div>}
        </div>
      ))}
    </div>
  );
}

function FlowTab({ activeFlow, setActiveFlow }) {
  const flow = flowSteps.find((f) => f.id === activeFlow);
  return (
    <div className="px-10 py-8">
      <div className="flex gap-3 mb-7">
        {flowSteps.map((f) => (
          <button
            key={f.id}
            onClick={() => setActiveFlow(f.id)}
            className={`px-6 py-2.5 rounded-md border text-xs tracking-wider uppercase transition-all ${
              activeFlow === f.id ? "text-slate-200" : "text-slate-500"
            }`}
            style={{ borderColor: activeFlow === f.id ? f.color : "#1e3a5f", background: activeFlow === f.id ? `${f.color}33` : "transparent" }}
          >
            {f.label}
          </button>
        ))}
      </div>
      <div className="flex flex-col gap-0">
        {flow.steps.map((step, i) => (
          <div key={i} className="flex items-stretch gap-0">
            <div className="flex flex-col items-center w-[60px] flex-shrink-0">
              <div className="w-9 h-9 rounded-full border-2 flex items-center justify-center text-[11px] font-bold text-slate-200 z-[1]" style={{ background: `${flow.color}33`, borderColor: flow.color }}>{step.num}</div>
              {i < flow.steps.length - 1 && <div className="w-0.5 flex-1 min-h-8" style={{ background: `${flow.color}33` }} />}
            </div>
            <div className="flex-1 bg-slate-900 border border-slate-600 rounded-lg py-3.5 px-5 ml-3 mb-2 border-l-[3px]" style={{ borderLeftColor: flow.color }}>
              <div className="text-sm font-semibold text-slate-100 mb-1">{step.title}</div>
              <div className="text-xs text-slate-500">{step.desc}</div>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

function StackTab() {
  const colors = ["#1b6ca8", "#2d6a4f", "#6a0dad", "#c9184a", "#b45309", "#0f766e"];
  const phases = [
    { phase: "01", label: "Foundation", weeks: "Wk 1–3", color: "#1b6ca8" },
    { phase: "02", label: "Fraud Engine", weeks: "Wk 4–6", color: "#6a0dad" },
    { phase: "03", label: "Care Agent", weeks: "Wk 7–9", color: "#c9184a" },
    { phase: "04", label: "Integration", weeks: "Wk 10–11", color: "#b45309" },
    { phase: "05", label: "Frontend", weeks: "Wk 12–13", color: "#2d6a4f" },
    { phase: "06", label: "Hardening", weeks: "Wk 14–16", color: "#0f766e" },
  ];
  return (
    <div className="px-10 py-8">
      <div className="grid grid-cols-[repeat(auto-fill,minmax(280px,1fr))] gap-4">
        {techStack.map((cat, i) => {
          const c = colors[i % colors.length];
          return (
            <div key={cat.cat} className="bg-slate-900 border rounded-xl p-5" style={{ borderColor: `${c}44`, borderTopWidth: 3, borderTopColor: c }}>
              <div className="text-[10px] tracking-widest text-slate-500 uppercase mb-4">{cat.cat}</div>
              <div className="flex flex-col gap-2">
                {cat.items.map((item) => (
                  <div key={item} className="flex items-center gap-2 rounded-md py-2 px-3" style={{ background: `${c}11`, border: `1px solid ${c}33` }}>
                    <div className="w-1.5 h-1.5 rounded-full" style={{ background: c }} />
                    <span className="text-sm text-slate-300">{item}</span>
                  </div>
                ))}
              </div>
            </div>
          );
        })}
      </div>
      <div className="mt-8">
        <div className="text-[10px] tracking-widest text-slate-500 uppercase mb-4">Build Sequence — 16 Weeks</div>
        <div className="flex gap-2 flex-wrap">
          {phases.map((p) => (
            <div key={p.phase} className="flex-1 min-w-[120px] rounded-lg p-4 text-center" style={{ background: `${p.color}22`, border: `1px solid ${p.color}66` }}>
              <div className="text-xl font-bold" style={{ color: p.color }}>{p.phase}</div>
              <div className="text-sm text-slate-200 mt-1">{p.label}</div>
              <div className="text-[10px] text-slate-500 mt-1">{p.weeks}</div>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}

export default function App() {
  const [activeTab, setActiveTab] = useState("architecture");
  const [activeFlow, setActiveFlow] = useState("fraud");
  const [activeEngine, setActiveEngine] = useState(null);

  return (
    <div className="min-h-screen bg-[#080c14] text-slate-200">
      <Header activeTab={activeTab} setActiveTab={setActiveTab} />
      <div className="py-8">
        {activeTab === "architecture" && <ArchitectureTab activeEngine={activeEngine} setActiveEngine={setActiveEngine} />}
        {activeTab === "flow" && <FlowTab activeFlow={activeFlow} setActiveFlow={setActiveFlow} />}
        {activeTab === "stack" && <StackTab />}
        {activeTab === "fraud" && <FraudTab />}
        {activeTab === "admin" && (
          <div className="flex flex-col lg:flex-row">
            <div className="flex-1">
              <OnboardTab />
            </div>
            <div className="flex-1">
              <CareMetricsPanel />
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
