import { useState, useEffect } from "react";
import PlatformSidebar from "./components/PlatformSidebar";

const API_BASE = import.meta.env.VITE_API_URL || "http://localhost:8000";

function OnboardTab({ adminFetch }) {
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
      const res = await adminFetch(`${API_BASE}/api/v1/admin/onboard`, {
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
      const res = await adminFetch(`${API_BASE}/api/v1/admin/tenants`);
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
      const res = await adminFetch(`${API_BASE}/api/v1/admin/tenants/${id}/api-key`, {
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

function CareMetricsPanel({ adminFetch, platformTenantId }) {
  const [metrics, setMetrics] = useState(null);
  const [careKpis, setCareKpis] = useState(null);
  const [error, setError] = useState(null);
  const [loading, setLoading] = useState(false);

  async function loadMetrics() {
    setLoading(true);
    setError(null);
    try {
      const res = await adminFetch(`${API_BASE}/api/v1/admin/care/metrics`);
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || res.statusText);
      setMetrics(data);
      if (platformTenantId) {
        const kRes = await adminFetch(
          `${API_BASE}/api/v1/admin/monitoring/model-kpis?tenant_id=${encodeURIComponent(platformTenantId)}&model_type=care&days=30`
        );
        const kData = await kRes.json().catch(() => null);
        if (kRes.ok && kData) setCareKpis(kData);
        else setCareKpis(null);
      } else {
        setCareKpis(null);
      }
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
      {careKpis && platformTenantId && (
        <div className="rounded-lg border border-cyan-900/50 bg-slate-900/60 p-4 mb-4">
          <p className="text-[10px] text-cyan-400/90 uppercase tracking-wider mb-3">Care model KPIs (30d, inference traces)</p>
          <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
            <div className="rounded border border-slate-700 bg-slate-950/40 p-3">
              <div className="text-[10px] text-slate-500 uppercase mb-1">Traces</div>
              <div className="text-lg font-semibold text-slate-100">{careKpis.total_scored}</div>
            </div>
            <div className="rounded border border-slate-700 bg-slate-950/40 p-3">
              <div className="text-[10px] text-slate-500 uppercase mb-1">Labeled (human feedback)</div>
              <div className="text-lg font-semibold text-slate-100">{careKpis.labeled_count ?? "—"}</div>
            </div>
            <div className="rounded border border-slate-700 bg-slate-950/40 p-3">
              <div className="text-[10px] text-slate-500 uppercase mb-1">Accuracy proxy</div>
              <div className="text-lg font-semibold text-emerald-300">
                {careKpis.precision_proxy != null ? `${(careKpis.precision_proxy * 100).toFixed(1)}%` : "—"}
              </div>
            </div>
            <div className="rounded border border-slate-700 bg-slate-950/40 p-3">
              <div className="text-[10px] text-slate-500 uppercase mb-1">Shadow disagree</div>
              <div className="text-lg font-semibold text-amber-300">
                {careKpis.shadow_disagree_rate != null ? `${(careKpis.shadow_disagree_rate * 100).toFixed(1)}%` : "—"}
              </div>
            </div>
            <div className="rounded border border-slate-700 bg-slate-950/40 p-3">
              <div className="text-[10px] text-slate-500 uppercase mb-1">Avg latency</div>
              <div className="text-lg font-semibold text-slate-200">
                {careKpis.avg_latency_ms != null ? `${careKpis.avg_latency_ms.toFixed(0)} ms` : "—"}
              </div>
            </div>
            <div className="rounded border border-slate-700 bg-slate-950/40 p-3">
              <div className="text-[10px] text-slate-500 uppercase mb-1">Avg calibrated conf.</div>
              <div className="text-lg font-semibold text-slate-200">
                {careKpis.avg_confidence != null ? careKpis.avg_confidence.toFixed(3) : "—"}
              </div>
            </div>
          </div>
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

function OpsCutoverPanel({ adminFetch }) {
  const [readiness, setReadiness] = useState(null);
  const [batch, setBatch] = useState(null);
  const [verifyResult, setVerifyResult] = useState(null);
  const [snapshotResult, setSnapshotResult] = useState(null);
  const [loading, setLoading] = useState(false);
  const [busy, setBusy] = useState(null);
  const [includePassed, setIncludePassed] = useState(true);
  const [batchError, setBatchError] = useState(null);

  async function loadReadiness() {
    try {
      const res = await adminFetch(`${API_BASE}/api/v1/admin/monitoring/deployment-readiness`);
      const data = await res.json();
      if (!res.ok) throw new Error(typeof data?.detail === "string" ? data.detail : res.statusText);
      setReadiness(data);
    } catch {
      setReadiness(null);
    }
  }

  async function loadBatch() {
    setLoading(true);
    setBatchError(null);
    try {
      const q = new URLSearchParams({ include_passed: String(includePassed) });
      const res = await adminFetch(`${API_BASE}/api/v1/admin/monitoring/cutover-gate/batch?${q}`);
      const data = await res.json();
      if (!res.ok) throw new Error(typeof data?.detail === "string" ? data.detail : res.statusText);
      setBatch(data);
    } catch (e) {
      setBatch(null);
      setBatchError(e.message || "Failed to load batch gate");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    loadReadiness();
  }, []);

  useEffect(() => {
    loadBatch();
  }, [includePassed]);

  async function runWarehouseVerify() {
    setBusy("verify");
    setVerifyResult(null);
    try {
      const res = await adminFetch(`${API_BASE}/api/v1/admin/monitoring/warehouse-isolation/verify`, {
        method: "POST",
      });
      const data = await res.json();
      setVerifyResult({ ok: res.ok, data });
    } catch (e) {
      setVerifyResult({ ok: false, data: { detail: e.message } });
    } finally {
      setBusy(null);
    }
  }

  async function runKpiSnapshot() {
    setBusy("snapshot");
    setSnapshotResult(null);
    try {
      const res = await adminFetch(`${API_BASE}/api/v1/admin/monitoring/model-kpis/snapshot/run?window_days=30`, {
        method: "POST",
      });
      const data = await res.json();
      setSnapshotResult({ ok: res.ok, data });
    } catch (e) {
      setSnapshotResult({ ok: false, data: { detail: e.message } });
    } finally {
      setBusy(null);
    }
  }

  const rBool = (v) => (v ? "yes" : "no");

  return (
    <div className="p-8 max-w-6xl space-y-6">
      <div>
        <p className="text-slate-500 text-[11px] tracking-wider uppercase mb-1">Ops / cutover</p>
        <p className="text-slate-400 text-xs">
          Batch cutover gate across visible banks, data-plane verification, and deployment flags.
        </p>
      </div>

      {readiness && (
        <div className="rounded-lg border border-slate-700 bg-slate-900/60 p-4">
          <p className="text-[10px] text-slate-500 uppercase tracking-wider mb-3">Deployment readiness (config)</p>
          <div className="grid grid-cols-2 md:grid-cols-3 gap-2 text-xs text-slate-300">
            <div>Environment: <span className="text-slate-200 font-mono">{readiness.environment || "—"}</span></div>
            <div>Prod hardening enforced: <span className="text-cyan-300">{rBool(readiness.enforce_production_hardening)}</span></div>
            <div>Prod hardening OK: <span className={readiness.production_hardening_ok ? "text-emerald-400" : "text-red-400"}>{rBool(readiness.production_hardening_ok)}</span></div>
            <div>Strict mapper: <span className="text-cyan-300">{rBool(readiness.strict_mapper_enforcement)}</span></div>
            <div>Strict training gov: <span className="text-cyan-300">{rBool(readiness.strict_training_governance)}</span></div>
            <div>Model fallback allowed: <span className="text-cyan-300">{rBool(readiness.allow_model_fallback)}</span></div>
            <div>Alert webhook: <span className="text-cyan-300">{rBool(readiness.alert_webhook_configured)}</span></div>
            <div>Paging webhook: <span className="text-cyan-300">{rBool(readiness.paging_webhook_configured)}</span></div>
            <div>Warehouse verify task: <span className="text-cyan-300">{rBool(readiness.warehouse_verification_enabled)}</span></div>
            <div>Training dir layout strict: <span className="text-cyan-300">{rBool(readiness.warehouse_require_local_training_layout)}</span></div>
            <div>Read replica DSN: <span className="text-cyan-300">{rBool(readiness.read_replica_configured)}</span></div>
            <div>Analytics warehouse: <span className="text-cyan-300">{rBool(readiness.analytics_warehouse_configured)}</span></div>
            <div>S3 data plane: <span className="text-cyan-300">{rBool(readiness.s3_data_plane_configured)}</span></div>
            <div>Calibration needs holdout: <span className="text-cyan-300">{rBool(readiness.calibration_activation_requires_validation)}</span></div>
            <div>Auto cutover: <span className="text-cyan-300">{rBool(readiness.auto_cutover_enabled)}</span></div>
            <div>Auto cutover dry-run: <span className="text-cyan-300">{rBool(readiness.auto_cutover_dry_run)}</span></div>
          </div>
          {(readiness.production_hardening_issues || []).length > 0 && (
            <ul className="mt-3 text-[11px] text-red-300 list-disc list-inside space-y-0.5">
              {readiness.production_hardening_issues.map((x) => (
                <li key={x}>{x}</li>
              ))}
            </ul>
          )}
        </div>
      )}

      <div className="flex flex-wrap gap-3 items-center">
        <label className="flex items-center gap-2 text-xs text-slate-400">
          <input
            type="checkbox"
            checked={includePassed}
            onChange={(e) => setIncludePassed(e.target.checked)}
          />
          Include passing rows
        </label>
        <button
          type="button"
          onClick={() => loadBatch()}
          disabled={loading}
          className="px-3 py-1.5 rounded border border-slate-600 text-xs uppercase text-slate-300 disabled:opacity-50"
        >
          {loading ? "Refreshing…" : "Refresh gate"}
        </button>
        <button
          type="button"
          onClick={runWarehouseVerify}
          disabled={busy === "verify"}
          className="px-3 py-1.5 rounded border border-amber-700/70 text-xs uppercase text-amber-200 disabled:opacity-50"
        >
          {busy === "verify" ? "Verify…" : "Run warehouse isolation verify"}
        </button>
        <button
          type="button"
          onClick={runKpiSnapshot}
          disabled={busy === "snapshot"}
          className="px-3 py-1.5 rounded border border-cyan-700/70 text-xs uppercase text-cyan-200 disabled:opacity-50"
        >
          {busy === "snapshot" ? "Snapshot…" : "Run KPI snapshots (owner)"}
        </button>
      </div>

      {batchError && (
        <div className="rounded border border-red-500/50 bg-red-500/10 px-3 py-2 text-sm text-red-300">{batchError}</div>
      )}

      {verifyResult && (
        <div className={`rounded border px-3 py-2 text-xs ${verifyResult.ok ? "border-emerald-700/50 bg-emerald-500/10 text-emerald-200" : "border-red-500/50 bg-red-500/10 text-red-300"}`}>
          <strong>Warehouse verify:</strong>{" "}
          {verifyResult.ok
            ? `passed=${String(verifyResult.data?.passed)} errors=${(verifyResult.data?.errors || []).length}`
            : JSON.stringify(verifyResult.data?.detail || verifyResult.data)}
        </div>
      )}

      {snapshotResult && (
        <div className={`rounded border px-3 py-2 text-xs ${snapshotResult.ok ? "border-cyan-700/50 bg-cyan-500/10 text-cyan-100" : "border-red-500/50 bg-red-500/10 text-red-300"}`}>
          <strong>KPI snapshot run:</strong>{" "}
          {snapshotResult.ok
            ? `created=${snapshotResult.data?.created} stale_flagged=${snapshotResult.data?.stale_flagged ?? 0}`
            : JSON.stringify(snapshotResult.data?.detail || snapshotResult.data)}
        </div>
      )}

      {batch && (
        <div className="rounded-lg border border-slate-700 overflow-hidden">
          <div className="px-4 py-2 border-b border-slate-700 text-[10px] text-slate-500 uppercase tracking-wider">
            Batch cutover gate — pass {batch.pass_count} / fail {batch.fail_count} (scanned {batch.scanned})
          </div>
          <div className="max-h-[480px] overflow-auto">
            <table className="w-full text-left text-xs">
              <thead>
                <tr className="border-b border-slate-800 text-slate-500">
                  <th className="p-2">Tenant</th>
                  <th className="p-2">Model</th>
                  <th className="p-2">Pass</th>
                  <th className="p-2">Blockers</th>
                </tr>
              </thead>
              <tbody>
                {batch.items?.length === 0 && (
                  <tr><td colSpan={4} className="p-4 text-slate-500">No rows (toggle “include passing” or check visibility).</td></tr>
                )}
                {batch.items?.map((row) => (
                  <tr key={`${row.tenant_id}-${row.model_type}`} className="border-b border-slate-800/80">
                    <td className="p-2 text-slate-300">{row.tenant_name || row.tenant_id.slice(0, 8)}</td>
                    <td className="p-2 font-mono text-slate-400">{row.model_type}</td>
                    <td className="p-2">{row.pass_gate ? <span className="text-emerald-400">yes</span> : <span className="text-red-400">no</span>}</td>
                    <td className="p-2 text-amber-200/90">{(row.blockers || []).join("; ") || "—"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </div>
  );
}

function TenantObservabilityPanel({ adminFetch, platformTenantId }) {
  const [fraudKpi, setFraudKpi] = useState(null);
  const [careKpi, setCareKpi] = useState(null);
  const [isoFraud, setIsoFraud] = useState(null);
  const [isoCare, setIsoCare] = useState(null);
  const [ccFraud, setCcFraud] = useState(null);
  const [ccCare, setCcCare] = useState(null);
  const [gateFraud, setGateFraud] = useState(null);
  const [gateCare, setGateCare] = useState(null);
  const [loading, setLoading] = useState(false);
  const [err, setErr] = useState(null);

  async function load() {
    if (!platformTenantId) return;
    setLoading(true);
    setErr(null);
    try {
      const tid = encodeURIComponent(platformTenantId);
      const urls = [
        ["fk", `${API_BASE}/api/v1/admin/monitoring/model-kpis?tenant_id=${tid}&model_type=fraud&days=30`],
        ["ck", `${API_BASE}/api/v1/admin/monitoring/model-kpis?tenant_id=${tid}&model_type=care&days=30`],
        ["if", `${API_BASE}/api/v1/admin/monitoring/isolation-readiness?tenant_id=${tid}&model_type=fraud`],
        ["ic", `${API_BASE}/api/v1/admin/monitoring/isolation-readiness?tenant_id=${tid}&model_type=care`],
        ["cf", `${API_BASE}/api/v1/admin/monitoring/champion-challenger?tenant_id=${tid}&model_type=fraud&window_hours=24`],
        ["cc", `${API_BASE}/api/v1/admin/monitoring/champion-challenger?tenant_id=${tid}&model_type=care&window_hours=24`],
        ["gf", `${API_BASE}/api/v1/admin/monitoring/cutover-gate?tenant_id=${tid}&model_type=fraud`],
        ["gc", `${API_BASE}/api/v1/admin/monitoring/cutover-gate?tenant_id=${tid}&model_type=care`],
      ];
      const responses = await Promise.all(urls.map(([, u]) => adminFetch(u)));
      const bodies = await Promise.all(responses.map((r) => r.json().catch(() => null)));
      const pick = (i) => (responses[i]?.ok ? bodies[i] : null);
      setFraudKpi(pick(0));
      setCareKpi(pick(1));
      setIsoFraud(pick(2));
      setIsoCare(pick(3));
      setCcFraud(pick(4));
      setCcCare(pick(5));
      setGateFraud(pick(6));
      setGateCare(pick(7));
      const bad = responses.find((r, i) => !r.ok && i < 2);
      if (bad) {
        const d = bodies[responses.indexOf(bad)];
        setErr(typeof d?.detail === "string" ? d.detail : "Some observability endpoints failed");
      }
    } catch (e) {
      setErr(e.message || "Load failed");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    load();
  }, [platformTenantId]);

  function kpiGrid(title, k, accent) {
    if (!k) return null;
    return (
      <div className={`rounded-lg border border-slate-700 bg-slate-900/50 p-4 ${accent}`}>
        <p className="text-[10px] text-slate-500 uppercase tracking-wider mb-3">{title} (30d)</p>
        <div className="grid grid-cols-2 md:grid-cols-4 gap-2 text-xs">
          <div><span className="text-slate-500">Scored</span> <span className="text-slate-200 font-semibold">{k.total_scored}</span></div>
          <div><span className="text-slate-500">Labeled</span> <span className="text-slate-200">{k.labeled_count ?? "—"}</span></div>
          <div><span className="text-slate-500">Block %</span> <span className="text-amber-300">{((k.block_rate || 0) * 100).toFixed(2)}</span></div>
          <div><span className="text-slate-500">OTP %</span> <span className="text-cyan-300">{((k.otp_rate || 0) * 100).toFixed(2)}</span></div>
          <div><span className="text-slate-500">AUC proxy</span> <span className="text-emerald-300">{k.auc_proxy != null ? k.auc_proxy.toFixed(3) : "—"}</span></div>
          <div><span className="text-slate-500">p90 lat ms</span> <span className="text-slate-200">{k.p90_latency_ms != null ? k.p90_latency_ms.toFixed(0) : "—"}</span></div>
          <div><span className="text-slate-500">Shadow Δ</span> <span className="text-slate-200">{k.shadow_disagree_rate != null ? `${(k.shadow_disagree_rate * 100).toFixed(1)}%` : "—"}</span></div>
          <div><span className="text-slate-500">Avg conf</span> <span className="text-slate-200">{k.avg_confidence != null ? k.avg_confidence.toFixed(3) : "—"}</span></div>
        </div>
      </div>
    );
  }

  function isoRow(label, row) {
    if (!row) return null;
    return (
      <div className="rounded border border-slate-800 bg-slate-950/40 p-3 text-xs">
        <p className="text-[10px] text-slate-500 uppercase mb-2">{label} isolation</p>
        <div className="flex flex-wrap gap-x-4 gap-y-1 text-slate-300">
          <span>registry: {row.has_active_model ? <b className="text-emerald-400">yes</b> : <b className="text-red-400">no</b>}</span>
          <span>mapper: {row.has_active_mapper ? <b className="text-emerald-400">yes</b> : <b className="text-red-400">no</b>}</span>
          <span>strict cutover ready: {row.ready_for_strict_cutover ? <b className="text-emerald-400">yes</b> : <b className="text-amber-400">no</b>}</span>
          <span className="text-slate-500 font-mono">{row.active_model_version || "—"}</span>
        </div>
      </div>
    );
  }

  function ccRow(label, row) {
    if (!row) return null;
    return (
      <div className="rounded border border-slate-800 bg-slate-950/40 p-3 text-xs text-slate-300">
        <p className="text-[10px] text-slate-500 uppercase mb-1">{label} champion/challenger (24h)</p>
        <span>Traces {row.total_traces}</span>
        <span className="mx-2 text-slate-600">·</span>
        <span>Compared {row.compared_traces}</span>
        {row.disagree_rate != null && (
          <>
            <span className="mx-2 text-slate-600">·</span>
            <span>Disagree {(row.disagree_rate * 100).toFixed(1)}%</span>
          </>
        )}
      </div>
    );
  }

  function gateRow(label, g) {
    if (!g) return null;
    return (
      <div className="rounded border border-slate-800 bg-slate-950/40 p-3 text-xs">
        <p className="text-[10px] text-slate-500 uppercase mb-1">{label} cutover gate</p>
        <span className={g.pass_gate ? "text-emerald-400" : "text-red-400"}>{g.pass_gate ? "PASS" : "BLOCKED"}</span>
        {(g.blockers || []).length > 0 && (
          <p className="text-amber-200/90 mt-1">{(g.blockers || []).join("; ")}</p>
        )}
      </div>
    );
  }

  if (!platformTenantId) {
    return (
      <div className="p-8 text-sm text-slate-500">Select a bank to view per-tenant observability.</div>
    );
  }

  return (
    <div className="p-8 max-w-5xl space-y-4">
      <div className="flex items-center justify-between gap-4">
        <div>
          <p className="text-slate-500 text-[11px] tracking-wider uppercase">Tenant observability</p>
          <p className="text-slate-400 text-xs">KPIs, isolation readiness, champion/challenger, cutover gate — fraud & care parity.</p>
        </div>
        <button
          type="button"
          onClick={load}
          disabled={loading}
          className="px-3 py-1.5 rounded border border-slate-600 text-xs uppercase text-slate-300 disabled:opacity-50"
        >
          {loading ? "Loading…" : "Refresh"}
        </button>
      </div>
      {err && <div className="rounded border border-amber-600/50 bg-amber-500/10 px-3 py-2 text-xs text-amber-200">{err}</div>}
      <div className="grid md:grid-cols-2 gap-3">
        {kpiGrid("Fraud model KPIs", fraudKpi, "")}
        {kpiGrid("Care model KPIs", careKpi, "border-cyan-900/30")}
      </div>
      <div className="grid md:grid-cols-2 gap-3">
        {isoRow("Fraud", isoFraud)}
        {isoRow("Care", isoCare)}
      </div>
      <div className="grid md:grid-cols-2 gap-3">
        {ccRow("Fraud", ccFraud)}
        {ccRow("Care", ccCare)}
      </div>
      <div className="grid md:grid-cols-2 gap-3">
        {gateRow("Fraud", gateFraud)}
        {gateRow("Care", gateCare)}
      </div>
    </div>
  );
}

function TenantHomePanel({ adminFetch, platformTenantId, platformTenantName }) {
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const [alerts, setAlerts] = useState([]);
  const [tx, setTx] = useState([]);
  const [analytics, setAnalytics] = useState(null);
  const [drift, setDrift] = useState(null);
  const [modelKpis, setModelKpis] = useState(null);

  async function load() {
    if (!platformTenantId) return;
    setLoading(true);
    setError(null);
    try {
      const [aRes, tRes, nRes, dRes, dLiveRes, kRes] = await Promise.all([
        adminFetch(`${API_BASE}/api/v1/fraud/alerts?status=OPEN`),
        adminFetch(`${API_BASE}/api/v1/fraud/transactions?limit=150`),
        adminFetch(`${API_BASE}/api/v1/fraud/network/analytics?since_days=30`),
        adminFetch(`${API_BASE}/api/v1/admin/monitoring/fraud-drift-status?tenant_id=${encodeURIComponent(platformTenantId)}`),
        adminFetch(`${API_BASE}/api/v1/admin/monitoring/fraud-drift?tenant_id=${encodeURIComponent(platformTenantId)}`),
        adminFetch(`${API_BASE}/api/v1/admin/monitoring/model-kpis?tenant_id=${encodeURIComponent(platformTenantId)}&model_type=fraud&days=30`),
      ]);
      const [aData, tData, nData, dData, dLiveData, kData] = await Promise.all([
        aRes.json(),
        tRes.json(),
        nRes.json(),
        dRes.json(),
        dLiveRes.json().catch(() => []),
        kRes.json().catch(() => ({})),
      ]);
      if (!aRes.ok) throw new Error(aData.detail || "Failed to load alerts");
      if (!tRes.ok) throw new Error(tData.detail || "Failed to load transactions");
      if (!nRes.ok) throw new Error(nData.detail || "Failed to load analytics");
      if (!dRes.ok) throw new Error(dData.detail || "Failed to load drift status");
      setAlerts(Array.isArray(aData) ? aData : []);
      setTx(Array.isArray(tData) ? tData : []);
      setAnalytics(nData || null);
      if (kRes.ok) setModelKpis(kData || null);
      let driftData = dData || null;
      if (driftData?.status === "unknown" && dLiveRes.ok && Array.isArray(dLiveData)) {
        const alertCount = dLiveData.filter((f) => !!f?.alert).length;
        driftData = {
          ...driftData,
          status: alertCount > 0 ? "yellow" : "green",
          alerts_count: alertCount,
          checked_at: new Date().toISOString(),
          source: "live_compute",
        };
      }
      setDrift(driftData);
    } catch (err) {
      setError(err.message || "Failed to load dashboard");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    load();
  }, [platformTenantId]);

  const totalTx = tx.length;
  const blocked = tx.filter((x) => x?.decision === "BLOCK").length;
  const otp = tx.filter((x) => x?.decision === "REQUEST_OTP").length;
  const avgScore = tx.length
    ? tx.reduce((sum, row) => sum + (typeof row?.fraud_score === "number" ? row.fraud_score : 0), 0) / tx.length
    : 0;

  const byDay = {};
  const decisionByDay = {};
  tx.forEach((row) => {
    const raw = row?.created_at || row?.tx_timestamp;
    if (!raw) return;
    const key = new Date(raw).toISOString().slice(0, 10);
    byDay[key] = (byDay[key] || 0) + 1;
    if (!decisionByDay[key]) decisionByDay[key] = { total: 0, blocked: 0, otp: 0, highRisk: 0 };
    decisionByDay[key].total += 1;
    const d = String(row?.decision || "").toUpperCase();
    if (d === "BLOCK") decisionByDay[key].blocked += 1;
    if (d === "REQUEST_OTP") decisionByDay[key].otp += 1;
    if (typeof row?.fraud_score === "number" && row.fraud_score >= 0.8) decisionByDay[key].highRisk += 1;
  });
  const dayRows = Object.entries(byDay)
    .sort((a, b) => (a[0] < b[0] ? -1 : 1))
    .slice(-7);
  const maxDay = Math.max(1, ...dayRows.map((x) => x[1]));
  const decisionTrendRows = Object.entries(decisionByDay)
    .sort((a, b) => (a[0] < b[0] ? -1 : 1))
    .slice(-7);

  const decisionCounts = {};
  tx.forEach((row) => {
    const key = row?.decision || "PENDING";
    decisionCounts[key] = (decisionCounts[key] || 0) + 1;
  });
  const topDecisions = Object.entries(decisionCounts)
    .sort((a, b) => b[1] - a[1])
    .slice(0, 6);
  const maxDecisionCount = Math.max(1, ...topDecisions.map(([, c]) => c));
  const analyticsNumeric = Object.entries(analytics || {})
    .filter(([, v]) => typeof v === "number" && Number.isFinite(v))
    .sort((a, b) => b[1] - a[1])
    .slice(0, 8);
  const maxAnalytics = Math.max(1, ...analyticsNumeric.map(([, v]) => v));

  return (
    <div className="p-8 space-y-5">
      <div className="flex items-center justify-between">
        <div>
          <p className="text-slate-400 text-[11px] tracking-wider uppercase">Tenant home</p>
          <h2 className="text-slate-100 text-xl font-semibold mt-1">{platformTenantName || "Selected bank"}</h2>
          <p className="text-xs text-slate-500 mt-1">Live operations snapshot for the currently selected tenant.</p>
        </div>
        <button
          type="button"
          onClick={load}
          disabled={loading || !platformTenantId}
          className="px-3 py-1.5 rounded border border-slate-700 text-xs text-slate-300 disabled:opacity-50"
        >
          {loading ? "Refreshing..." : "Refresh"}
        </button>
      </div>

      {!platformTenantId && (
        <div className="rounded-lg border border-amber-900/50 bg-amber-950/20 p-3 text-xs text-amber-200/90">
          Select a bank at login to load the tenant dashboard.
        </div>
      )}
      {error && <div className="rounded-lg border border-red-500/40 bg-red-500/10 px-4 py-2 text-sm text-red-300">{error}</div>}

      <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-4 gap-4">
        <div className="rounded-xl border border-slate-800 bg-slate-900/50 p-4">
          <p className="text-[10px] uppercase tracking-wider text-slate-500">Transactions (last pull)</p>
          <p className="text-2xl font-semibold text-slate-100 mt-2">{totalTx}</p>
        </div>
        <div className="rounded-xl border border-slate-800 bg-slate-900/50 p-4">
          <p className="text-[10px] uppercase tracking-wider text-slate-500">Open alerts</p>
          <p className="text-2xl font-semibold text-amber-200 mt-2">{alerts.length}</p>
        </div>
        <div className="rounded-xl border border-slate-800 bg-slate-900/50 p-4">
          <p className="text-[10px] uppercase tracking-wider text-slate-500">Blocked / OTP</p>
          <p className="text-2xl font-semibold text-slate-100 mt-2">{blocked} / {otp}</p>
        </div>
        <div className="rounded-xl border border-slate-800 bg-slate-900/50 p-4">
          <p className="text-[10px] uppercase tracking-wider text-slate-500">Avg fraud score</p>
          <p className="text-2xl font-semibold text-cyan-200 mt-2">{avgScore.toFixed(3)}</p>
        </div>
      </div>

      {modelKpis && (
        <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-9 gap-4">
          <div className="rounded-xl border border-slate-800 bg-slate-900/50 p-4">
            <p className="text-[10px] uppercase tracking-wider text-slate-500">30d scored</p>
            <p className="text-2xl font-semibold text-slate-100 mt-2">{modelKpis.total_scored ?? 0}</p>
          </div>
          <div className="rounded-xl border border-slate-800 bg-slate-900/50 p-4">
            <p className="text-[10px] uppercase tracking-wider text-slate-500">Block rate</p>
            <p className="text-2xl font-semibold text-rose-200 mt-2">{((modelKpis.block_rate || 0) * 100).toFixed(2)}%</p>
          </div>
          <div className="rounded-xl border border-slate-800 bg-slate-900/50 p-4">
            <p className="text-[10px] uppercase tracking-wider text-slate-500">OTP burden</p>
            <p className="text-2xl font-semibold text-amber-200 mt-2">{((modelKpis.otp_rate || 0) * 100).toFixed(2)}%</p>
          </div>
          <div className="rounded-xl border border-slate-800 bg-slate-900/50 p-4">
            <p className="text-[10px] uppercase tracking-wider text-slate-500">Alert rate</p>
            <p className="text-2xl font-semibold text-indigo-200 mt-2">{((modelKpis.alert_rate || 0) * 100).toFixed(2)}%</p>
          </div>
          <div className="rounded-xl border border-slate-800 bg-slate-900/50 p-4">
            <p className="text-[10px] uppercase tracking-wider text-slate-500">Precision</p>
            <p className="text-2xl font-semibold text-emerald-200 mt-2">
              {modelKpis.precision_proxy == null ? "—" : `${(modelKpis.precision_proxy * 100).toFixed(2)}%`}
            </p>
          </div>
          <div className="rounded-xl border border-slate-800 bg-slate-900/50 p-4">
            <p className="text-[10px] uppercase tracking-wider text-slate-500">Recall</p>
            <p className="text-2xl font-semibold text-cyan-200 mt-2">
              {modelKpis.recall_proxy == null ? "—" : `${(modelKpis.recall_proxy * 100).toFixed(2)}%`}
            </p>
          </div>
          <div className="rounded-xl border border-slate-800 bg-slate-900/50 p-4">
            <p className="text-[10px] uppercase tracking-wider text-slate-500">False positive rate</p>
            <p className="text-2xl font-semibold text-rose-200 mt-2">
              {modelKpis.fpr_proxy == null ? "—" : `${(modelKpis.fpr_proxy * 100).toFixed(2)}%`}
            </p>
          </div>
          <div className="rounded-xl border border-slate-800 bg-slate-900/50 p-4">
            <p className="text-[10px] uppercase tracking-wider text-slate-500">Labeled samples</p>
            <p className="text-2xl font-semibold text-slate-100 mt-2">{modelKpis.labeled_count ?? 0}</p>
          </div>
          <div className="rounded-xl border border-slate-800 bg-slate-900/50 p-4">
            <p className="text-[10px] uppercase tracking-wider text-slate-500">AUC</p>
            <p className="text-2xl font-semibold text-fuchsia-200 mt-2">
              {modelKpis.auc_proxy == null ? "—" : Number(modelKpis.auc_proxy).toFixed(3)}
            </p>
          </div>
        </div>
      )}

      <div className="grid grid-cols-1 xl:grid-cols-2 gap-4">
        <div className="rounded-xl border border-slate-800 bg-slate-900/50 p-4">
          <p className="text-[10px] uppercase tracking-wider text-slate-500 mb-3">7-day transaction trend</p>
          <div className="space-y-2">
            {dayRows.length === 0 && <p className="text-xs text-slate-500">No recent data.</p>}
            {dayRows.map(([day, count]) => (
              <div key={day} className="flex items-center gap-3">
                <div className="w-24 text-xs text-slate-400">{day.slice(5)}</div>
                <div className="flex-1 h-2.5 bg-slate-800 rounded overflow-hidden">
                  <div className="h-full bg-gradient-to-r from-cyan-400 to-emerald-400" style={{ width: `${Math.max(4, (count / maxDay) * 100)}%` }} />
                </div>
                <div className="w-10 text-right text-xs text-slate-300">{count}</div>
              </div>
            ))}
          </div>
        </div>

        <div className="rounded-xl border border-slate-800 bg-slate-900/50 p-4">
          <p className="text-[10px] uppercase tracking-wider text-slate-500 mb-3">Decision mix</p>
          <div className="space-y-2 mb-4">
            {topDecisions.length === 0 && <p className="text-xs text-slate-500">No decision data.</p>}
            {topDecisions.map(([decision, count]) => (
              <div key={decision} className="space-y-1">
                <div className="flex items-center justify-between text-sm">
                  <span className="text-slate-300">{decision}</span>
                  <span className="text-slate-500">{count}</span>
                </div>
                <div className="h-2 rounded bg-slate-800 overflow-hidden">
                  <div
                    className="h-full bg-gradient-to-r from-indigo-400 to-cyan-300"
                    style={{ width: `${Math.max(5, (count / maxDecisionCount) * 100)}%` }}
                  />
                </div>
              </div>
            ))}
          </div>
          <div className="mt-4 rounded border border-slate-800 bg-slate-950/50 p-3 text-xs text-slate-400">
            Drift status: <span className="text-slate-200">{drift?.status || "unknown"}</span>
            {typeof drift?.alerts_count === "number" && <> · Alerts: <span className="text-slate-200">{drift.alerts_count}</span></>}
            {drift?.source === "live_compute" && <> · <span className="text-cyan-200">live computed</span></>}
          </div>
        </div>
      </div>

      <div className="rounded-xl border border-slate-800 bg-slate-900/50 p-4">
        <p className="text-[10px] uppercase tracking-wider text-slate-500 mb-3">Fraud / OTP / High-risk trend (7d)</p>
        <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
          {decisionTrendRows.length === 0 && <p className="text-xs text-slate-500">No trend data.</p>}
          {decisionTrendRows.map(([day, stats]) => (
            <div key={day} className="rounded border border-slate-800 bg-slate-950/50 p-3">
              <div className="flex items-center justify-between text-xs mb-2">
                <span className="text-slate-400">{day}</span>
                <span className="text-slate-500">total {stats.total}</span>
              </div>
              <div className="space-y-1.5">
                <div className="text-[11px] text-slate-400">Blocked {stats.blocked}</div>
                <div className="h-1.5 bg-slate-800 rounded"><div className="h-full bg-rose-400 rounded" style={{ width: `${Math.max(2, (stats.blocked / Math.max(1, stats.total)) * 100)}%` }} /></div>
                <div className="text-[11px] text-slate-400">OTP {stats.otp}</div>
                <div className="h-1.5 bg-slate-800 rounded"><div className="h-full bg-amber-300 rounded" style={{ width: `${Math.max(2, (stats.otp / Math.max(1, stats.total)) * 100)}%` }} /></div>
                <div className="text-[11px] text-slate-400">High risk (score ≥ 0.8) {stats.highRisk}</div>
                <div className="h-1.5 bg-slate-800 rounded"><div className="h-full bg-cyan-300 rounded" style={{ width: `${Math.max(2, (stats.highRisk / Math.max(1, stats.total)) * 100)}%` }} /></div>
              </div>
            </div>
          ))}
        </div>
      </div>

      <div className="rounded-xl border border-slate-800 bg-slate-900/50 overflow-hidden">
        <div className="px-4 py-3 border-b border-slate-800">
          <p className="text-[10px] uppercase tracking-wider text-slate-500">Latest open alerts</p>
        </div>
        <table className="w-full text-left text-xs">
          <thead>
            <tr className="border-b border-slate-800 text-slate-500 uppercase tracking-wider">
              <th className="p-3">Alert ID</th>
              <th className="p-3">Type</th>
              <th className="p-3">Severity</th>
              <th className="p-3">Status</th>
              <th className="p-3">Created</th>
            </tr>
          </thead>
          <tbody>
            {alerts.slice(0, 8).map((a) => (
              <tr key={a.id || a.alert_id} className="border-b border-slate-900">
                <td className="p-3 text-slate-300">{a.id || a.alert_id || "—"}</td>
                <td className="p-3 text-slate-300">{a.alert_type || "—"}</td>
                <td className="p-3 text-slate-300">{a.severity || "—"}</td>
                <td className="p-3 text-slate-300">{a.status || "—"}</td>
                <td className="p-3 text-slate-500">{a.created_at ? new Date(a.created_at).toLocaleString() : "—"}</td>
              </tr>
            ))}
            {alerts.length === 0 && (
              <tr>
                <td colSpan={5} className="p-4 text-slate-500">No open alerts.</td>
              </tr>
            )}
          </tbody>
        </table>
      </div>

      <div className="rounded-xl border border-slate-800 bg-slate-900/50 p-4">
        <p className="text-[10px] uppercase tracking-wider text-slate-500 mb-2">Network analytics (30d)</p>
        {analyticsNumeric.length === 0 ? (
          <p className="text-xs text-slate-500">No numeric analytics available.</p>
        ) : (
          <div className="space-y-2">
            {analyticsNumeric.map(([k, v]) => (
              <div key={k} className="space-y-1">
                <div className="flex items-center justify-between text-xs">
                  <span className="text-slate-300">{k}</span>
                  <span className="text-slate-500">{Number(v).toLocaleString()}</span>
                </div>
                <div className="h-2 rounded bg-slate-800 overflow-hidden">
                  <div className="h-full bg-gradient-to-r from-emerald-400 to-cyan-300" style={{ width: `${Math.max(5, (v / maxAnalytics) * 100)}%` }} />
                </div>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}

function FraudPolicyPanel({ adminFetch, platformTenantId, platformTenantName }) {
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
  const [tenantId, setTenantId] = useState("");
  useEffect(() => {
    if (platformTenantId) setTenantId(platformTenantId);
  }, [platformTenantId]);
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

  async function loadPolicy() {
    if (!tenantId) return;
    setLoadingPolicy(true);
    setError(null);
    try {
      const res = await adminFetch(`${API_BASE}/api/v1/admin/tenants/${tenantId}/fraud-policy`);
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
      const res = await adminFetch(`${API_BASE}/api/v1/admin/tenants/${tenantId}/fraud-policy`, {
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

  useEffect(() => {
    if (tenantId) loadPolicy();
  }, [tenantId]);

  return (
    <div className="p-8">
      <p className="text-slate-500 text-[11px] tracking-wider mb-4 uppercase">Fraud policy &amp; training</p>
      <div className="space-y-4">
        <div className="rounded border border-slate-800 bg-slate-900/40 px-3 py-2 text-xs text-slate-400">
          {tenantId ? <>Bank policy loaded from selected bank: <span className="text-slate-200">{platformTenantName || tenantId}</span></> : "Select a bank at login to load policy."}
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
                <label className="block text-[10px] text-slate-500 uppercase mb-1">OTP-&gt;BLOCK amount cap</label>
                <input type="number" step="1" value={form.request_otp_block_amount} onChange={(e) => setForm((f) => ({ ...f, request_otp_block_amount: e.target.value }))} className="w-full rounded border border-slate-600 bg-slate-900 px-3 py-2 text-slate-200 text-sm" />
              </div>
              <div>
                <label className="block text-[10px] text-slate-500 uppercase mb-1">OTP-&gt;BLOCK txn / 1h cap</label>
                <input type="number" step="1" value={form.request_otp_block_txn_1h} onChange={(e) => setForm((f) => ({ ...f, request_otp_block_txn_1h: e.target.value }))} className="w-full rounded border border-slate-600 bg-slate-900 px-3 py-2 text-slate-200 text-sm" />
              </div>
              <div>
                <label className="block text-[10px] text-slate-500 uppercase mb-1">OTP-&gt;BLOCK network risk</label>
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
    </div>
  );
}

function TenantReportsPanel({
  adminFetch,
  platformTenantId,
  platformTenantName,
  canManagePresets = false,
}) {
  const today = new Date();
  const defaultFrom = new Date(today.getTime() - 30 * 24 * 60 * 60 * 1000);
  const [fromDate, setFromDate] = useState(defaultFrom.toISOString().slice(0, 10));
  const [toDate, setToDate] = useState(today.toISOString().slice(0, 10));
  const [decisionFilter, setDecisionFilter] = useState("ALL");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const [report, setReport] = useState(null);
  const [jobId, setJobId] = useState(null);
  const [jobStatus, setJobStatus] = useState(null);
  const [history, setHistory] = useState([]);
  const [historyLoading, setHistoryLoading] = useState(false);
  const [historyPage, setHistoryPage] = useState(1);
  const [historyPageSize] = useState(12);
  const [historyTotal, setHistoryTotal] = useState(0);
  const [historyStatusFilter, setHistoryStatusFilter] = useState("ALL");
  const [historyFromDate, setHistoryFromDate] = useState("");
  const [historyToDate, setHistoryToDate] = useState("");
  const [historyAutoRefresh, setHistoryAutoRefresh] = useState(true);
  const [historySortBy, setHistorySortBy] = useState("created_at");
  const [historySortDir, setHistorySortDir] = useState("desc");
  const [historyTypeFilter, setHistoryTypeFilter] = useState("ALL");
  const [historyJumpPage, setHistoryJumpPage] = useState("1");
  const [presetName, setPresetName] = useState("");
  const [presets, setPresets] = useState([]);
  const [editingPresetId, setEditingPresetId] = useState(null);
  const [auditItems, setAuditItems] = useState([]);
  const [auditLoading, setAuditLoading] = useState(false);
  const [auditEventType, setAuditEventType] = useState("ALL");
  const [selectedAudit, setSelectedAudit] = useState(null);
  const [auditJsonCopied, setAuditJsonCopied] = useState(false);
  const [exportJobId, setExportJobId] = useState(null);
  const [exportJob, setExportJob] = useState(null);
  const [exportLoading, setExportLoading] = useState(false);

  const normalizeError = (val, fallback) => {
    if (!val) return fallback;
    if (typeof val === "string") return val;
    if (Array.isArray(val)) {
      const items = val
        .map((x) => {
          if (typeof x === "string") return x;
          if (x && typeof x === "object") {
            const loc = Array.isArray(x.loc) ? x.loc.join(".") : null;
            if (typeof x.msg === "string" && loc) return `${loc}: ${x.msg}`;
            if (typeof x.msg === "string") return x.msg;
          }
          return null;
        })
        .filter(Boolean);
      return items.length ? items.join(" | ") : fallback;
    }
    if (typeof val === "object") {
      if (typeof val.detail === "string") return val.detail;
      if (Array.isArray(val.detail)) return normalizeError(val.detail, fallback);
      if (typeof val.message === "string") return val.message;
    }
    return fallback;
  };

  async function generate() {
    if (!platformTenantId) return;
    setLoading(true);
    setError(null);
    try {
      const from = new Date(`${fromDate}T00:00:00`);
      const to = new Date(`${toDate}T23:59:59`);
      if (Number.isNaN(from.getTime()) || Number.isNaN(to.getTime()) || from > to) {
        throw new Error("Invalid date range. Ensure From <= To.");
      }
      const res = await adminFetch(`${API_BASE}/api/v1/admin/reports/jobs`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          tenant_id: platformTenantId,
          from_date: fromDate,
          to_date: toDate,
          decision_filter: decisionFilter,
        }),
      });
      const data = await res.json();
      if (!res.ok) throw new Error(normalizeError(data?.detail ?? data, "Failed to create report job"));
      setJobId(data.job_id);
      setJobStatus(data.status);
      setReport(null);
      loadHistory();
    } catch (err) {
      setError(normalizeError(err?.message || err, "Failed to generate report"));
    } finally {
      setLoading(false);
    }
  }

  function downloadPdf() {
    signAndOpen("pdf");
  }

  function downloadExcel() {
    signAndOpen("xlsx");
  }

  async function signAndOpen(fmt) {
    if (!jobId || !report) return;
    try {
      const res = await adminFetch(
        `${API_BASE}/api/v1/admin/reports/jobs/${encodeURIComponent(jobId)}/sign-download?format=${fmt}`,
        { method: "POST" },
      );
      const data = await res.json();
      if (!res.ok) throw new Error(normalizeError(data?.detail ?? data, "Failed to sign download URL"));
      const url = String(data.url || "");
      if (!url) throw new Error("Signed URL missing");
      window.open(`${API_BASE}${url}`, "_blank");
    } catch (err) {
      setError(normalizeError(err?.message || err, "Failed to download"));
    }
  }

  async function loadHistory() {
    if (!platformTenantId) {
      setHistory([]);
      setHistoryTotal(0);
      return;
    }
    setHistoryLoading(true);
    try {
      const q = new URLSearchParams();
      q.set("tenant_id", platformTenantId);
      q.set("page", String(historyPage));
      q.set("page_size", String(historyPageSize));
      if (historyStatusFilter !== "ALL") q.set("status", historyStatusFilter.toLowerCase());
      if (historyTypeFilter === "EXPORTS") q.set("kind", "tenant_export");
      if (historyTypeFilter === "REPORTS") q.set("kind", "report");
      if (historyFromDate) q.set("from_date", historyFromDate);
      if (historyToDate) q.set("to_date", historyToDate);
      q.set("sort_by", historySortBy);
      q.set("sort_dir", historySortDir);
      const res = await adminFetch(
        `${API_BASE}/api/v1/admin/reports/jobs?${q.toString()}`,
      );
      const data = await res.json();
      if (!res.ok) throw new Error(normalizeError(data?.detail ?? data, "Failed to load report history"));
      setHistory(Array.isArray(data.items) ? data.items : []);
      setHistoryTotal(Number(data.total || 0));
      setHistoryJumpPage(String(Number(data.page || historyPage)));
    } catch (err) {
      setError(normalizeError(err?.message || err, "Failed to load report history"));
    } finally {
      setHistoryLoading(false);
    }
  }

  async function createComplianceExportJob() {
    if (!platformTenantId) return;
    setExportLoading(true);
    setError(null);
    try {
      const res = await adminFetch(
        `${API_BASE}/api/v1/admin/compliance/tenant-export/jobs?tenant_id=${encodeURIComponent(platformTenantId)}`,
        { method: "POST" },
      );
      const data = await res.json();
      if (!res.ok) throw new Error(normalizeError(data?.detail ?? data, "Failed to create export job"));
      setExportJobId(data.job_id);
      setExportJob(data);
    } catch (err) {
      setError(normalizeError(err?.message || err, "Failed to create export job"));
    } finally {
      setExportLoading(false);
    }
  }

  async function signAndOpenComplianceExport() {
    if (!exportJobId) return;
    try {
      const res = await adminFetch(
        `${API_BASE}/api/v1/admin/compliance/tenant-export/jobs/${encodeURIComponent(exportJobId)}/sign-download`,
        { method: "POST" },
      );
      const data = await res.json();
      if (!res.ok) throw new Error(normalizeError(data?.detail ?? data, "Failed to sign export download"));
      const url = String(data.url || "");
      if (!url) throw new Error("Signed URL missing");
      window.open(`${API_BASE}${url}`, "_blank");
    } catch (err) {
      setError(normalizeError(err?.message || err, "Failed to download export"));
    }
  }

  async function loadPresets() {
    if (!platformTenantId) {
      setPresets([]);
      return;
    }
    try {
      const res = await adminFetch(
        `${API_BASE}/api/v1/admin/reports/presets?tenant_id=${encodeURIComponent(platformTenantId)}`,
      );
      const data = await res.json();
      if (!res.ok) throw new Error(normalizeError(data?.detail ?? data, "Failed to load presets"));
      setPresets(Array.isArray(data) ? data : []);
    } catch (err) {
      setError(normalizeError(err?.message || err, "Failed to load presets"));
    }
  }

  async function loadAudit() {
    if (!platformTenantId) {
      setAuditItems([]);
      return;
    }
    setAuditLoading(true);
    try {
      const q = new URLSearchParams();
      q.set("tenant_id", platformTenantId);
      q.set("limit", "40");
      if (auditEventType !== "ALL") q.set("event_type", auditEventType);
      const res = await adminFetch(`${API_BASE}/api/v1/admin/reports/audit?${q.toString()}`);
      const data = await res.json();
      if (!res.ok) throw new Error(normalizeError(data?.detail ?? data, "Failed to load report audit timeline"));
      setAuditItems(Array.isArray(data) ? data : []);
    } catch (err) {
      setError(normalizeError(err?.message || err, "Failed to load report audit timeline"));
    } finally {
      setAuditLoading(false);
    }
  }

  async function savePreset() {
    if (!platformTenantId || !presetName.trim()) return;
    try {
      const targetUrl = editingPresetId
        ? `${API_BASE}/api/v1/admin/reports/presets/${encodeURIComponent(editingPresetId)}`
        : `${API_BASE}/api/v1/admin/reports/presets?tenant_id=${encodeURIComponent(platformTenantId)}`;
      const res = await adminFetch(
        targetUrl,
        {
          method: editingPresetId ? "PUT" : "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            name: presetName.trim(),
            decision_filter: decisionFilter,
            from_date: fromDate,
            to_date: toDate,
            sort_by: historySortBy,
            sort_dir: historySortDir,
          }),
        },
      );
      const data = await res.json();
      if (!res.ok) throw new Error(normalizeError(data?.detail ?? data, "Failed to save/update preset"));
      setPresetName("");
      setEditingPresetId(null);
      loadPresets();
    } catch (err) {
      setError(normalizeError(err?.message || err, "Failed to save/update preset"));
    }
  }

  function applyPreset(p) {
    setDecisionFilter(p.decision_filter || "ALL");
    setFromDate(p.from_date || fromDate);
    setToDate(p.to_date || toDate);
    setHistorySortBy(p.sort_by || "created_at");
    setHistorySortDir(p.sort_dir || "desc");
    setHistoryPage(1);
  }

  async function deletePreset(presetId) {
    try {
      const res = await adminFetch(`${API_BASE}/api/v1/admin/reports/presets/${encodeURIComponent(presetId)}`, {
        method: "DELETE",
      });
      const data = await res.json();
      if (!res.ok) throw new Error(normalizeError(data?.detail ?? data, "Failed to delete preset"));
      loadPresets();
    } catch (err) {
      setError(normalizeError(err?.message || err, "Failed to delete preset"));
    }
  }

  async function duplicatePreset(presetId) {
    try {
      const res = await adminFetch(`${API_BASE}/api/v1/admin/reports/presets/${encodeURIComponent(presetId)}/duplicate`, {
        method: "POST",
      });
      const data = await res.json();
      if (!res.ok) throw new Error(normalizeError(data?.detail ?? data, "Failed to duplicate preset"));
      loadPresets();
    } catch (err) {
      setError(normalizeError(err?.message || err, "Failed to duplicate preset"));
    }
  }

  function editPreset(p) {
    setEditingPresetId(p.preset_id);
    setPresetName(p.name || "");
    setDecisionFilter(p.decision_filter || "ALL");
    setFromDate(p.from_date || fromDate);
    setToDate(p.to_date || toDate);
    setHistorySortBy(p.sort_by || "created_at");
    setHistorySortDir(p.sort_dir || "desc");
  }

  async function runPresetNow(presetId) {
    try {
      const res = await adminFetch(`${API_BASE}/api/v1/admin/reports/presets/${encodeURIComponent(presetId)}/run`, {
        method: "POST",
      });
      const data = await res.json();
      if (!res.ok) throw new Error(normalizeError(data?.detail ?? data, "Failed to run preset"));
      setJobId(data.job_id);
      setJobStatus(data.status);
      setReport(null);
      setHistoryPage(1);
      loadHistory();
    } catch (err) {
      setError(normalizeError(err?.message || err, "Failed to run preset"));
    }
  }

  function jumpFromAudit(a) {
    const data = a?.event_data || {};
    const jobIdFromAudit = data.job_id || null;
    const presetIdFromAudit = data.source_preset_id || a?.entity_id || null;
    if (jobIdFromAudit) {
      setJobId(String(jobIdFromAudit));
      setJobStatus("queued");
      setHistoryPage(1);
      loadHistory();
      return;
    }
    if (presetIdFromAudit) {
      const p = presets.find((x) => x.preset_id === String(presetIdFromAudit));
      if (p) {
        applyPreset(p);
      }
    }
  }

  async function copyAuditJson(a) {
    try {
      const text = JSON.stringify(a?.event_data || {}, null, 2);
      await navigator.clipboard.writeText(text);
      setAuditJsonCopied(true);
      setTimeout(() => setAuditJsonCopied(false), 1200);
    } catch {
      setError("Failed to copy JSON");
    }
  }

  function downloadAuditPdf(a) {
    if (!platformTenantId || !a?.id) return;
    adminFetch(
      `${API_BASE}/api/v1/admin/reports/audit/${encodeURIComponent(a.id)}/pdf?tenant_id=${encodeURIComponent(platformTenantId)}`,
    )
      .then(async (res) => {
        if (!res.ok) {
          let msg = "Failed to download PDF";
          try {
            const j = await res.json();
            msg = normalizeError(j?.detail ?? j, msg);
          } catch {
            // ignore
          }
          throw new Error(msg);
        }
        return res.blob();
      })
      .then((blob) => {
        const url = URL.createObjectURL(blob);
        const link = document.createElement("a");
        link.href = url;
        link.download = `audit-${String(a.id)}.pdf`;
        document.body.appendChild(link);
        link.click();
        link.remove();
        URL.revokeObjectURL(url);
      })
      .catch((err) => {
        setError(normalizeError(err?.message || err, "Failed to download PDF"));
      });
  }


  async function cancelJob(targetJobId) {
    try {
      const res = await adminFetch(`${API_BASE}/api/v1/admin/reports/jobs/${encodeURIComponent(targetJobId)}/cancel`, {
        method: "POST",
      });
      const data = await res.json();
      if (!res.ok) throw new Error(normalizeError(data?.detail ?? data, "Failed to cancel report job"));
      if (jobId === targetJobId) setJobStatus(data.status || "cancelled");
      loadHistory();
    } catch (err) {
      setError(normalizeError(err?.message || err, "Failed to cancel report job"));
    }
  }

  async function retryJob(targetJobId) {
    try {
      const res = await adminFetch(`${API_BASE}/api/v1/admin/reports/jobs/${encodeURIComponent(targetJobId)}/retry`, {
        method: "POST",
      });
      const data = await res.json();
      if (!res.ok) throw new Error(normalizeError(data?.detail ?? data, "Failed to retry report job"));
      setJobId(data.job_id);
      setJobStatus(data.status);
      setReport(null);
      setHistoryPage(1);
      loadHistory();
    } catch (err) {
      setError(normalizeError(err?.message || err, "Failed to retry report job"));
    }
  }

  useEffect(() => {
    if (!jobId) return;
    let live = true;
    const tick = async () => {
      try {
        const res = await adminFetch(`${API_BASE}/api/v1/admin/reports/jobs/${encodeURIComponent(jobId)}`);
        const data = await res.json();
        if (!res.ok) throw new Error(normalizeError(data?.detail ?? data, "Failed to read report job"));
        if (!live) return;
        setJobStatus(data.status);
        if (data.status === "done") {
          setReport({
            generated_at: data.finished_at || data.created_at,
            tenant_id: data.tenant_id,
            tenant_name: platformTenantName || null,
            period: data.filters || {},
            summary: data.summary || {},
          });
        } else if (data.status === "failed") {
          setError(data.error || "Report job failed");
        }
      } catch (err) {
        if (live) setError(normalizeError(err?.message || err, "Failed to poll job"));
      }
    };
    tick();
    const id = setInterval(tick, 2500);
    return () => {
      live = false;
      clearInterval(id);
    };
  }, [jobId]);

  useEffect(() => {
    if (!exportJobId) return;
    let live = true;
    const tick = async () => {
      try {
        const res = await adminFetch(
          `${API_BASE}/api/v1/admin/compliance/tenant-export/jobs/${encodeURIComponent(exportJobId)}`,
        );
        const data = await res.json();
        if (!res.ok) throw new Error(normalizeError(data?.detail ?? data, "Failed to read export job"));
        if (!live) return;
        setExportJob(data);
        if (data.status === "failed") setError(data.error || "Export job failed");
      } catch (err) {
        if (live) setError(normalizeError(err?.message || err, "Failed to poll export job"));
      }
    };
    tick();
    const id = setInterval(tick, 2500);
    return () => {
      live = false;
      clearInterval(id);
    };
  }, [exportJobId]);

  useEffect(() => {
    loadHistory();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [platformTenantId, historyPage, historyStatusFilter, historyFromDate, historyToDate, historySortBy, historySortDir, historyTypeFilter]);

  useEffect(() => {
    loadPresets();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [platformTenantId]);

  useEffect(() => {
    loadAudit();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [platformTenantId, auditEventType]);

  useEffect(() => {
    if (!historyAutoRefresh || !platformTenantId) return;
    const id = setInterval(() => {
      loadHistory();
      loadAudit();
    }, 5000);
    return () => clearInterval(id);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [
    historyAutoRefresh,
    platformTenantId,
    historyPage,
    historyStatusFilter,
    historyFromDate,
    historyToDate,
    historySortBy,
    historySortDir,
    historyTypeFilter,
  ]);

  const historyMaxPage = Math.max(1, Math.ceil(historyTotal / historyPageSize));

  function submitJumpPage() {
    const n = Number(historyJumpPage);
    if (!Number.isInteger(n) || n < 1) return;
    setHistoryPage(Math.min(historyMaxPage, n));
  }

  return (
    <div className="p-8 space-y-5">
      <div className="flex items-center justify-between gap-3">
        <div>
          <p className="text-slate-400 text-[11px] tracking-wider uppercase">Reports</p>
          <h2 className="text-slate-100 text-xl font-semibold mt-1">{platformTenantName || "Selected bank"} report builder</h2>
          <p className="text-xs text-slate-500 mt-1">Generate and export tenant report data for compliance or management updates.</p>
        </div>
      </div>
      {!platformTenantId && (
        <div className="rounded-lg border border-amber-900/50 bg-amber-950/20 p-3 text-xs text-amber-200/90">
          Select a bank at login to generate report data.
        </div>
      )}
      <div className="rounded-xl border border-slate-800 bg-slate-900/50 p-4 flex flex-wrap items-end gap-3">
        <div>
          <label className="block text-[10px] uppercase tracking-wider text-slate-500 mb-1">From</label>
          <input
            type="date"
            value={fromDate}
            onChange={(e) => setFromDate(e.target.value)}
            className="rounded border border-slate-700 bg-slate-950 px-3 py-2 text-sm text-slate-200"
          />
        </div>
        <div>
          <label className="block text-[10px] uppercase tracking-wider text-slate-500 mb-1">To</label>
          <input
            type="date"
            value={toDate}
            onChange={(e) => setToDate(e.target.value)}
            className="rounded border border-slate-700 bg-slate-950 px-3 py-2 text-sm text-slate-200"
          />
        </div>
        <div>
          <label className="block text-[10px] uppercase tracking-wider text-slate-500 mb-1">Decision filter</label>
          <select
            value={decisionFilter}
            onChange={(e) => setDecisionFilter(e.target.value)}
            className="rounded border border-slate-700 bg-slate-950 px-3 py-2 text-sm text-slate-200"
          >
            <option value="ALL">ALL</option>
            <option value="APPROVE">APPROVE</option>
            <option value="LIMITED_APPROVAL">LIMITED_APPROVAL</option>
            <option value="REQUEST_OTP">REQUEST_OTP</option>
            <option value="SOFT_DECLINE">SOFT_DECLINE</option>
            <option value="BLOCK">BLOCK</option>
          </select>
        </div>
        <button
          type="button"
          onClick={generate}
          disabled={loading || !platformTenantId}
          className="px-4 py-2 rounded border border-cyan-400/70 text-cyan-200 text-xs uppercase tracking-wider disabled:opacity-50"
        >
          {loading ? "Generating..." : "Generate report"}
        </button>
        <button
          type="button"
          onClick={downloadPdf}
          disabled={!report}
          className="px-4 py-2 rounded border border-slate-700 text-slate-200 text-xs uppercase tracking-wider disabled:opacity-50"
        >
          Download PDF
        </button>
        <button
          type="button"
          onClick={downloadExcel}
          disabled={!report}
          className="px-4 py-2 rounded border border-slate-700 text-slate-200 text-xs uppercase tracking-wider disabled:opacity-50"
        >
          Download Excel
        </button>
      </div>
      <div className="rounded-xl border border-slate-800 bg-slate-900/50 p-4">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div>
            <p className="text-[10px] uppercase tracking-wider text-slate-500">Compliance export</p>
            <p className="text-xs text-slate-400 mt-1">Generate tenant export snapshot (async job) and download signed artifact.</p>
          </div>
          <div className="flex items-center gap-2">
            <button
              type="button"
              onClick={createComplianceExportJob}
              disabled={exportLoading || !platformTenantId}
              className="px-3 py-1.5 rounded border border-cyan-500/70 text-cyan-200 text-[11px] uppercase tracking-wider disabled:opacity-50"
            >
              {exportLoading ? "Starting..." : "Start export"}
            </button>
            <button
              type="button"
              onClick={signAndOpenComplianceExport}
              disabled={!exportJobId || exportJob?.status !== "done"}
              className="px-3 py-1.5 rounded border border-slate-700 text-slate-200 text-[11px] uppercase tracking-wider disabled:opacity-50"
            >
              Download export
            </button>
          </div>
        </div>
        <div className="mt-3 text-xs text-slate-400">
          Job: <span className="text-slate-300">{exportJobId ? `${String(exportJobId).slice(0, 8)}...` : "-"}</span>
          {" · "}Status: <span className="text-slate-300">{exportJob?.status || "-"}</span>
          {exportJob?.error ? <span className="text-rose-300"> · {exportJob.error}</span> : null}
        </div>
      </div>
      <div className="rounded-xl border border-slate-800 bg-slate-900/50 p-4">
        <div className="flex items-center justify-between gap-2 mb-3">
          <p className="text-[10px] uppercase tracking-wider text-slate-500">Audit timeline</p>
          <div className="flex items-center gap-2">
            <select
              value={auditEventType}
              onChange={(e) => setAuditEventType(e.target.value)}
              className="rounded border border-slate-700 bg-slate-950 px-2 py-1.5 text-xs text-slate-200"
            >
              <option value="ALL">ALL</option>
              <option value="REPORT_PRESET_CREATED">PRESET_CREATED</option>
              <option value="REPORT_PRESET_UPDATED">PRESET_UPDATED</option>
              <option value="REPORT_PRESET_DELETED">PRESET_DELETED</option>
              <option value="REPORT_PRESET_DUPLICATED">PRESET_DUPLICATED</option>
              <option value="REPORT_PRESET_RUN">PRESET_RUN</option>
              <option value="REPORT_JOB_COMPLETE">JOB_COMPLETE</option>
              <option value="REPORT_JOB_FAILED">JOB_FAILED</option>
            </select>
            <button
              type="button"
              onClick={loadAudit}
              className="px-3 py-1.5 rounded border border-slate-700 text-[10px] uppercase tracking-wider text-slate-300"
            >
              Refresh
            </button>
          </div>
        </div>
        {auditLoading ? (
          <p className="text-xs text-slate-500">Loading audit...</p>
        ) : auditItems.length ? (
          <div className="space-y-2 max-h-72 overflow-auto pr-1">
            {auditItems.map((a) => (
              <div key={a.id} className="rounded border border-slate-800 bg-slate-950/40 px-3 py-2">
                <div className="flex items-center justify-between gap-2 text-xs">
                  <span className="text-cyan-300">{a.event_type}</span>
                  <span className="text-slate-500">{a.created_at ? new Date(a.created_at).toLocaleString() : ""}</span>
                </div>
                <div className="mt-1 text-[11px] text-slate-400">
                  actor: <span className="text-slate-300">{a.actor_id || "-"}</span>
                  {a.entity_id ? (
                    <>
                      {" | "}entity: <span className="text-slate-300">{String(a.entity_id).slice(0, 8)}...</span>
                    </>
                  ) : null}
                </div>
                <div className="mt-2 flex items-center gap-2">
                  <button
                    type="button"
                    onClick={() => setSelectedAudit(a)}
                    className="px-2 py-1 rounded border border-slate-700 text-[10px] uppercase text-slate-300"
                  >
                    Details
                  </button>
                  <button
                    type="button"
                    onClick={() => jumpFromAudit(a)}
                    className="px-2 py-1 rounded border border-cyan-700/60 text-[10px] uppercase text-cyan-300"
                  >
                    Jump
                  </button>
                </div>
              </div>
            ))}
          </div>
        ) : (
          <p className="text-xs text-slate-500">No audit events yet.</p>
        )}
      </div>
      {selectedAudit && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 p-4" role="dialog">
          <div className="w-full max-w-3xl rounded-2xl border border-slate-700 bg-slate-950 p-5 shadow-2xl">
            <div className="flex items-center justify-between gap-3">
              <div>
                <p className="text-[10px] uppercase tracking-wider text-slate-500">Audit details</p>
                <h3 className="text-slate-100 text-sm font-semibold mt-1">{selectedAudit.event_type}</h3>
              </div>
              <button
                type="button"
                onClick={() => setSelectedAudit(null)}
                className="px-3 py-1.5 rounded border border-slate-700 text-xs text-slate-300"
              >
                Close
              </button>
            </div>
            <div className="mt-3 text-xs text-slate-400">
              <span>actor: </span>
              <span className="text-slate-200">{selectedAudit.actor_id || "-"}</span>
              <span className="mx-2">|</span>
              <span>time: </span>
              <span className="text-slate-200">
                {selectedAudit.created_at ? new Date(selectedAudit.created_at).toLocaleString() : "-"}
              </span>
            </div>
            <div className="mt-4">
              <p className="text-[10px] uppercase tracking-wider text-slate-500 mb-2">Event data JSON</p>
              <pre className="max-h-80 overflow-auto rounded border border-slate-800 bg-slate-900/60 p-3 text-[11px] text-slate-200">
                {JSON.stringify(selectedAudit.event_data || {}, null, 2)}
              </pre>
            </div>
            <div className="mt-4 flex items-center gap-2">
              <button
                type="button"
                onClick={() => copyAuditJson(selectedAudit)}
                className="px-3 py-1.5 rounded border border-slate-700 text-xs text-slate-300"
              >
                {auditJsonCopied ? "Copied" : "Copy JSON"}
              </button>
              <button
                type="button"
                onClick={() => downloadAuditPdf(selectedAudit)}
                className="px-3 py-1.5 rounded border border-emerald-700/70 text-xs text-emerald-300"
              >
                Download PDF
              </button>
              <button
                type="button"
                onClick={() => jumpFromAudit(selectedAudit)}
                className="px-3 py-1.5 rounded border border-cyan-700/70 text-xs text-cyan-300"
              >
                Jump to related item
              </button>
            </div>
          </div>
        </div>
      )}
      <div className="rounded-xl border border-slate-800 bg-slate-900/50 p-4">
        <div className="flex flex-wrap items-end gap-2">
          {canManagePresets && (
            <>
              <div>
                <label className="block text-[10px] uppercase tracking-wider text-slate-500 mb-1">Preset name</label>
                <input
                  value={presetName}
                  onChange={(e) => setPresetName(e.target.value)}
                  placeholder="e.g. Monthly board report"
                  className="rounded border border-slate-700 bg-slate-950 px-3 py-2 text-sm text-slate-200"
                />
              </div>
              <button
                type="button"
                onClick={savePreset}
                disabled={!platformTenantId || !presetName.trim()}
                className="px-4 py-2 rounded border border-emerald-700/70 text-emerald-300 text-xs uppercase tracking-wider disabled:opacity-50"
              >
                {editingPresetId ? "Update preset" : "Save preset"}
              </button>
              {editingPresetId && (
                <button
                  type="button"
                  onClick={() => {
                    setEditingPresetId(null);
                    setPresetName("");
                  }}
                  className="px-4 py-2 rounded border border-slate-700 text-slate-300 text-xs uppercase tracking-wider"
                >
                  Cancel edit
                </button>
              )}
            </>
          )}
        </div>
        {!canManagePresets && (
          <p className="text-xs text-slate-500">Viewer mode: you can apply and run presets, but cannot modify them.</p>
        )}
        <div className="mt-3 space-y-2">
          {presets.length ? (
            presets.map((p) => (
              <div
                key={p.preset_id}
                className="rounded border border-slate-800 bg-slate-950/40 px-3 py-2 flex flex-wrap items-center justify-between gap-2"
              >
                <div className="text-xs text-slate-300">
                  <span className="font-semibold">{p.name}</span>
                  <span className="text-slate-500 ml-2">
                    {p.from_date} to {p.to_date} | {p.decision_filter} | {p.sort_by}:{p.sort_dir}
                  </span>
                </div>
                <div className="flex items-center gap-2">
                  <button
                    type="button"
                    onClick={() => runPresetNow(p.preset_id)}
                    className="px-2 py-1 rounded border border-emerald-700/70 text-emerald-300 text-[10px] uppercase"
                  >
                    Run now
                  </button>
                  <button
                    type="button"
                    onClick={() => applyPreset(p)}
                    className="px-2 py-1 rounded border border-cyan-700/70 text-cyan-300 text-[10px] uppercase"
                  >
                    Apply
                  </button>
                  {canManagePresets && (
                    <>
                      <button
                        type="button"
                        onClick={() => editPreset(p)}
                        className="px-2 py-1 rounded border border-violet-700/70 text-violet-300 text-[10px] uppercase"
                      >
                        Edit
                      </button>
                      <button
                        type="button"
                        onClick={() => duplicatePreset(p.preset_id)}
                        className="px-2 py-1 rounded border border-blue-700/70 text-blue-300 text-[10px] uppercase"
                      >
                        Duplicate
                      </button>
                      <button
                        type="button"
                        onClick={() => deletePreset(p.preset_id)}
                        className="px-2 py-1 rounded border border-red-700/70 text-red-300 text-[10px] uppercase"
                      >
                        Delete
                      </button>
                    </>
                  )}
                </div>
              </div>
            ))
          ) : (
            <p className="text-xs text-slate-500">No presets yet.</p>
          )}
        </div>
      </div>
      {jobStatus && (
        <div className="text-xs text-slate-400">
          Report job status: <span className="text-slate-200">{jobStatus}</span> {jobId ? `(${jobId.slice(0, 8)}...)` : ""}
        </div>
      )}
      {error && <div className="rounded-lg border border-red-500/40 bg-red-500/10 px-4 py-2 text-sm text-red-300">{error}</div>}

      {report && (
        <div className="space-y-4">
          <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-4 gap-4">
            <div className="rounded-xl border border-slate-800 bg-slate-900/50 p-4">
              <p className="text-[10px] uppercase tracking-wider text-slate-500">Transactions</p>
              <p className="text-2xl font-semibold text-slate-100 mt-2">{report.summary.total_transactions}</p>
            </div>
            <div className="rounded-xl border border-slate-800 bg-slate-900/50 p-4">
              <p className="text-[10px] uppercase tracking-wider text-slate-500">Total amount</p>
              <p className="text-2xl font-semibold text-slate-100 mt-2">{report.summary.total_amount.toLocaleString()}</p>
            </div>
            <div className="rounded-xl border border-slate-800 bg-slate-900/50 p-4">
              <p className="text-[10px] uppercase tracking-wider text-slate-500">Open alerts</p>
              <p className="text-2xl font-semibold text-amber-200 mt-2">{report.summary.open_alerts}</p>
            </div>
            <div className="rounded-xl border border-slate-800 bg-slate-900/50 p-4">
              <p className="text-[10px] uppercase tracking-wider text-slate-500">Avg fraud score</p>
              <p className="text-2xl font-semibold text-cyan-200 mt-2">{report.summary.avg_fraud_score}</p>
            </div>
          </div>
          <div className="rounded-xl border border-slate-800 bg-slate-900/50 p-4">
            <p className="text-[10px] uppercase tracking-wider text-slate-500 mb-2">Decision counts</p>
            <div className="grid grid-cols-2 md:grid-cols-4 gap-2">
              {Object.entries(report.summary.decision_counts || {}).map(([k, v]) => (
                <div key={k} className="rounded border border-slate-800 bg-slate-950/50 px-3 py-2 text-sm">
                  <div className="text-slate-400 text-[10px] uppercase">{k}</div>
                  <div className="text-slate-200 font-semibold">{v}</div>
                </div>
              ))}
            </div>
          </div>
        </div>
      )}
      <div className="rounded-xl border border-slate-800 bg-slate-900/50 p-4">
        <div className="flex items-center justify-between gap-2 mb-3">
          <p className="text-[10px] uppercase tracking-wider text-slate-500">Report job history</p>
          <div className="flex items-center gap-2">
            <label className="flex items-center gap-1 text-[10px] uppercase tracking-wider text-slate-400">
              <input
                type="checkbox"
                checked={historyAutoRefresh}
                onChange={(e) => setHistoryAutoRefresh(Boolean(e.target.checked))}
              />
              Auto refresh
            </label>
            <button
              type="button"
              onClick={loadHistory}
              className="px-3 py-1.5 rounded border border-slate-700 text-[10px] uppercase tracking-wider text-slate-300"
            >
              Refresh
            </button>
          </div>
        </div>
        <div className="mb-3 flex flex-wrap items-end gap-2">
          <div>
            <label className="block text-[10px] uppercase tracking-wider text-slate-500 mb-1">Type</label>
            <div className="inline-flex rounded border border-slate-700 overflow-hidden">
              {["ALL", "REPORTS", "EXPORTS"].map((t) => (
                <button
                  key={t}
                  type="button"
                  onClick={() => {
                    setHistoryPage(1);
                    setHistoryTypeFilter(t);
                  }}
                  className={`px-2.5 py-1.5 text-[10px] uppercase tracking-wider ${
                    historyTypeFilter === t ? "bg-slate-800 text-slate-100" : "bg-slate-950 text-slate-400"
                  }`}
                >
                  {t}
                </button>
              ))}
            </div>
          </div>
          <div>
            <label className="block text-[10px] uppercase tracking-wider text-slate-500 mb-1">Status</label>
            <select
              value={historyStatusFilter}
              onChange={(e) => {
                setHistoryPage(1);
                setHistoryStatusFilter(e.target.value);
              }}
              className="rounded border border-slate-700 bg-slate-950 px-2 py-1.5 text-xs text-slate-200"
            >
              <option value="ALL">ALL</option>
              <option value="QUEUED">QUEUED</option>
              <option value="RUNNING">RUNNING</option>
              <option value="DONE">DONE</option>
              <option value="FAILED">FAILED</option>
              <option value="CANCELLED">CANCELLED</option>
            </select>
          </div>
          <div>
            <label className="block text-[10px] uppercase tracking-wider text-slate-500 mb-1">From</label>
            <input
              type="date"
              value={historyFromDate}
              onChange={(e) => {
                setHistoryPage(1);
                setHistoryFromDate(e.target.value);
              }}
              className="rounded border border-slate-700 bg-slate-950 px-2 py-1.5 text-xs text-slate-200"
            />
          </div>
          <div>
            <label className="block text-[10px] uppercase tracking-wider text-slate-500 mb-1">To</label>
            <input
              type="date"
              value={historyToDate}
              onChange={(e) => {
                setHistoryPage(1);
                setHistoryToDate(e.target.value);
              }}
              className="rounded border border-slate-700 bg-slate-950 px-2 py-1.5 text-xs text-slate-200"
            />
          </div>
          <div>
            <label className="block text-[10px] uppercase tracking-wider text-slate-500 mb-1">Sort by</label>
            <select
              value={historySortBy}
              onChange={(e) => {
                setHistoryPage(1);
                setHistorySortBy(e.target.value);
              }}
              className="rounded border border-slate-700 bg-slate-950 px-2 py-1.5 text-xs text-slate-200"
            >
              <option value="created_at">Created</option>
              <option value="finished_at">Finished</option>
              <option value="status">Status</option>
            </select>
          </div>
          <div>
            <label className="block text-[10px] uppercase tracking-wider text-slate-500 mb-1">Direction</label>
            <select
              value={historySortDir}
              onChange={(e) => {
                setHistoryPage(1);
                setHistorySortDir(e.target.value);
              }}
              className="rounded border border-slate-700 bg-slate-950 px-2 py-1.5 text-xs text-slate-200"
            >
              <option value="desc">DESC</option>
              <option value="asc">ASC</option>
            </select>
          </div>
        </div>
        {historyLoading ? (
          <p className="text-xs text-slate-500">Loading history...</p>
        ) : history.length ? (
          <div className="space-y-2">
            {history.map((h) => (
              (() => {
                const isExport = String(h?.filters?.kind || "") === "tenant_export";
                return (
              <div
                key={h.job_id}
                className="rounded border border-slate-800 bg-slate-950/40 px-3 py-2 flex flex-wrap items-center justify-between gap-2"
              >
                <div className="text-xs text-slate-300">
                  <span className="font-mono text-slate-400">{String(h.job_id).slice(0, 8)}...</span>
                  {"  "}
                  <span className="text-[10px] px-1.5 py-0.5 rounded border border-slate-700 text-slate-300">
                    {isExport ? "EXPORT" : "REPORT"}
                  </span>
                  {"  "}
                  <span className="uppercase">{h.status}</span>
                  {"  "}
                  <span className="text-slate-500">{h.created_at ? new Date(h.created_at).toLocaleString() : ""}</span>
                </div>
                <div className="flex items-center gap-2">
                  {(h.status === "queued" || h.status === "running") && !isExport && (
                    <button
                      type="button"
                      onClick={() => cancelJob(h.job_id)}
                      className="px-2 py-1 rounded border border-amber-700/70 text-amber-300 text-[10px] uppercase"
                    >
                      Cancel
                    </button>
                  )}
                  {(h.status === "failed" || h.status === "cancelled") && !isExport && (
                    <button
                      type="button"
                      onClick={() => retryJob(h.job_id)}
                      className="px-2 py-1 rounded border border-cyan-700/70 text-cyan-300 text-[10px] uppercase"
                    >
                      Retry
                    </button>
                  )}
                  {isExport && h.status === "done" && (
                    <button
                      type="button"
                      onClick={async () => {
                        try {
                          const res = await adminFetch(
                            `${API_BASE}/api/v1/admin/compliance/tenant-export/jobs/${encodeURIComponent(h.job_id)}/sign-download`,
                            { method: "POST" },
                          );
                          const data = await res.json();
                          if (!res.ok) throw new Error(normalizeError(data?.detail ?? data, "Failed to sign export download"));
                          const url = String(data.url || "");
                          if (!url) throw new Error("Signed URL missing");
                          window.open(`${API_BASE}${url}`, "_blank");
                        } catch (err) {
                          setError(normalizeError(err?.message || err, "Failed to download export"));
                        }
                      }}
                      className="px-2 py-1 rounded border border-emerald-700/70 text-emerald-300 text-[10px] uppercase"
                    >
                      Download
                    </button>
                  )}
                </div>
              </div>
                );
              })()
            ))}
          </div>
        ) : (
          <p className="text-xs text-slate-500">No report/export jobs yet.</p>
        )}
        <div className="mt-3 flex items-center justify-between text-xs text-slate-400">
          <span>
            Page {historyPage} of {historyMaxPage} ({historyTotal} report/export jobs)
          </span>
          <div className="flex items-center gap-2">
            <input
              type="number"
              min={1}
              max={historyMaxPage}
              value={historyJumpPage}
              onChange={(e) => setHistoryJumpPage(e.target.value)}
              className="w-20 rounded border border-slate-700 bg-slate-950 px-2 py-1"
            />
            <button
              type="button"
              onClick={submitJumpPage}
              className="px-2 py-1 rounded border border-slate-700"
            >
              Go
            </button>
            <button
              type="button"
              onClick={() => setHistoryPage((p) => Math.max(1, p - 1))}
              disabled={historyPage <= 1}
              className="px-2 py-1 rounded border border-slate-700 disabled:opacity-40"
            >
              Prev
            </button>
            <button
              type="button"
              onClick={() =>
                setHistoryPage((p) => {
                  return Math.min(historyMaxPage, p + 1);
                })
              }
              disabled={historyPage >= historyMaxPage}
              className="px-2 py-1 rounded border border-slate-700 disabled:opacity-40"
            >
              Next
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}

function ManualModelTrainingPanel({ adminFetch, platformTenantId }) {
  const [modelType, setModelType] = useState("fraud");
  const [contractVersion, setContractVersion] = useState("v1");
  const [file, setFile] = useState(null);
  const [uploads, setUploads] = useState([]);
  const [loading, setLoading] = useState(false);
  const [msg, setMsg] = useState(null);
  const [testModal, setTestModal] = useState(null);
  const [testLoadingId, setTestLoadingId] = useState(null);
  const [trainPendingId, setTrainPendingId] = useState(null);
  const [labelMapModal, setLabelMapModal] = useState(null);
  const [labelMapLoadingId, setLabelMapLoadingId] = useState(null);
  const [careHoldoutFile, setCareHoldoutFile] = useState(null);
  const [careHoldoutTesting, setCareHoldoutTesting] = useState(false);
  const [saveDefaultHoldout, setSaveDefaultHoldout] = useState(true);
  const [useDefaultHoldout, setUseDefaultHoldout] = useState(false);
  const [fraudHoldoutFile, setFraudHoldoutFile] = useState(null);
  const [fraudHoldoutTesting, setFraudHoldoutTesting] = useState(false);
  const [saveFraudDefaultHoldout, setSaveFraudDefaultHoldout] = useState(true);
  const [useFraudDefaultHoldout, setUseFraudDefaultHoldout] = useState(false);
  const [fraudDriftStatus, setFraudDriftStatus] = useState(null);
  const [splitLoadingId, setSplitLoadingId] = useState(null);
  const [qualityLoadingId, setQualityLoadingId] = useState(null);
  const [qualityModal, setQualityModal] = useState(null);
  const [qualityByUpload, setQualityByUpload] = useState({});
  const [recoCfg, setRecoCfg] = useState({
    trust_green_min: "0.72",
    dup_green_max: "0.45",
    trust_amber_min: "0.52",
  });
  const [recoCfgLoading, setRecoCfgLoading] = useState(false);

  async function loadUploads(nextModel = modelType) {
    try {
      const tid = platformTenantId ? `&tenant_id=${encodeURIComponent(platformTenantId)}` : "";
      const res = await adminFetch(`${API_BASE}/api/v1/admin/training/uploads?model_type=${nextModel}&limit=30${tid}`);
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || res.statusText);
      const list = Array.isArray(data) ? data : [];
      setUploads(list);
      if (nextModel === "care" && list.length) {
        const qualityPairs = await Promise.all(
          list.map(async (u) => {
            try {
              const r = await adminFetch(
                `${API_BASE}/api/v1/admin/training/care/data-quality?upload_id=${u.id}`
              );
              const j = await r.json();
              if (!r.ok) return [u.id, null];
              return [u.id, j];
            } catch {
              return [u.id, null];
            }
          })
        );
        setQualityByUpload(Object.fromEntries(qualityPairs.filter(([_, q]) => !!q)));
      } else if (nextModel !== "care") {
        setQualityByUpload({});
      }
    } catch (err) {
      setMsg(err.message || "Failed to load uploads");
    }
  }

  useEffect(() => {
    loadUploads(modelType);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [modelType, platformTenantId]);

  useEffect(() => {
    if (modelType !== "fraud") return;
    let alive = true;
    const load = async () => {
      try {
        const res = await adminFetch(`${API_BASE}/api/v1/admin/monitoring/fraud-drift-status`);
        const data = await res.json();
        if (!res.ok) return;
        if (alive) setFraudDriftStatus(data);
      } catch {
        // ignore badge failures
      }
    };
    load();
    const id = setInterval(load, 30000);
    return () => {
      alive = false;
      clearInterval(id);
    };
  }, [modelType]);

  useEffect(() => {
    if (modelType !== "care") return;
    (async () => {
      try {
        setRecoCfgLoading(true);
        const res = await adminFetch(`${API_BASE}/api/v1/admin/training/care/retrain-reco-config`);
        const data = await res.json();
        if (!res.ok) throw new Error(data.detail || res.statusText);
        setRecoCfg({
          trust_green_min: String(data.trust_green_min ?? "0.72"),
          dup_green_max: String(data.dup_green_max ?? "0.45"),
          trust_amber_min: String(data.trust_amber_min ?? "0.52"),
        });
      } catch (err) {
        setMsg(err.message || "Failed to load recommendation config");
      } finally {
        setRecoCfgLoading(false);
      }
    })();
  }, [modelType]);

  const trainingInFlight = uploads.some((u) => u.status === "TRAINING");
  useEffect(() => {
    if (!trainingInFlight) return;
    const id = setInterval(() => loadUploads(modelType), 3000);
    return () => clearInterval(id);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [trainingInFlight, modelType]);

  async function onUpload() {
    if (!file) return;
    setLoading(true);
    setMsg(null);
    try {
      const form = new FormData();
      form.append("model_type", modelType);
      form.append("contract_version", contractVersion);
      form.append("file", file);
      if (platformTenantId) form.append("tenant_id", platformTenantId);
      const res = await adminFetch(`${API_BASE}/api/v1/admin/training/upload`, {
        method: "POST",
        body: form,
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || res.statusText);
      setMsg(`Uploaded ${data.filename} (${data.row_count} rows).`);
      setFile(null);
      await loadUploads(modelType);
    } catch (err) {
      setMsg(err.message || "Upload failed");
    } finally {
      setLoading(false);
    }
  }

  async function triggerTrain(uploadId) {
    setTrainPendingId(uploadId);
    setLoading(true);
    setMsg(null);
    try {
      const form = new FormData();
      form.append("upload_id", uploadId);
      const res = await adminFetch(`${API_BASE}/api/v1/admin/training/${modelType}/trigger`, {
        method: "POST",
        body: form,
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || res.statusText);
      setMsg(data.message || "Training started.");
      await loadUploads(modelType);
    } catch (err) {
      setMsg(err.message || "Failed to start training");
    } finally {
      setLoading(false);
      setTrainPendingId(null);
    }
  }

  async function testUpload(uploadId) {
    setTestLoadingId(uploadId);
    setMsg(null);
    try {
      const form = new FormData();
      form.append("upload_id", uploadId);
      form.append("sample_max", modelType === "fraud" ? "120" : "300");
      const testPath =
        modelType === "fraud"
          ? `${API_BASE}/api/v1/admin/training/fraud/test-upload`
          : `${API_BASE}/api/v1/admin/training/care/test-upload`;
      const res = await adminFetch(testPath, {
        method: "POST",
        body: form,
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || res.statusText);
      setTestModal(data);
      setMsg(
        data.retrain_locked
          ? "Quality thresholds met — further manual training on this upload is disabled."
          : "Evaluation complete. You can train again if needed."
      );
      await loadUploads(modelType);
    } catch (err) {
      setMsg(err.message || "Test failed");
    } finally {
      setTestLoadingId(null);
    }
  }

  async function showLabelMap(uploadId) {
    setLabelMapLoadingId(uploadId);
    setMsg(null);
    try {
      const res = await adminFetch(`${API_BASE}/api/v1/admin/training/care/label-mapping?upload_id=${uploadId}`);
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || res.statusText);
      setLabelMapModal(data);
    } catch (err) {
      setMsg(err.message || "Failed to load label mapping");
    } finally {
      setLabelMapLoadingId(null);
    }
  }

  async function testCareExternalHoldout() {
    if (!careHoldoutFile && !useDefaultHoldout) return;
    setCareHoldoutTesting(true);
    setMsg(null);
    try {
      const form = new FormData();
      if (careHoldoutFile) form.append("file", careHoldoutFile);
      form.append("sample_max", "1000");
      form.append("use_default", useDefaultHoldout ? "true" : "false");
      form.append("save_as_default", saveDefaultHoldout ? "true" : "false");
      const res = await adminFetch(`${API_BASE}/api/v1/admin/training/care/test-external`, {
        method: "POST",
        body: form,
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || res.statusText);
      setTestModal(data);
      setMsg("External holdout evaluation complete.");
    } catch (err) {
      setMsg(err.message || "External holdout test failed");
    } finally {
      setCareHoldoutTesting(false);
    }
  }

  async function testFraudExternalHoldout() {
    if (!fraudHoldoutFile && !useFraudDefaultHoldout) return;
    setFraudHoldoutTesting(true);
    setMsg(null);
    try {
      const form = new FormData();
      if (fraudHoldoutFile) form.append("file", fraudHoldoutFile);
      form.append("sample_max", "1200");
      form.append("use_default", useFraudDefaultHoldout ? "true" : "false");
      form.append("save_as_default", saveFraudDefaultHoldout ? "true" : "false");
      const res = await adminFetch(`${API_BASE}/api/v1/admin/training/fraud/test-external`, {
        method: "POST",
        body: form,
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || res.statusText);
      setTestModal(data);
      setMsg("Fraud external holdout evaluation complete.");
    } catch (err) {
      setMsg(err.message || "Fraud external holdout test failed");
    } finally {
      setFraudHoldoutTesting(false);
    }
  }

  async function autoSplitCareUpload(uploadId) {
    setSplitLoadingId(uploadId);
    setMsg(null);
    try {
      const form = new FormData();
      form.append("upload_id", uploadId);
      form.append("test_ratio", "0.2");
      const res = await adminFetch(`${API_BASE}/api/v1/admin/training/care/split-upload`, {
        method: "POST",
        body: form,
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || res.statusText);
      setUseDefaultHoldout(true);
      setMsg(
        `Split done. Train rows: ${data.train_rows}, test rows: ${data.test_rows}. Default holdout is now ready.`
      );
    } catch (err) {
      setMsg(err.message || "Auto split failed");
    } finally {
      setSplitLoadingId(null);
    }
  }

  async function analyzeCareDataQuality(uploadId) {
    setQualityLoadingId(uploadId);
    setMsg(null);
    try {
      const res = await adminFetch(`${API_BASE}/api/v1/admin/training/care/data-quality?upload_id=${uploadId}`);
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || res.statusText);
      setQualityModal(data);
      setQualityByUpload((prev) => ({ ...prev, [uploadId]: data }));
    } catch (err) {
      setMsg(err.message || "Data quality analysis failed");
    } finally {
      setQualityLoadingId(null);
    }
  }

  async function analyzeFraudDataQuality(uploadId) {
    setQualityLoadingId(uploadId);
    setMsg(null);
    try {
      const res = await adminFetch(`${API_BASE}/api/v1/admin/training/fraud/data-quality?upload_id=${uploadId}`);
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || res.statusText);
      setQualityModal(data);
    } catch (err) {
      setMsg(err.message || "Fraud data quality analysis failed");
    } finally {
      setQualityLoadingId(null);
    }
  }

  async function saveCareRecoConfig() {
    setMsg(null);
    try {
      const form = new FormData();
      form.append("trust_green_min", String(Number(recoCfg.trust_green_min)));
      form.append("dup_green_max", String(Number(recoCfg.dup_green_max)));
      form.append("trust_amber_min", String(Number(recoCfg.trust_amber_min)));
      const res = await adminFetch(`${API_BASE}/api/v1/admin/training/care/retrain-reco-config`, {
        method: "PATCH",
        body: form,
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || res.statusText);
      setRecoCfg({
        trust_green_min: String(data.trust_green_min),
        dup_green_max: String(data.dup_green_max),
        trust_amber_min: String(data.trust_amber_min),
      });
      setMsg("Recommendation thresholds saved.");
      await loadUploads("care");
    } catch (err) {
      setMsg(err.message || "Failed to save recommendation config");
    }
  }

  async function resetCareRecoConfig() {
    setMsg(null);
    try {
      const res = await adminFetch(`${API_BASE}/api/v1/admin/training/care/retrain-reco-config/reset`, {
        method: "POST",
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || res.statusText);
      setRecoCfg({
        trust_green_min: String(data.trust_green_min),
        dup_green_max: String(data.dup_green_max),
        trust_amber_min: String(data.trust_amber_min),
      });
      setMsg("Recommendation thresholds reset to env defaults.");
      await loadUploads("care");
    } catch (err) {
      setMsg(err.message || "Failed to reset recommendation config");
    }
  }

  return (
    <div className="space-y-4">
      <style>{`
        @keyframes manualTrainIndeterminate {
          0% { left: -45%; }
          100% { left: 100%; }
        }
      `}</style>
      <div className="flex flex-wrap items-center gap-2">
        <span className="inline-flex items-center rounded-md border border-cyan-500/50 bg-cyan-950/40 px-2.5 py-1 text-[10px] font-bold tracking-wider text-cyan-200">
          Manual · CSV upload
        </span>
        <span className="text-[11px] text-slate-500 max-w-xl">
          File → stored rows → import + trainer subprocess. Distinct from the DB-wide &quot;Trigger fraud train&quot; below.
        </span>
      </div>
      <div className="rounded-xl border border-slate-700 bg-slate-900/60 p-4 space-y-3">
        <div className="text-xs uppercase tracking-wider text-slate-400">Upload dataset for manual training</div>
        {platformTenantId ? (
          <p className="text-[11px] text-slate-500">
            File is stored under the <span className="text-slate-300">selected bank</span> (needed for tenant fine-tune / eligibility).
          </p>
        ) : (
          <p className="text-[11px] text-amber-600/90">
            No bank selected — upload is <span className="font-semibold">global</span> and won&apos;t count for per-bank Phase 3 eligibility. Choose a bank on Home first.
          </p>
        )}
        <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
          <div>
            <label className="block text-[10px] text-slate-500 uppercase mb-1">Model</label>
            <select
              value={modelType}
              onChange={(e) => setModelType(e.target.value)}
              className="w-full rounded border border-slate-600 bg-slate-900 px-3 py-2 text-slate-200 text-sm"
            >
              <option value="fraud">Fraud model</option>
              <option value="care">Customer care model</option>
            </select>
          </div>
          <div>
            <label className="block text-[10px] text-slate-500 uppercase mb-1">Contract</label>
            <select
              value={contractVersion}
              onChange={(e) => setContractVersion(e.target.value)}
              className="w-full rounded border border-slate-600 bg-slate-900 px-3 py-2 text-slate-200 text-sm"
            >
              <option value="v1">v1</option>
            </select>
          </div>
          <div className="md:col-span-2">
            <label className="block text-[10px] text-slate-500 uppercase mb-1">Data file</label>
            <input
              type="file"
              accept={modelType === "fraud" ? ".csv" : ".csv,.jsonl"}
              onChange={(e) => setFile(e.target.files?.[0] || null)}
              className="w-full rounded border border-slate-600 bg-slate-900 px-3 py-2 text-slate-200 text-sm"
            />
          </div>
        </div>
        <button
          type="button"
          onClick={onUpload}
          disabled={loading || !file}
          className="px-4 py-2 rounded-md border border-cyan-500 bg-cyan-900/50 text-cyan-200 text-xs tracking-wider uppercase disabled:opacity-50"
        >
          {loading ? "Uploading..." : "Upload file"}
        </button>
        {msg && <div className="text-xs text-slate-300">{msg}</div>}
      </div>
      {modelType === "care" && (
        <div className="rounded-xl border border-indigo-700/60 bg-indigo-950/10 p-4 space-y-3">
          <div className="text-xs uppercase tracking-wider text-indigo-300">External holdout test (care)</div>
          <div className="grid grid-cols-1 md:grid-cols-3 gap-3 items-end">
            <div className="md:col-span-2">
              <label className="block text-[10px] text-slate-500 uppercase mb-1">Holdout file (.csv or .jsonl)</label>
              <input
                type="file"
                accept=".csv,.jsonl"
                onChange={(e) => setCareHoldoutFile(e.target.files?.[0] || null)}
                className="w-full rounded border border-slate-600 bg-slate-900 px-3 py-2 text-slate-200 text-sm"
              />
            </div>
            <button
              type="button"
              onClick={testCareExternalHoldout}
              disabled={(!careHoldoutFile && !useDefaultHoldout) || careHoldoutTesting || loading}
              className="px-4 py-2 rounded-md border border-indigo-500 bg-indigo-900/40 text-indigo-200 text-xs tracking-wider uppercase disabled:opacity-50"
            >
              {careHoldoutTesting ? "Testing..." : "Test external"}
            </button>
          </div>
          <div className="flex flex-wrap items-center gap-3 text-xs text-slate-300">
            <label className="flex items-center gap-1.5">
              <input
                type="checkbox"
                checked={saveDefaultHoldout}
                onChange={(e) => setSaveDefaultHoldout(e.target.checked)}
                className="rounded border-slate-600"
              />
              Save selected file as default holdout
            </label>
            <label className="flex items-center gap-1.5">
              <input
                type="checkbox"
                checked={useDefaultHoldout}
                onChange={(e) => setUseDefaultHoldout(e.target.checked)}
                className="rounded border-slate-600"
              />
              Use default holdout when no file selected
            </label>
          </div>
        </div>
      )}
      {modelType === "fraud" && (
        <div className="rounded-xl border border-cyan-700/60 bg-cyan-950/10 p-4 space-y-3">
          <div className="flex items-center justify-between gap-2">
            <div className="text-xs uppercase tracking-wider text-cyan-300">External holdout test (fraud)</div>
            {fraudDriftStatus?.status && (
              <span
                className={`px-2 py-0.5 rounded border text-[10px] uppercase tracking-wider ${
                  fraudDriftStatus.status === "red"
                    ? "border-rose-500/60 bg-rose-900/35 text-rose-200"
                    : fraudDriftStatus.status === "yellow"
                    ? "border-amber-500/60 bg-amber-900/35 text-amber-200"
                    : fraudDriftStatus.status === "green"
                    ? "border-emerald-500/60 bg-emerald-900/35 text-emerald-200"
                    : "border-slate-500/60 bg-slate-900/35 text-slate-200"
                }`}
                title={fraudDriftStatus.checked_at ? `Last drift check: ${new Date(fraudDriftStatus.checked_at).toLocaleString()}` : ""}
              >
                drift: {fraudDriftStatus.status}
              </span>
            )}
          </div>
          <div className="grid grid-cols-1 md:grid-cols-3 gap-3 items-end">
            <div className="md:col-span-2">
              <label className="block text-[10px] text-slate-500 uppercase mb-1">Holdout file (.csv/.jsonl)</label>
              <input
                type="file"
                accept=".csv,.jsonl"
                onChange={(e) => setFraudHoldoutFile(e.target.files?.[0] || null)}
                className="w-full rounded border border-slate-600 bg-slate-900 px-3 py-2 text-slate-200 text-sm"
              />
            </div>
            <button
              type="button"
              onClick={testFraudExternalHoldout}
              disabled={(!fraudHoldoutFile && !useFraudDefaultHoldout) || fraudHoldoutTesting || loading}
              className="px-4 py-2 rounded-md border border-cyan-500 bg-cyan-900/40 text-cyan-200 text-xs tracking-wider uppercase disabled:opacity-50"
            >
              {fraudHoldoutTesting ? "Testing..." : "Test external"}
            </button>
          </div>
          <div className="flex flex-wrap items-center gap-3 text-xs text-slate-300">
            <label className="flex items-center gap-1.5">
              <input
                type="checkbox"
                checked={saveFraudDefaultHoldout}
                onChange={(e) => setSaveFraudDefaultHoldout(e.target.checked)}
                className="rounded border-slate-600"
              />
              Save selected file as default holdout
            </label>
            <label className="flex items-center gap-1.5">
              <input
                type="checkbox"
                checked={useFraudDefaultHoldout}
                onChange={(e) => setUseFraudDefaultHoldout(e.target.checked)}
                className="rounded border-slate-600"
              />
              Use default holdout when no file selected
            </label>
          </div>
        </div>
      )}
      {modelType === "care" && (
        <div className="rounded-xl border border-fuchsia-700/60 bg-fuchsia-950/10 p-4 space-y-3">
          <div className="text-xs uppercase tracking-wider text-fuchsia-300">
            Retrain recommendation thresholds (live)
          </div>
          <div className="grid grid-cols-1 md:grid-cols-4 gap-3">
            <div>
              <label className="block text-[10px] text-slate-500 uppercase mb-1">Green min trust</label>
              <input
                type="number"
                step="0.01"
                value={recoCfg.trust_green_min}
                onChange={(e) => setRecoCfg((s) => ({ ...s, trust_green_min: e.target.value }))}
                className="w-full rounded border border-slate-600 bg-slate-900 px-3 py-2 text-slate-200 text-sm"
              />
            </div>
            <div>
              <label className="block text-[10px] text-slate-500 uppercase mb-1">Green max duplicate</label>
              <input
                type="number"
                step="0.01"
                value={recoCfg.dup_green_max}
                onChange={(e) => setRecoCfg((s) => ({ ...s, dup_green_max: e.target.value }))}
                className="w-full rounded border border-slate-600 bg-slate-900 px-3 py-2 text-slate-200 text-sm"
              />
            </div>
            <div>
              <label className="block text-[10px] text-slate-500 uppercase mb-1">Amber min trust</label>
              <input
                type="number"
                step="0.01"
                value={recoCfg.trust_amber_min}
                onChange={(e) => setRecoCfg((s) => ({ ...s, trust_amber_min: e.target.value }))}
                className="w-full rounded border border-slate-600 bg-slate-900 px-3 py-2 text-slate-200 text-sm"
              />
            </div>
            <div className="flex items-end gap-2">
              <button
                type="button"
                onClick={saveCareRecoConfig}
                disabled={loading || recoCfgLoading}
                className="w-full px-4 py-2 rounded-md border border-fuchsia-500 bg-fuchsia-900/40 text-fuchsia-200 text-xs tracking-wider uppercase disabled:opacity-50"
              >
                {recoCfgLoading ? "Loading..." : "Save thresholds"}
              </button>
              <button
                type="button"
                onClick={resetCareRecoConfig}
                disabled={loading || recoCfgLoading}
                className="w-full px-4 py-2 rounded-md border border-slate-500 bg-slate-900/60 text-slate-200 text-xs tracking-wider uppercase disabled:opacity-50"
              >
                Reset defaults
              </button>
            </div>
          </div>
        </div>
      )}

      <div className="rounded-xl border border-slate-700 bg-slate-900/60 p-4">
        <div className="text-xs uppercase tracking-wider text-slate-400 mb-3">Uploaded datasets ({modelType})</div>
        <div className="overflow-auto rounded border border-slate-800">
          <table className="w-full text-sm">
            <thead className="bg-slate-950 text-slate-400 uppercase text-[10px] tracking-wider">
              <tr>
                <th className="p-2 text-left">File</th>
                <th className="p-2 text-left">Rows</th>
                <th className="p-2 text-left">Status</th>
                <th className="p-2 text-left">Created</th>
                <th className="p-2 text-left">Action</th>
              </tr>
            </thead>
            <tbody>
              {uploads.map((u) => (
                <tr key={u.id} className="border-t border-slate-800">
                  <td className="p-2 font-mono text-xs">{u.filename}</td>
                  <td className="p-2">{u.row_count}</td>
                  <td className="p-2 min-w-[140px]">
                    {u.status === "TRAINING" ? (
                      <div className="space-y-1">
                        <div className="text-[10px] font-semibold tracking-wider text-slate-200">Training</div>
                        <div className="relative h-2 w-full overflow-hidden rounded-full bg-slate-800">
                          <div
                            className="absolute top-0 bottom-0 w-2/5 rounded-full bg-gradient-to-r from-emerald-600 to-cyan-400"
                            style={{
                              animation: "manualTrainIndeterminate 1.4s ease-in-out infinite",
                            }}
                          />
                        </div>
                      </div>
                    ) : (
                      <div className="flex flex-col gap-0.5">
                        <span>{u.status}</span>
                        {u.status === "FAILED" && u.last_error && (
                          <span className="text-[10px] text-rose-300/90">{u.last_error}</span>
                        )}
                        {u.eval_summary?.accuracy != null && (
                          <span className="text-[10px] text-slate-500">
                            last test: acc {(u.eval_summary.accuracy * 100).toFixed(1)}%
                            {u.eval_summary.auc != null ? ` · AUC ${u.eval_summary.auc.toFixed(3)}` : ""}
                          </span>
                        )}
                        {u.last_retrained_at && (
                          <span className="text-[10px] text-slate-500">
                            last retrained: {new Date(u.last_retrained_at).toLocaleString()}
                            {u.last_training_duration_s != null
                              ? ` · duration: ${u.last_training_duration_s.toFixed(1)}s`
                              : ""}
                          </span>
                        )}
                        {u.retrain_locked && (
                          <span className="text-[10px] font-medium text-amber-300/90">Retrain locked</span>
                        )}
                        {modelType === "care" && qualityByUpload[u.id] && (() => {
                          const rec = qualityByUpload[u.id];
                          if (!rec?.retrain_recommendation) return null;
                          const label =
                            rec.retrain_recommendation === "retrain_now"
                              ? "Retrain now"
                              : rec.retrain_recommendation === "retrain_optional"
                              ? "Retrain optional"
                              : "Fix data first";
                          const cls =
                            rec.retrain_recommendation === "retrain_now"
                              ? "border-emerald-500/50 bg-emerald-900/30 text-emerald-200"
                              : rec.retrain_recommendation === "retrain_optional"
                              ? "border-amber-500/50 bg-amber-900/25 text-amber-200"
                              : "border-rose-500/50 bg-rose-900/25 text-rose-200";
                          return (
                            <span
                              className={`inline-flex w-fit items-center rounded border px-1.5 py-0.5 text-[10px] font-medium ${cls}`}
                              title={rec.retrain_recommendation_note || ""}
                            >
                              {label}
                            </span>
                          );
                        })()}
                      </div>
                    )}
                  </td>
                  <td className="p-2">{u.created_at ? new Date(u.created_at).toLocaleString() : "—"}</td>
                  <td className="p-2">
                    <div className="flex flex-wrap gap-1.5">
                      <button
                        type="button"
                        onClick={() => triggerTrain(u.id)}
                        disabled={
                          loading ||
                          trainPendingId === u.id ||
                          u.status === "TRAINING" ||
                          (modelType === "fraud" && u.retrain_locked)
                        }
                        title={
                          u.retrain_locked
                            ? "Quality gate passed on last test — upload a new file to train again."
                            : undefined
                        }
                        className="px-2.5 py-1.5 rounded border border-emerald-500/60 bg-emerald-900/40 text-emerald-200 text-[11px] uppercase tracking-wider disabled:opacity-40 disabled:cursor-not-allowed"
                      >
                        {trainPendingId === u.id
                          ? "Starting..."
                          : u.status === "TRAINED"
                          ? `Retrain ${modelType}`
                          : `Train ${modelType}`}
                      </button>
                      {u.status === "TRAINED" && (
                        <button
                          type="button"
                          onClick={() => testUpload(u.id)}
                          disabled={testLoadingId === u.id || loading}
                          className="px-2.5 py-1.5 rounded border border-sky-500/60 bg-sky-900/35 text-sky-200 text-[11px] uppercase tracking-wider disabled:opacity-50"
                        >
                          {testLoadingId === u.id ? "Testing…" : "Test"}
                        </button>
                      )}
                      {modelType === "care" && (
                        <button
                          type="button"
                          onClick={() => showLabelMap(u.id)}
                          disabled={labelMapLoadingId === u.id || loading}
                          className="px-2.5 py-1.5 rounded border border-indigo-500/60 bg-indigo-900/35 text-indigo-200 text-[11px] uppercase tracking-wider disabled:opacity-50"
                        >
                          {labelMapLoadingId === u.id ? "Loading…" : "Label map"}
                        </button>
                      )}
                      {modelType === "care" && (
                        <button
                          type="button"
                          onClick={() => autoSplitCareUpload(u.id)}
                          disabled={splitLoadingId === u.id || loading}
                          className="px-2.5 py-1.5 rounded border border-violet-500/60 bg-violet-900/35 text-violet-200 text-[11px] uppercase tracking-wider disabled:opacity-50"
                        >
                          {splitLoadingId === u.id ? "Splitting…" : "Auto split"}
                        </button>
                      )}
                      {modelType === "care" && (
                        <button
                          type="button"
                          onClick={() => analyzeCareDataQuality(u.id)}
                          disabled={qualityLoadingId === u.id || loading}
                          className="px-2.5 py-1.5 rounded border border-fuchsia-500/60 bg-fuchsia-900/35 text-fuchsia-200 text-[11px] uppercase tracking-wider disabled:opacity-50"
                        >
                          {qualityLoadingId === u.id ? "Analyzing…" : "Data quality"}
                        </button>
                      )}
                      {modelType === "fraud" && (
                        <button
                          type="button"
                          onClick={() => analyzeFraudDataQuality(u.id)}
                          disabled={qualityLoadingId === u.id || loading}
                          className="px-2.5 py-1.5 rounded border border-fuchsia-500/60 bg-fuchsia-900/35 text-fuchsia-200 text-[11px] uppercase tracking-wider disabled:opacity-50"
                        >
                          {qualityLoadingId === u.id ? "Analyzing…" : "Data quality"}
                        </button>
                      )}
                    </div>
                  </td>
                </tr>
              ))}
              {!uploads.length && (
                <tr>
                  <td colSpan={5} className="p-3 text-xs text-slate-500">No uploads yet.</td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </div>
      {testModal && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 p-4" role="dialog">
          <div className="max-h-[85vh] w-full max-w-lg overflow-auto rounded-xl border border-slate-600 bg-slate-950 p-5 shadow-xl">
            <div className="flex items-start justify-between gap-2 mb-3">
              <div className="text-sm font-semibold text-slate-100">
                {modelType === "fraud" ? "Fraud model — test on upload" : "Care model — test on upload"}
              </div>
              <button
                type="button"
                onClick={() => setTestModal(null)}
                className="text-slate-400 hover:text-slate-200 text-lg leading-none"
              >
                ×
              </button>
            </div>
            <p className="text-xs text-slate-400 mb-3">
              Scored {testModal.n_scored} rows (skipped {testModal.n_skipped}).
              {modelType === "fraud" ? (
                <>
                  {" "}
                  Thresholds use env <code className="text-slate-300">FRAUD_UPLOAD_LOCK_MIN_*</code>.
                </>
              ) : (
                <>
                  {" "}
                  {testModal.upload_id === "external_holdout"
                    ? "Using external holdout file."
                    : "Using holdout test split when available."}
                </>
              )}
            </p>
            <div className="grid grid-cols-2 gap-2 text-xs mb-4">
              <div className="rounded border border-slate-700 p-2">
                <div className="text-slate-500 uppercase text-[10px]">Accuracy</div>
                <div className="text-slate-100 font-mono">{(testModal.accuracy * 100).toFixed(2)}%</div>
              </div>
              <div className="rounded border border-slate-700 p-2">
                <div className="text-slate-500 uppercase text-[10px]">AUC</div>
                <div className="text-slate-100 font-mono">{testModal.auc != null ? testModal.auc.toFixed(4) : "—"}</div>
              </div>
            </div>
            <div className="rounded-md border border-slate-700/80 bg-slate-900/40 px-3 py-2 text-xs text-slate-200 mb-3">
              {modelType === "fraud" ? (
                <>
                  {testModal.accuracy >= 0.93
                    ? "The fraud brain got most answers right, like scoring above 9/10 in class."
                    : testModal.accuracy >= 0.85
                    ? "The fraud brain is okay, like around 8/10 in class, but it still makes some mistakes."
                    : "The fraud brain is struggling right now, like below 8/10 in class."}{" "}
                  {testModal.auc != null && testModal.auc >= 0.9
                    ? "It also separates bad vs good payments really well."
                    : testModal.auc != null
                    ? "It can tell some bad vs good payments apart, but not strongly yet."
                    : "We could not compute the separation score this time."}
                </>
              ) : (
                <>
                  {testModal.accuracy >= 0.9
                    ? "The care brain understood almost everything you taught it."
                    : testModal.accuracy >= 0.8
                    ? "The care brain understood most things, but still gets confused sometimes."
                    : "The care brain is still learning and gets many prompts wrong."}
                </>
              )}
            </div>
            {testModal.retrain_locked ? (
              <div className="rounded-md border border-amber-500/50 bg-amber-950/30 px-3 py-2 text-xs text-amber-100 mb-3">
                Retrain locked for this upload — manual train button disabled until you upload a new dataset.
              </div>
            ) : (
              <div className="rounded-md border border-slate-600 bg-slate-900/50 px-3 py-2 text-xs text-slate-300 mb-3">
                Below quality thresholds — you can run manual train again if you want a new model.
              </div>
            )}
            <div className="text-[10px] uppercase tracking-wider text-slate-500 mb-1">Sample predictions</div>
            <div className="max-h-48 overflow-auto rounded border border-slate-800 font-mono text-[10px]">
              {(testModal.samples || []).map((s, i) => (
                <div key={i} className="border-b border-slate-800/80 px-2 py-1 text-slate-300">
                  {modelType === "fraud" ? (
                    <>
                      {s.external_tx_id?.slice(0, 12)}… label={s.label} p={s.fraud_proba?.toFixed(4)} →{" "}
                      {s.predicted_fraud ? "FRAUD" : "legit"}
                    </>
                  ) : (
                    <>
                      "{s.text}" · label={s.label} → {s.predicted_intent} {s.correct ? "✓" : "✗"}
                    </>
                  )}
                </div>
              ))}
            </div>
            {modelType === "care" && testModal.per_intent?.length > 0 && (
              <>
                <div className="text-[10px] uppercase tracking-wider text-slate-500 mt-3 mb-1">
                  Per-intent precision / recall
                </div>
                <div className="overflow-auto rounded border border-slate-800">
                  <table className="w-full text-[10px]">
                    <thead className="bg-slate-900 text-slate-400 uppercase">
                      <tr>
                        <th className="p-1.5 text-left">Intent</th>
                        <th className="p-1.5 text-right">Precision</th>
                        <th className="p-1.5 text-right">Recall</th>
                        <th className="p-1.5 text-right">F1</th>
                        <th className="p-1.5 text-right">Support</th>
                      </tr>
                    </thead>
                    <tbody>
                      {testModal.per_intent.map((m, i) => (
                        <tr key={i} className="border-t border-slate-800">
                          <td className="p-1.5 text-slate-200">{m.intent}</td>
                          <td className="p-1.5 text-right text-slate-300">{(m.precision * 100).toFixed(1)}%</td>
                          <td className="p-1.5 text-right text-slate-300">{(m.recall * 100).toFixed(1)}%</td>
                          <td className="p-1.5 text-right text-slate-300">{(m.f1 * 100).toFixed(1)}%</td>
                          <td className="p-1.5 text-right text-slate-300">{m.support}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </>
            )}
            {testModal.threshold_metrics?.length > 0 && (
              <>
                <div className="text-[10px] uppercase tracking-wider text-slate-500 mt-3 mb-1">
                  Threshold sweep (fraud)
                </div>
                <div className="overflow-auto rounded border border-slate-800">
                  <table className="w-full text-[10px]">
                    <thead className="bg-slate-900 text-slate-400 uppercase">
                      <tr>
                        <th className="p-1.5 text-right">Threshold</th>
                        <th className="p-1.5 text-right">Accuracy</th>
                        <th className="p-1.5 text-right">Precision</th>
                        <th className="p-1.5 text-right">Recall</th>
                        <th className="p-1.5 text-right">F1</th>
                      </tr>
                    </thead>
                    <tbody>
                      {testModal.threshold_metrics.map((m, i) => (
                        <tr key={i} className="border-t border-slate-800">
                          <td className="p-1.5 text-right text-slate-200">{m.threshold.toFixed(2)}</td>
                          <td className="p-1.5 text-right text-slate-300">{(m.accuracy * 100).toFixed(1)}%</td>
                          <td className="p-1.5 text-right text-slate-300">{(m.precision * 100).toFixed(1)}%</td>
                          <td className="p-1.5 text-right text-slate-300">{(m.recall * 100).toFixed(1)}%</td>
                          <td className="p-1.5 text-right text-slate-300">{(m.f1 * 100).toFixed(1)}%</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </>
            )}
            {testModal.segments && (
              <>
                <div className="text-[10px] uppercase tracking-wider text-slate-500 mt-3 mb-1">
                  Segment metrics (fraud)
                </div>
                <div className="overflow-auto rounded border border-slate-800 p-2 text-[10px] text-slate-300 space-y-2">
                  {["channel", "amount_bucket"].map((k) => (
                    <div key={k}>
                      <div className="text-slate-500 mb-1">{k}</div>
                      <table className="w-full text-[10px]">
                        <thead className="text-slate-500">
                          <tr>
                            <th className="p-1 text-left">Segment</th>
                            <th className="p-1 text-right">N</th>
                            <th className="p-1 text-right">Acc</th>
                            <th className="p-1 text-right">Prec</th>
                            <th className="p-1 text-right">Rec</th>
                          </tr>
                        </thead>
                        <tbody>
                          {(testModal.segments[k] || []).slice(0, 8).map((r, i) => (
                            <tr key={i} className="border-t border-slate-800">
                              <td className="p-1">{r.segment}</td>
                              <td className="p-1 text-right">{r.n}</td>
                              <td className="p-1 text-right">{(r.accuracy * 100).toFixed(1)}%</td>
                              <td className="p-1 text-right">{(r.precision * 100).toFixed(1)}%</td>
                              <td className="p-1 text-right">{(r.recall * 100).toFixed(1)}%</td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                  ))}
                </div>
              </>
            )}
            {testModal.confusion?.labels?.length > 0 && (
              <>
                <div className="text-[10px] uppercase tracking-wider text-slate-500 mt-3 mb-1">Confusion matrix</div>
                <div className="overflow-auto rounded border border-slate-800 p-2 text-[10px] text-slate-300">
                  <div className="mb-1 text-slate-500">Rows = true label, Columns = predicted label</div>
                  <table className="text-[10px]">
                    <thead>
                      <tr>
                        <th className="p-1 text-left text-slate-500">true \ pred</th>
                        {testModal.confusion.labels.map((l, i) => (
                          <th key={i} className="p-1 text-left text-slate-500">{l}</th>
                        ))}
                      </tr>
                    </thead>
                    <tbody>
                      {testModal.confusion.matrix.map((row, ri) => (
                        <tr key={ri}>
                          <td className="p-1 text-slate-500">{testModal.confusion.labels[ri]}</td>
                          {row.map((v, ci) => (
                            <td key={ci} className="p-1">{v}</td>
                          ))}
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </>
            )}
          </div>
        </div>
      )}
      {labelMapModal && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 p-4" role="dialog">
          <div className="max-h-[85vh] w-full max-w-xl overflow-auto rounded-xl border border-slate-600 bg-slate-950 p-5 shadow-xl">
            <div className="flex items-start justify-between gap-2 mb-3">
              <div className="text-sm font-semibold text-slate-100">Care label mapping</div>
              <button
                type="button"
                onClick={() => setLabelMapModal(null)}
                className="text-slate-400 hover:text-slate-200 text-lg leading-none"
              >
                ×
              </button>
            </div>
            <p className="text-xs text-slate-400 mb-3">
              Total rows: {labelMapModal.total_rows} · Ignored: {labelMapModal.ignored_rows}
            </p>
            <div className="overflow-auto rounded border border-slate-800">
              <table className="w-full text-xs">
                <thead className="bg-slate-900 text-slate-400 uppercase tracking-wider">
                  <tr>
                    <th className="p-2 text-left">Raw label</th>
                    <th className="p-2 text-left">Mapped intent</th>
                    <th className="p-2 text-right">Count</th>
                  </tr>
                </thead>
                <tbody>
                  {(labelMapModal.rows || []).map((r, i) => (
                    <tr key={i} className="border-t border-slate-800">
                      <td className="p-2 font-mono text-[11px] text-slate-200">{r.raw_label}</td>
                      <td className="p-2 text-slate-200">{r.mapped_intent}</td>
                      <td className="p-2 text-right text-slate-300">{r.count}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        </div>
      )}
      {qualityModal && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 p-4" role="dialog">
          <div className="max-h-[85vh] w-full max-w-xl overflow-auto rounded-xl border border-slate-600 bg-slate-950 p-5 shadow-xl">
            <div className="flex items-start justify-between gap-2 mb-3">
              <div className="text-sm font-semibold text-slate-100">
                {modelType === "fraud" ? "Fraud data quality" : "Care data quality"}
              </div>
              <button
                type="button"
                onClick={() => setQualityModal(null)}
                className="text-slate-400 hover:text-slate-200 text-lg leading-none"
              >
                ×
              </button>
            </div>
            {qualityModal.intent_balance_entropy_norm != null ? (
              <div className="grid grid-cols-2 gap-2 text-xs mb-3">
                <div className="rounded border border-slate-700 p-2">
                  <div className="text-slate-500 uppercase text-[10px]">Duplicate rate</div>
                  <div className="text-slate-100 font-mono">{(qualityModal.duplicate_rate * 100).toFixed(1)}%</div>
                </div>
                <div className="rounded border border-slate-700 p-2">
                  <div className="text-slate-500 uppercase text-[10px]">Intent balance</div>
                  <div className="text-slate-100 font-mono">{(qualityModal.intent_balance_entropy_norm * 100).toFixed(1)}%</div>
                </div>
                <div className="rounded border border-slate-700 p-2">
                  <div className="text-slate-500 uppercase text-[10px]">Trust score</div>
                  <div className="text-slate-100 font-mono">{(qualityModal.trustworthiness_score * 100).toFixed(1)}%</div>
                </div>
                <div className="rounded border border-slate-700 p-2">
                  <div className="text-slate-500 uppercase text-[10px]">Hard/easy estimate</div>
                  <div className="text-slate-100">{qualityModal.difficulty_estimate}</div>
                </div>
              </div>
            ) : (
              <div className="grid grid-cols-2 gap-2 text-xs mb-3">
                <div className="rounded border border-slate-700 p-2">
                  <div className="text-slate-500 uppercase text-[10px]">Duplicate tx ids</div>
                  <div className="text-slate-100 font-mono">
                    {(qualityModal.duplicate_external_tx_rate * 100).toFixed(1)}%
                  </div>
                </div>
                <div className="rounded border border-slate-700 p-2">
                  <div className="text-slate-500 uppercase text-[10px]">Class balance</div>
                  <div className="text-slate-100 font-mono">
                    {(qualityModal.class_balance_entropy_norm * 100).toFixed(1)}%
                  </div>
                </div>
                <div className="rounded border border-slate-700 p-2">
                  <div className="text-slate-500 uppercase text-[10px]">Missing critical</div>
                  <div className="text-slate-100 font-mono">
                    {(qualityModal.missing_critical_fields_rate * 100).toFixed(1)}%
                  </div>
                </div>
                <div className="rounded border border-slate-700 p-2">
                  <div className="text-slate-500 uppercase text-[10px]">Trust score</div>
                  <div className="text-slate-100 font-mono">
                    {(qualityModal.trustworthiness_score * 100).toFixed(1)}%
                  </div>
                </div>
              </div>
            )}
            <div className="rounded border border-slate-700 bg-slate-900/30 p-2 text-xs text-slate-300 mb-3">
              {qualityModal.summary}
            </div>
            <div className="text-[10px] uppercase tracking-wider text-slate-500 mb-1">
              {qualityModal.intent_counts ? "Intent balance detail" : "Channel distribution"}
            </div>
            <div className="overflow-auto rounded border border-slate-800">
              <table className="w-full text-xs">
                <thead className="bg-slate-900 text-slate-400 uppercase">
                  <tr>
                    <th className="p-2 text-left">{qualityModal.intent_counts ? "Intent" : "Channel"}</th>
                    <th className="p-2 text-right">Rows</th>
                    <th className="p-2 text-right">Percent</th>
                  </tr>
                </thead>
                <tbody>
                  {(qualityModal.intent_counts || qualityModal.channel_counts || []).map((r, i) => (
                    <tr key={i} className="border-t border-slate-800">
                      <td className="p-2 text-slate-200">{r.intent || r.channel}</td>
                      <td className="p-2 text-right text-slate-300">{r.count}</td>
                      <td className="p-2 text-right text-slate-300">{r.pct.toFixed(2)}%</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

function TriggerFraudTrain({ adminFetch }) {
  const [loading, setLoading] = useState(false);
  const [message, setMessage] = useState(null);
  const [status, setStatus] = useState(null);
  const [polling, setPolling] = useState(false);
  const [pollMs, setPollMs] = useState(5000);
  const [pollStartAt, setPollStartAt] = useState(null);

  async function loadStatus() {
    try {
      const res = await adminFetch(`${API_BASE}/api/v1/admin/fraud-train-status`);
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
      const res = await adminFetch(`${API_BASE}/api/v1/admin/trigger-fraud-train`, { method: "POST" });
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
      <div className="flex flex-wrap items-center gap-2 mb-2">
        <span className="inline-flex items-center rounded-md border border-amber-500/50 bg-amber-950/35 px-2.5 py-1 text-[10px] font-bold tracking-wider text-amber-200">
          Scheduled / DB retrain
        </span>
        <span className="text-[11px] text-slate-500 max-w-xl">
          Runs the standard trainer over labelled <code className="text-slate-400">FraudOutcome</code> rows already in
          the database — not tied to a CSV upload above.
        </span>
      </div>
      <p className="text-[10px] text-slate-500 uppercase mb-2">Trigger fraud train</p>
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

function FraudTab({ adminFetch, platformTenantId }) {
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

  async function loadAlerts() {
    if (!platformTenantId) return;
    setAlertsLoading(true);
    setAlertsError(null);
    try {
      const res = await adminFetch(`${API_BASE}/api/v1/fraud/alerts`);
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
    if (!platformTenantId) return;
    setReviewAlertsLoading(true);
    setReviewAlertsError(null);
    setReviewTxLoading(true);
    setReviewTxError(null);
    try {
      const aRes = await adminFetch(`${API_BASE}/api/v1/fraud/alerts?status=OPEN`);
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
      const tRes = await adminFetch(`${API_BASE}/api/v1/fraud/transactions?${params}`);
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
    if (!platformTenantId || !alertId) return;
    try {
      const res = await adminFetch(`${API_BASE}/api/v1/fraud/alerts/${encodeURIComponent(alertId)}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
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
    if (!platformTenantId || !alertId || !transactionId || !classification) return;
    try {
      const res = await adminFetch(`${API_BASE}/api/v1/fraud/outcome`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
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
    if (!platformTenantId || !transactionId || !classification) return;
    try {
      const res = await adminFetch(`${API_BASE}/api/v1/fraud/outcome`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
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
    if (!platformTenantId || !accountId.trim()) return;
    try {
      const res = await adminFetch(`${API_BASE}/api/v1/fraud/customer-risk/${encodeURIComponent(accountId)}`);
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || res.statusText);
      setCustomerRisk(data);
    } catch (err) {
      setCustomerRisk({ error: err.message });
    }
  }

  async function runDeviceCheck(e) {
    e.preventDefault();
    if (!platformTenantId) return;
    try {
      const res = await adminFetch(`${API_BASE}/api/v1/fraud/device-check`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
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
    if (!platformTenantId) return;
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
      const res = await adminFetch(`${API_BASE}/api/v1/fraud/score/detail`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
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
    if (!platformTenantId) return;
    setStreamLoading(true);
    setStreamError(null);
    try {
      const params = new URLSearchParams({ limit: "50" }).toString();
      const res = await adminFetch(`${API_BASE}/api/v1/fraud/transactions?${params}`);
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
    if (!platformTenantId) return;
    setNetworkGraphLoading(true);
    try {
      const res = await adminFetch(`${API_BASE}/api/v1/fraud/network/graph?since_days=30`);
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
    if (!platformTenantId) return;
    setRingsLoading(true);
    setRingsError(null);
    try {
      const res = await adminFetch(`${API_BASE}/api/v1/fraud/network/rings?since_days=30`);
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
    if (!platformTenantId) return;
    setAnalyticsLoading(true);
    try {
      const res = await adminFetch(`${API_BASE}/api/v1/fraud/network/analytics?since_days=30`);
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
    if (!platformTenantId) return;
    setFeatureImpLoading(true);
    setFeatureImpError(null);
    try {
      const res = await adminFetch(`${API_BASE}/api/v1/fraud/feature-importances`);
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
    if (!platformTenantId || !transactionId) return;
    setTxDetailLoading(true);
    setTxDetailError(null);
    try {
      const res = await adminFetch(`${API_BASE}/api/v1/fraud/transactions/${encodeURIComponent(transactionId)}/detail`);
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

  useEffect(() => {
    if (!platformTenantId) return;
    loadAlerts();
    loadReviewQueue();
    loadFeatureImportances();
    loadStream();
  }, [platformTenantId]);

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
      {!platformTenantId && (
        <div className="rounded-lg border border-amber-900/50 bg-amber-950/20 p-3 text-xs text-amber-200/90">
          Select a bank at login to load Fraud Ops.
        </div>
      )}

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
              disabled={!platformTenantId || reviewAlertsLoading || reviewTxLoading}
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
              disabled={!platformTenantId || networkGraphLoading}
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
              disabled={!platformTenantId || ringsLoading}
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
              disabled={!platformTenantId || analyticsLoading}
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
            disabled={!platformTenantId || alertsLoading}
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
                <tr><td colSpan={7} className="p-4 text-slate-500">No alerts found. Click Refresh.</td></tr>
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
          <button type="submit" disabled={!platformTenantId} className="px-4 py-2 rounded border border-slate-600 text-xs uppercase text-slate-300 disabled:opacity-50">Lookup</button>
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
          <button type="submit" disabled={!platformTenantId} className="px-4 py-2 rounded border border-slate-600 text-xs uppercase text-slate-300 disabled:opacity-50">Check</button>
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
            disabled={!platformTenantId || txLoading}
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
            disabled={!platformTenantId || featureImpLoading}
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
            disabled={!platformTenantId || streamLoading}
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

/** Bundled paths the API can resolve locally (fraud = directory with lgb_fraud.txt; care = joblib file). */
const REGISTRY_DEFAULT_ARTIFACT_URI = {
  fraud: "models/fraud",
  care: "app/ml/models/care_intent_model.joblib",
};

function defaultRegistryArtifactUri(mt) {
  return REGISTRY_DEFAULT_ARTIFACT_URI[mt] || REGISTRY_DEFAULT_ARTIFACT_URI.fraud;
}

function ModelRegistryPanel({ adminFetch, platformTenantId }) {
  const [modelType, setModelType] = useState(
    () => localStorage.getItem("bankai_registry_model_type") || "fraud",
  );
  const [entries, setEntries] = useState([]);
  const [mappers, setMappers] = useState([]);
  const [calibrations, setCalibrations] = useState([]);
  const [traces, setTraces] = useState([]);
  const [rollbackEvents, setRollbackEvents] = useState([]);
  const [promotionEvents, setPromotionEvents] = useState([]);
  const [modelKpis, setModelKpis] = useState(null);
  const [finetuneRuns, setFinetuneRuns] = useState([]);
  const [championChallengerKpi, setChampionChallengerKpi] = useState(null);
  const [championChallengerKpi72h, setChampionChallengerKpi72h] = useState(null);
  const [isolationReadiness, setIsolationReadiness] = useState(null);
  const [cutoverGate, setCutoverGate] = useState(null);
  const [jobRuns, setJobRuns] = useState([]);
  const [jobRunNameFilter, setJobRunNameFilter] = useState("");
  const [jobRunStatusFilter, setJobRunStatusFilter] = useState("all");
  const [jobRunLimit, setJobRunLimit] = useState("30");
  const [cutoverRunning, setCutoverRunning] = useState(false);
  const [guardrailRunning, setGuardrailRunning] = useState(false);
  const [evaluatorRunning, setEvaluatorRunning] = useState(false);
  const [challengerPolicy, setChallengerPolicy] = useState(null);
  const [policyForm, setPolicyForm] = useState({
    min_compared: "",
    max_block_rate_delta: "",
    max_otp_rate_delta: "",
    max_disagree_rate: "",
    cooldown_hours: "",
    candidate_min_age_hours: "",
  });
  const [eligibility, setEligibility] = useState(null);
  const [finetuneForm, setFinetuneForm] = useState({
    upload_id: "",
    candidate_version: "",
    artifact_uri: "",
    auto_activate: false,
  });
  const [traceRouteFilter, setTraceRouteFilter] = useState(
    () => localStorage.getItem("bankai_trace_route_filter") || "all",
  );
  const [traceTimeWindow, setTraceTimeWindow] = useState(null);
  const [prefsNotice, setPrefsNotice] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const [registryForm, setRegistryForm] = useState(() => ({
    version: "",
    artifact_uri: defaultRegistryArtifactUri(localStorage.getItem("bankai_registry_model_type") || "fraud"),
    feature_contract_version: "v1",
    mapper_version: "v1",
    status: "shadow",
  }));
  const [mapperForm, setMapperForm] = useState({
    mapper_version: "",
    contract_version: "v1",
    mapping_json: "{}",
    is_active: true,
  });
  const [calibrationForm, setCalibrationForm] = useState({
    model_version: "",
    calibration_version: "",
    method: "platt",
    params_json: '{"a":1.0,"b":0.0}',
    status: "shadow",
  });
  const [mapperDryRunRaw, setMapperDryRunRaw] = useState("{}");
  const [mapperDryRunOut, setMapperDryRunOut] = useState(null);
  const [mapperTesting, setMapperTesting] = useState(false);

  const activeMapper = Array.isArray(mappers) ? mappers.find((m) => m.is_active) : null;
  const activeModel = Array.isArray(entries) ? entries.find((e) => e.status === "active") : null;
  const routeCounts = traces.reduce(
    (acc, t) => {
      const src = String(t?.trace_json?.route_source || "").toLowerCase();
      if (src === "tenant") acc.tenant += 1;
      else if (src === "global") acc.global += 1;
      else if (src === "fallback") acc.fallback += 1;
      return acc;
    },
    { tenant: 0, global: 0, fallback: 0 },
  );
  const filteredTraces = traces.filter((t) => {
    if (traceRouteFilter === "all") return true;
    const routeOk = String(t?.trace_json?.route_source || "").toLowerCase() === traceRouteFilter;
    if (!routeOk) return false;
    if (!traceTimeWindow) return true;
    const ts = new Date(t?.created_at || "").getTime();
    if (!Number.isFinite(ts)) return false;
    return ts > Number(traceTimeWindow.start) && ts <= Number(traceTimeWindow.end);
  });
  const strictReady = Boolean(platformTenantId && activeModel && activeMapper);
  const fraudSamplePayload = JSON.stringify(
    {
      txn: {
        transaction_id: "txn-1001",
        account_id: "acct-7781",
        amount: 245.75,
        currency: "USD",
        channel: "mobile_app",
        device_id: "ios-445",
        ip_address: "197.210.1.40",
        merchant_id: "mid-4421",
        location_country: "GH",
        tx_timestamp: "2026-03-13T10:12:03Z",
        velocity_1h: 2,
      },
    },
    null,
    2,
  );
  const careSamplePayload = JSON.stringify(
    {
      care: {
        session_id: "sess-009",
        customer_id: "cust-225",
        message_text: "I was charged twice for the same transfer.",
        channel: "mobile_app",
        language: "en",
        intent_metadata: { priority: "high" },
        message_ts: "2026-03-13T10:12:03Z",
      },
    },
    null,
    2,
  );

  useEffect(() => {
    localStorage.setItem("bankai_trace_route_filter", traceRouteFilter);
  }, [traceRouteFilter]);
  useEffect(() => {
    localStorage.setItem("bankai_registry_model_type", modelType);
  }, [modelType]);

  function resetPanelPreferences() {
    localStorage.removeItem("bankai_registry_model_type");
    localStorage.removeItem("bankai_trace_route_filter");
    setModelType("fraud");
    setTraceRouteFilter("all");
    setPrefsNotice(true);
    setTimeout(() => setPrefsNotice(false), 1800);
  }

  function loadSamplePayload() {
    setMapperDryRunRaw(modelType === "fraud" ? fraudSamplePayload : careSamplePayload);
  }

  const toErr = (val, fallback) => {
    if (typeof val === "string" && val.trim()) return val;
    if (Array.isArray(val)) return val.map((x) => (typeof x === "string" ? x : JSON.stringify(x))).join("; ");
    if (val && typeof val === "object") {
      if (typeof val.detail === "string") return val.detail;
      return JSON.stringify(val);
    }
    return fallback;
  };

  async function loadAll() {
    if (!platformTenantId) return;
    setLoading(true);
    setError(null);
    try {
      const qRegistry = new URLSearchParams({
        tenant_id: platformTenantId,
        model_type: modelType,
        limit: "80",
      }).toString();
      const qMapper = new URLSearchParams({
        tenant_id: platformTenantId,
        model_type: modelType,
        limit: "80",
      }).toString();
      const qTrace = new URLSearchParams({
        tenant_id: platformTenantId,
        model_type: modelType,
        limit: "120",
      }).toString();
      const qCal = new URLSearchParams({
        tenant_id: platformTenantId,
        model_type: modelType,
        limit: "50",
      }).toString();
      const qRollback = new URLSearchParams({
        event_type: "MODEL_AUTO_ROLLBACK",
        tenant_id: platformTenantId,
        limit: "20",
      }).toString();
      const qPromotion = new URLSearchParams({
        event_type: "MODEL_AUTO_PROMOTED",
        tenant_id: platformTenantId,
        limit: "20",
      }).toString();
      const qRuns = new URLSearchParams({
        model_type: modelType,
        tenant_id: platformTenantId,
        limit: "40",
      }).toString();
      const [r1, r2, r3, r4, r5, r6, r7, r8, r9, r10, r11, r12, r13, r14, r15] = await Promise.all([
        adminFetch(`${API_BASE}/api/v1/admin/model-registry?${qRegistry}`),
        adminFetch(`${API_BASE}/api/v1/admin/tenant-mappers?${qMapper}`),
        adminFetch(`${API_BASE}/api/v1/admin/inference-trace?${qTrace}`),
        adminFetch(`${API_BASE}/api/v1/admin/calibration?${qCal}`),
        adminFetch(`${API_BASE}/api/v1/admin/audit/events?${qRollback}`),
        adminFetch(`${API_BASE}/api/v1/admin/training/${modelType}/tenant-eligibility?tenant_id=${encodeURIComponent(platformTenantId)}&min_rows_required=500`),
        adminFetch(`${API_BASE}/api/v1/admin/training/uploads?${qRuns}`),
        adminFetch(`${API_BASE}/api/v1/admin/monitoring/champion-challenger?tenant_id=${encodeURIComponent(platformTenantId)}&model_type=${encodeURIComponent(modelType)}&window_hours=24`),
        adminFetch(`${API_BASE}/api/v1/admin/audit/events?${qPromotion}`),
        adminFetch(`${API_BASE}/api/v1/admin/monitoring/challenger-policy?tenant_id=${encodeURIComponent(platformTenantId)}`),
        adminFetch(`${API_BASE}/api/v1/admin/monitoring/champion-challenger?tenant_id=${encodeURIComponent(platformTenantId)}&model_type=${encodeURIComponent(modelType)}&window_hours=72`),
        adminFetch(`${API_BASE}/api/v1/admin/monitoring/model-kpis?tenant_id=${encodeURIComponent(platformTenantId)}&model_type=${encodeURIComponent(modelType)}&days=30`),
        adminFetch(`${API_BASE}/api/v1/admin/monitoring/isolation-readiness?tenant_id=${encodeURIComponent(platformTenantId)}&model_type=${encodeURIComponent(modelType)}`),
        adminFetch(`${API_BASE}/api/v1/admin/monitoring/cutover-gate?tenant_id=${encodeURIComponent(platformTenantId)}&model_type=${encodeURIComponent(modelType)}`),
        adminFetch(
          `${API_BASE}/api/v1/admin/monitoring/job-runs?${new URLSearchParams({
            limit: String(Math.max(1, Number(jobRunLimit) || 30)),
            ...(jobRunNameFilter.trim() ? { job_name: jobRunNameFilter.trim() } : {}),
            ...(jobRunStatusFilter !== "all" ? { status: jobRunStatusFilter } : {}),
          }).toString()}`
        ),
      ]);
      const [d1, d2, d3, d4, d5, d6, d7, d8, d9, d10, d11, d12, d13, d14, d15] = await Promise.all([
        r1.json().catch(() => []),
        r2.json().catch(() => []),
        r3.json().catch(() => []),
        r4.json().catch(() => []),
        r5.json().catch(() => []),
        r6.json().catch(() => ({})),
        r7.json().catch(() => []),
        r8.json().catch(() => ({})),
        r9.json().catch(() => []),
        r10.json().catch(() => ({})),
        r11.json().catch(() => ({})),
        r12.json().catch(() => ({})),
        r13.json().catch(() => ({})),
        r14.json().catch(() => ({})),
        r15.json().catch(() => []),
      ]);
      if (!r1.ok) throw new Error(toErr(d1, "Failed to load model registry"));
      if (!r2.ok) throw new Error(toErr(d2, "Failed to load tenant mappers"));
      if (!r3.ok) throw new Error(toErr(d3, "Failed to load inference traces"));
      if (!r4.ok) throw new Error(toErr(d4, "Failed to load calibrations"));
      setEntries(Array.isArray(d1) ? d1 : []);
      setMappers(Array.isArray(d2) ? d2 : []);
      setTraces(Array.isArray(d3) ? d3 : []);
      setCalibrations(Array.isArray(d4) ? d4 : []);
      setRollbackEvents(Array.isArray(d5) ? d5 : []);
      setEligibility(r6 && typeof d6 === "object" ? d6 : null);
      setFinetuneRuns(Array.isArray(d7) ? d7 : []);
      setChampionChallengerKpi(r8.ok && d8 && typeof d8 === "object" ? d8 : null);
      setPromotionEvents(Array.isArray(d9) ? d9 : []);
      setChallengerPolicy(r10.ok && d10 && typeof d10 === "object" ? d10 : null);
      setChampionChallengerKpi72h(r11.ok && d11 && typeof d11 === "object" ? d11 : null);
      setModelKpis(r12.ok && d12 && typeof d12 === "object" ? d12 : null);
      setIsolationReadiness(r13.ok && d13 && typeof d13 === "object" ? d13 : null);
      setCutoverGate(r14.ok && d14 && typeof d14 === "object" ? d14 : null);
      setJobRuns(Array.isArray(d15) ? d15 : []);
    } catch (e) {
      setError(e.message || "Failed to load");
      setEntries([]);
      setMappers([]);
      setCalibrations([]);
      setTraces([]);
      setRollbackEvents([]);
      setEligibility(null);
      setFinetuneRuns([]);
      setChampionChallengerKpi(null);
      setPromotionEvents([]);
      setChallengerPolicy(null);
      setChampionChallengerKpi72h(null);
      setModelKpis(null);
      setIsolationReadiness(null);
      setCutoverGate(null);
      setJobRuns([]);
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    loadAll();
  }, [platformTenantId, modelType, jobRunNameFilter, jobRunStatusFilter, jobRunLimit]);

  useEffect(() => {
    setRegistryForm((f) => {
      const t = f.artifact_uri.trim();
      if (!t) return { ...f, artifact_uri: defaultRegistryArtifactUri(modelType) };
      const known = new Set(Object.values(REGISTRY_DEFAULT_ARTIFACT_URI));
      if (known.has(t)) return { ...f, artifact_uri: defaultRegistryArtifactUri(modelType) };
      return f;
    });
  }, [modelType]);

  async function createRegistryEntry(e) {
    e.preventDefault();
    if (!platformTenantId) return;
    setError(null);
    const payload = {
      tenant_id: platformTenantId,
      model_type: modelType,
      version: registryForm.version.trim(),
      artifact_uri: registryForm.artifact_uri.trim(),
      feature_contract_version: registryForm.feature_contract_version.trim() || "v1",
      mapper_version: registryForm.mapper_version.trim() || "v1",
      status: registryForm.status,
      metadata_json: {},
    };
    const r = await adminFetch(`${API_BASE}/api/v1/admin/model-registry`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    const d = await r.json().catch(() => ({}));
    if (!r.ok) {
      setError(toErr(d, "Failed to create model entry"));
      return;
    }
    setRegistryForm((f) => ({
      ...f,
      version: "",
      artifact_uri: defaultRegistryArtifactUri(modelType),
    }));
    await loadAll();
  }

  async function activateModel(entryId) {
    setError(null);
    const r = await adminFetch(`${API_BASE}/api/v1/admin/model-registry/${encodeURIComponent(entryId)}/activate`, {
      method: "POST",
    });
    const d = await r.json().catch(() => ({}));
    if (!r.ok) {
      setError(toErr(d, "Failed to activate model"));
      return;
    }
    await loadAll();
  }

  async function rollbackModel(entryId) {
    setError(null);
    const r = await adminFetch(`${API_BASE}/api/v1/admin/model-registry/${encodeURIComponent(entryId)}/rollback`, {
      method: "POST",
    });
    const d = await r.json().catch(() => ({}));
    if (!r.ok) {
      setError(toErr(d, "Failed to rollback model"));
      return;
    }
    await loadAll();
  }

  async function promoteModel(entryId) {
    setError(null);
    const r = await adminFetch(`${API_BASE}/api/v1/admin/model-registry/${encodeURIComponent(entryId)}/promote`, {
      method: "POST",
    });
    const d = await r.json().catch(() => ({}));
    if (!r.ok) {
      setError(toErr(d, "Failed to promote model"));
      return;
    }
    await loadAll();
  }

  async function pauseModel(entryId) {
    setError(null);
    const r = await adminFetch(`${API_BASE}/api/v1/admin/model-registry/${encodeURIComponent(entryId)}/pause`, {
      method: "POST",
    });
    const d = await r.json().catch(() => ({}));
    if (!r.ok) {
      setError(toErr(d, "Failed to pause model"));
      return;
    }
    await loadAll();
  }

  async function createMapper(e) {
    e.preventDefault();
    if (!platformTenantId) return;
    setError(null);
    let mappingJson = {};
    try {
      mappingJson = mapperForm.mapping_json?.trim() ? JSON.parse(mapperForm.mapping_json) : {};
    } catch {
      setError("Mapper JSON is invalid.");
      return;
    }
    const payload = {
      tenant_id: platformTenantId,
      model_type: modelType,
      mapper_version: mapperForm.mapper_version.trim(),
      contract_version: mapperForm.contract_version.trim() || "v1",
      mapping_json: mappingJson,
      is_active: !!mapperForm.is_active,
    };
    const r = await adminFetch(`${API_BASE}/api/v1/admin/tenant-mappers`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    const d = await r.json().catch(() => ({}));
    if (!r.ok) {
      setError(toErr(d, "Failed to create mapper"));
      return;
    }
    setMapperForm((f) => ({ ...f, mapper_version: "", mapping_json: "{}" }));
    await loadAll();
  }

  async function validateMapperDraft() {
    setError(null);
    setMapperDryRunOut(null);
    let mappingJson = {};
    try {
      mappingJson = mapperForm.mapping_json?.trim() ? JSON.parse(mapperForm.mapping_json) : {};
    } catch {
      setError("Mapper JSON is invalid.");
      return;
    }
    setMapperTesting(true);
    try {
      const r = await adminFetch(`${API_BASE}/api/v1/admin/tenant-mappers/validate`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          model_type: modelType,
          contract_version: mapperForm.contract_version || "v1",
          mapping_json: mappingJson,
        }),
      });
      const d = await r.json().catch(() => ({}));
      if (!r.ok) throw new Error(toErr(d, "Mapper validation failed"));
      setMapperDryRunOut({ mode: "validate", ...d });
    } catch (e) {
      setError(e.message || "Mapper validation failed");
    } finally {
      setMapperTesting(false);
    }
  }

  async function dryRunMapperDraft() {
    setError(null);
    setMapperDryRunOut(null);
    let mappingJson = {};
    let rawPayload = {};
    try {
      mappingJson = mapperForm.mapping_json?.trim() ? JSON.parse(mapperForm.mapping_json) : {};
      rawPayload = mapperDryRunRaw?.trim() ? JSON.parse(mapperDryRunRaw) : {};
    } catch {
      setError("Mapper JSON or raw payload JSON is invalid.");
      return;
    }
    setMapperTesting(true);
    try {
      const r = await adminFetch(`${API_BASE}/api/v1/admin/tenant-mappers/dry-run`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          model_type: modelType,
          contract_version: mapperForm.contract_version || "v1",
          mapping_json: mappingJson,
          raw_payload: rawPayload,
        }),
      });
      const d = await r.json().catch(() => ({}));
      if (!r.ok) throw new Error(toErr(d, "Mapper dry-run failed"));
      setMapperDryRunOut({ mode: "dry-run", ...d });
    } catch (e) {
      setError(e.message || "Mapper dry-run failed");
    } finally {
      setMapperTesting(false);
    }
  }

  async function activateMapper(mapperId) {
    setError(null);
    const r = await adminFetch(`${API_BASE}/api/v1/admin/tenant-mappers/${encodeURIComponent(mapperId)}/activate`, {
      method: "POST",
    });
    const d = await r.json().catch(() => ({}));
    if (!r.ok) {
      setError(toErr(d, "Failed to activate mapper"));
      return;
    }
    await loadAll();
  }

  async function createCalibration(e) {
    e.preventDefault();
    if (!platformTenantId) return;
    setError(null);
    let paramsJson = {};
    try {
      paramsJson = calibrationForm.params_json?.trim() ? JSON.parse(calibrationForm.params_json) : {};
    } catch {
      setError("Calibration params JSON is invalid.");
      return;
    }
    const r = await adminFetch(`${API_BASE}/api/v1/admin/calibration`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        tenant_id: platformTenantId,
        model_type: modelType,
        model_version: calibrationForm.model_version.trim(),
        calibration_version: calibrationForm.calibration_version.trim(),
        method: calibrationForm.method,
        params_json: paramsJson,
        status: calibrationForm.status,
      }),
    });
    const d = await r.json().catch(() => ({}));
    if (!r.ok) {
      setError(toErr(d, "Failed to create calibration"));
      return;
    }
    setCalibrationForm((f) => ({ ...f, calibration_version: "", params_json: '{"a":1.0,"b":0.0}' }));
    await loadAll();
  }

  async function activateCalibration(id) {
    setError(null);
    const r = await adminFetch(`${API_BASE}/api/v1/admin/calibration/${encodeURIComponent(id)}/activate`, {
      method: "POST",
    });
    const d = await r.json().catch(() => ({}));
    if (!r.ok) {
      setError(toErr(d, "Failed to activate calibration"));
      return;
    }
    await loadAll();
  }

  async function runGuardrailsNow() {
    setGuardrailRunning(true);
    setError(null);
    try {
      const r = await adminFetch(`${API_BASE}/api/v1/admin/monitoring/model-guardrails/run`, { method: "POST" });
      const d = await r.json().catch(() => ({}));
      if (!r.ok) throw new Error(toErr(d, "Failed to run guardrails"));
      await loadAll();
    } catch (e) {
      setError(e.message || "Failed to run guardrails");
    } finally {
      setGuardrailRunning(false);
    }
  }

  async function runChallengerEvaluatorNow() {
    setEvaluatorRunning(true);
    setError(null);
    try {
      const r = await adminFetch(`${API_BASE}/api/v1/admin/monitoring/challenger-evaluator/run`, { method: "POST" });
      const d = await r.json().catch(() => ({}));
      if (!r.ok) throw new Error(toErr(d, "Failed to run challenger evaluator"));
      await loadAll();
    } catch (e) {
      setError(e.message || "Failed to run challenger evaluator");
    } finally {
      setEvaluatorRunning(false);
    }
  }

  async function runCutoverExecute() {
    if (!platformTenantId) return;
    setCutoverRunning(true);
    setError(null);
    try {
      const r = await adminFetch(
        `${API_BASE}/api/v1/admin/monitoring/cutover-execute?tenant_id=${encodeURIComponent(platformTenantId)}&model_type=${encodeURIComponent(modelType)}`,
        { method: "POST" },
      );
      const d = await r.json().catch(() => ({}));
      if (!r.ok) throw new Error(toErr(d, "Failed to execute cutover"));
      if (!d.executed) throw new Error((d.blockers || []).join(" | ") || "Cutover blocked by gate");
      await loadAll();
    } catch (e) {
      setError(e.message || "Failed to execute cutover");
    } finally {
      setCutoverRunning(false);
    }
  }

  async function copyText(value) {
    const text = String(value || "").trim();
    if (!text) return;
    try {
      if (navigator?.clipboard?.writeText) {
        await navigator.clipboard.writeText(text);
        return;
      }
    } catch {
      // fall through to legacy copy
    }
    try {
      const ta = document.createElement("textarea");
      ta.value = text;
      ta.setAttribute("readonly", "");
      ta.style.position = "absolute";
      ta.style.left = "-9999px";
      document.body.appendChild(ta);
      ta.select();
      document.execCommand("copy");
      document.body.removeChild(ta);
    } catch {
      // ignore copy failures
    }
  }

  async function saveChallengerPolicy(e) {
    e.preventDefault();
    if (!platformTenantId) return;
    setError(null);
    const payload = {};
    ["min_compared", "max_block_rate_delta", "max_otp_rate_delta", "max_disagree_rate", "cooldown_hours", "candidate_min_age_hours"].forEach((k) => {
      const raw = String(policyForm[k] || "").trim();
      if (!raw) return;
      const v = Number(raw);
      if (!Number.isNaN(v)) payload[k] = v;
    });
    const r = await adminFetch(`${API_BASE}/api/v1/admin/monitoring/challenger-policy?tenant_id=${encodeURIComponent(platformTenantId)}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    const d = await r.json().catch(() => ({}));
    if (!r.ok) {
      setError(toErr(d, "Failed to save challenger policy"));
      return;
    }
    await loadAll();
  }

  async function resetChallengerPolicy() {
    if (!platformTenantId) return;
    setError(null);
    const r = await adminFetch(`${API_BASE}/api/v1/admin/monitoring/challenger-policy?tenant_id=${encodeURIComponent(platformTenantId)}`, {
      method: "DELETE",
    });
    const d = await r.json().catch(() => ({}));
    if (!r.ok) {
      setError(toErr(d, "Failed to reset challenger policy"));
      return;
    }
    setPolicyForm({
      min_compared: "",
      max_block_rate_delta: "",
      max_otp_rate_delta: "",
      max_disagree_rate: "",
      cooldown_hours: "",
      candidate_min_age_hours: "",
    });
    await loadAll();
  }

  const disagreeTrend = (() => {
    const now = Date.now();
    const buckets = [];
    for (let i = 11; i >= 0; i -= 1) {
      const end = now - i * 6 * 60 * 60 * 1000;
      const start = end - 6 * 60 * 60 * 1000;
      buckets.push({ start, end, total: 0, disagree: 0 });
    }
    (traces || []).forEach((t) => {
      const ts = new Date(t.created_at || "").getTime();
      if (!Number.isFinite(ts)) return;
      const champ = String(t?.decision || "").toUpperCase();
      const cand = String(t?.trace_json?.mapper_validation?.shadow?.candidate_decision || "").toUpperCase();
      if (!champ || !cand) return;
      const b = buckets.find((x) => ts > x.start && ts <= x.end);
      if (!b) return;
      b.total += 1;
      if (champ !== cand) b.disagree += 1;
    });
    return buckets.map((b) => ({
      start: b.start,
      end: b.end,
      total: b.total,
      disagree: b.disagree,
      rate: b.total > 0 ? b.disagree / b.total : 0,
    }));
  })();
  const sparkPoints = disagreeTrend
    .map((v, i) => `${(i / Math.max(1, disagreeTrend.length - 1)) * 100},${100 - Math.max(0, Math.min(1, v.rate)) * 100}`)
    .join(" ");
  const latestDisagreeRate = disagreeTrend.length > 0 ? Number(disagreeTrend[disagreeTrend.length - 1].rate || 0) : 0;
  const sparkColor =
    latestDisagreeRate >= 0.25 ? "#f43f5e" : latestDisagreeRate >= 0.12 ? "#f59e0b" : "#22d3ee";

  async function startTenantFineTune(e) {
    e.preventDefault();
    if (!platformTenantId) return;
    setError(null);
    try {
      const fd = new FormData();
      fd.append("tenant_id", platformTenantId);
      fd.append("upload_id", finetuneForm.upload_id.trim());
      fd.append("candidate_version", finetuneForm.candidate_version.trim());
      fd.append("artifact_uri", finetuneForm.artifact_uri.trim());
      fd.append("auto_activate", finetuneForm.auto_activate ? "true" : "false");
      const r = await adminFetch(`${API_BASE}/api/v1/admin/training/${modelType}/tenant-finetune/start`, {
        method: "POST",
        body: fd,
      });
      const d = await r.json().catch(() => ({}));
      if (!r.ok) throw new Error(toErr(d, "Failed to start tenant fine-tune"));
      await loadAll();
    } catch (e2) {
      setError(e2.message || "Failed to start tenant fine-tune");
    }
  }

  function useLatestTrainedUpload() {
    const latest = (finetuneRuns || []).find((r) => r.status === "TRAINED");
    if (!latest?.id) {
      setError("No TRAINED upload found for this tenant/model yet.");
      return;
    }
    setFinetuneForm((f) => ({
      ...f,
      upload_id: latest.id,
      candidate_version: f.candidate_version || `${modelType}-tenant-${new Date().toISOString().slice(0, 10).replace(/-/g, "")}`,
    }));
  }

  return (
    <div className="space-y-6">
      <p className="text-slate-400 text-[11px] tracking-wider uppercase">Model registry & mapper routing</p>
      {!platformTenantId && (
        <div className="rounded-lg border border-amber-900/50 bg-amber-950/20 p-3 text-xs text-amber-200/90">
          Select a bank at login to manage registry and mappers.
        </div>
      )}
      {platformTenantId && !activeMapper && (
        <div className="rounded-lg border border-rose-700/60 bg-rose-900/20 p-3 text-xs text-rose-200">
          No active {modelType} mapper for this tenant. If strict mapper enforcement is enabled, scoring will be rejected.
        </div>
      )}
      {platformTenantId && (
        <div
          className={`rounded-lg border p-3 text-xs ${
            strictReady
              ? "border-emerald-700/60 bg-emerald-900/20 text-emerald-200"
              : "border-amber-700/60 bg-amber-900/20 text-amber-200"
          }`}
        >
          Strict-mode readiness:{" "}
          <span className="font-semibold">{strictReady ? "Ready" : "Not ready"}</span>
          {" · "}
          active model: <span className="font-semibold">{activeModel ? "yes" : "no"}</span>
          {" · "}
          active mapper: <span className="font-semibold">{activeMapper ? "yes" : "no"}</span>
        </div>
      )}
      {error && <div className="rounded-lg border border-rose-700/60 bg-rose-900/20 p-3 text-xs text-rose-200">{error}</div>}
      {prefsNotice && (
        <div className="rounded-lg border border-cyan-700/60 bg-cyan-900/20 p-3 text-xs text-cyan-200">
          Panel preferences reset.
        </div>
      )}

      <div className="flex items-center gap-3">
        <label className="text-xs text-slate-400 uppercase tracking-wider">Model type</label>
        <select
          value={modelType}
          onChange={(e) => setModelType(e.target.value)}
          className="rounded border border-slate-700 bg-slate-950 px-3 py-1.5 text-sm text-slate-200"
        >
          <option value="fraud">fraud</option>
          <option value="care">care</option>
        </select>
        <button
          type="button"
          onClick={loadAll}
          disabled={!platformTenantId || loading}
          className="px-3 py-1.5 rounded border border-slate-600 text-xs text-slate-300 hover:bg-slate-800 disabled:opacity-50"
        >
          {loading ? "Loading..." : "Refresh"}
        </button>
        <button
          type="button"
          onClick={resetPanelPreferences}
          className="px-3 py-1.5 rounded border border-slate-700 text-xs text-slate-300 hover:bg-slate-800"
        >
          Reset panel prefs
        </button>
        <div className="ml-auto flex items-center gap-2">
          <button
            type="button"
            onClick={() => setTraceRouteFilter("tenant")}
            className={`px-2 py-1 rounded border text-[11px] ${
              traceRouteFilter === "tenant"
                ? "ring-1 ring-emerald-400/60 border-emerald-500/80 bg-emerald-900/30 text-emerald-100"
                : routeCounts.tenant > 0
                  ? "border-emerald-700/70 bg-emerald-900/20 text-emerald-200"
                  : "border-slate-700 bg-slate-900 text-slate-400"
            }`}
          >
            tenant: {routeCounts.tenant}
          </button>
          <button
            type="button"
            onClick={() => setTraceRouteFilter("global")}
            className={`px-2 py-1 rounded border text-[11px] ${
              traceRouteFilter === "global"
                ? "ring-1 ring-amber-400/60 border-amber-500/80 bg-amber-900/30 text-amber-100"
                : routeCounts.global > 0
                  ? "border-amber-700/70 bg-amber-900/20 text-amber-200"
                  : "border-slate-700 bg-slate-900 text-slate-400"
            }`}
          >
            global: {routeCounts.global}
          </button>
          <button
            type="button"
            onClick={() => setTraceRouteFilter("fallback")}
            className={`px-2 py-1 rounded border text-[11px] ${
              traceRouteFilter === "fallback"
                ? "ring-1 ring-rose-400/60 border-rose-500/80 bg-rose-900/30 text-rose-100"
                : routeCounts.fallback > 0
                  ? "border-rose-700/70 bg-rose-900/20 text-rose-200"
                  : "border-slate-700 bg-slate-900 text-slate-400"
            }`}
          >
            fallback: {routeCounts.fallback}
          </button>
          <button
            type="button"
            onClick={() => setTraceRouteFilter("all")}
            className={`px-2 py-1 rounded border text-[11px] ${
              traceRouteFilter === "all"
                ? "ring-1 ring-cyan-400/60 border-cyan-500/80 bg-cyan-900/30 text-cyan-100"
                : "border-slate-700 bg-slate-900 text-slate-300"
            }`}
          >
            all: {traces.length}
          </button>
        </div>
      </div>

      <div className="grid grid-cols-1 xl:grid-cols-2 gap-6">
        <form onSubmit={createRegistryEntry} className="rounded-xl border border-slate-800 bg-slate-900/50 p-4 space-y-3">
          <p className="text-xs text-slate-400 uppercase tracking-wider">Create model entry</p>
          <input
            required
            value={registryForm.version}
            onChange={(e) => setRegistryForm((f) => ({ ...f, version: e.target.value }))}
            placeholder="version (e.g. fraud-v3.2.1)"
            className="w-full rounded border border-slate-700 bg-slate-950 px-3 py-2 text-sm"
          />
          <input
            required
            value={registryForm.artifact_uri}
            onChange={(e) => setRegistryForm((f) => ({ ...f, artifact_uri: e.target.value }))}
            placeholder="Folder or file: models/fraud | s3://bucket/prefix | file:///abs/path"
            className="w-full rounded border border-slate-700 bg-slate-950 px-3 py-2 text-sm"
          />
          <p className="text-[10px] text-slate-500">
            Fraud: directory containing lgb_fraud.txt (and optional isolation_forest.joblib). Care: path to care_intent_model.joblib.
            Defaults pre-filled for local bundles; change for per-tenant S3 or another path.
          </p>
          <div className="grid grid-cols-1 md:grid-cols-3 gap-2">
            <input
              value={registryForm.feature_contract_version}
              onChange={(e) => setRegistryForm((f) => ({ ...f, feature_contract_version: e.target.value }))}
              placeholder="contract version"
              className="rounded border border-slate-700 bg-slate-950 px-3 py-2 text-sm"
            />
            <input
              value={registryForm.mapper_version}
              onChange={(e) => setRegistryForm((f) => ({ ...f, mapper_version: e.target.value }))}
              placeholder="mapper version"
              className="rounded border border-slate-700 bg-slate-950 px-3 py-2 text-sm"
            />
            <select
              value={registryForm.status}
              onChange={(e) => setRegistryForm((f) => ({ ...f, status: e.target.value }))}
              className="rounded border border-slate-700 bg-slate-950 px-3 py-2 text-sm"
            >
              <option value="shadow">shadow</option>
              <option value="active">active</option>
              <option value="disabled">disabled</option>
            </select>
          </div>
          <button
            type="submit"
            disabled={!platformTenantId}
            className="px-4 py-2 rounded bg-cyan-500/90 text-slate-900 text-xs font-semibold uppercase tracking-wider disabled:opacity-50"
          >
            Create entry
          </button>
        </form>

        <form onSubmit={createMapper} className="rounded-xl border border-slate-800 bg-slate-900/50 p-4 space-y-3">
          <p className="text-xs text-slate-400 uppercase tracking-wider">Create mapper</p>
          <input
            required
            value={mapperForm.mapper_version}
            onChange={(e) => setMapperForm((f) => ({ ...f, mapper_version: e.target.value }))}
            placeholder="mapper version (e.g. mapper-v7)"
            className="w-full rounded border border-slate-700 bg-slate-950 px-3 py-2 text-sm"
          />
          <input
            value={mapperForm.contract_version}
            onChange={(e) => setMapperForm((f) => ({ ...f, contract_version: e.target.value }))}
            placeholder="contract version"
            className="w-full rounded border border-slate-700 bg-slate-950 px-3 py-2 text-sm"
          />
          <textarea
            value={mapperForm.mapping_json}
            onChange={(e) => setMapperForm((f) => ({ ...f, mapping_json: e.target.value }))}
            placeholder='{"amount":"txn.amount","currency":"txn.ccy"}'
            className="w-full h-28 rounded border border-slate-700 bg-slate-950 px-3 py-2 text-xs font-mono"
          />
          <textarea
            value={mapperDryRunRaw}
            onChange={(e) => setMapperDryRunRaw(e.target.value)}
            placeholder='Dry-run raw payload JSON, e.g. {"txn":{"amount":120}}'
            className="w-full h-24 rounded border border-slate-700 bg-slate-950 px-3 py-2 text-xs font-mono"
          />
          <div className="flex flex-wrap gap-2">
            <button
              type="button"
              onClick={loadSamplePayload}
              className="px-3 py-1.5 rounded border border-slate-600 text-slate-200 text-xs uppercase"
            >
              Use sample payload
            </button>
            <button
              type="button"
              onClick={validateMapperDraft}
              disabled={mapperTesting}
              className="px-3 py-1.5 rounded border border-indigo-600/70 text-indigo-200 text-xs uppercase disabled:opacity-50"
            >
              {mapperTesting ? "Running..." : "Validate mapper"}
            </button>
            <button
              type="button"
              onClick={dryRunMapperDraft}
              disabled={mapperTesting}
              className="px-3 py-1.5 rounded border border-amber-600/70 text-amber-200 text-xs uppercase disabled:opacity-50"
            >
              {mapperTesting ? "Running..." : "Dry-run"}
            </button>
          </div>
          {mapperDryRunOut && (
            <div className="rounded border border-slate-700 bg-slate-950/60 p-2 text-xs">
              <div className={`${mapperDryRunOut.valid ? "text-emerald-300" : "text-rose-300"}`}>
                {mapperDryRunOut.mode === "dry-run" ? "Dry-run" : "Validate"}: {mapperDryRunOut.valid ? "valid" : "invalid"}
              </div>
              {Array.isArray(mapperDryRunOut.errors) && mapperDryRunOut.errors.length > 0 && (
                <div className="mt-1 text-rose-300">{mapperDryRunOut.errors.join(" | ")}</div>
              )}
              {mapperDryRunOut.canonical_payload && (
                <pre className="mt-2 max-h-44 overflow-auto rounded bg-black/40 p-2 text-[11px] text-slate-300">
                  {JSON.stringify(mapperDryRunOut.canonical_payload, null, 2)}
                </pre>
              )}
            </div>
          )}
          <label className="flex items-center gap-2 text-xs text-slate-300">
            <input
              type="checkbox"
              checked={mapperForm.is_active}
              onChange={(e) => setMapperForm((f) => ({ ...f, is_active: e.target.checked }))}
            />
            Activate immediately
          </label>
          <button
            type="submit"
            disabled={!platformTenantId}
            className="px-4 py-2 rounded bg-emerald-500/90 text-slate-900 text-xs font-semibold uppercase tracking-wider disabled:opacity-50"
          >
            Create mapper
          </button>
        </form>
      </div>

      <div className="grid grid-cols-1 xl:grid-cols-2 gap-6">
        <form onSubmit={createCalibration} className="rounded-xl border border-slate-800 bg-slate-900/50 p-4 space-y-3">
          <p className="text-xs text-slate-400 uppercase tracking-wider">Calibration & guardrails</p>
          {eligibility && (
            <div className={`rounded border p-2 text-xs ${eligibility.eligible ? "border-emerald-700/60 bg-emerald-900/20 text-emerald-200" : "border-amber-700/60 bg-amber-900/20 text-amber-200"}`}>
              Fine-tune eligibility ({modelType}): {eligibility.eligible ? "eligible" : "not eligible"} · rows {eligibility.rows_available}/{eligibility.min_rows_required}
            </div>
          )}
          <input
            required
            value={calibrationForm.model_version}
            onChange={(e) => setCalibrationForm((f) => ({ ...f, model_version: e.target.value }))}
            placeholder="model version (must match active model)"
            className="w-full rounded border border-slate-700 bg-slate-950 px-3 py-2 text-sm"
          />
          <div className="grid grid-cols-1 md:grid-cols-3 gap-2">
            <input
              required
              value={calibrationForm.calibration_version}
              onChange={(e) => setCalibrationForm((f) => ({ ...f, calibration_version: e.target.value }))}
              placeholder="calibration version"
              className="rounded border border-slate-700 bg-slate-950 px-3 py-2 text-sm"
            />
            <select value={calibrationForm.method} onChange={(e) => setCalibrationForm((f) => ({ ...f, method: e.target.value }))} className="rounded border border-slate-700 bg-slate-950 px-3 py-2 text-sm">
              <option value="none">none</option>
              <option value="platt">platt</option>
              <option value="isotonic">isotonic</option>
            </select>
            <select value={calibrationForm.status} onChange={(e) => setCalibrationForm((f) => ({ ...f, status: e.target.value }))} className="rounded border border-slate-700 bg-slate-950 px-3 py-2 text-sm">
              <option value="shadow">shadow</option>
              <option value="active">active</option>
              <option value="disabled">disabled</option>
            </select>
          </div>
          <textarea value={calibrationForm.params_json} onChange={(e) => setCalibrationForm((f) => ({ ...f, params_json: e.target.value }))} className="w-full h-20 rounded border border-slate-700 bg-slate-950 px-3 py-2 text-xs font-mono" />
          <div className="flex gap-2">
            <button type="submit" className="px-4 py-2 rounded bg-indigo-500/90 text-slate-900 text-xs font-semibold uppercase tracking-wider">Create calibration</button>
            <button type="button" onClick={runGuardrailsNow} disabled={guardrailRunning} className="px-4 py-2 rounded border border-rose-700/70 text-rose-200 text-xs font-semibold uppercase tracking-wider disabled:opacity-50">
              {guardrailRunning ? "Running..." : "Run guardrails now"}
            </button>
            <button type="button" onClick={runChallengerEvaluatorNow} disabled={evaluatorRunning} className="px-4 py-2 rounded border border-emerald-700/70 text-emerald-200 text-xs font-semibold uppercase tracking-wider disabled:opacity-50">
              {evaluatorRunning ? "Running..." : "Run challenger evaluator"}
            </button>
          </div>
          {challengerPolicy && (
            <div className="rounded border border-slate-700 bg-slate-950/50 p-2 text-[11px] text-slate-300">
              Auto-promote policy: {challengerPolicy.enabled ? "enabled" : "disabled"} · window {challengerPolicy.window_hours}h · min compared {challengerPolicy.min_compared} · max block delta {Number(challengerPolicy.max_block_rate_delta).toFixed(4)} · max otp delta {Number(challengerPolicy.max_otp_rate_delta).toFixed(4)} · max disagree {Number(challengerPolicy.max_disagree_rate).toFixed(4)} · cooldown {challengerPolicy.cooldown_hours}h · min-age {challengerPolicy.candidate_min_age_hours}h
            </div>
          )}
          <div className="grid grid-cols-2 md:grid-cols-3 gap-2">
            <input value={policyForm.min_compared} onChange={(e) => setPolicyForm((f) => ({ ...f, min_compared: e.target.value }))} placeholder="min compared" className="rounded border border-slate-700 bg-slate-950 px-2 py-1.5 text-xs" />
            <input value={policyForm.max_block_rate_delta} onChange={(e) => setPolicyForm((f) => ({ ...f, max_block_rate_delta: e.target.value }))} placeholder="max block delta" className="rounded border border-slate-700 bg-slate-950 px-2 py-1.5 text-xs" />
            <input value={policyForm.max_otp_rate_delta} onChange={(e) => setPolicyForm((f) => ({ ...f, max_otp_rate_delta: e.target.value }))} placeholder="max otp delta" className="rounded border border-slate-700 bg-slate-950 px-2 py-1.5 text-xs" />
            <input value={policyForm.max_disagree_rate} onChange={(e) => setPolicyForm((f) => ({ ...f, max_disagree_rate: e.target.value }))} placeholder="max disagree" className="rounded border border-slate-700 bg-slate-950 px-2 py-1.5 text-xs" />
            <input value={policyForm.cooldown_hours} onChange={(e) => setPolicyForm((f) => ({ ...f, cooldown_hours: e.target.value }))} placeholder="cooldown hours" className="rounded border border-slate-700 bg-slate-950 px-2 py-1.5 text-xs" />
            <input value={policyForm.candidate_min_age_hours} onChange={(e) => setPolicyForm((f) => ({ ...f, candidate_min_age_hours: e.target.value }))} placeholder="candidate min-age hours" className="rounded border border-slate-700 bg-slate-950 px-2 py-1.5 text-xs" />
            <button type="button" onClick={(e) => saveChallengerPolicy(e)} className="px-3 py-1.5 rounded border border-cyan-700/70 text-cyan-200 text-xs uppercase">Save tenant override</button>
            <button type="button" onClick={resetChallengerPolicy} className="px-3 py-1.5 rounded border border-slate-600 text-slate-300 text-xs uppercase">Reset to global</button>
          </div>
        </form>

        <div className="rounded-xl border border-slate-800 bg-slate-900/50 overflow-hidden">
          <div className="px-4 py-3 border-b border-slate-800 text-xs text-slate-400 uppercase tracking-wider">Calibrations</div>
          <table className="w-full text-left text-xs">
            <thead>
              <tr className="border-b border-slate-800 text-slate-500 uppercase tracking-wider">
                <th className="p-3">Version</th>
                <th className="p-3">Method</th>
                <th className="p-3">Status</th>
                <th className="p-3">Created</th>
                <th className="p-3">Action</th>
              </tr>
            </thead>
            <tbody>
              {calibrations.length === 0 && <tr><td colSpan={5} className="p-4 text-slate-500">No calibrations yet.</td></tr>}
              {calibrations.map((c) => (
                <tr key={c.id} className="border-b border-slate-800/70">
                  <td className="p-3 text-slate-200">{c.calibration_version}</td>
                  <td className="p-3">{c.method}</td>
                  <td className="p-3">{c.status}</td>
                  <td className="p-3 text-slate-400">{c.created_at ? new Date(c.created_at).toLocaleString() : "—"}</td>
                  <td className="p-3"><button type="button" onClick={() => activateCalibration(c.id)} disabled={c.status === "active"} className="px-2 py-1 rounded border border-indigo-700/70 text-indigo-200 disabled:opacity-50">Activate</button></td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      <form onSubmit={startTenantFineTune} className="rounded-xl border border-slate-800 bg-slate-900/50 p-4 space-y-3">
        <p className="text-xs text-slate-400 uppercase tracking-wider">Phase 3 tenant fine-tune start</p>
        <button
          type="button"
          onClick={useLatestTrainedUpload}
          className="px-3 py-1.5 rounded border border-slate-700 text-slate-200 text-xs uppercase"
        >
          Use latest trained upload
        </button>
        <div className="grid grid-cols-1 md:grid-cols-3 gap-2">
          <input
            required
            value={finetuneForm.upload_id}
            onChange={(e) => setFinetuneForm((f) => ({ ...f, upload_id: e.target.value }))}
            placeholder="tenant upload_id"
            className="rounded border border-slate-700 bg-slate-950 px-3 py-2 text-sm"
          />
          <input
            required
            value={finetuneForm.candidate_version}
            onChange={(e) => setFinetuneForm((f) => ({ ...f, candidate_version: e.target.value }))}
            placeholder={`${modelType}-tenant-vX`}
            className="rounded border border-slate-700 bg-slate-950 px-3 py-2 text-sm"
          />
          <input
            required
            value={finetuneForm.artifact_uri}
            onChange={(e) => setFinetuneForm((f) => ({ ...f, artifact_uri: e.target.value }))}
            placeholder="artifact_uri (s3://... or file://...)"
            className="rounded border border-slate-700 bg-slate-950 px-3 py-2 text-sm"
          />
        </div>
        <label className="flex items-center gap-2 text-xs text-slate-300">
          <input
            type="checkbox"
            checked={finetuneForm.auto_activate}
            onChange={(e) => setFinetuneForm((f) => ({ ...f, auto_activate: e.target.checked }))}
          />
          Auto-activate candidate immediately
        </label>
        <button type="submit" className="px-4 py-2 rounded bg-fuchsia-500/90 text-slate-900 text-xs font-semibold uppercase tracking-wider">
          Start tenant fine-tune
        </button>
      </form>

      <div className="rounded-xl border border-slate-800 bg-slate-900/50 overflow-hidden">
        <div className="px-4 py-3 border-b border-slate-800 text-xs text-slate-400 uppercase tracking-wider">Fine-tune runs ({modelType})</div>
        <table className="w-full text-left text-xs">
          <thead>
            <tr className="border-b border-slate-800 text-slate-500 uppercase tracking-wider">
              <th className="p-3">Upload</th>
              <th className="p-3">Status</th>
              <th className="p-3">Rows</th>
              <th className="p-3">Trained at</th>
              <th className="p-3">Error</th>
            </tr>
          </thead>
          <tbody>
            {finetuneRuns.length === 0 && <tr><td colSpan={5} className="p-4 text-slate-500">No fine-tune runs yet.</td></tr>}
            {finetuneRuns.map((r) => (
              <tr key={r.id} className="border-b border-slate-800/70">
                <td className="p-3 text-slate-200">{r.id}</td>
                <td className="p-3">
                  <span
                    className={`px-2 py-0.5 rounded border text-[11px] uppercase tracking-wider ${
                      r.status === "TRAINED"
                        ? "border-emerald-500/60 bg-emerald-900/35 text-emerald-200"
                        : r.status === "TRAINING"
                          ? "border-cyan-500/60 bg-cyan-900/35 text-cyan-200"
                          : r.status === "FAILED"
                            ? "border-rose-500/60 bg-rose-900/35 text-rose-200"
                            : "border-slate-500/60 bg-slate-900/35 text-slate-200"
                    }`}
                  >
                    {r.status === "TRAINED"
                      ? "Ready"
                      : r.status === "TRAINING"
                        ? "Training"
                        : r.status === "FAILED"
                          ? "Failed"
                          : r.status === "UPLOADED"
                            ? "Queued"
                            : r.status}
                  </span>
                </td>
                <td className="p-3">{r.row_count}</td>
                <td className="p-3 text-slate-400">{r.last_retrained_at ? new Date(r.last_retrained_at).toLocaleString() : "—"}</td>
                <td className="p-3 text-rose-300">{r.last_error || "—"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <div className="rounded-xl border border-slate-800 bg-slate-900/50 overflow-hidden">
        <div className="px-4 py-3 border-b border-slate-800 text-xs text-slate-400 uppercase tracking-wider">Model entries</div>
        <table className="w-full text-left text-xs">
          <thead>
            <tr className="border-b border-slate-800 text-slate-500 uppercase tracking-wider">
              <th className="p-3">Version</th>
              <th className="p-3">Status</th>
              <th className="p-3">Contract</th>
              <th className="p-3">Mapper</th>
              <th className="p-3">Created</th>
              <th className="p-3">Actions</th>
            </tr>
          </thead>
          <tbody>
            {entries.length === 0 && (
              <tr>
                <td colSpan={6} className="p-4 text-slate-500">No model entries yet.</td>
              </tr>
            )}
            {entries.map((row) => (
              <tr key={row.id} className="border-b border-slate-800/70">
                <td className="p-3 text-slate-200">{row.version}</td>
                <td className="p-3">{row.status}</td>
                <td className="p-3">{row.feature_contract_version}</td>
                <td className="p-3">{row.mapper_version}</td>
                <td className="p-3 text-slate-400">{row.created_at ? new Date(row.created_at).toLocaleString() : "—"}</td>
                <td className="p-3">
                  <div className="flex gap-2">
                    <button
                      type="button"
                      onClick={() => activateModel(row.id)}
                      className="px-2 py-1 rounded border border-cyan-700/70 text-cyan-200"
                    >
                      Activate
                    </button>
                    <button
                      type="button"
                      onClick={() => rollbackModel(row.id)}
                      className="px-2 py-1 rounded border border-amber-700/70 text-amber-200"
                    >
                      Force rollback
                    </button>
                    {row.status !== "active" && (
                      <>
                        <button
                          type="button"
                          onClick={() => promoteModel(row.id)}
                          className="px-2 py-1 rounded border border-emerald-700/70 text-emerald-200"
                        >
                          Promote
                        </button>
                        <button
                          type="button"
                          onClick={() => pauseModel(row.id)}
                          className="px-2 py-1 rounded border border-slate-600 text-slate-300"
                        >
                          Pause
                        </button>
                      </>
                    )}
                  </div>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <div className="rounded-xl border border-slate-800 bg-slate-900/50 p-4">
        <p className="text-xs text-slate-400 uppercase tracking-wider mb-3">Champion vs challenger (24h)</p>
        {!championChallengerKpi ? (
          <p className="text-xs text-slate-500">No comparison data yet.</p>
        ) : (
          <div className="grid grid-cols-1 md:grid-cols-3 gap-3 text-xs">
            <div className="rounded border border-slate-700 bg-slate-950/50 p-3">
              <div className="text-slate-400">Compared traces</div>
              <div className="text-slate-100 mt-1">{championChallengerKpi.compared_traces}/{championChallengerKpi.total_traces}</div>
              <div className="text-slate-500 mt-1">Disagree: {championChallengerKpi.disagree_rate != null ? `${(Number(championChallengerKpi.disagree_rate) * 100).toFixed(2)}%` : "—"}</div>
              <div className="text-slate-500">72h disagree: {championChallengerKpi72h?.disagree_rate != null ? `${(Number(championChallengerKpi72h.disagree_rate) * 100).toFixed(2)}%` : "—"}</div>
              <div className="mt-2 rounded border border-slate-700 bg-black/20 p-1">
                <svg viewBox="0 0 100 100" className="w-full h-12">
                  <polyline fill="none" stroke={sparkColor} strokeWidth="2.5" points={sparkPoints} />
                  {disagreeTrend.map((b, i) => {
                    const x = (i / Math.max(1, disagreeTrend.length - 1)) * 100;
                    const y = 100 - Math.max(0, Math.min(1, b.rate)) * 100;
                    const s = new Date(b.start).toLocaleString();
                    const e = new Date(b.end).toLocaleString();
                    return (
                      <circle
                        key={`${b.start}-${i}`}
                        cx={x}
                        cy={y}
                        r={traceTimeWindow && Number(traceTimeWindow.start) === Number(b.start) ? "2.6" : "1.8"}
                        fill={sparkColor}
                        className="cursor-pointer"
                        onClick={() => {
                          if (traceTimeWindow && Number(traceTimeWindow.start) === Number(b.start)) {
                            setTraceTimeWindow(null);
                          } else {
                            setTraceTimeWindow({ start: b.start, end: b.end });
                          }
                        }}
                      >
                        <title>{`window: ${s} - ${e}\ncompared: ${b.total}\ndisagree: ${(b.rate * 100).toFixed(2)}%`}</title>
                      </circle>
                    );
                  })}
                </svg>
              </div>
              <div className="mt-1 flex items-center gap-3 text-[10px] text-slate-400">
                <span className="inline-flex items-center gap-1"><span className="inline-block h-2 w-2 rounded-full bg-cyan-400" /> low (&lt;12%)</span>
                <span className="inline-flex items-center gap-1"><span className="inline-block h-2 w-2 rounded-full bg-amber-400" /> medium (12-25%)</span>
                <span className="inline-flex items-center gap-1"><span className="inline-block h-2 w-2 rounded-full bg-rose-400" /> high (&gt;=25%)</span>
              </div>
              {traceTimeWindow && (
                <div className="mt-1 text-[10px] text-cyan-300">
                  Trace window filter active: {new Date(traceTimeWindow.start).toLocaleString()} - {new Date(traceTimeWindow.end).toLocaleString()}
                  <button type="button" onClick={() => setTraceTimeWindow(null)} className="ml-2 underline text-cyan-200">clear</button>
                </div>
              )}
            </div>
            <div className="rounded border border-slate-700 bg-slate-950/50 p-3">
              <div className="text-cyan-300">Champion {championChallengerKpi.champion_model_version || "—"}</div>
              <div className="text-slate-300 mt-1">Block {(Number(championChallengerKpi.champion_block_rate || 0) * 100).toFixed(2)}%</div>
              <div className="text-slate-300">OTP {(Number(championChallengerKpi.champion_otp_rate || 0) * 100).toFixed(2)}%</div>
              <div className="text-slate-300">Approve {(Number(championChallengerKpi.champion_approve_rate || 0) * 100).toFixed(2)}%</div>
            </div>
            <div className="rounded border border-slate-700 bg-slate-950/50 p-3">
              <div className="text-emerald-300">Challenger {championChallengerKpi.challenger_model_version || "—"}</div>
              <div className="text-slate-300 mt-1">Block {championChallengerKpi.challenger_block_rate != null ? `${(Number(championChallengerKpi.challenger_block_rate) * 100).toFixed(2)}%` : "—"}</div>
              <div className="text-slate-300">OTP {championChallengerKpi.challenger_otp_rate != null ? `${(Number(championChallengerKpi.challenger_otp_rate) * 100).toFixed(2)}%` : "—"}</div>
              <div className="text-slate-300">Approve {championChallengerKpi.challenger_approve_rate != null ? `${(Number(championChallengerKpi.challenger_approve_rate) * 100).toFixed(2)}%` : "—"}</div>
            </div>
          </div>
        )}
      </div>

      {isolationReadiness && (
        <div className={`rounded-xl border p-4 ${isolationReadiness.ready_for_strict_cutover ? "border-emerald-700/60 bg-emerald-900/20" : "border-amber-700/60 bg-amber-900/20"}`}>
          <p className="text-xs uppercase tracking-wider text-slate-300">Isolation readiness</p>
          <p className={`text-sm mt-1 ${isolationReadiness.ready_for_strict_cutover ? "text-emerald-200" : "text-amber-200"}`}>
            {isolationReadiness.ready_for_strict_cutover ? "Ready for strict cutover" : "Not ready for strict cutover"}
          </p>
          <div className="mt-2 grid grid-cols-1 md:grid-cols-3 gap-2 text-xs text-slate-300">
            <div>strict mapper: <span className="font-semibold">{String(isolationReadiness.strict_mapper_enforcement)}</span></div>
            <div>model fallback: <span className="font-semibold">{String(isolationReadiness.allow_model_fallback)}</span></div>
            <div>active model/mapper: <span className="font-semibold">{String(isolationReadiness.has_active_model)}/{String(isolationReadiness.has_active_mapper)}</span></div>
            <div>artifact check: <span className="font-semibold">{isolationReadiness.artifact_check}</span></div>
            <div>artifact exists: <span className="font-semibold">{isolationReadiness.artifact_exists == null ? "unknown" : String(isolationReadiness.artifact_exists)}</span></div>
            <div>model version: <span className="font-semibold">{isolationReadiness.active_model_version || "—"}</span></div>
          </div>
        </div>
      )}

      {cutoverGate && (
        <div className={`rounded-xl border p-4 ${cutoverGate.pass_gate ? "border-emerald-700/60 bg-emerald-900/20" : "border-rose-700/60 bg-rose-900/20"}`}>
          <p className="text-xs uppercase tracking-wider text-slate-300">Production cutover gate</p>
          <p className={`text-sm mt-1 ${cutoverGate.pass_gate ? "text-emerald-200" : "text-rose-200"}`}>
            {cutoverGate.pass_gate ? "PASS" : "BLOCKED"}
          </p>
          <div className="mt-2 text-xs text-slate-300 grid grid-cols-1 md:grid-cols-3 gap-2">
            <div>fallback traces (24h): <span className="font-semibold">{cutoverGate.fallback_trace_count_24h ?? 0}</span></div>
            <div>labeled (30d): <span className="font-semibold">{cutoverGate.latest_labeled_count_30d ?? 0}</span></div>
            <div>precision (30d): <span className="font-semibold">{cutoverGate.latest_precision_30d == null ? "—" : `${(Number(cutoverGate.latest_precision_30d) * 100).toFixed(2)}%`}</span></div>
            <div>last cutover at: <span className="font-semibold">{cutoverGate.last_executed_at ? new Date(cutoverGate.last_executed_at).toLocaleString() : "—"}</span></div>
            <div>
              last cutover by: <span className="font-semibold">{cutoverGate.last_executed_by || "—"}</span>
              {cutoverGate.last_executed_by && (
                <button
                  type="button"
                  onClick={() => copyText(cutoverGate.last_executed_by)}
                  className="ml-2 px-1.5 py-0.5 rounded border border-slate-600 text-[10px] text-slate-300 uppercase"
                >
                  Copy
                </button>
              )}
            </div>
          </div>
          {Array.isArray(cutoverGate.blockers) && cutoverGate.blockers.length > 0 && (
            <div className="mt-3">
              <p className="text-[11px] uppercase tracking-wider text-rose-200">Blockers</p>
              <ul className="mt-1 list-disc list-inside text-xs text-rose-100 space-y-1">
                {cutoverGate.blockers.map((b, i) => <li key={`b-${i}`}>{b}</li>)}
              </ul>
            </div>
          )}
          {Array.isArray(cutoverGate.warnings) && cutoverGate.warnings.length > 0 && (
            <div className="mt-3">
              <p className="text-[11px] uppercase tracking-wider text-amber-200">Warnings</p>
              <ul className="mt-1 list-disc list-inside text-xs text-amber-100 space-y-1">
                {cutoverGate.warnings.map((w, i) => <li key={`w-${i}`}>{w}</li>)}
              </ul>
            </div>
          )}
          <div className="mt-3">
            <button
              type="button"
              onClick={runCutoverExecute}
              disabled={cutoverRunning || !cutoverGate.pass_gate}
              className="px-3 py-1.5 rounded border border-emerald-700/70 text-emerald-200 text-xs uppercase disabled:opacity-50"
            >
              {cutoverRunning ? "Executing..." : "Execute cutover"}
            </button>
          </div>
        </div>
      )}

      {modelKpis && (
        <div className="rounded-xl border border-slate-800 bg-slate-900/50 p-4">
          <p className="text-xs text-slate-400 uppercase tracking-wider mb-3">Labeled quality snapshot (30d)</p>
          <div className="grid grid-cols-2 md:grid-cols-5 gap-3 text-xs">
            <div className="rounded border border-slate-700 bg-slate-950/50 p-3">
              <div className="text-slate-400">Precision</div>
              <div className="text-emerald-300 mt-1">{modelKpis.precision_proxy == null ? "—" : `${(Number(modelKpis.precision_proxy) * 100).toFixed(2)}%`}</div>
            </div>
            <div className="rounded border border-slate-700 bg-slate-950/50 p-3">
              <div className="text-slate-400">Recall</div>
              <div className="text-cyan-300 mt-1">{modelKpis.recall_proxy == null ? "—" : `${(Number(modelKpis.recall_proxy) * 100).toFixed(2)}%`}</div>
            </div>
            <div className="rounded border border-slate-700 bg-slate-950/50 p-3">
              <div className="text-slate-400">False positive rate</div>
              <div className="text-rose-300 mt-1">{modelKpis.fpr_proxy == null ? "—" : `${(Number(modelKpis.fpr_proxy) * 100).toFixed(2)}%`}</div>
            </div>
            <div className="rounded border border-slate-700 bg-slate-950/50 p-3">
              <div className="text-slate-400">Labeled</div>
              <div className="text-slate-100 mt-1">{modelKpis.labeled_count ?? 0}</div>
            </div>
            <div className="rounded border border-slate-700 bg-slate-950/50 p-3">
              <div className="text-slate-400">AUC</div>
              <div className="text-fuchsia-300 mt-1">{modelKpis.auc_proxy == null ? "—" : Number(modelKpis.auc_proxy).toFixed(3)}</div>
            </div>
          </div>
        </div>
      )}

      <div className="rounded-xl border border-slate-800 bg-slate-900/50 overflow-hidden">
        <div className="px-4 py-3 border-b border-slate-800 text-xs text-slate-400 uppercase tracking-wider">Recent auto-rollbacks</div>
        <table className="w-full text-left text-xs">
          <thead>
            <tr className="border-b border-slate-800 text-slate-500 uppercase tracking-wider">
              <th className="p-3">Time</th>
              <th className="p-3">From</th>
              <th className="p-3">To</th>
              <th className="p-3">Block rate</th>
              <th className="p-3">Alert rate</th>
            </tr>
          </thead>
          <tbody>
            {rollbackEvents.length === 0 && <tr><td colSpan={5} className="p-4 text-slate-500">No rollback events yet.</td></tr>}
            {rollbackEvents.map((ev, i) => (
              <tr key={`${ev.created_at}-${i}`} className="border-b border-slate-800/70">
                <td className="p-3 text-slate-400">{ev.created_at ? new Date(ev.created_at).toLocaleString() : "—"}</td>
                <td className="p-3 text-slate-200">{ev?.event_data?.from_model_version || "—"}</td>
                <td className="p-3 text-slate-200">{ev?.event_data?.to_model_version || "—"}</td>
                <td className="p-3">{ev?.event_data?.block_rate != null ? `${(Number(ev.event_data.block_rate) * 100).toFixed(2)}%` : "—"}</td>
                <td className="p-3">{ev?.event_data?.alert_rate != null ? `${(Number(ev.event_data.alert_rate) * 100).toFixed(2)}%` : "—"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <div className="rounded-xl border border-slate-800 bg-slate-900/50 overflow-hidden">
        <div className="px-4 py-3 border-b border-slate-800 text-xs text-slate-400 uppercase tracking-wider">Recent auto-promotions</div>
        <table className="w-full text-left text-xs">
          <thead>
            <tr className="border-b border-slate-800 text-slate-500 uppercase tracking-wider">
              <th className="p-3">Time</th>
              <th className="p-3">From</th>
              <th className="p-3">To</th>
              <th className="p-3">Compared</th>
              <th className="p-3">Disagree</th>
              <th className="p-3">Precision delta</th>
            </tr>
          </thead>
          <tbody>
            {promotionEvents.length === 0 && <tr><td colSpan={6} className="p-4 text-slate-500">No auto-promotion events yet.</td></tr>}
            {promotionEvents.map((ev, i) => (
              <tr key={`${ev.created_at}-${i}`} className="border-b border-slate-800/70">
                <td className="p-3 text-slate-400">{ev.created_at ? new Date(ev.created_at).toLocaleString() : "—"}</td>
                <td className="p-3 text-slate-200">{ev?.event_data?.from_model_version || "—"}</td>
                <td className="p-3 text-slate-200">{ev?.event_data?.to_model_version || "—"}</td>
                <td className="p-3">{ev?.event_data?.compared_traces ?? "—"}</td>
                <td className="p-3">{ev?.event_data?.disagree_rate != null ? `${(Number(ev.event_data.disagree_rate) * 100).toFixed(2)}%` : "—"}</td>
                <td className="p-3">
                  {ev?.event_data?.champion_precision != null && ev?.event_data?.challenger_precision != null
                    ? `${((Number(ev.event_data.challenger_precision) - Number(ev.event_data.champion_precision)) * 100).toFixed(2)}%`
                    : "—"}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <div className="rounded-xl border border-slate-800 bg-slate-900/50 overflow-hidden">
        <div className="px-4 py-3 border-b border-slate-800 text-xs text-slate-400 uppercase tracking-wider">Tenant mappers</div>
        <table className="w-full text-left text-xs">
          <thead>
            <tr className="border-b border-slate-800 text-slate-500 uppercase tracking-wider">
              <th className="p-3">Version</th>
              <th className="p-3">Contract</th>
              <th className="p-3">Active</th>
              <th className="p-3">Created</th>
              <th className="p-3">Actions</th>
            </tr>
          </thead>
          <tbody>
            {mappers.length === 0 && (
              <tr>
                <td colSpan={5} className="p-4 text-slate-500">No mapper entries yet.</td>
              </tr>
            )}
            {mappers.map((row) => (
              <tr key={row.id} className="border-b border-slate-800/70">
                <td className="p-3 text-slate-200">{row.mapper_version}</td>
                <td className="p-3">{row.contract_version}</td>
                <td className="p-3">{row.is_active ? "yes" : "no"}</td>
                <td className="p-3 text-slate-400">{row.created_at ? new Date(row.created_at).toLocaleString() : "—"}</td>
                <td className="p-3">
                  <button
                    type="button"
                    onClick={() => activateMapper(row.id)}
                    disabled={!!row.is_active}
                    className="px-2 py-1 rounded border border-cyan-700/70 text-cyan-200 disabled:opacity-50"
                  >
                    Activate
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <div className="rounded-xl border border-slate-800 bg-slate-900/50 overflow-hidden">
        <div className="px-4 py-3 border-b border-slate-800 text-xs text-slate-400 uppercase tracking-wider">Recent job runs</div>
        <div className="px-4 py-2 border-b border-slate-800 flex flex-wrap items-center gap-2 text-xs">
          <input
            value={jobRunNameFilter}
            onChange={(e) => setJobRunNameFilter(e.target.value)}
            placeholder="filter job name"
            className="rounded border border-slate-700 bg-slate-950 px-2 py-1.5 text-xs text-slate-200"
          />
          <select
            value={jobRunStatusFilter}
            onChange={(e) => setJobRunStatusFilter(e.target.value)}
            className="rounded border border-slate-700 bg-slate-950 px-2 py-1.5 text-xs text-slate-200"
          >
            <option value="all">all statuses</option>
            <option value="started">started</option>
            <option value="success">success</option>
            <option value="failed">failed</option>
          </select>
          <input
            value={jobRunLimit}
            onChange={(e) => setJobRunLimit(e.target.value)}
            placeholder="limit"
            className="w-20 rounded border border-slate-700 bg-slate-950 px-2 py-1.5 text-xs text-slate-200"
          />
          <button
            type="button"
            onClick={loadAll}
            disabled={!platformTenantId || loading}
            className="px-2 py-1 rounded border border-slate-600 text-[11px] text-slate-300 disabled:opacity-50"
          >
            Apply
          </button>
        </div>
        <table className="w-full text-left text-xs">
          <thead>
            <tr className="border-b border-slate-800 text-slate-500 uppercase tracking-wider">
              <th className="p-3">Started</th>
              <th className="p-3">Job</th>
              <th className="p-3">Status</th>
              <th className="p-3">Duration</th>
              <th className="p-3">Trigger</th>
              <th className="p-3">Error</th>
            </tr>
          </thead>
          <tbody>
            {jobRuns.length === 0 && (
              <tr>
                <td colSpan={6} className="p-4 text-slate-500">No job runs yet.</td>
              </tr>
            )}
            {jobRuns.map((jr) => (
              <tr key={jr.id} className="border-b border-slate-800/70">
                <td className="p-3 text-slate-400">{jr.started_at ? new Date(jr.started_at).toLocaleString() : "—"}</td>
                <td className="p-3 text-slate-200">{jr.job_name || "—"}</td>
                <td className="p-3">
                  <span
                    className={`px-2 py-0.5 rounded border text-[11px] uppercase tracking-wider ${
                      jr.status === "success"
                        ? "border-emerald-500/60 bg-emerald-900/35 text-emerald-200"
                        : jr.status === "failed"
                          ? "border-rose-500/60 bg-rose-900/35 text-rose-200"
                          : "border-cyan-500/60 bg-cyan-900/35 text-cyan-200"
                    }`}
                  >
                    {jr.status || "started"}
                  </span>
                </td>
                <td className="p-3">{jr.duration_ms != null ? `${jr.duration_ms}ms` : "—"}</td>
                <td className="p-3">{jr.trigger_source || "—"}</td>
                <td className="p-3 text-rose-300">{jr.error_summary || "—"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <div className="rounded-xl border border-slate-800 bg-slate-900/50 overflow-hidden">
        <div className="px-4 py-3 border-b border-slate-800 text-xs text-slate-400 uppercase tracking-wider">Recent inference traces</div>
        <table className="w-full text-left text-xs">
          <thead>
            <tr className="border-b border-slate-800 text-slate-500 uppercase tracking-wider">
              <th className="p-3">Time</th>
              <th className="p-3">Model</th>
              <th className="p-3">Mapper</th>
              <th className="p-3">Contract</th>
              <th className="p-3">Decision</th>
              <th className="p-3">Route</th>
              <th className="p-3">Latency</th>
            </tr>
          </thead>
          <tbody>
            {filteredTraces.length === 0 && (
              <tr>
                <td colSpan={7} className="p-4 text-slate-500">
                  {traces.length === 0 ? "No inference traces yet." : "No traces match current route filter."}
                </td>
              </tr>
            )}
            {filteredTraces.map((row) => (
              <tr key={row.id} className="border-b border-slate-800/70">
                <td className="p-3 text-slate-400">{row.created_at ? new Date(row.created_at).toLocaleString() : "—"}</td>
                <td className="p-3 text-slate-200">{row.model_version || "—"}</td>
                <td className="p-3">{row.mapper_version || "—"}</td>
                <td className="p-3">{row.contract_version || "—"}</td>
                <td className="p-3">{row.decision || "—"}</td>
                <td className="p-3">{row?.trace_json?.route_source || "—"}</td>
                <td className="p-3">{row.processing_ms != null ? `${row.processing_ms}ms` : "—"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function Header({ email, bankLabel, onLogout }) {
  return (
    <div className="border-b border-slate-800/70 bg-gradient-to-br from-[#0b1224] via-[#0a1630] to-[#07101f] px-10 py-7 flex items-center justify-between gap-4">
      <div>
        <div className="flex items-center gap-3 mb-1.5">
          <div className="w-2.5 h-2.5 rounded-full bg-cyan-300 shadow-[0_0_12px] shadow-cyan-300/60 animate-pulse" />
          <span className="text-slate-400 text-[11px] tracking-[0.24em] uppercase">Admin Console</span>
        </div>
        <h1 className="m-0 text-2xl font-bold tracking-tight text-slate-100">BankAI Platform</h1>
        <p className="mt-1 text-slate-400 text-sm">
          {bankLabel ? (
            <>
              Active bank: <span className="text-cyan-200/90">{bankLabel}</span>
            </>
          ) : (
            <>Multi-tenant fraud + care operations.</>
          )}
        </p>
      </div>
      <div className="flex flex-col items-end gap-2 text-right">
        {email && <span className="text-xs text-slate-400">{email}</span>}
        {onLogout && (
          <button
            type="button"
            onClick={onLogout}
            className="px-3 py-1.5 rounded border border-slate-600 text-[10px] uppercase tracking-wider text-slate-200 hover:bg-slate-800/80"
          >
            Log out
          </button>
        )}
      </div>
    </div>
  );
}

function PlatformUsersPanel({ adminFetch }) {
  const [users, setUsers] = useState([]);
  const [err, setErr] = useState(null);
  const [loading, setLoading] = useState(true);
  const [email, setEmail] = useState("");
  const [tempPw, setTempPw] = useState("");
  const [role, setRole] = useState("viewer");
  const [tenantIds, setTenantIds] = useState("");

  async function load() {
    setLoading(true);
    setErr(null);
    try {
      const r = await adminFetch(`${API_BASE}/api/v1/platform/users`);
      const d = await r.json();
      if (!r.ok) throw new Error(typeof d.detail === "string" ? d.detail : "Failed to load users");
      setUsers(Array.isArray(d) ? d : []);
    } catch (e) {
      setErr(e.message);
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    load();
  }, []);

  async function createUser(e) {
    e.preventDefault();
    setErr(null);
    const tids = tenantIds
      .split(/[,\s]+/)
      .map((s) => s.trim())
      .filter(Boolean);
    const r = await adminFetch(`${API_BASE}/api/v1/platform/users`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        email: email.trim(),
        temporary_password: tempPw,
        role,
        tenant_ids: tids,
      }),
    });
    const d = await r.json().catch(() => ({}));
    if (!r.ok) {
      setErr(typeof d.detail === "string" ? d.detail : "Create failed");
      return;
    }
    setEmail("");
    setTempPw("");
    setTenantIds("");
    load();
  }

  return (
    <div className="max-w-3xl space-y-6">
      <p className="text-slate-400 text-[11px] tracking-wider uppercase">Platform users</p>
      {err && <p className="text-rose-400 text-sm">{err}</p>}
      <form onSubmit={createUser} className="rounded-xl border border-slate-800 bg-slate-900/50 p-4 space-y-3">
        <p className="text-xs text-slate-400">New user gets a temporary password; they must change it on first login.</p>
        <input
          type="email"
          required
          value={email}
          onChange={(e) => setEmail(e.target.value)}
          placeholder="Email"
          className="w-full rounded border border-slate-700 bg-slate-950 px-3 py-2 text-sm"
        />
        <input
          type="text"
          required
          value={tempPw}
          onChange={(e) => setTempPw(e.target.value)}
          placeholder="Temporary password (min 10 chars)"
          className="w-full rounded border border-slate-700 bg-slate-950 px-3 py-2 text-sm"
        />
        <select
          value={role}
          onChange={(e) => setRole(e.target.value)}
          className="w-full rounded border border-slate-700 bg-slate-950 px-3 py-2 text-sm"
        >
          <option value="viewer">viewer</option>
          <option value="editor">editor</option>
          <option value="owner">owner</option>
        </select>
        <input
          type="text"
          value={tenantIds}
          onChange={(e) => setTenantIds(e.target.value)}
          placeholder="Bank UUIDs (comma-separated) — leave empty only for global owner ops"
          className="w-full rounded border border-slate-700 bg-slate-950 px-3 py-2 text-sm"
        />
        <button
          type="submit"
          className="px-4 py-2 rounded bg-cyan-500/90 text-slate-900 text-xs font-semibold uppercase tracking-wider"
        >
          Create user
        </button>
      </form>
      {loading ? (
        <p className="text-slate-500 text-sm">Loading…</p>
      ) : (
        <ul className="space-y-2 text-sm">
          {users.map((u) => (
            <li key={u.id} className="rounded border border-slate-800 bg-slate-900/40 px-3 py-2">
              <span className="text-slate-200">{u.email}</span>{" "}
              <span className="text-slate-500">
                ({u.role}) {u.must_change_password ? "· must reset pwd" : ""}
              </span>
              <div className="text-[11px] text-slate-500 mt-1">Banks: {u.tenant_ids?.length ? u.tenant_ids.join(", ") : "—"}</div>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

export default function App() {
  const [activeView, setActiveView] = useState("home");
  const [accessToken, setAccessToken] = useState(() => localStorage.getItem("bankai_access_token") || "");
  const [legacyAdminToken, setLegacyAdminToken] = useState(() => localStorage.getItem("bankai_admin_token") || "");
  const [userMe, setUserMe] = useState(null);
  const [activeTenantId, setActiveTenantId] = useState(() => localStorage.getItem("bankai_active_tenant") || null);
  const [bankPicked, setBankPicked] = useState(false);
  const [loginEmail, setLoginEmail] = useState("");
  const [loginPassword, setLoginPassword] = useState("");
  const [loginErr, setLoginErr] = useState(null);
  const [showLegacy, setShowLegacy] = useState(false);
  const [pwdCurrent, setPwdCurrent] = useState("");
  const [pwdNew, setPwdNew] = useState("");
  const [pwdConfirm, setPwdConfirm] = useState("");
  const [pwdErr, setPwdErr] = useState(null);
  const [loginLoading, setLoginLoading] = useState(false);
  const [meLoading, setMeLoading] = useState(false);
  const [activeBankLogoSrc, setActiveBankLogoSrc] = useState(null);

  useEffect(() => {
    localStorage.setItem("bankai_access_token", accessToken || "");
  }, [accessToken]);
  useEffect(() => {
    localStorage.setItem("bankai_admin_token", legacyAdminToken || "");
  }, [legacyAdminToken]);
  useEffect(() => {
    if (activeTenantId) localStorage.setItem("bankai_active_tenant", activeTenantId);
    else localStorage.removeItem("bankai_active_tenant");
  }, [activeTenantId]);
  useEffect(() => {
    if (!accessToken) setBankPicked(false);
  }, [accessToken]);

  async function adminFetch(input, init = {}) {
    const headers = new Headers(init?.headers || {});
    const url = typeof input === "string" ? input : String(input?.url || "");
    const needsCreds =
      url.includes("/api/v1/admin/") ||
      url.includes("/api/v1/platform/") ||
      url.includes("/api/v1/auth/me") ||
      url.includes("/api/v1/fraud/");
    if (needsCreds) {
      if (accessToken.trim()) headers.set("Authorization", `Bearer ${accessToken.trim()}`);
      else if (legacyAdminToken.trim()) headers.set("X-Admin-Token", legacyAdminToken.trim());
    }
    if (url.includes("/api/v1/fraud/") && activeTenantId) {
      headers.set("X-Tenant-ID", activeTenantId);
    }
    return fetch(input, { ...init, headers });
  }

  async function refreshMe() {
    if (!accessToken) {
      setUserMe(null);
      setMeLoading(false);
      return;
    }
    setMeLoading(true);
    try {
      const r = await fetch(`${API_BASE}/api/v1/auth/me`, {
        headers: { Authorization: `Bearer ${accessToken}` },
      });
      const d = await r.json();
      if (!r.ok) {
        setUserMe(null);
        return;
      }
      setUserMe(d);
      if (!d.must_change_password && !d.needs_bank_selection && d.default_tenant_id) {
        setActiveTenantId(d.default_tenant_id);
      }
    } catch {
      setUserMe(null);
    } finally {
      setMeLoading(false);
    }
  }

  useEffect(() => {
    refreshMe();
  }, [accessToken]);

  const canUseApp = Boolean(accessToken || legacyAdminToken);
  const isOwnerJwt = userMe?.role === "owner" || userMe?.is_owner;
  const bankLabel =
    userMe?.banks?.find((b) => b.id === activeTenantId)?.name ||
    (activeTenantId ? activeTenantId.slice(0, 8) + "…" : null);
  const activeBankName = userMe?.banks?.find((b) => b.id === activeTenantId)?.name || null;
  const activeBankLogoUrl = userMe?.banks?.find((b) => b.id === activeTenantId)?.logo_url
    ? `${API_BASE}${userMe?.banks?.find((b) => b.id === activeTenantId)?.logo_url}`
    : null;

  async function uploadActiveBankLogo(file, opts = {}) {
    if (!activeTenantId) return;
    if (opts?.remove) {
      const res = await adminFetch(`${API_BASE}/api/v1/admin/tenants/${encodeURIComponent(activeTenantId)}/logo`, {
        method: "DELETE",
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) {
        throw new Error(typeof data?.detail === "string" ? data.detail : "Failed to remove logo");
      }
      await refreshMe();
      return;
    }
    if (!file) return;
    const fd = new FormData();
    fd.append("file", file);
    const res = await adminFetch(`${API_BASE}/api/v1/admin/tenants/${encodeURIComponent(activeTenantId)}/logo`, {
      method: "POST",
      body: fd,
    });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) {
      throw new Error(typeof data?.detail === "string" ? data.detail : "Failed to upload logo");
    }
    await refreshMe();
  }

  useEffect(() => {
    let revokedUrl = null;
    async function loadLogo() {
      if (!activeBankLogoUrl) {
        setActiveBankLogoSrc(null);
        return;
      }
      try {
        const res = await adminFetch(activeBankLogoUrl);
        if (!res.ok) {
          setActiveBankLogoSrc(null);
          return;
        }
        const blob = await res.blob();
        const objUrl = URL.createObjectURL(blob);
        revokedUrl = objUrl;
        setActiveBankLogoSrc(objUrl);
      } catch {
        setActiveBankLogoSrc(null);
      }
    }
    loadLogo();
    return () => {
      if (revokedUrl) URL.revokeObjectURL(revokedUrl);
    };
  }, [activeBankLogoUrl, accessToken, legacyAdminToken]);

  async function handleLogin(e) {
    e.preventDefault();
    setLoginErr(null);
    setLoginLoading(true);
    try {
      const r = await fetch(`${API_BASE}/api/v1/auth/login`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ email: loginEmail.trim(), password: loginPassword }),
      });
      const d = await r.json().catch(() => ({}));
      if (!r.ok) {
        setLoginErr(typeof d.detail === "string" ? d.detail : "Login failed");
        return;
      }
      setAccessToken(d.access_token);
      setLoginPassword("");
    } finally {
      setLoginLoading(false);
    }
  }

  function logout() {
    setAccessToken("");
    setLegacyAdminToken("");
    setUserMe(null);
    setActiveTenantId(null);
    setBankPicked(false);
    localStorage.removeItem("bankai_active_tenant");
  }

  async function submitPasswordChange(e) {
    e.preventDefault();
    setPwdErr(null);
    if (pwdNew.length < 10) {
      setPwdErr("Min 10 characters");
      return;
    }
    if (pwdNew !== pwdConfirm) {
      setPwdErr("Passwords do not match");
      return;
    }
    const r = await fetch(`${API_BASE}/api/v1/auth/change-password`, {
      method: "POST",
      headers: {
        Authorization: `Bearer ${accessToken}`,
        "Content-Type": "application/json",
      },
      body: JSON.stringify({ current_password: pwdCurrent, new_password: pwdNew }),
    });
    const d = await r.json().catch(() => ({}));
    if (!r.ok) {
      setPwdErr(typeof d.detail === "string" ? d.detail : "Failed");
      return;
    }
    setPwdCurrent("");
    setPwdNew("");
    setPwdConfirm("");
    await refreshMe();
  }

  const showPwdModal = Boolean(accessToken && userMe?.must_change_password);
  const showBankModal = Boolean(
    accessToken &&
      userMe &&
      !userMe.must_change_password &&
      userMe.needs_bank_selection &&
      !bankPicked &&
      !activeTenantId,
  );
  const showAuthLoading = Boolean(accessToken && meLoading);

  return (
    <div className="h-screen overflow-hidden flex flex-col text-slate-100 bg-[radial-gradient(1200px_800px_at_20%_0%,rgba(56,189,248,0.18),transparent_60%),radial-gradient(900px_700px_at_90%_20%,rgba(34,197,94,0.10),transparent_55%),linear-gradient(180deg,#050812_0%,#060a14_55%,#04060e_100%)]">
      {!canUseApp && (
        <div className="flex-1 flex items-center justify-center p-8">
          <div className="w-full max-w-md rounded-2xl border border-slate-800 bg-slate-900/80 p-8 shadow-xl">
            <h2 className="text-lg font-semibold text-slate-100 mb-1">Sign in</h2>
            <p className="text-xs text-slate-500 mb-6">Platform admin (JWT). Use bootstrap credentials from backend .env.</p>
            <form onSubmit={handleLogin} className="space-y-3">
              <input
                type="email"
                value={loginEmail}
                onChange={(e) => setLoginEmail(e.target.value)}
                placeholder="Email"
                required
                className="w-full rounded border border-slate-700 bg-slate-950 px-3 py-2 text-sm"
              />
              <input
                type="password"
                value={loginPassword}
                onChange={(e) => setLoginPassword(e.target.value)}
                placeholder="Password"
                required
                className="w-full rounded border border-slate-700 bg-slate-950 px-3 py-2 text-sm"
              />
              {loginErr && <p className="text-rose-400 text-xs">{loginErr}</p>}
              <button
                type="submit"
                disabled={loginLoading}
                className="w-full py-2.5 rounded bg-cyan-500 text-slate-900 text-sm font-semibold disabled:opacity-70 disabled:cursor-not-allowed flex items-center justify-center gap-2"
              >
                {loginLoading ? (
                  <>
                    <span className="inline-block h-4 w-4 rounded-full border-2 border-slate-900 border-t-transparent animate-spin" />
                    Signing in...
                  </>
                ) : (
                  "Continue"
                )}
              </button>
            </form>
            <button
              type="button"
              className="mt-4 text-[11px] text-slate-500 underline"
              onClick={() => setShowLegacy((v) => !v)}
            >
              Legacy X-Admin-Token (break-glass)
            </button>
            {showLegacy && (
              <div className="mt-3 space-y-2">
                <input
                  type="password"
                  value={legacyAdminToken}
                  onChange={(e) => setLegacyAdminToken(e.target.value)}
                  placeholder="X-Admin-Token"
                  className="w-full rounded border border-slate-700 bg-slate-950 px-3 py-2 text-xs"
                />
                <p className="text-[10px] text-slate-600">No bank picker / password flows for legacy tokens.</p>
              </div>
            )}
          </div>
        </div>
      )}

      {showAuthLoading && (
        <div className="flex-1 flex items-center justify-center p-8">
          <div className="rounded-xl border border-slate-800 bg-slate-900/80 px-5 py-4 text-sm text-slate-300 flex items-center gap-3">
            <span className="inline-block h-4 w-4 rounded-full border-2 border-cyan-300 border-t-transparent animate-spin" />
            Loading your account...
          </div>
        </div>
      )}

      {showBankModal && (
        <div className="flex-1 flex items-center justify-center p-4">
          <div className="w-full max-w-lg rounded-xl border border-slate-700 bg-slate-900 p-6 shadow-2xl max-h-[80vh] overflow-y-auto">
            <h3 className="text-slate-100 font-semibold mb-1">Choose bank</h3>
            <p className="text-xs text-slate-500 mb-4">
              {userMe?.is_owner ? "All banks on the platform." : "Banks assigned to your account."}
            </p>
            <ul className="space-y-2">
              {(userMe?.banks || []).map((b) => (
                <li key={b.id}>
                  <button
                    type="button"
                    onClick={() => {
                      setActiveTenantId(b.id);
                      setBankPicked(true);
                    }}
                    className="w-full text-left rounded-lg border border-slate-700 bg-slate-950/80 px-4 py-3 text-sm hover:border-cyan-500/50"
                  >
                    <span className="text-slate-100 font-medium">{b.name}</span>
                    <span className="text-slate-500 text-xs ml-2">{b.country_code}</span>
                    <div className="text-[10px] text-slate-600 font-mono mt-1">{b.id}</div>
                  </button>
                </li>
              ))}
            </ul>
            {!userMe?.banks?.length && <p className="text-amber-400 text-sm">No banks available. Onboard a bank first (owner).</p>}
          </div>
        </div>
      )}

      {canUseApp && !showAuthLoading && !showBankModal && (
        <>
          <Header
            email={userMe?.email || (legacyAdminToken ? "legacy token" : "")}
            bankLabel={bankLabel}
            onLogout={logout}
          />

          {showPwdModal && (
            <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 p-4">
              <div className="w-full max-w-md rounded-xl border border-slate-700 bg-slate-900 p-6 shadow-2xl">
                <h3 className="text-slate-100 font-semibold mb-1">Set a new password</h3>
                <p className="text-xs text-slate-500 mb-4">Your account used a temporary password.</p>
                <form onSubmit={submitPasswordChange} className="space-y-3">
                  <input
                    type="password"
                    value={pwdCurrent}
                    onChange={(e) => setPwdCurrent(e.target.value)}
                    placeholder="Current password"
                    required
                    className="w-full rounded border border-slate-700 bg-slate-950 px-3 py-2 text-sm"
                  />
                  <input
                    type="password"
                    value={pwdNew}
                    onChange={(e) => setPwdNew(e.target.value)}
                    placeholder="New password (10+ chars)"
                    required
                    className="w-full rounded border border-slate-700 bg-slate-950 px-3 py-2 text-sm"
                  />
                  <input
                    type="password"
                    value={pwdConfirm}
                    onChange={(e) => setPwdConfirm(e.target.value)}
                    placeholder="Confirm new password"
                    required
                    className="w-full rounded border border-slate-700 bg-slate-950 px-3 py-2 text-sm"
                  />
                  {pwdErr && <p className="text-rose-400 text-xs">{pwdErr}</p>}
                  <button type="submit" className="w-full py-2 rounded bg-cyan-500 text-slate-900 text-sm font-semibold">
                    Update password
                  </button>
                </form>
              </div>
            </div>
          )}

          <div className="flex flex-1 min-h-0 bg-slate-950/60">
            <PlatformSidebar
              activeView={activeView}
              onChange={setActiveView}
              isOwner={Boolean(legacyAdminToken) || isOwnerJwt}
              bankLogoUrl={activeBankLogoSrc}
              canManageBranding={Boolean(legacyAdminToken) || userMe?.role === "owner" || userMe?.role === "editor"}
              hasActiveBank={Boolean(activeTenantId)}
              onUploadLogo={uploadActiveBankLogo}
            />
            <main className="flex-1 min-w-0 overflow-auto py-8 px-8">
              {legacyAdminToken && !accessToken && (
                <div className="mb-4 rounded-lg border border-amber-900/50 bg-amber-950/20 p-3 text-xs text-amber-200/90">
                  Using legacy <code className="text-amber-100">X-Admin-Token</code>. Prefer JWT login for audit trails and bank scoping.
                </div>
              )}
              {accessToken && userMe?.is_owner && !activeTenantId && !showBankModal && (
                <div className="mb-4 rounded-lg border border-cyan-900/40 bg-cyan-950/20 p-3 text-xs text-cyan-100/90">
                  Select a bank from the login chooser to continue.
                </div>
              )}
              {activeView === "home" && (
                <TenantHomePanel
                  adminFetch={adminFetch}
                  platformTenantId={activeTenantId || undefined}
                  platformTenantName={activeBankName || undefined}
                />
              )}
              {activeView === "onboard" && <OnboardTab adminFetch={adminFetch} />}
              {activeView === "care" && (
                <CareMetricsPanel adminFetch={adminFetch} platformTenantId={activeTenantId} />
              )}
              {activeView === "ops-cutover" && <OpsCutoverPanel adminFetch={adminFetch} />}
              {activeView === "observability" && (
                <TenantObservabilityPanel adminFetch={adminFetch} platformTenantId={activeTenantId} />
              )}
              {activeView === "policy" && (
                <FraudPolicyPanel
                  adminFetch={adminFetch}
                  platformTenantId={activeTenantId || undefined}
                  platformTenantName={activeBankName || undefined}
                />
              )}
              {activeView === "reports" && (
                <TenantReportsPanel
                  adminFetch={adminFetch}
                  platformTenantId={activeTenantId || undefined}
                  platformTenantName={activeBankName || undefined}
                  canManagePresets={Boolean(legacyAdminToken) || userMe?.role === "owner" || userMe?.role === "editor"}
                />
              )}
              {activeView === "fraud-train" && (
                <div>
                  <p className="text-slate-400 text-[11px] tracking-wider mb-4 uppercase">
                    Fraud model training
                  </p>
                  <div className="rounded-xl border border-cyan-900/40 bg-slate-900/40 p-5 mb-4 ring-1 ring-cyan-500/10">
                    <ManualModelTrainingPanel adminFetch={adminFetch} platformTenantId={activeTenantId || undefined} />
                  </div>
                  <div className="rounded-xl border border-amber-900/40 bg-slate-900/40 p-5 ring-1 ring-amber-500/10">
                    <TriggerFraudTrain adminFetch={adminFetch} />
                  </div>
                </div>
              )}
              {activeView === "fraud-ops" && (
                <div>
                  <p className="text-slate-400 text-[11px] tracking-wider mb-4 uppercase">
                    Fraud ops — alerts, review queue, network &amp; analytics
                  </p>
                  <FraudTab adminFetch={adminFetch} platformTenantId={activeTenantId || undefined} />
                </div>
              )}
              {activeView === "model-registry" && (
                <ModelRegistryPanel
                  adminFetch={adminFetch}
                  platformTenantId={activeTenantId || undefined}
                />
              )}
              {activeView === "team" && <PlatformUsersPanel adminFetch={adminFetch} />}
            </main>
          </div>
        </>
      )}
    </div>
  );
}
