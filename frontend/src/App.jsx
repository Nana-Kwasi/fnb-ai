import { useState, useEffect } from "react";
import PlatformSidebar from "./components/PlatformSidebar";

const API_BASE = import.meta.env.VITE_API_URL || "http://localhost:8000";

function OnboardTab() {
  const [name, setName] = useState("");
  const [countryCode, setCountryCode] = useState("GH");
  const [result, setResult] = useState(null);
  const [error, setError] = useState(null);
  const [loading, setLoading] = useState(false);
  const [copied, setCopied] = useState(false);
  const [banks, setBanks] = useState([]);
  const [banksLoading, setBanksLoading] = useState(false);
  const [banksError, setBanksError] = useState(null);
  const [selectedBank, setSelectedBank] = useState(null);
  const [rotateLoading, setRotateLoading] = useState(false);
  const [rotateError, setRotateError] = useState(null);
  const [rotateResult, setRotateResult] = useState(null);

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

  async function loadBanks() {
    setBanksLoading(true);
    setBanksError(null);
    try {
      const res = await fetch(`${API_BASE}/api/v1/admin/tenants`);
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || res.statusText);
      setBanks(Array.isArray(data) ? data : []);
    } catch (err) {
      setBanksError(err.message || "Failed to load banks");
    } finally {
      setBanksLoading(false);
    }
  }

  async function rotateKey(id) {
    if (!id) return;
    setRotateLoading(true);
    setRotateError(null);
    setRotateResult(null);
    try {
      const res = await fetch(`${API_BASE}/api/v1/admin/tenants/${id}/api-key`, {
        method: "POST",
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || res.statusText);
      setRotateResult(data);
    } catch (err) {
      setRotateError(err.message || "Failed to rotate key");
    } finally {
      setRotateLoading(false);
    }
  }

  return (
    <div className="p-8 space-y-8">
      <div className="max-w-xl">
        <p className="text-slate-400 text-xs tracking-wider mb-6 uppercase">Onboard a new bank tenant</p>
        <form onSubmit={handleSubmit} className="space-y-4">
          <div>
            <label className="block text-[11px] tracking-wider text-slate-500 uppercase mb-1.5">Bank name</label>
            <input
              type="text"
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="e.g. Bank A"
              required
              className="w-full rounded-lg border border-slate-700 bg-slate-950/60 px-4 py-2.5 text-slate-100 placeholder-slate-500 focus:border-cyan-400 focus:outline-none"
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
              className="w-full rounded-lg border border-slate-700 bg-slate-950/60 px-4 py-2.5 text-slate-100 placeholder-slate-500 focus:border-cyan-400 focus:outline-none uppercase"
            />
          </div>
          {error && (
            <div className="rounded-lg border border-red-500/40 bg-red-500/10 px-4 py-2 text-sm text-red-200">{error}</div>
          )}
          <button
            type="submit"
            disabled={loading}
            className="px-6 py-2.5 rounded-md border border-cyan-400/80 bg-cyan-500/10 text-cyan-200 text-xs tracking-wider uppercase disabled:opacity-50"
          >
            {loading ? "Creating…" : "Onboard bank"}
          </button>
        </form>
        {result && (
          <div className="mt-8 rounded-xl border border-emerald-400/40 bg-emerald-500/10 p-5 space-y-3">
            <div className="text-[11px] tracking-wider text-emerald-300 uppercase">Created</div>
            <div>
              <div className="text-[10px] text-slate-400 uppercase mb-1">Bank ID</div>
              <code className="text-sm text-slate-100 break-all">{result.bank_id}</code>
            </div>
            <div>
              <div className="text-[10px] text-slate-400 uppercase mb-1">API Key (use in X-API-Key header)</div>
              <div className="flex items-center gap-2">
                <code className="flex-1 text-sm text-slate-100 break-all bg-slate-950/80 rounded px-2 py-1.5">
                  {result.api_key}
                </code>
                <button
                  type="button"
                  onClick={copyKey}
                  className="px-3 py-1.5 rounded border border-emerald-400/70 text-xs text-emerald-200 hover:bg-emerald-500/10"
                >
                  {copied ? "Copied" : "Copy"}
                </button>
              </div>
            </div>
          </div>
        )}
      </div>

      <div className="rounded-2xl border border-slate-800 bg-slate-950/60 shadow-[0_18px_60px_rgba(15,23,42,0.75)]">
        <div className="flex items-center justify-between px-5 py-4 border-b border-slate-800/80">
          <div>
            <p className="text-[11px] text-slate-400 tracking-wider uppercase mb-1">Banks</p>
            <p className="text-xs text-slate-500">Click a bank to manage keys &amp; policy.</p>
          </div>
          <button
            type="button"
            onClick={loadBanks}
            disabled={banksLoading}
            className="px-3 py-1.5 rounded-md border border-slate-600 text-xs text-slate-300 hover:bg-white/5 disabled:opacity-50"
          >
            {banksLoading ? "Loading…" : "Refresh"}
          </button>
        </div>
        {banksError && <p className="px-5 py-3 text-xs text-red-400 border-b border-slate-800">{banksError}</p>}
        <div className="max-h-64 overflow-auto">
          <table className="w-full text-left text-xs">
            <thead>
              <tr className="border-b border-slate-800 text-slate-500 uppercase tracking-wider">
                <th className="p-3">Name</th>
                <th className="p-3">Country</th>
                <th className="p-3">ID</th>
              </tr>
            </thead>
            <tbody>
              {banks.length === 0 && !banksLoading && (
                <tr>
                  <td colSpan={3} className="p-4 text-slate-500">
                    No banks yet. Onboard one to get started.
                  </td>
                </tr>
              )}
              {banks.map((b) => (
                <tr
                  key={b.id}
                  className="border-b border-slate-900/80 hover:bg-white/5 cursor-pointer"
                  onClick={() => {
                    setSelectedBank(b);
                    setRotateResult(null);
                    setRotateError(null);
                  }}
                >
                  <td className="p-3">{b.name}</td>
                  <td className="p-3">{b.country_code}</td>
                  <td className="p-3 font-mono text-slate-500">{String(b.id).slice(0, 8)}…</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      {selectedBank && (
        <div className="fixed inset-0 z-40 flex items-center justify-center bg-black/60 backdrop-blur-sm">
          <div className="w-full max-w-lg rounded-2xl border border-slate-700 bg-slate-950/95 shadow-2xl p-6 space-y-4">
            <div className="flex items-center justify-between mb-1">
              <h3 className="text-sm font-semibold text-slate-100">Manage bank</h3>
              <button
                type="button"
                onClick={() => {
                  setSelectedBank(null);
                  setRotateResult(null);
                  setRotateError(null);
                }}
                className="text-slate-400 hover:text-slate-100 text-sm"
              >
                ✕
              </button>
            </div>
            <p className="text-xs text-slate-500">
              {selectedBank.name} ({selectedBank.country_code})
            </p>
            <div>
              <div className="text-[10px] text-slate-500 uppercase mb-1">Bank ID</div>
              <code className="text-[11px] text-slate-300 break-all bg-slate-900/80 rounded px-2 py-1.5 block">
                {selectedBank.id}
              </code>
            </div>
            <div className="space-y-2 pt-2 border-t border-slate-800 mt-2">
              <p className="text-[10px] text-slate-500 uppercase">Actions</p>
              <div className="flex flex-wrap gap-2">
                <button
                  type="button"
                  disabled={rotateLoading}
                  onClick={() => rotateKey(selectedBank.id)}
                  className="px-3 py-1.5 rounded-md border border-amber-400/70 bg-amber-500/10 text-xs text-amber-100 tracking-wider uppercase disabled:opacity-50"
                >
                  {rotateLoading ? "Rotating key…" : "Generate new API key"}
                </button>
                <span className="text-[11px] text-slate-500">
                  Old keys stop working immediately after rotation.
                </span>
              </div>
              {rotateError && <p className="text-xs text-red-400">{rotateError}</p>}
              {rotateResult && (
                <div className="mt-2 rounded-lg border border-emerald-400/60 bg-emerald-500/10 p-3 space-y-2">
                  <div className="text-[10px] text-emerald-300 uppercase tracking-wider">New API key</div>
                  <code className="text-[11px] text-slate-100 break-all bg-slate-950/80 rounded px-2 py-1.5 block">
                    {rotateResult.api_key}
                  </code>
                  <p className="text-[11px] text-slate-400">
                    Copy this key now – it will not be shown again.
                  </p>
                </div>
              )}
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
    <div className="p-8">
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

function FraudPolicyPanel() {
  const PRESETS = {
    STRICT: {
      label: "Strict",
      note: "Higher friction, lower fraud loss. Escalates faster to OTP/BLOCK.",
      values: {
        model_weight: "0.50",
        iso_weight: "0.20",
        rule_weight: "0.20",
        network_weight: "0.10",
        fraud_block_threshold: "0.75",
        fraud_otp_threshold: "0.50",
        limited_approval_max_amount: "100",
        limited_approval_max_txn_1h: "2",
        limited_approval_escalate_ratio: "0.85",
        limited_approval_escalate_network_risk: "0.50",
        approve_max_amount: "200",
        approve_max_txn_1h: "3",
        request_otp_block_amount: "1200",
        request_otp_block_txn_1h: "8",
        request_otp_block_network_risk: "0.75",
        velocity_zscore_threshold: "2.0",
        challenged_txn_1h_threshold: "3",
        heuristic_amount_threshold: "20000",
        heuristic_velocity_1h_threshold: "6",
        heuristic_suspicious_countries: "XX,RU,KP,IR",
        dynamic_threshold_enabled: true,
        dynamic_threshold_min_samples: "300",
        dynamic_threshold_block_percentile: "0.98",
        dynamic_threshold_otp_percentile: "0.90",
        shadow_mode: false,
        kill_switch: false,
      },
    },
    BALANCED: {
      label: "Balanced",
      note: "Model-first defaults. Overrides are mostly neutral unless you tighten them.",
      values: {
        model_weight: "0.50",
        iso_weight: "0.20",
        rule_weight: "0.20",
        network_weight: "0.10",
        fraud_block_threshold: "0.80",
        fraud_otp_threshold: "0.55",
        limited_approval_max_amount: "250",
        limited_approval_max_txn_1h: "4",
        limited_approval_escalate_ratio: "0.90",
        limited_approval_escalate_network_risk: "0.60",
        approve_max_amount: "1000000",
        approve_max_txn_1h: "1000",
        request_otp_block_amount: "1000000",
        request_otp_block_txn_1h: "1000",
        request_otp_block_network_risk: "0.99",
        velocity_zscore_threshold: "2.0",
        challenged_txn_1h_threshold: "3",
        heuristic_amount_threshold: "50000",
        heuristic_velocity_1h_threshold: "10",
        heuristic_suspicious_countries: "XX,RU,KP,IR",
        dynamic_threshold_enabled: true,
        dynamic_threshold_min_samples: "300",
        dynamic_threshold_block_percentile: "0.98",
        dynamic_threshold_otp_percentile: "0.90",
        shadow_mode: false,
        kill_switch: false,
      },
    },
    LENIENT: {
      label: "Lenient",
      note: "Lower friction, higher fraud risk tolerance.",
      values: {
        model_weight: "0.50",
        iso_weight: "0.20",
        rule_weight: "0.20",
        network_weight: "0.10",
        fraud_block_threshold: "0.85",
        fraud_otp_threshold: "0.65",
        limited_approval_max_amount: "500",
        limited_approval_max_txn_1h: "8",
        limited_approval_escalate_ratio: "0.95",
        limited_approval_escalate_network_risk: "0.75",
        approve_max_amount: "900",
        approve_max_txn_1h: "12",
        request_otp_block_amount: "3500",
        request_otp_block_txn_1h: "18",
        request_otp_block_network_risk: "0.92",
        velocity_zscore_threshold: "2.2",
        challenged_txn_1h_threshold: "4",
        heuristic_amount_threshold: "80000",
        heuristic_velocity_1h_threshold: "14",
        heuristic_suspicious_countries: "XX,RU,KP,IR",
        dynamic_threshold_enabled: true,
        dynamic_threshold_min_samples: "300",
        dynamic_threshold_block_percentile: "0.98",
        dynamic_threshold_otp_percentile: "0.90",
        shadow_mode: false,
        kill_switch: false,
      },
    },
    LOCKDOWN: {
      label: "Lockdown",
      note: "Emergency mode: kill switch on, all scores force BLOCK.",
      values: {
        model_weight: "0.50",
        iso_weight: "0.20",
        rule_weight: "0.20",
        network_weight: "0.10",
        fraud_block_threshold: "0.80",
        fraud_otp_threshold: "0.55",
        limited_approval_max_amount: "50",
        limited_approval_max_txn_1h: "1",
        limited_approval_escalate_ratio: "0.80",
        limited_approval_escalate_network_risk: "0.40",
        approve_max_amount: "50",
        approve_max_txn_1h: "1",
        request_otp_block_amount: "100",
        request_otp_block_txn_1h: "1",
        request_otp_block_network_risk: "0.30",
        velocity_zscore_threshold: "1.4",
        challenged_txn_1h_threshold: "1",
        heuristic_amount_threshold: "20000",
        heuristic_velocity_1h_threshold: "4",
        heuristic_suspicious_countries: "XX,RU,KP,IR",
        dynamic_threshold_enabled: true,
        dynamic_threshold_min_samples: "300",
        dynamic_threshold_block_percentile: "0.98",
        dynamic_threshold_otp_percentile: "0.90",
        shadow_mode: false,
        kill_switch: true,
      },
    },
  };
  const [tenants, setTenants] = useState([]);
  const [tenantId, setTenantId] = useState("");
  const [policy, setPolicy] = useState(null);
  const [preset, setPreset] = useState("BALANCED");
  const [form, setForm] = useState({
    model_weight: "",
    iso_weight: "",
    rule_weight: "",
    network_weight: "",
    fraud_block_threshold: "",
    fraud_otp_threshold: "",
    shadow_mode: false,
    kill_switch: false,
    limited_approval_max_amount: "",
    limited_approval_max_txn_1h: "",
    limited_approval_escalate_ratio: "",
    limited_approval_escalate_network_risk: "",
    approve_max_amount: "",
    approve_max_txn_1h: "",
    request_otp_block_amount: "",
    request_otp_block_txn_1h: "",
    request_otp_block_network_risk: "",
    velocity_zscore_threshold: "",
    challenged_txn_1h_threshold: "",
    heuristic_amount_threshold: "",
    heuristic_velocity_1h_threshold: "",
    heuristic_suspicious_countries: "",
    dynamic_threshold_enabled: true,
    dynamic_threshold_min_samples: "",
    dynamic_threshold_block_percentile: "",
    dynamic_threshold_otp_percentile: "",
  });
  const [loading, setLoading] = useState(false);
  const [loadingPolicy, setLoadingPolicy] = useState(false);
  const [error, setError] = useState(null);
  const [saved, setSaved] = useState(false);
  const velocityZ = parseFloat(form?.velocity_zscore_threshold || "");
  const challenged1h = parseInt(form?.challenged_txn_1h_threshold || "", 10);
  const velocityZState = Number.isNaN(velocityZ)
    ? "unset"
    : velocityZ < 1.8
      ? "aggressive"
      : velocityZ > 2.6
        ? "lax"
        : "recommended";
  const challengedState = Number.isNaN(challenged1h)
    ? "unset"
    : challenged1h < 2
      ? "aggressive"
      : challenged1h > 5
        ? "lax"
        : "recommended";
  const guardrailTone =
    velocityZState === "aggressive" || challengedState === "aggressive"
      ? "border-amber-500/50 bg-amber-500/10 text-amber-200"
      : velocityZState === "lax" || challengedState === "lax"
        ? "border-rose-500/50 bg-rose-500/10 text-rose-200"
        : "border-emerald-500/50 bg-emerald-500/10 text-emerald-200";
  const velocityChipTone =
    velocityZState === "recommended"
      ? "border-emerald-500/50 bg-emerald-500/10 text-emerald-200"
      : velocityZState === "aggressive"
        ? "border-amber-500/50 bg-amber-500/10 text-amber-200"
        : velocityZState === "lax"
          ? "border-rose-500/50 bg-rose-500/10 text-rose-200"
          : "border-slate-600 bg-slate-900 text-slate-300";
  const challengedChipTone =
    challengedState === "recommended"
      ? "border-emerald-500/50 bg-emerald-500/10 text-emerald-200"
      : challengedState === "aggressive"
        ? "border-amber-500/50 bg-amber-500/10 text-amber-200"
        : challengedState === "lax"
          ? "border-rose-500/50 bg-rose-500/10 text-rose-200"
          : "border-slate-600 bg-slate-900 text-slate-300";
  const velocityStateLabel =
    velocityZState === "recommended"
      ? "Recommended"
      : velocityZState === "aggressive"
        ? "Too aggressive"
        : velocityZState === "lax"
          ? "Too lax"
          : "Unset";
  const challengedStateLabel =
    challengedState === "recommended"
      ? "Recommended"
      : challengedState === "aggressive"
        ? "Too aggressive"
        : challengedState === "lax"
          ? "Too lax"
          : "Unset";
  const guardrailMessage =
    velocityZState === "aggressive" || challengedState === "aggressive"
      ? "Current setup may increase false positives and customer friction."
      : velocityZState === "lax" || challengedState === "lax"
        ? "Current setup may let fraud bursts pass before challenge."
        : "Current setup is in recommended production range.";

  async function loadTenants() {
    setLoading(true);
    setError(null);
    try {
      const res = await fetch(`${API_BASE}/api/v1/admin/tenants`);
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || res.statusText);
      setTenants(Array.isArray(data) ? data : []);
      if (data?.length && !tenantId) setTenantId(data[0].id);
    } catch (err) {
      setError(err.message || "Failed to load tenants");
    } finally {
      setLoading(false);
    }
  }

  async function loadPolicy() {
    if (!tenantId) return;
    setLoadingPolicy(true);
    setError(null);
    try {
      const res = await fetch(`${API_BASE}/api/v1/admin/tenants/${tenantId}/fraud-policy`);
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || res.statusText);
      setPolicy(data);
      setForm({
        model_weight: data.model_weight != null ? String(data.model_weight) : "",
        iso_weight: data.iso_weight != null ? String(data.iso_weight) : "",
        rule_weight: data.rule_weight != null ? String(data.rule_weight) : "",
        network_weight: data.network_weight != null ? String(data.network_weight) : "",
        fraud_block_threshold: data.fraud_block_threshold != null ? String(data.fraud_block_threshold) : "",
        fraud_otp_threshold: data.fraud_otp_threshold != null ? String(data.fraud_otp_threshold) : "",
        shadow_mode: !!data.shadow_mode,
        kill_switch: !!data.kill_switch,
        limited_approval_max_amount: data.limited_approval_max_amount != null ? String(data.limited_approval_max_amount) : "",
        limited_approval_max_txn_1h: data.limited_approval_max_txn_1h != null ? String(data.limited_approval_max_txn_1h) : "",
        limited_approval_escalate_ratio: data.limited_approval_escalate_ratio != null ? String(data.limited_approval_escalate_ratio) : "",
        limited_approval_escalate_network_risk: data.limited_approval_escalate_network_risk != null ? String(data.limited_approval_escalate_network_risk) : "",
        approve_max_amount: data.approve_max_amount != null ? String(data.approve_max_amount) : "",
        approve_max_txn_1h: data.approve_max_txn_1h != null ? String(data.approve_max_txn_1h) : "",
        request_otp_block_amount: data.request_otp_block_amount != null ? String(data.request_otp_block_amount) : "",
        request_otp_block_txn_1h: data.request_otp_block_txn_1h != null ? String(data.request_otp_block_txn_1h) : "",
        request_otp_block_network_risk: data.request_otp_block_network_risk != null ? String(data.request_otp_block_network_risk) : "",
        velocity_zscore_threshold: data.velocity_zscore_threshold != null ? String(data.velocity_zscore_threshold) : "",
        challenged_txn_1h_threshold: data.challenged_txn_1h_threshold != null ? String(data.challenged_txn_1h_threshold) : "",
        heuristic_amount_threshold: data.heuristic_amount_threshold != null ? String(data.heuristic_amount_threshold) : "",
        heuristic_velocity_1h_threshold: data.heuristic_velocity_1h_threshold != null ? String(data.heuristic_velocity_1h_threshold) : "",
        heuristic_suspicious_countries: Array.isArray(data.heuristic_suspicious_countries)
          ? data.heuristic_suspicious_countries.join(",")
          : "",
        dynamic_threshold_enabled:
          data.dynamic_threshold_enabled != null ? !!data.dynamic_threshold_enabled : true,
        dynamic_threshold_min_samples: data.dynamic_threshold_min_samples != null ? String(data.dynamic_threshold_min_samples) : "",
        dynamic_threshold_block_percentile: data.dynamic_threshold_block_percentile != null ? String(data.dynamic_threshold_block_percentile) : "",
        dynamic_threshold_otp_percentile: data.dynamic_threshold_otp_percentile != null ? String(data.dynamic_threshold_otp_percentile) : "",
      });
    } catch (err) {
      setError(err.message || "Failed to load policy");
    } finally {
      setLoadingPolicy(false);
    }
  }

  async function savePolicy(e) {
    e.preventDefault();
    if (!tenantId) return;
    setLoading(true);
    setError(null);
    setSaved(false);
    try {
      const payload = {};
      if (form.model_weight !== "") payload.model_weight = parseFloat(form.model_weight);
      if (form.iso_weight !== "") payload.iso_weight = parseFloat(form.iso_weight);
      if (form.rule_weight !== "") payload.rule_weight = parseFloat(form.rule_weight);
      if (form.network_weight !== "") payload.network_weight = parseFloat(form.network_weight);
      if (form.fraud_block_threshold !== "") payload.fraud_block_threshold = parseFloat(form.fraud_block_threshold);
      if (form.fraud_otp_threshold !== "") payload.fraud_otp_threshold = parseFloat(form.fraud_otp_threshold);
      payload.shadow_mode = form.shadow_mode;
      payload.kill_switch = form.kill_switch;
      if (form.limited_approval_max_amount !== "") payload.limited_approval_max_amount = parseFloat(form.limited_approval_max_amount);
      if (form.limited_approval_max_txn_1h !== "") payload.limited_approval_max_txn_1h = parseFloat(form.limited_approval_max_txn_1h);
      if (form.limited_approval_escalate_ratio !== "") payload.limited_approval_escalate_ratio = parseFloat(form.limited_approval_escalate_ratio);
      if (form.limited_approval_escalate_network_risk !== "") payload.limited_approval_escalate_network_risk = parseFloat(form.limited_approval_escalate_network_risk);
      if (form.approve_max_amount !== "") payload.approve_max_amount = parseFloat(form.approve_max_amount);
      if (form.approve_max_txn_1h !== "") payload.approve_max_txn_1h = parseFloat(form.approve_max_txn_1h);
      if (form.request_otp_block_amount !== "") payload.request_otp_block_amount = parseFloat(form.request_otp_block_amount);
      if (form.request_otp_block_txn_1h !== "") payload.request_otp_block_txn_1h = parseFloat(form.request_otp_block_txn_1h);
      if (form.request_otp_block_network_risk !== "") payload.request_otp_block_network_risk = parseFloat(form.request_otp_block_network_risk);
      if (form.velocity_zscore_threshold !== "") payload.velocity_zscore_threshold = parseFloat(form.velocity_zscore_threshold);
      if (form.challenged_txn_1h_threshold !== "") payload.challenged_txn_1h_threshold = parseInt(form.challenged_txn_1h_threshold, 10);
      if (form.heuristic_amount_threshold !== "") payload.heuristic_amount_threshold = parseFloat(form.heuristic_amount_threshold);
      if (form.heuristic_velocity_1h_threshold !== "") payload.heuristic_velocity_1h_threshold = parseInt(form.heuristic_velocity_1h_threshold, 10);
      if (form.heuristic_suspicious_countries !== "") {
        payload.heuristic_suspicious_countries = form.heuristic_suspicious_countries
          .split(",")
          .map((s) => s.trim().toUpperCase())
          .filter(Boolean);
      }
      payload.dynamic_threshold_enabled = form.dynamic_threshold_enabled;
      if (form.dynamic_threshold_min_samples !== "") payload.dynamic_threshold_min_samples = parseInt(form.dynamic_threshold_min_samples, 10);
      if (form.dynamic_threshold_block_percentile !== "") payload.dynamic_threshold_block_percentile = parseFloat(form.dynamic_threshold_block_percentile);
      if (form.dynamic_threshold_otp_percentile !== "") payload.dynamic_threshold_otp_percentile = parseFloat(form.dynamic_threshold_otp_percentile);
      const res = await fetch(`${API_BASE}/api/v1/admin/tenants/${tenantId}/fraud-policy`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || res.statusText);
      setPolicy(data);
      setSaved(true);
      setTimeout(() => setSaved(false), 3000);
    } catch (err) {
      setError(err.message || "Failed to save");
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="p-8">
      <p className="text-slate-500 text-[11px] tracking-wider mb-4 uppercase">Fraud policy &amp; training</p>
      <div className="space-y-4">
        <div>
          <div className="flex gap-2 mb-2">
            <button
              type="button"
              onClick={loadTenants}
              disabled={loading}
              className="px-4 py-2 rounded-md border border-slate-600 text-xs tracking-wider uppercase text-slate-300 disabled:opacity-50"
            >
              {loading ? "Loading…" : "Load tenants"}
            </button>
            {tenants.length > 0 && (
              <select
                value={tenantId}
                onChange={(e) => setTenantId(e.target.value)}
                className="rounded-lg border border-slate-600 bg-slate-900 px-3 py-2 text-slate-200 text-sm min-w-[200px]"
              >
                {tenants.map((t) => (
                  <option key={t.id} value={t.id}>{t.name} ({t.country_code})</option>
                ))}
              </select>
            )}
          </div>
          {tenantId && (
            <button
              type="button"
              onClick={loadPolicy}
              disabled={loadingPolicy}
              className="px-3 py-1.5 rounded border border-slate-600 text-xs text-slate-400 hover:bg-slate-800 disabled:opacity-50"
            >
              {loadingPolicy ? "Loading…" : "Load policy"}
            </button>
          )}
        </div>
        {error && (
          <div className="rounded-lg border border-red-500/50 bg-red-500/10 px-4 py-2 text-sm text-red-300">{error}</div>
        )}
        {policy != null && (
          <form onSubmit={savePolicy} className="space-y-5 rounded-xl border border-slate-700 bg-slate-900/60 p-5">
            <div className="rounded-lg border border-cyan-500/30 bg-cyan-500/5 p-3">
              <label className="block text-[10px] text-cyan-300 uppercase mb-1">Policy preset</label>
              <div className="flex flex-wrap items-center gap-2">
                <select
                  value={preset}
                  onChange={(e) => setPreset(e.target.value)}
                  className="rounded border border-slate-600 bg-slate-900 px-3 py-2 text-slate-200 text-sm"
                >
                  {Object.entries(PRESETS).map(([k, p]) => (
                    <option key={k} value={k}>{p.label}</option>
                  ))}
                </select>
                <button
                  type="button"
                  onClick={() => setForm((f) => ({ ...f, ...PRESETS[preset].values }))}
                  className="px-3 py-2 rounded border border-cyan-400/70 text-xs text-cyan-200 hover:bg-cyan-500/10"
                >
                  Apply preset
                </button>
                <span className="text-xs text-slate-400">{PRESETS[preset].note}</span>
              </div>
            </div>
            <div className="rounded-xl border border-slate-700/90 bg-slate-950/40 p-4 space-y-3">
            <div className="flex items-center gap-2">
              <span className="inline-flex items-center rounded border border-slate-500/60 bg-slate-800/70 px-2 py-0.5 text-[10px] font-bold tracking-wider text-slate-200">GLOBAL</span>
              <div className="text-sm font-semibold text-slate-100">Global model mix & thresholds</div>
            </div>
            <div className="text-xs text-slate-400">Core model blending and base thresholds.</div>
            <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
              <div>
                <label className="block text-[10px] text-slate-500 uppercase mb-1">Model weight</label>
                <input type="number" step="0.01" value={form.model_weight} onChange={(e) => setForm((f) => ({ ...f, model_weight: e.target.value }))} className="w-full rounded border border-slate-600 bg-slate-900 px-3 py-2 text-slate-200 text-sm" />
              </div>
              <div>
                <label className="block text-[10px] text-slate-500 uppercase mb-1">ISO weight</label>
                <input type="number" step="0.01" value={form.iso_weight} onChange={(e) => setForm((f) => ({ ...f, iso_weight: e.target.value }))} className="w-full rounded border border-slate-600 bg-slate-900 px-3 py-2 text-slate-200 text-sm" />
              </div>
              <div>
                <label className="block text-[10px] text-slate-500 uppercase mb-1">Rule weight</label>
                <input type="number" step="0.01" value={form.rule_weight} onChange={(e) => setForm((f) => ({ ...f, rule_weight: e.target.value }))} className="w-full rounded border border-slate-600 bg-slate-900 px-3 py-2 text-slate-200 text-sm" />
              </div>
              <div>
                <label className="block text-[10px] text-slate-500 uppercase mb-1">Network weight</label>
                <input type="number" step="0.01" value={form.network_weight} onChange={(e) => setForm((f) => ({ ...f, network_weight: e.target.value }))} className="w-full rounded border border-slate-600 bg-slate-900 px-3 py-2 text-slate-200 text-sm" />
              </div>
              <div>
                <label className="block text-[10px] text-slate-500 uppercase mb-1">Block threshold</label>
                <input type="number" step="0.01" value={form.fraud_block_threshold} onChange={(e) => setForm((f) => ({ ...f, fraud_block_threshold: e.target.value }))} className="w-full rounded border border-slate-600 bg-slate-900 px-3 py-2 text-slate-200 text-sm" />
              </div>
              <div>
                <label className="block text-[10px] text-slate-500 uppercase mb-1">OTP threshold</label>
                <input type="number" step="0.01" value={form.fraud_otp_threshold} onChange={(e) => setForm((f) => ({ ...f, fraud_otp_threshold: e.target.value }))} className="w-full rounded border border-slate-600 bg-slate-900 px-3 py-2 text-slate-200 text-sm" />
              </div>
            </div>
            </div>
            <div className="rounded-xl border border-fuchsia-500/35 bg-fuchsia-500/5 p-4 space-y-3">
            <div className="flex items-center gap-2">
              <span className="inline-flex items-center rounded border border-fuchsia-400/70 bg-fuchsia-900/40 px-2 py-0.5 text-[10px] font-bold tracking-wider text-fuchsia-100">VELOCITY</span>
              <div className="text-sm font-bold text-fuchsia-200">ADAPTIVE VELOCITY CONTROLS</div>
            </div>
            <div className="text-xs text-fuchsia-100/70">Tune anomaly sensitivity to customer baseline and retry pressure.</div>
            <div className="grid grid-cols-1 md:grid-cols-2 gap-2">
              <div className={`rounded-md border px-2.5 py-1.5 text-[11px] ${velocityChipTone}`}>
                <span className="font-semibold">Velocity z-score:</span> {velocityStateLabel} <span className="opacity-80">(recommended 1.8 - 2.6)</span>
              </div>
              <div className={`rounded-md border px-2.5 py-1.5 text-[11px] ${challengedChipTone}`}>
                <span className="font-semibold">Challenged / 1h:</span> {challengedStateLabel} <span className="opacity-80">(recommended 2 - 5)</span>
              </div>
            </div>
            <div className={`rounded-md border px-3 py-2 text-[11px] ${guardrailTone}`}>
              {guardrailMessage}
            </div>
            <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
              <div>
                <label className="block text-[10px] text-slate-500 uppercase mb-1">Velocity z-score threshold</label>
                <input type="number" step="0.1" value={form.velocity_zscore_threshold} onChange={(e) => setForm((f) => ({ ...f, velocity_zscore_threshold: e.target.value }))} className="w-full rounded border border-slate-600 bg-slate-900 px-3 py-2 text-slate-200 text-sm" />
              </div>
              <div>
                <label className="block text-[10px] text-slate-500 uppercase mb-1">Challenged txn / 1h threshold</label>
                <input type="number" step="1" value={form.challenged_txn_1h_threshold} onChange={(e) => setForm((f) => ({ ...f, challenged_txn_1h_threshold: e.target.value }))} className="w-full rounded border border-slate-600 bg-slate-900 px-3 py-2 text-slate-200 text-sm" />
              </div>
            </div>
            <div className="grid grid-cols-1 md:grid-cols-3 gap-3 mt-2">
              <div className="md:col-span-1">
                <label className="block text-[10px] text-slate-500 uppercase mb-1">Heuristic amount threshold</label>
                <input type="number" step="1" value={form.heuristic_amount_threshold} onChange={(e) => setForm((f) => ({ ...f, heuristic_amount_threshold: e.target.value }))} className="w-full rounded border border-slate-600 bg-slate-900 px-3 py-2 text-slate-200 text-sm" />
              </div>
              <div className="md:col-span-1">
                <label className="block text-[10px] text-slate-500 uppercase mb-1">Heuristic velocity 1h</label>
                <input type="number" step="1" value={form.heuristic_velocity_1h_threshold} onChange={(e) => setForm((f) => ({ ...f, heuristic_velocity_1h_threshold: e.target.value }))} className="w-full rounded border border-slate-600 bg-slate-900 px-3 py-2 text-slate-200 text-sm" />
              </div>
              <div className="md:col-span-1">
                <label className="block text-[10px] text-slate-500 uppercase mb-1">Heuristic suspicious countries</label>
                <input type="text" value={form.heuristic_suspicious_countries} onChange={(e) => setForm((f) => ({ ...f, heuristic_suspicious_countries: e.target.value }))} placeholder="XX,RU,KP,IR" className="w-full rounded border border-slate-600 bg-slate-900 px-3 py-2 text-slate-200 text-sm" />
              </div>
            </div>
            <div className="mt-3">
              <label className="flex items-center gap-2 text-xs text-slate-300">
                <input
                  type="checkbox"
                  checked={form.dynamic_threshold_enabled}
                  onChange={(e) => setForm((f) => ({ ...f, dynamic_threshold_enabled: e.target.checked }))}
                  className="rounded border-slate-600"
                />
                Rolling percentile thresholds (segment + country + channel)
              </label>
              <div className="grid grid-cols-1 md:grid-cols-3 gap-3 mt-2">
                <div>
                  <label className="block text-[10px] text-slate-500 uppercase mb-1">Min samples</label>
                  <input
                    type="number"
                    step="1"
                    value={form.dynamic_threshold_min_samples}
                    disabled={!form.dynamic_threshold_enabled}
                    onChange={(e) => setForm((f) => ({ ...f, dynamic_threshold_min_samples: e.target.value }))}
                    className="w-full rounded border border-slate-600 bg-slate-900 px-3 py-2 text-slate-200 text-sm disabled:opacity-50"
                  />
                </div>
                <div>
                  <label className="block text-[10px] text-slate-500 uppercase mb-1">Block percentile</label>
                  <input
                    type="number"
                    step="0.01"
                    value={form.dynamic_threshold_block_percentile}
                    disabled={!form.dynamic_threshold_enabled}
                    onChange={(e) => setForm((f) => ({ ...f, dynamic_threshold_block_percentile: e.target.value }))}
                    className="w-full rounded border border-slate-600 bg-slate-900 px-3 py-2 text-slate-200 text-sm disabled:opacity-50"
                  />
                </div>
                <div>
                  <label className="block text-[10px] text-slate-500 uppercase mb-1">OTP percentile</label>
                  <input
                    type="number"
                    step="0.01"
                    value={form.dynamic_threshold_otp_percentile}
                    disabled={!form.dynamic_threshold_enabled}
                    onChange={(e) => setForm((f) => ({ ...f, dynamic_threshold_otp_percentile: e.target.value }))}
                    className="w-full rounded border border-slate-600 bg-slate-900 px-3 py-2 text-slate-200 text-sm disabled:opacity-50"
                  />
                </div>
              </div>
            </div>
            </div>

            <div className="rounded-xl border border-emerald-500/35 bg-emerald-500/5 p-4 space-y-3">
            <div className="flex items-center gap-2">
              <span className="inline-flex items-center rounded border border-emerald-400/70 bg-emerald-900/40 px-2 py-0.5 text-[10px] font-bold tracking-wider text-emerald-100">APPROVE</span>
              <div className="text-sm font-bold text-emerald-200">APPROVE DECISION CONTROLS</div>
            </div>
            <div className="text-xs text-emerald-100/70">Escalate APPROVE to OTP only when caps are exceeded.</div>
            <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
              <div>
                <label className="block text-[10px] text-slate-500 uppercase mb-1">Approve max amount</label>
                <input type="number" step="1" value={form.approve_max_amount} onChange={(e) => setForm((f) => ({ ...f, approve_max_amount: e.target.value }))} className="w-full rounded border border-slate-600 bg-slate-900 px-3 py-2 text-slate-200 text-sm" />
              </div>
              <div>
                <label className="block text-[10px] text-slate-500 uppercase mb-1">Approve max txn / 1h</label>
                <input type="number" step="1" value={form.approve_max_txn_1h} onChange={(e) => setForm((f) => ({ ...f, approve_max_txn_1h: e.target.value }))} className="w-full rounded border border-slate-600 bg-slate-900 px-3 py-2 text-slate-200 text-sm" />
              </div>
            </div>
            </div>

            <div className="rounded-xl border border-amber-500/35 bg-amber-500/5 p-4 space-y-3">
            <div className="flex items-center gap-2">
              <span className="inline-flex items-center rounded border border-amber-400/70 bg-amber-900/40 px-2 py-0.5 text-[10px] font-bold tracking-wider text-amber-100">OTP</span>
              <div className="text-sm font-bold text-amber-200">REQUEST_OTP DECISION CONTROLS</div>
            </div>
            <div className="text-xs text-amber-100/70">Escalate OTP challenges to BLOCK under hard-risk gates.</div>
            <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
              <div>
                <label className="block text-[10px] text-slate-500 uppercase mb-1">OTP->BLOCK amount cap</label>
                <input type="number" step="1" value={form.request_otp_block_amount} onChange={(e) => setForm((f) => ({ ...f, request_otp_block_amount: e.target.value }))} className="w-full rounded border border-slate-600 bg-slate-900 px-3 py-2 text-slate-200 text-sm" />
              </div>
              <div>
                <label className="block text-[10px] text-slate-500 uppercase mb-1">OTP->BLOCK txn / 1h cap</label>
                <input type="number" step="1" value={form.request_otp_block_txn_1h} onChange={(e) => setForm((f) => ({ ...f, request_otp_block_txn_1h: e.target.value }))} className="w-full rounded border border-slate-600 bg-slate-900 px-3 py-2 text-slate-200 text-sm" />
              </div>
              <div>
                <label className="block text-[10px] text-slate-500 uppercase mb-1">OTP->BLOCK network risk</label>
                <input type="number" step="0.01" value={form.request_otp_block_network_risk} onChange={(e) => setForm((f) => ({ ...f, request_otp_block_network_risk: e.target.value }))} className="w-full rounded border border-slate-600 bg-slate-900 px-3 py-2 text-slate-200 text-sm" />
              </div>
            </div>
            </div>

            <div className="rounded-xl border border-cyan-500/35 bg-cyan-500/5 p-4 space-y-3">
            <div className="flex items-center gap-2">
              <span className="inline-flex items-center rounded border border-cyan-400/70 bg-cyan-900/40 px-2 py-0.5 text-[10px] font-bold tracking-wider text-cyan-100">LIMITED</span>
              <div className="text-sm font-bold text-cyan-200">LIMITED_APPROVAL DECISION CONTROLS</div>
            </div>
            <div className="text-xs text-cyan-100/70">Caps and escalation for medium-risk approvals.</div>
            <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
              <div>
                <label className="block text-[10px] text-slate-500 uppercase mb-1">Limited max amount</label>
                <input type="number" step="1" value={form.limited_approval_max_amount} onChange={(e) => setForm((f) => ({ ...f, limited_approval_max_amount: e.target.value }))} className="w-full rounded border border-slate-600 bg-slate-900 px-3 py-2 text-slate-200 text-sm" />
              </div>
              <div>
                <label className="block text-[10px] text-slate-500 uppercase mb-1">Limited max txn / 1h</label>
                <input type="number" step="1" value={form.limited_approval_max_txn_1h} onChange={(e) => setForm((f) => ({ ...f, limited_approval_max_txn_1h: e.target.value }))} className="w-full rounded border border-slate-600 bg-slate-900 px-3 py-2 text-slate-200 text-sm" />
              </div>
              <div>
                <label className="block text-[10px] text-slate-500 uppercase mb-1">Limited escalate ratio</label>
                <input type="number" step="0.01" value={form.limited_approval_escalate_ratio} onChange={(e) => setForm((f) => ({ ...f, limited_approval_escalate_ratio: e.target.value }))} className="w-full rounded border border-slate-600 bg-slate-900 px-3 py-2 text-slate-200 text-sm" />
              </div>
              <div>
                <label className="block text-[10px] text-slate-500 uppercase mb-1">Limited network risk threshold</label>
                <input type="number" step="0.01" value={form.limited_approval_escalate_network_risk} onChange={(e) => setForm((f) => ({ ...f, limited_approval_escalate_network_risk: e.target.value }))} className="w-full rounded border border-slate-600 bg-slate-900 px-3 py-2 text-slate-200 text-sm" />
              </div>
            </div>
            </div>
            <div className="rounded-xl border border-slate-700/90 bg-slate-950/40 p-4 space-y-3">
            <div className="flex items-center gap-2">
              <span className="inline-flex items-center rounded border border-slate-500/60 bg-slate-800/70 px-2 py-0.5 text-[10px] font-bold tracking-wider text-slate-200">OPS</span>
              <div className="text-sm font-semibold text-slate-100">Operational switches</div>
            </div>
            {form.kill_switch && (
              <div className="rounded-md border border-red-500/60 bg-red-500/10 px-3 py-2 text-xs font-semibold text-red-200">
                Kill switch is ON: all transfers will be blocked regardless of other fields.
              </div>
            )}
            <label className="flex items-center gap-2 text-xs text-slate-300">
              <input type="checkbox" checked={form.shadow_mode} onChange={(e) => setForm((f) => ({ ...f, shadow_mode: e.target.checked }))} className="rounded border-slate-600" />
              Shadow mode
            </label>
            <label className="flex items-center gap-2 text-xs text-amber-300 font-medium">
              <input type="checkbox" checked={form.kill_switch} onChange={(e) => setForm((f) => ({ ...f, kill_switch: e.target.checked }))} className="rounded border-slate-600" />
              Kill switch (force BLOCK for all transactions)
            </label>
            </div>
            <button type="submit" disabled={loading} className="px-4 py-2 rounded-md border border-blue-500 bg-blue-900/50 text-blue-200 text-xs tracking-wider uppercase disabled:opacity-50">
              {loading ? "Saving…" : saved ? "Saved" : "Save policy"}
            </button>
          </form>
        )}
      </div>
      <div className="mt-6 pt-6 border-t border-slate-700">
        <TriggerFraudTrain />
      </div>
    </div>
  );
}

function TriggerFraudTrain() {
  const [loading, setLoading] = useState(false);
  const [message, setMessage] = useState(null);
  const [status, setStatus] = useState(null);
  const [polling, setPolling] = useState(false);
  const [pollMs, setPollMs] = useState(5000);
  const [pollStartAt, setPollStartAt] = useState(null);

  async function loadStatus() {
    try {
      const res = await fetch(`${API_BASE}/api/v1/admin/fraud-train-status`);
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || res.statusText);
      setStatus(data);
    } catch {
      // best-effort only
    }
  }

  useEffect(() => {
    loadStatus();
  }, []);

  // Visibility-aware polling with exponential backoff.
  useEffect(() => {
    if (!polling) return;
    let timeout = null;
    let cancelled = false;

    const tick = async () => {
      if (cancelled) return;
      // don't poll when tab is hidden
      if (typeof document !== "undefined" && document.visibilityState === "hidden") {
        timeout = setTimeout(tick, pollMs);
        return;
      }
      await loadStatus();
      timeout = setTimeout(tick, pollMs);
    };

    timeout = setTimeout(tick, pollMs);
    return () => {
      cancelled = true;
      if (timeout) clearTimeout(timeout);
    };
  }, [polling, pollMs]);

  useEffect(() => {
    if (!polling) return;
    const s = status?.state;
    if (s === "done" || s === "error") {
      setPolling(false);
      return;
    }
    if (!pollStartAt) return;
    const elapsed = Date.now() - pollStartAt;
    // 0-30s: 5s, 30-90s: 10s, 90-300s: 20s, 5m+: 30s
    const next =
      elapsed < 30_000 ? 5000 : elapsed < 90_000 ? 10_000 : elapsed < 300_000 ? 20_000 : 30_000;
    if (next !== pollMs) setPollMs(next);
    // stop polling after 15 minutes regardless
    if (elapsed > 15 * 60 * 1000) setPolling(false);
  }, [status, polling, pollStartAt, pollMs]);

  async function trigger() {
    setLoading(true);
    setMessage(null);
    try {
      const res = await fetch(`${API_BASE}/api/v1/admin/trigger-fraud-train`, { method: "POST" });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || data.message || res.statusText);
      setMessage(data.message || "Training started.");
      setPollStartAt(Date.now());
      setPollMs(5000);
      setPolling(true);
    } catch (err) {
      setMessage(err.message || "Request failed");
    } finally {
      setLoading(false);
    }
  }

  return (
    <div>
      <p className="text-[10px] text-slate-500 uppercase mb-2">Fraud model retrain</p>
      <button
        type="button"
        onClick={trigger}
        disabled={loading}
        className="px-4 py-2 rounded-md border border-amber-500/60 bg-amber-500/10 text-amber-200 text-xs tracking-wider uppercase disabled:opacity-50"
      >
        {loading ? "Starting…" : "Trigger fraud train"}
      </button>
      {message && <p className="mt-2 text-xs text-slate-400">{message}</p>}
      {status && (
        <p className="mt-1 text-[11px] text-slate-500">
          Status:{" "}
          <span className="text-slate-200">
            {status.state === "running"
              ? "Training in progress…"
              : status.state === "done"
              ? "Done"
              : status.state === "idle"
              ? "Idle"
              : status.state}
          </span>
          {status.started_at && (
            <> · started {new Date(status.started_at).toLocaleString()}</>
          )}
          {status.finished_at && status.state === "done" && (
            <> · finished {new Date(status.finished_at).toLocaleString()}</>
          )}
        </p>
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
  const [txForm, setTxForm] = useState({
    transaction_id: "",
    account_id: "",
    amount: 0,
    currency: "USD",
    merchant_category: "",
    location: "",
    device_id: "",
    ip_address: "",
  });
  const [txResult, setTxResult] = useState(null);
  const [txError, setTxError] = useState(null);
  const [txLoading, setTxLoading] = useState(false);
  const [stream, setStream] = useState([]);
  const [streamLoading, setStreamLoading] = useState(false);
  const [streamError, setStreamError] = useState(null);
  const [fraudSubTab, setFraudSubTab] = useState("main");
  const [networkGraph, setNetworkGraph] = useState(null);
  const [networkGraphLoading, setNetworkGraphLoading] = useState(false);
  const [rings, setRings] = useState([]);
  const [ringsLoading, setRingsLoading] = useState(false);
  const [ringsError, setRingsError] = useState(null);
  const [analytics, setAnalytics] = useState(null);
  const [analyticsLoading, setAnalyticsLoading] = useState(false);
  const [featureImp, setFeatureImp] = useState([]);
  const [featureImpLoading, setFeatureImpLoading] = useState(false);
  const [featureImpError, setFeatureImpError] = useState(null);
  const [reviewAlerts, setReviewAlerts] = useState([]);
  const [reviewAlertsLoading, setReviewAlertsLoading] = useState(false);
  const [reviewAlertsError, setReviewAlertsError] = useState(null);
  const [reviewTx, setReviewTx] = useState([]);
  const [reviewTxLoading, setReviewTxLoading] = useState(false);
  const [reviewTxError, setReviewTxError] = useState(null);
  const [reviewQueueMode, setReviewQueueMode] = useState("stepup-block");
  const [txDetail, setTxDetail] = useState(null);
  const [txDetailLoading, setTxDetailLoading] = useState(false);
  const [txDetailError, setTxDetailError] = useState(null);
  const [alertsPage, setAlertsPage] = useState(1);
  const [reviewAlertsPage, setReviewAlertsPage] = useState(1);
  const [reviewTxPage, setReviewTxPage] = useState(1);
  const pageSize = 20;

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
      setAlertsPage(1);
    } catch (err) {
      setAlertsError(err.message || "Failed to load alerts");
    } finally {
      setAlertsLoading(false);
    }
  }

  async function loadReviewQueue() {
    if (!apiKey.trim()) return;
    setReviewAlertsLoading(true);
    setReviewAlertsError(null);
    setReviewTxLoading(true);
    setReviewTxError(null);
    try {
      const aRes = await fetch(`${API_BASE}/api/v1/fraud/alerts?status=OPEN`, { headers: headers() });
      const aData = await aRes.json();
      if (!aRes.ok) throw new Error(aData.detail || aRes.statusText);
      setReviewAlerts(Array.isArray(aData) ? aData : []);
      setReviewAlertsPage(1);
    } catch (err) {
      setReviewAlerts([]);
      setReviewAlertsError(err.message || "Failed to load OPEN alerts");
    } finally {
      setReviewAlertsLoading(false);
    }
    try {
      const params = new URLSearchParams({ limit: "200" }).toString();
      const tRes = await fetch(`${API_BASE}/api/v1/fraud/transactions?${params}`, { headers: headers() });
      const tData = await tRes.json();
      if (!tRes.ok) throw new Error(tData.detail || tRes.statusText);
      const rows = Array.isArray(tData) ? tData : [];
      setReviewTx(
        rows.filter((r) =>
          ["REQUEST_OTP", "BLOCK", "SOFT_DECLINE", "MANUAL_REVIEW", "LIMITED_APPROVAL"].includes(r?.decision),
        ),
      );
      setReviewTxPage(1);
    } catch (err) {
      setReviewTx([]);
      setReviewTxError(err.message || "Failed to load transactions");
    } finally {
      setReviewTxLoading(false);
    }
  }

  async function closeAlert(alertId) {
    if (!apiKey.trim() || !alertId) return;
    try {
      const res = await fetch(`${API_BASE}/api/v1/fraud/alerts/${encodeURIComponent(alertId)}`, {
        method: "PATCH",
        headers: headers(),
        body: JSON.stringify({ status: "CLOSED" }),
      });
      const data = await res.json().catch(() => null);
      if (!res.ok) throw new Error(data?.detail || res.statusText);
      // Refresh both alert list and transaction preview.
      await loadReviewQueue();
    } catch (err) {
      setReviewAlertsError(err.message || "Failed to close alert");
    }
  }

  async function labelOutcomeAndClose({ alertId, transactionId, classification }) {
    if (!apiKey.trim() || !alertId || !transactionId || !classification) return;
    try {
      const res = await fetch(`${API_BASE}/api/v1/fraud/outcome`, {
        method: "POST",
        headers: headers(),
        body: JSON.stringify({
          transaction_id: transactionId,
          classification,
          source: "FRAUD_OPS",
          notes: null,
        }),
      });
      const data = await res.json().catch(() => null);
      if (!res.ok) throw new Error(data?.detail || res.statusText);
      await closeAlert(alertId);
    } catch (err) {
      setReviewAlertsError(err.message || "Failed to label fraud outcome");
    }
  }

  async function labelOutcomeAndRefresh({ transactionId, classification }) {
    if (!apiKey.trim() || !transactionId || !classification) return;
    try {
      const res = await fetch(`${API_BASE}/api/v1/fraud/outcome`, {
        method: "POST",
        headers: headers(),
        body: JSON.stringify({
          transaction_id: transactionId,
          classification,
          source: "FRAUD_OPS",
          notes: null,
        }),
      });
      const data = await res.json().catch(() => null);
      if (!res.ok) throw new Error(data?.detail || res.statusText);
      await loadReviewQueue();
    } catch (err) {
      setReviewTxError(err.message || "Failed to label fraud outcome");
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

  async function runTransactionScore(e) {
    e.preventDefault();
    if (!apiKey.trim()) return;
    setTxLoading(true);
    setTxError(null);
    setTxResult(null);
    try {
      const payload = {
        transaction_id: txForm.transaction_id || `demo-${Date.now()}`,
        account_id: txForm.account_id || "demo-account",
        amount: Number(txForm.amount) || 0,
        currency: txForm.currency || "USD",
        merchant_category: txForm.merchant_category || null,
        location: txForm.location || null,
        device_id: txForm.device_id || null,
        ip_address: txForm.ip_address || null,
        timestamp: new Date().toISOString(),
      };
      const res = await fetch(`${API_BASE}/api/v1/fraud/score/detail`, {
        method: "POST",
        headers: headers(),
        body: JSON.stringify(payload),
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || res.statusText);
      setTxResult(data);
    } catch (err) {
      setTxError(err.message || "Failed to score transaction");
    } finally {
      setTxLoading(false);
    }
  }

  async function loadStream() {
    if (!apiKey.trim()) return;
    setStreamLoading(true);
    setStreamError(null);
    try {
      const params = new URLSearchParams({ limit: "50" }).toString();
      const res = await fetch(`${API_BASE}/api/v1/fraud/transactions?${params}`, { headers: headers() });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || res.statusText);
      setStream(Array.isArray(data) ? data : []);
    } catch (err) {
      setStreamError(err.message || "Failed to load transactions");
    } finally {
      setStreamLoading(false);
    }
  }

  async function loadNetworkGraph() {
    if (!apiKey.trim()) return;
    setNetworkGraphLoading(true);
    try {
      const res = await fetch(`${API_BASE}/api/v1/fraud/network/graph?since_days=30`, { headers: headers() });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || res.statusText);
      setNetworkGraph(data);
    } catch (err) {
      setNetworkGraph({ error: err.message });
    } finally {
      setNetworkGraphLoading(false);
    }
  }

  async function loadRings() {
    if (!apiKey.trim()) return;
    setRingsLoading(true);
    setRingsError(null);
    try {
      const res = await fetch(`${API_BASE}/api/v1/fraud/network/rings?since_days=30`, { headers: headers() });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || res.statusText);
      setRings(Array.isArray(data) ? data : []);
    } catch (err) {
      setRings([]);
      setRingsError(err.message || "Failed to load rings");
    } finally {
      setRingsLoading(false);
    }
  }

  async function loadAnalytics() {
    if (!apiKey.trim()) return;
    setAnalyticsLoading(true);
    try {
      const res = await fetch(`${API_BASE}/api/v1/fraud/network/analytics?since_days=30`, { headers: headers() });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || res.statusText);
      setAnalytics(data);
    } catch (err) {
      setAnalytics({ error: err.message });
    } finally {
      setAnalyticsLoading(false);
    }
  }

  async function loadFeatureImportances() {
    if (!apiKey.trim()) return;
    setFeatureImpLoading(true);
    setFeatureImpError(null);
    try {
      const res = await fetch(`${API_BASE}/api/v1/fraud/feature-importances`, {
        headers: headers(),
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || res.statusText);
      setFeatureImp(Array.isArray(data) ? data : []);
    } catch (err) {
      setFeatureImpError(err.message || "Failed to load feature importances");
    } finally {
      setFeatureImpLoading(false);
    }
  }

  async function openTxDetail(transactionId) {
    if (!apiKey.trim() || !transactionId) return;
    setTxDetailLoading(true);
    setTxDetailError(null);
    try {
      const res = await fetch(`${API_BASE}/api/v1/fraud/transactions/${encodeURIComponent(transactionId)}/detail`, { headers: headers() });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || res.statusText);
      setTxDetail(data);
    } catch (err) {
      setTxDetail(null);
      setTxDetailError(err.message || "Failed to load transaction detail");
    } finally {
      setTxDetailLoading(false);
    }
  }

  const reviewQueueConfig = {
    "stepup-block": {
      alertTypes: ["FRAUD_RISK_BLOCK", "STEP_UP_REQUIRED"],
      decisions: ["BLOCK", "REQUEST_OTP"],
      label: "BLOCK / REQUEST_OTP",
    },
    "soft-decline": {
      alertTypes: ["SOFT_DECLINE_REVIEW"],
      decisions: ["SOFT_DECLINE"],
      label: "SOFT_DECLINE",
    },
    "manual-review": {
      alertTypes: ["MANUAL_REVIEW_QUEUE"],
      decisions: ["MANUAL_REVIEW"],
      label: "MANUAL_REVIEW",
    },
    "limited-approval": {
      alertTypes: ["LIMITED_APPROVAL_WATCH"],
      decisions: ["LIMITED_APPROVAL"],
      label: "LIMITED_APPROVAL",
    },
    all: {
      alertTypes: null,
      decisions: null,
      label: "ALL OPEN",
    },
  };

  const activeReviewCfg = reviewQueueConfig[reviewQueueMode] || reviewQueueConfig["stepup-block"];
  const filteredReviewAlerts = Array.isArray(reviewAlerts)
    ? reviewAlerts.filter((a) => !activeReviewCfg.alertTypes || activeReviewCfg.alertTypes.includes(a.alert_type))
    : [];
  const filteredReviewTx = Array.isArray(reviewTx)
    ? reviewTx.filter((t) => !activeReviewCfg.decisions || activeReviewCfg.decisions.includes(t.decision))
    : [];

  const severityPillClass = (sev) => {
    const s = String(sev || "").toUpperCase();
    if (s === "CRITICAL") return "border-red-500/70 bg-red-500/10 text-red-200";
    if (s === "HIGH") return "border-amber-500/70 bg-amber-500/10 text-amber-200";
    if (s === "MEDIUM") return "border-cyan-500/60 bg-cyan-500/10 text-cyan-200";
    if (s === "LOW") return "border-slate-600 bg-white/5 text-slate-200";
    return "border-slate-600 bg-white/5 text-slate-200";
  };

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
        {apiKey.trim() && (
          <p className="mt-2 text-xs text-slate-500">
            Viewing data for key: ***{apiKey.trim().slice(-4)}
          </p>
        )}
      </div>

      <div className="flex gap-2 flex-wrap border-b border-slate-800/70 pb-3">
        {["main", "review-queue", "network-graph", "ring-alerts", "network-analytics"].map((tab) => (
          <button
            key={tab}
            type="button"
            onClick={() => setFraudSubTab(tab)}
            className={`px-3.5 py-2 rounded-full text-[11px] uppercase tracking-[0.18em] transition ${
              fraudSubTab === tab
                ? "text-slate-900 bg-gradient-to-r from-cyan-300 to-emerald-300 shadow-[0_8px_30px_rgba(56,189,248,0.18)]"
                : "text-slate-400 hover:text-slate-200 bg-white/0 hover:bg-white/5"
            }`}
          >
            {tab === "main"
              ? "Alerts & Simulator"
              : tab === "review-queue"
              ? "OTP / Blocked"
              : tab.replace(/-/g, " ")}
          </button>
        ))}
      </div>

      {txDetail && (
        <div className="rounded-2xl border border-slate-800 bg-slate-950/60 p-5">
          <div className="flex items-center justify-between gap-3 mb-3">
            <div>
              <p className="text-[10px] text-slate-400 uppercase tracking-wider">Transaction detail</p>
              <p className="text-xs text-slate-500">{txDetail.transaction_id}</p>
            </div>
            <button
              type="button"
              onClick={() => setTxDetail(null)}
              className="px-3 py-1.5 rounded-md border border-slate-600 text-xs text-slate-300 hover:bg-white/5"
            >
              Close
            </button>
          </div>

          {txDetailError && <p className="text-xs text-red-400 mb-2">{txDetailError}</p>}
          {txDetailLoading && <p className="text-xs text-slate-500">Loading…</p>}

          <div className="grid grid-cols-1 md:grid-cols-3 gap-3 text-xs">
            <div className="rounded-xl border border-slate-800 bg-slate-950/60 p-3">
              <p className="text-[10px] text-slate-500 uppercase mb-1">Decision</p>
              <p className="text-slate-100 font-semibold">{txDetail.decision ?? "—"}</p>
              <p className="text-slate-500 text-[11px]">Score: {txDetail.fraud_score ?? "—"}</p>
              <p className="text-slate-500 text-[11px]">Confidence: {txDetail.confidence ?? "—"}</p>
            </div>
            <div className="rounded-xl border border-slate-800 bg-slate-950/60 p-3">
              <p className="text-[10px] text-slate-500 uppercase mb-1">Transaction</p>
              <p className="text-slate-200">{txDetail.currency} {Number(txDetail.amount || 0).toFixed(2)}</p>
              <p className="text-slate-500 text-[11px]">Account: {txDetail.account_id}</p>
              <p className="text-slate-500 text-[11px]">Status: {txDetail.status}</p>
            </div>
            <div className="rounded-xl border border-slate-800 bg-slate-950/60 p-3">
              <p className="text-[10px] text-slate-500 uppercase mb-1">Meta</p>
              <p className="text-slate-500 text-[11px]">MCC: {txDetail.merchant_category ?? "—"}</p>
              <p className="text-slate-500 text-[11px]">Location: {txDetail.location_country ?? "—"}</p>
              <p className="text-slate-500 text-[11px]">Time: {txDetail.tx_timestamp ? new Date(txDetail.tx_timestamp).toLocaleString() : "—"}</p>
            </div>
          </div>

          {Array.isArray(txDetail.reasons) && txDetail.reasons.length > 0 && (
            <div className="mt-4 rounded-xl border border-slate-800 bg-slate-950/60 p-3 text-xs">
              <p className="text-[10px] text-slate-500 uppercase mb-2">Reasons</p>
              <div className="flex flex-wrap gap-2">
                {txDetail.reasons.map((r, i) => (
                  <span key={i} className="px-2 py-1 rounded-full bg-white/5 border border-slate-700 text-slate-200">
                    {r}
                  </span>
                ))}
              </div>
            </div>
          )}

          <div className="mt-4 grid grid-cols-1 md:grid-cols-2 gap-3 text-xs">
            <div className="rounded-xl border border-slate-800 bg-slate-950/60 p-3">
              <p className="text-[10px] text-slate-500 uppercase mb-2">Scores</p>
              <p className="text-slate-400">LGBM: <span className="text-slate-200">{txDetail.lgbm_score ?? "—"}</span></p>
              <p className="text-slate-400">Anomaly: <span className="text-slate-200">{txDetail.anomaly_score ?? "—"}</span></p>
              <p className="text-slate-400">Rule: <span className="text-slate-200">{txDetail.rule_score ?? "—"}</span></p>
              <p className="text-slate-400">Model version: <span className="text-slate-200">{txDetail.model_version ?? "—"}</span></p>
              <p className="text-slate-400">Latency: <span className="text-slate-200">{txDetail.processing_time_ms ?? "—"}ms</span></p>
            </div>
            <div className="rounded-xl border border-slate-800 bg-slate-950/60 p-3">
              <p className="text-[10px] text-slate-500 uppercase mb-2">Raw</p>
              <details className="text-slate-300">
                <summary className="cursor-pointer text-slate-400 hover:text-slate-200">Feature vector</summary>
                <pre className="mt-2 text-[11px] overflow-auto max-h-64 bg-black/30 p-2 rounded border border-slate-800">{JSON.stringify(txDetail.feature_vector || {}, null, 2)}</pre>
              </details>
              <details className="text-slate-300 mt-2">
                <summary className="cursor-pointer text-slate-400 hover:text-slate-200">SHAP values</summary>
                <pre className="mt-2 text-[11px] overflow-auto max-h-64 bg-black/30 p-2 rounded border border-slate-800">{JSON.stringify(txDetail.shap_values || {}, null, 2)}</pre>
              </details>
            </div>
          </div>
        </div>
      )}

      {fraudSubTab === "review-queue" && (
        <div className="space-y-6">
          <div className="flex items-start justify-between gap-3 flex-wrap">
            <div className="space-y-2">
              <h3 className="text-sm font-semibold text-slate-200">Fraud Review Queue</h3>
              <div className="flex flex-wrap gap-2">
                {[
                  ["stepup-block", "Step-up / Block"],
                  ["soft-decline", "Soft decline"],
                  ["manual-review", "Manual review"],
                  ["limited-approval", "Limited approval"],
                  ["all", "All open"],
                ].map(([mode, label]) => (
                  <button
                    key={mode}
                    type="button"
                    onClick={() => { setReviewQueueMode(mode); setReviewAlertsPage(1); setReviewTxPage(1); }}
                    className={`px-3 py-1 rounded border text-[11px] uppercase tracking-wider transition ${
                      reviewQueueMode === mode
                        ? "border-cyan-400/60 bg-cyan-400/10 text-cyan-200"
                        : "border-slate-600 bg-white/0 text-slate-400 hover:bg-white/5"
                    }`}
                  >
                    {label}
                  </button>
                ))}
              </div>
            </div>
            <button
              type="button"
              onClick={loadReviewQueue}
              disabled={!apiKey.trim() || reviewAlertsLoading || reviewTxLoading}
              className="px-3 py-1.5 rounded border border-slate-600 text-xs text-slate-400 hover:bg-slate-800 disabled:opacity-50 h-fit"
            >
              {(reviewAlertsLoading || reviewTxLoading) ? "Loading…" : "Refresh"}
            </button>
          </div>

          <div className="rounded-lg border border-slate-700 bg-slate-900/60 overflow-hidden">
            <div className="px-4 py-3 border-b border-slate-700">
              <p className="text-[10px] text-slate-500 uppercase tracking-wider">OPEN fraud alerts ({activeReviewCfg.label})</p>
            </div>
            {reviewAlertsError && <p className="px-4 py-3 text-xs text-red-400">{reviewAlertsError}</p>}
            <table className="w-full text-left text-xs">
              <thead>
                <tr className="border-b border-slate-700 text-slate-500 uppercase tracking-wider">
                  <th className="p-3">Alert</th>
                  <th className="p-3">Transaction</th>
                  <th className="p-3">Account</th>
                  <th className="p-3">Severity</th>
                  <th className="p-3">Action</th>
                  <th className="p-3">Created</th>
                </tr>
              </thead>
              <tbody>
                {filteredReviewAlerts.length === 0 && !reviewAlertsLoading && (
                  <tr><td colSpan={6} className="p-4 text-slate-500">No OPEN alerts.</td></tr>
                )}
                {filteredReviewAlerts
                  .slice((reviewAlertsPage - 1) * pageSize, reviewAlertsPage * pageSize)
                  .map((a) => (
                  <tr
                    key={a.alert_id}
                    className="border-b border-slate-800 hover:bg-white/5 cursor-pointer"
                    onClick={() => openTxDetail(a.transaction_id)}
                  >
                    <td className="p-3 font-mono text-slate-400">{String(a.alert_id).slice(0, 8)}…</td>
                    <td className="p-3 font-mono">{String(a.transaction_id).slice(0, 8)}…</td>
                    <td className="p-3">{a.account_id ?? "—"}</td>
                    <td className="p-3">
                      <span className={`inline-flex items-center px-2 py-0.5 rounded border ${severityPillClass(a.severity)}`}>
                        {a.severity}
                      </span>
                    </td>
                    <td className="p-3">
                      <div className="flex flex-wrap gap-2 items-center">
                        <button
                          type="button"
                          onClick={(e) => { e.stopPropagation(); labelOutcomeAndClose({ alertId: a.alert_id, transactionId: a.transaction_id, classification: "CONFIRMED_FRAUD" }); }}
                          className="px-2 py-1 rounded border border-red-500/60 text-[11px] text-red-200 hover:bg-red-500/10"
                        >
                          Fraud
                        </button>
                        <button
                          type="button"
                          onClick={(e) => { e.stopPropagation(); labelOutcomeAndClose({ alertId: a.alert_id, transactionId: a.transaction_id, classification: "FALSE_POSITIVE" }); }}
                          className="px-2 py-1 rounded border border-amber-500/60 text-[11px] text-amber-200 hover:bg-amber-500/10"
                        >
                          False +
                        </button>
                        <button
                          type="button"
                          onClick={(e) => { e.stopPropagation(); labelOutcomeAndClose({ alertId: a.alert_id, transactionId: a.transaction_id, classification: "CONFIRMED_LEGIT" }); }}
                          className="px-2 py-1 rounded border border-emerald-500/60 text-[11px] text-emerald-200 hover:bg-emerald-500/10"
                        >
                          Legit
                        </button>
                        <button
                          type="button"
                          onClick={(e) => { e.stopPropagation(); closeAlert(a.alert_id); }}
                          className="px-2 py-1 rounded border border-slate-600 text-[11px] text-slate-300 hover:bg-white/5"
                        >
                          Close
                        </button>
                      </div>
                    </td>
                    <td className="p-3 text-slate-500">{a.created_at ? new Date(a.created_at).toLocaleString() : "—"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
            {filteredReviewAlerts.length > pageSize && (
              <div className="flex justify-end items-center gap-3 px-4 py-2 border-t border-slate-800 text-[11px] text-slate-500">
                <span>
                  Page {reviewAlertsPage} of {Math.ceil(filteredReviewAlerts.length / pageSize)}
                </span>
                <div className="flex gap-2">
                  <button
                    type="button"
                    disabled={reviewAlertsPage === 1}
                    onClick={() => setReviewAlertsPage((p) => Math.max(1, p - 1))}
                    className="px-2 py-1 rounded border border-slate-600 disabled:opacity-40"
                  >
                    Prev
                  </button>
                  <button
                    type="button"
                    disabled={reviewAlertsPage >= Math.ceil(filteredReviewAlerts.length / pageSize)}
                    onClick={() =>
                      setReviewAlertsPage((p) => Math.min(Math.ceil(filteredReviewAlerts.length / pageSize), p + 1))
                    }
                    className="px-2 py-1 rounded border border-slate-600 disabled:opacity-40"
                  >
                    Next
                  </button>
                </div>
              </div>
            )}
          </div>

          <div className="rounded-lg border border-slate-700 bg-slate-900/60 overflow-hidden">
            <div className="px-4 py-3 border-b border-slate-700">
              <p className="text-[10px] text-slate-500 uppercase tracking-wider">Recent scored transactions (filtered: {activeReviewCfg.label})</p>
            </div>
            {reviewTxError && <p className="px-4 py-3 text-xs text-red-400">{reviewTxError}</p>}
            <table className="w-full text-left text-xs">
              <thead>
                <tr className="border-b border-slate-700 text-slate-500 uppercase tracking-wider">
                  <th className="p-3">Time</th>
                  <th className="p-3">Account</th>
                  <th className="p-3">Amount</th>
                  <th className="p-3">Decision</th>
                  <th className="p-3">Score</th>
                  <th className="p-3">Status</th>
                  <th className="p-3">Actions</th>
                </tr>
              </thead>
              <tbody>
                {filteredReviewTx.length === 0 && !reviewTxLoading && (
                  <tr><td colSpan={7} className="p-4 text-slate-500">No {activeReviewCfg.label} decisions in last 200.</td></tr>
                )}
                {filteredReviewTx
                  .slice((reviewTxPage - 1) * pageSize, reviewTxPage * pageSize)
                  .map((t) => (
                  <tr
                    key={t.transaction_id}
                    className="border-b border-slate-800 hover:bg-white/5 cursor-pointer"
                    onClick={() => openTxDetail(t.transaction_id)}
                  >
                    <td className="p-3 text-slate-500">{t.created_at ? new Date(t.created_at).toLocaleString() : "—"}</td>
                    <td className="p-3">{t.account_id ?? "—"}</td>
                    <td className="p-3">{t.currency} {Number(t.amount || 0).toFixed(2)}</td>
                    <td className="p-3">{t.decision ?? "—"}</td>
                    <td className="p-3">{typeof t.fraud_score === "number" ? t.fraud_score.toFixed(3) : (t.fraud_score ?? "—")}</td>
                    <td className="p-3">{t.status ?? "—"}</td>
                    <td className="p-3">
                      <div className="flex flex-wrap gap-2 items-center">
                        <button
                          type="button"
                          onClick={(e) => { e.stopPropagation(); labelOutcomeAndRefresh({ transactionId: t.transaction_id, classification: "CONFIRMED_FRAUD" }); }}
                          className="px-2 py-1 rounded border border-red-500/60 text-[11px] text-red-200 hover:bg-red-500/10"
                        >
                          Fraud
                        </button>
                        <button
                          type="button"
                          onClick={(e) => { e.stopPropagation(); labelOutcomeAndRefresh({ transactionId: t.transaction_id, classification: "FALSE_POSITIVE" }); }}
                          className="px-2 py-1 rounded border border-amber-500/60 text-[11px] text-amber-200 hover:bg-amber-500/10"
                        >
                          False +
                        </button>
                        <button
                          type="button"
                          onClick={(e) => { e.stopPropagation(); labelOutcomeAndRefresh({ transactionId: t.transaction_id, classification: "CONFIRMED_LEGIT" }); }}
                          className="px-2 py-1 rounded border border-emerald-500/60 text-[11px] text-emerald-200 hover:bg-emerald-500/10"
                        >
                          Legit
                        </button>
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
            {filteredReviewTx.length > pageSize && (
              <div className="flex justify-end items-center gap-3 px-4 py-2 border-t border-slate-800 text-[11px] text-slate-500">
                <span>
                  Page {reviewTxPage} of {Math.ceil(filteredReviewTx.length / pageSize)}
                </span>
                <div className="flex gap-2">
                  <button
                    type="button"
                    disabled={reviewTxPage === 1}
                    onClick={() => setReviewTxPage((p) => Math.max(1, p - 1))}
                    className="px-2 py-1 rounded border border-slate-600 disabled:opacity-40"
                  >
                    Prev
                  </button>
                  <button
                    type="button"
                    disabled={reviewTxPage >= Math.ceil(filteredReviewTx.length / pageSize)}
                    onClick={() =>
                      setReviewTxPage((p) => Math.min(Math.ceil(filteredReviewTx.length / pageSize), p + 1))
                    }
                    className="px-2 py-1 rounded border border-slate-600 disabled:opacity-40"
                  >
                    Next
                  </button>
                </div>
              </div>
            )}
          </div>
        </div>
      )}

      {fraudSubTab === "network-graph" && (
        <div>
          <div className="flex items-center gap-3 mb-3">
            <h3 className="text-sm font-semibold text-slate-200">Fraud Network Graph</h3>
            <button
              type="button"
              onClick={loadNetworkGraph}
              disabled={!apiKey.trim() || networkGraphLoading}
              className="px-3 py-1.5 rounded border border-slate-600 text-xs text-slate-400 hover:bg-slate-800 disabled:opacity-50"
            >
              {networkGraphLoading ? "Loading…" : "Load graph"}
            </button>
          </div>
          {networkGraph?.error && <p className="text-xs text-red-400 mb-2">{networkGraph.error}</p>}
          {networkGraph?.nodes && (
            <div className="rounded-lg border border-slate-700 bg-slate-900/60 p-4 space-y-4">
              <div>
                <p className="text-[10px] text-slate-500 uppercase tracking-wider mb-2">Nodes ({networkGraph.nodes.length})</p>
                <div className="flex flex-wrap gap-2">
                  {networkGraph.nodes.slice(0, 80).map((n) => (
                    <span
                      key={n.id}
                      className={`px-2 py-1 rounded text-[11px] font-mono ${
                        n.type === "device" ? "bg-amber-500/20 text-amber-300" :
                        n.type === "ip" ? "bg-blue-500/20 text-blue-300" :
                        n.type === "merchant" ? "bg-purple-500/20 text-purple-300" : "bg-slate-600/50 text-slate-300"
                      }`}
                    >
                      {n.type}: {String(n.id).replace(/^(acc|dev|ip|merchant):/, "")}
                    </span>
                  ))}
                  {networkGraph.nodes.length > 80 && <span className="text-slate-500 text-xs">+{networkGraph.nodes.length - 80} more</span>}
                </div>
              </div>
              <div>
                <p className="text-[10px] text-slate-500 uppercase tracking-wider mb-2">Edges ({networkGraph.edges.length})</p>
                <div className="flex flex-wrap gap-2 text-[11px] font-mono text-slate-400">
                  {networkGraph.edges.slice(0, 50).map((e, i) => (
                    <span key={i} className="px-2 py-1 rounded bg-slate-800/70">{e.source} → {e.target}</span>
                  ))}
                  {networkGraph.edges.length > 50 && <span className="text-slate-500">+{networkGraph.edges.length - 50} more</span>}
                </div>
              </div>
            </div>
          )}
          {!networkGraph?.nodes && !networkGraph?.error && !networkGraphLoading && (
            <p className="text-xs text-slate-500">Click &quot;Load graph&quot; to fetch accounts, devices, IPs, merchants.</p>
          )}
        </div>
      )}

      {fraudSubTab === "ring-alerts" && (
        <div>
          <div className="flex items-center gap-3 mb-3">
            <h3 className="text-sm font-semibold text-slate-200">Fraud Ring Alerts</h3>
            <button
              type="button"
              onClick={loadRings}
              disabled={!apiKey.trim() || ringsLoading}
              className="px-3 py-1.5 rounded border border-slate-600 text-xs text-slate-400 hover:bg-slate-800 disabled:opacity-50"
            >
              {ringsLoading ? "Loading…" : "Refresh"}
            </button>
          </div>
          {ringsError && <p className="text-xs text-red-400 mb-2">{ringsError}</p>}
          <div className="rounded-lg border border-slate-700 bg-slate-900/60 overflow-hidden">
            <table className="w-full text-left text-xs">
              <thead>
                <tr className="border-b border-slate-700 text-slate-500 uppercase tracking-wider">
                  <th className="p-3">Type</th>
                  <th className="p-3">Entity ID</th>
                  <th className="p-3">Account count</th>
                  <th className="p-3">Size / nodes</th>
                </tr>
              </thead>
              <tbody>
                {rings.length === 0 && !ringsLoading && (
                  <tr><td colSpan={4} className="p-4 text-slate-500">No rings detected (yet). Generate cross-account reuse (same device/IP across 3+ accounts) then refresh.</td></tr>
                )}
                {rings.map((r, i) => (
                  <tr key={i} className="border-b border-slate-800">
                    <td className="p-3">{r.type}</td>
                    <td className="p-3 font-mono">{r.entity_id ?? "—"}</td>
                    <td className="p-3">{r.account_count ?? "—"}</td>
                    <td className="p-3">{r.size ?? (r.nodes?.length ? String(r.nodes.length) : "—")}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {fraudSubTab === "network-analytics" && (
        <div>
          <div className="flex items-center gap-3 mb-3">
            <h3 className="text-sm font-semibold text-slate-200">Network Risk Analytics</h3>
            <button
              type="button"
              onClick={loadAnalytics}
              disabled={!apiKey.trim() || analyticsLoading}
              className="px-3 py-1.5 rounded border border-slate-600 text-xs text-slate-400 hover:bg-slate-800 disabled:opacity-50"
            >
              {analyticsLoading ? "Loading…" : "Refresh"}
            </button>
          </div>
          {analytics?.error && <p className="text-xs text-red-400 mb-2">{analytics.error}</p>}
          {analytics?.accounts_per_device && (
            <div className="space-y-6">
              <div className="rounded-lg border border-slate-700 bg-slate-900/60 p-4">
                <p className="text-[10px] text-slate-500 uppercase tracking-wider mb-2">Accounts per device (top 20)</p>
                <ul className="space-y-1 text-xs">
                  {analytics.accounts_per_device.slice(0, 20).map((d, i) => (
                    <li key={i} className="flex justify-between"><span className="font-mono text-slate-400">{d.device_id}</span><span>{d.account_count}</span></li>
                  ))}
                </ul>
              </div>
              <div className="rounded-lg border border-slate-700 bg-slate-900/60 p-4">
                <p className="text-[10px] text-slate-500 uppercase tracking-wider mb-2">Shared IP usage (top 20)</p>
                <ul className="space-y-1 text-xs">
                  {analytics.shared_ip_usage?.slice(0, 20).map((s, i) => (
                    <li key={i} className="flex justify-between"><span className="font-mono text-slate-400">{s.ip}</span><span>{s.account_count}</span></li>
                  ))}
                </ul>
              </div>
              <div className="rounded-lg border border-slate-700 bg-slate-900/60 p-4">
                <p className="text-[10px] text-slate-500 uppercase tracking-wider mb-2">Fraud clusters</p>
                <ul className="space-y-1 text-xs">
                  {(analytics.fraud_clusters || []).map((c, i) => (
                    <li key={i}>{c.type}: {c.entity_id ?? "—"} ({c.account_count ?? 0} accounts)</li>
                  ))}
                  {(!analytics.fraud_clusters || analytics.fraud_clusters.length === 0) && <li className="text-slate-500">None</li>}
                </ul>
              </div>
              <div className="rounded-lg border border-slate-700 bg-slate-900/60 p-4">
                <p className="text-[10px] text-slate-500 uppercase tracking-wider mb-2">High-risk merchants</p>
                <ul className="space-y-1 text-xs">
                  {(analytics.high_risk_merchants || []).slice(0, 20).map((m, i) => (
                    <li key={i} className="flex justify-between"><span className="font-mono text-slate-400">{m.merchant_id}</span><span>{(m.fraud_rate * 100).toFixed(1)}% ({m.total_transactions} tx)</span></li>
                  ))}
                  {(!analytics.high_risk_merchants || analytics.high_risk_merchants.length === 0) && <li className="text-slate-500">None</li>}
                </ul>
              </div>
            </div>
          )}
          {!analytics?.accounts_per_device && !analytics?.error && !analyticsLoading && (
            <p className="text-xs text-slate-500">Click &quot;Refresh&quot; to load network analytics.</p>
          )}
        </div>
      )}

      {fraudSubTab === "main" && (
      <>
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
              {alerts
                .slice((alertsPage - 1) * pageSize, alertsPage * pageSize)
                .map((a) => (
                <tr
                  key={a.alert_id}
                  className="border-b border-slate-800 hover:bg-white/5 cursor-pointer"
                  onClick={() => openTxDetail(a.transaction_id)}
                >
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
          {alerts.length > pageSize && (
            <div className="flex justify-end items-center gap-3 px-4 py-2 border-t border-slate-800 text-[11px] text-slate-500">
              <span>
                Page {alertsPage} of {Math.ceil(alerts.length / pageSize)}
              </span>
              <div className="flex gap-2">
                <button
                  type="button"
                  disabled={alertsPage === 1}
                  onClick={() => setAlertsPage((p) => Math.max(1, p - 1))}
                  className="px-2 py-1 rounded border border-slate-600 disabled:opacity-40"
                >
                  Prev
                </button>
                <button
                  type="button"
                  disabled={alertsPage >= Math.ceil(alerts.length / pageSize)}
                  onClick={() =>
                    setAlertsPage((p) => Math.min(Math.ceil(alerts.length / pageSize), p + 1))
                  }
                  className="px-2 py-1 rounded border border-slate-600 disabled:opacity-40"
                >
                  Next
                </button>
              </div>
            </div>
          )}
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

      <div>
        <h3 className="text-sm font-semibold text-slate-200 mb-3">Transaction Fraud Simulator</h3>
        <form onSubmit={runTransactionScore} className="grid grid-cols-1 md:grid-cols-3 gap-3 mb-3 text-xs">
          <input
            type="text"
            placeholder="Account ID"
            value={txForm.account_id}
            onChange={(e) => setTxForm((f) => ({ ...f, account_id: e.target.value }))}
            className="rounded-lg border border-slate-600 bg-slate-900 px-3 py-2 text-slate-200"
          />
          <input
            type="number"
            step="0.01"
            placeholder="Amount"
            value={txForm.amount}
            onChange={(e) => setTxForm((f) => ({ ...f, amount: e.target.value }))}
            className="rounded-lg border border-slate-600 bg-slate-900 px-3 py-2 text-slate-200"
          />
          <input
            type="text"
            placeholder="Currency (USD)"
            value={txForm.currency}
            onChange={(e) => setTxForm((f) => ({ ...f, currency: e.target.value }))}
            className="rounded-lg border border-slate-600 bg-slate-900 px-3 py-2 text-slate-200"
          />
          <input
            type="text"
            placeholder="Merchant category (e.g. GAMBLING)"
            value={txForm.merchant_category}
            onChange={(e) => setTxForm((f) => ({ ...f, merchant_category: e.target.value }))}
            className="rounded-lg border border-slate-600 bg-slate-900 px-3 py-2 text-slate-200"
          />
          <input
            type="text"
            placeholder="Location country code (e.g. GH)"
            value={txForm.location}
            onChange={(e) => setTxForm((f) => ({ ...f, location: e.target.value }))}
            className="rounded-lg border border-slate-600 bg-slate-900 px-3 py-2 text-slate-200"
          />
          <input
            type="text"
            placeholder="Device ID"
            value={txForm.device_id}
            onChange={(e) => setTxForm((f) => ({ ...f, device_id: e.target.value }))}
            className="rounded-lg border border-slate-600 bg-slate-900 px-3 py-2 text-slate-200"
          />
          <input
            type="text"
            placeholder="IP address (optional)"
            value={txForm.ip_address}
            onChange={(e) => setTxForm((f) => ({ ...f, ip_address: e.target.value }))}
            className="rounded-lg border border-slate-600 bg-slate-900 px-3 py-2 text-slate-200"
          />
          <button
            type="submit"
            disabled={!apiKey.trim() || txLoading}
            className="md:col-span-3 px-4 py-2 rounded border border-slate-600 text-xs uppercase text-slate-300 disabled:opacity-50"
          >
            {txLoading ? "Scoring…" : "Score transaction"}
          </button>
        </form>
        {txError && <p className="text-xs text-red-400 mb-2">{txError}</p>}
        {txResult && (
          <div className="rounded-lg border border-slate-700 bg-slate-900/60 p-4 text-xs space-y-1">
            <p><span className="text-slate-500">Decision:</span> {txResult.decision}</p>
            <p><span className="text-slate-500">Risk score:</span> {txResult.risk_score}</p>
            <p><span className="text-slate-500">Model score:</span> {txResult.model_score}</p>
            <p><span className="text-slate-500">Anomaly score:</span> {txResult.anomaly_score ?? "—"}</p>
            <p><span className="text-slate-500">Rule score:</span> {txResult.rule_score}</p>
            {txResult.network_risk_score != null && <p><span className="text-slate-500">Network risk score:</span> {txResult.network_risk_score}</p>}
            <p><span className="text-slate-500">Reasons:</span> {txResult.reasons?.join("; ")}</p>
          </div>
        )}
      </div>

      <div>
        <div className="flex items-center gap-3 mb-3 mt-6">
          <h3 className="text-sm font-semibold text-slate-200">Model Feature Importance</h3>
          <button
            type="button"
            onClick={loadFeatureImportances}
            disabled={!apiKey.trim() || featureImpLoading}
            className="px-3 py-1.5 rounded border border-slate-600 text-xs text-slate-400 hover:bg-slate-800 disabled:opacity-50"
          >
            {featureImpLoading ? "Loading…" : featureImp.length ? "Refresh" : "Load"}
          </button>
        </div>
        {featureImpError && <p className="text-xs text-red-400 mb-2">{featureImpError}</p>}
        {featureImp.length > 0 && (
          <div className="rounded-lg border border-slate-700 bg-slate-900/60 p-4">
            <p className="text-[10px] text-slate-500 uppercase tracking-wider mb-2">Top features (by gain)</p>
            <ul className="space-y-1 text-xs">
              {featureImp.slice(0, 20).map((f, i) => (
                <li key={f.feature} className="flex items-center gap-2">
                  <span className="w-6 text-right text-slate-500">{String(i + 1).padStart(2, "0")}.</span>
                  <span className="flex-1 font-mono text-slate-300">{f.feature}</span>
                  <span className="text-slate-400">{f.importance_gain.toFixed(3)}</span>
                </li>
              ))}
            </ul>
          </div>
        )}
        {!featureImp.length && !featureImpError && !featureImpLoading && (
          <p className="text-xs text-slate-500">Click &quot;Load&quot; to fetch feature importances from the latest trained model.</p>
        )}
      </div>

      <div>
        <div className="flex items-center gap-3 mb-3 mt-6">
          <h3 className="text-sm font-semibold text-slate-200">Recent Transactions (Monitor)</h3>
          <button
            type="button"
            onClick={loadStream}
            disabled={!apiKey.trim() || streamLoading}
            className="px-3 py-1.5 rounded border border-slate-600 text-xs text-slate-400 hover:bg-slate-800 disabled:opacity-50"
          >
            {streamLoading ? "Loading…" : "Refresh"}
          </button>
        </div>
        {streamError && <p className="text-xs text-red-400 mb-2">{streamError}</p>}
        <div className="rounded-lg border border-slate-700 bg-slate-900/60 overflow-hidden">
          <table className="w-full text-left text-xs">
            <thead>
              <tr className="border-b border-slate-700 text-slate-500 uppercase tracking-wider">
                <th className="p-3">Time</th>
                <th className="p-3">Account</th>
                <th className="p-3">Amount</th>
                <th className="p-3">Channel</th>
                <th className="p-3">Decision</th>
                <th className="p-3">Fraud score</th>
              </tr>
            </thead>
            <tbody>
              {stream.length === 0 && !streamLoading && (
                <tr>
                  <td colSpan={6} className="p-4 text-slate-500">
                    No transactions. Use the mobile app or simulator to generate activity.
                  </td>
                </tr>
              )}
              {stream.map((tx) => (
                <tr key={tx.transaction_id} className="border-b border-slate-800">
                  <td className="p-3 text-slate-400">
                    {tx.created_at ? new Date(tx.created_at).toLocaleString() : "—"}
                  </td>
                  <td className="p-3">{tx.account_id}</td>
                  <td className="p-3">
                    {tx.currency} {tx.amount.toFixed(2)}
                  </td>
                  <td className="p-3">{tx.channel || "—"}</td>
                  <td className="p-3">{tx.decision || "PENDING"}</td>
                  <td className="p-3">
                    {tx.fraud_score != null ? tx.fraud_score.toFixed(3) : "—"}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
      </>
      )}
    </div>
  );
}

function Header() {
  return (
    <div className="border-b border-slate-800/70 bg-gradient-to-br from-[#0b1224] via-[#0a1630] to-[#07101f] px-10 py-7 flex items-center justify-between">
      <div>
        <div className="flex items-center gap-3 mb-1.5">
          <div className="w-2.5 h-2.5 rounded-full bg-cyan-300 shadow-[0_0_12px] shadow-cyan-300/60 animate-pulse" />
          <span className="text-slate-400 text-[11px] tracking-[0.24em] uppercase">Admin Console</span>
        </div>
        <h1 className="m-0 text-2xl font-bold tracking-tight text-slate-100">BankAI Platform</h1>
        <p className="mt-1 text-slate-400 text-sm">FIRST NATIONAL BANK FRAUD MODEL MONITORING 24/7.</p>
      </div>
    </div>
  );
}

export default function App() {
  const [activeView, setActiveView] = useState("care");

  return (
    <div className="h-screen overflow-hidden flex flex-col text-slate-100 bg-[radial-gradient(1200px_800px_at_20%_0%,rgba(56,189,248,0.18),transparent_60%),radial-gradient(900px_700px_at_90%_20%,rgba(34,197,94,0.10),transparent_55%),linear-gradient(180deg,#050812_0%,#060a14_55%,#04060e_100%)]">
      <Header />
      <div className="flex flex-1 min-h-0 bg-slate-950/60">
        <PlatformSidebar activeView={activeView} onChange={setActiveView} />
        <main className="flex-1 min-w-0 overflow-auto py-8 px-8">
          {activeView === "onboard" && <OnboardTab />}
          {activeView === "care" && <CareMetricsPanel />}
          {activeView === "policy" && <FraudPolicyPanel />}
          {activeView === "fraud-ops" && (
            <div>
              <p className="text-slate-400 text-[11px] tracking-wider mb-4 uppercase">
                Fraud ops — alerts, review queue, network &amp; analytics
              </p>
              <FraudTab />
            </div>
          )}
        </main>
      </div>
    </div>
  );
}
