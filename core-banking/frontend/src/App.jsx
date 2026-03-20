import { useState, useEffect } from "react";

const API = import.meta.env.VITE_CORE_BANKING_API || "http://127.0.0.1:8001";
const TRANSACTIONS_PAGE_SIZE = 20;

function TransactionsTable({ transactions, loading, onSelectTransaction }) {
  return (
    <div className="rounded-xl border border-slate-600 bg-slate-800/50 overflow-hidden">
      {loading ? (
        <div className="px-6 py-12 text-slate-400 text-sm">Loading…</div>
      ) : (
        <table className="w-full text-left">
          <thead>
            <tr className="border-b border-slate-600">
              <th className="px-6 py-3 text-xs font-medium text-slate-400 uppercase tracking-wider">Transaction ID</th>
              <th className="px-6 py-3 text-xs font-medium text-slate-400 uppercase tracking-wider">Account ID</th>
              <th className="px-6 py-3 text-xs font-medium text-slate-400 uppercase tracking-wider">Amount</th>
              <th className="px-6 py-3 text-xs font-medium text-slate-400 uppercase tracking-wider">Channel</th>
              <th className="px-6 py-3 text-xs font-medium text-slate-400 uppercase tracking-wider">Status</th>
              <th className="px-6 py-3 text-xs font-medium text-slate-400 uppercase tracking-wider">Created at</th>
              <th className="px-6 py-3 text-xs font-medium text-slate-400 uppercase tracking-wider">Decision</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-700">
            {transactions.length === 0 && !loading && (
              <tr>
                <td colSpan={7} className="px-6 py-8 text-slate-500 text-sm">No scored transactions yet. Run transfers through the app to see fraud decisions here.</td>
              </tr>
            )}
            {transactions.map((t) => (
              <tr
                key={t.transaction_id}
                className="hover:bg-slate-800/80 cursor-pointer"
                onClick={() => onSelectTransaction(t.transaction_id)}
              >
                <td className="px-6 py-4 text-slate-300 text-sm font-mono">{t.transaction_id}</td>
                <td className="px-6 py-4 text-slate-300 text-sm">{t.account_id ?? "—"}</td>
                <td className="px-6 py-4 text-slate-200">{Number(t.amount).toLocaleString()} {t.currency ?? ""}</td>
                <td className="px-6 py-4 text-slate-400 text-sm">{t.channel ?? "—"}</td>
                <td className="px-6 py-4 text-slate-400 text-sm">{t.status ?? "—"}</td>
                <td className="px-6 py-4 text-slate-400 text-sm">{t.created_at ? new Date(t.created_at).toLocaleString() : "—"}</td>
                <td className="px-6 py-4">
                  <span className={`text-sm font-medium ${
                    t.decision === "APPROVE" ? "text-emerald-400" :
                    t.decision === "LIMITED_APPROVAL" ? "text-amber-400" :
                    t.decision === "REQUEST_OTP" ? "text-orange-400" :
                    t.decision === "BLOCK" ? "text-red-400" : "text-slate-400"
                  }`}>
                    {t.decision ?? "—"}
                  </span>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}

function TransactionDetail({ transactionId, onBack }) {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      setLoading(true);
      setError(null);
      try {
        const res = await fetch(`${API}/api/admin/fraud/transactions/${encodeURIComponent(transactionId)}/detail`);
        if (!res.ok) throw new Error(await res.text());
        const json = await res.json();
        if (!cancelled) setData(json);
      } catch (e) {
        if (!cancelled) setError(e.message);
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => { cancelled = true; };
  }, [transactionId]);

  if (loading) {
    return (
      <div>
        <button type="button" onClick={onBack} className="text-slate-400 hover:text-slate-200 text-sm mb-6">← Back to transactions</button>
        <div className="text-slate-400">Loading…</div>
      </div>
    );
  }
  if (error || !data) {
    return (
      <div>
        <button type="button" onClick={onBack} className="text-slate-400 hover:text-slate-200 text-sm mb-6">← Back to transactions</button>
        <div className="text-red-400">{error || "Not found"}</div>
      </div>
    );
  }

  return (
    <div>
      <button type="button" onClick={onBack} className="text-slate-400 hover:text-slate-200 text-sm mb-6">← Back to transactions</button>
      <div className="mb-6">
        <h1 className="text-xl font-semibold text-slate-100">Transaction detail</h1>
        <p className="text-slate-500 text-sm mt-1">ID: {data.external_tx_id || data.transaction_id} · Account: {data.account_id}</p>
      </div>
      <div className="rounded-xl border border-slate-600 bg-slate-800/50 p-6 space-y-6">
        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          <div><span className="text-slate-500 text-sm">Amount</span><p className="text-slate-200">{Number(data.amount).toLocaleString()} {data.currency}</p></div>
          <div><span className="text-slate-500 text-sm">Channel</span><p className="text-slate-200">{data.channel ?? "—"}</p></div>
          <div><span className="text-slate-500 text-sm">Status</span><p className="text-slate-200">{data.status ?? "—"}</p></div>
          <div><span className="text-slate-500 text-sm">Timestamp</span><p className="text-slate-200">{data.tx_timestamp ? new Date(data.tx_timestamp).toLocaleString() : "—"}</p></div>
        </div>
        <div className="border-t border-slate-600 pt-6">
          <h2 className="text-slate-300 font-medium mb-2">Fraud model result</h2>
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            <div>
              <span className="text-slate-500 text-sm">Decision</span>
              <p className={`font-medium ${
                data.decision === "APPROVE" ? "text-emerald-400" :
                data.decision === "LIMITED_APPROVAL" ? "text-amber-400" :
                data.decision === "REQUEST_OTP" ? "text-orange-400" :
                data.decision === "BLOCK" ? "text-red-400" : "text-slate-200"
              }`}>{data.decision ?? "—"}</p>
            </div>
            <div><span className="text-slate-500 text-sm">Fraud score</span><p className="text-slate-200">{data.fraud_score != null ? Number(data.fraud_score).toFixed(4) : "—"}</p></div>
            <div><span className="text-slate-500 text-sm">Confidence</span><p className="text-slate-200">{data.confidence ?? "—"}</p></div>
            <div><span className="text-slate-500 text-sm">Processing time</span><p className="text-slate-200">{data.processing_time_ms != null ? `${data.processing_time_ms} ms` : "—"}</p></div>
          </div>
        </div>
        {data.reasons && data.reasons.length > 0 && (
          <div className="border-t border-slate-600 pt-6">
            <h2 className="text-slate-300 font-medium mb-2">Reasons</h2>
            <ul className="list-disc list-inside text-slate-300 text-sm space-y-1">
              {data.reasons.map((r, i) => (
                <li key={i}>{r}</li>
              ))}
            </ul>
          </div>
        )}
        <div className="border-t border-slate-600 pt-6 grid grid-cols-1 md:grid-cols-3 gap-4">
          <div><span className="text-slate-500 text-sm">LGBM score</span><p className="text-slate-200">{data.lgbm_score != null ? Number(data.lgbm_score).toFixed(4) : "—"}</p></div>
          <div><span className="text-slate-500 text-sm">Anomaly score</span><p className="text-slate-200">{data.anomaly_score != null ? Number(data.anomaly_score).toFixed(4) : "—"}</p></div>
          <div><span className="text-slate-500 text-sm">Rule score</span><p className="text-slate-200">{data.rule_score != null ? Number(data.rule_score).toFixed(4) : "—"}</p></div>
        </div>
      </div>
    </div>
  );
}

const NAV = [
  { id: "transactions", label: "Transactions" },
  { id: "customers", label: "Customers" },
  { id: "manage", label: "Add customer" },
];

function AdminSidebar({ currentView, onNavigate }) {
  return (
    <aside className="w-56 shrink-0 border-r border-slate-700 bg-slate-900/80 flex flex-col">
      <div className="p-4 border-b border-slate-700">
        <h1 className="text-sm font-semibold text-slate-100">Core Banking</h1>
        <p className="text-xs text-slate-500 mt-0.5">Admin</p>
      </div>
      <nav className="p-2 flex-1">
        {NAV.map(({ id, label }) => (
          <button
            key={id}
            type="button"
            onClick={() => onNavigate(id)}
            className={`w-full text-left px-3 py-2.5 rounded-lg text-sm font-medium transition-colors ${
              currentView === id ? "bg-amber-600/90 text-slate-900" : "text-slate-300 hover:bg-slate-800 hover:text-slate-100"
            }`}
          >
            {label}
          </button>
        ))}
      </nav>
    </aside>
  );
}

function TransactionsScreen({ transactions, loading, error, onSelectTransaction, accountFilter, setAccountFilter, onRefresh, page, setPage, pageSize }) {
  return (
    <>
      <h2 className="text-lg font-semibold text-slate-100 mb-1">Transactions</h2>
      <p className="text-slate-400 text-sm mb-2">Scored transactions. Click a row for full fraud detail.</p>
      <div className="mb-4 flex flex-wrap items-center gap-2">
        <label className="text-slate-500 text-sm">Filter by account:</label>
        <input
          type="text"
          placeholder="Account ID (optional)"
          value={accountFilter}
          onChange={(e) => setAccountFilter(e.target.value)}
          className="rounded border border-slate-600 bg-slate-800 px-3 py-1.5 text-slate-200 text-sm w-48"
        />
        <button type="button" onClick={onRefresh} className="rounded border border-slate-600 bg-slate-700 px-3 py-1.5 text-slate-200 text-sm hover:bg-slate-600">Apply</button>
      </div>
      {error && (
        <div className="mb-4 rounded-lg border border-amber-500/50 bg-amber-500/10 px-4 py-3 text-amber-200 text-sm">
          {error}
          <span className="block mt-1 text-slate-400">Set BANKAI_API_URL and BANKAI_API_KEY in core-banking/backend/.env and ensure BankAI (port 8000) is running.</span>
        </div>
      )}
      <TransactionsTable
        transactions={transactions.slice((page - 1) * pageSize, page * pageSize)}
        loading={loading}
        onSelectTransaction={onSelectTransaction}
      />
      {!loading && transactions.length > 0 && (
        <div className="mt-4 flex items-center justify-between text-sm">
          <span className="text-slate-500">Page {page} of {Math.max(1, Math.ceil(transactions.length / pageSize))} ({transactions.length} total)</span>
          <div className="flex gap-2">
            <button type="button" disabled={page <= 1} onClick={() => setPage((p) => p - 1)} className="rounded border border-slate-600 bg-slate-800 px-3 py-1.5 text-slate-200 disabled:opacity-50 disabled:cursor-not-allowed hover:bg-slate-700">Prev</button>
            <button type="button" disabled={page >= Math.ceil(transactions.length / pageSize)} onClick={() => setPage((p) => p + 1)} className="rounded border border-slate-600 bg-slate-800 px-3 py-1.5 text-slate-200 disabled:opacity-50 disabled:cursor-not-allowed hover:bg-slate-700">Next</button>
          </div>
        </div>
      )}
    </>
  );
}

function CustomersScreen({ customers, loading, onSelectCustomer }) {
  return (
    <>
      <h2 className="text-lg font-semibold text-slate-100 mb-1">Customers</h2>
      <p className="text-slate-400 text-sm mb-6">Click a row to see transactions and manage fraud labels.</p>
      <div className="rounded-xl border border-slate-600 bg-slate-800/50 overflow-hidden">
        {loading ? (
          <div className="px-6 py-12 text-slate-400 text-sm">Loading…</div>
        ) : (
          <table className="w-full text-left">
            <thead>
              <tr className="border-b border-slate-600">
                <th className="px-6 py-3 text-xs font-medium text-slate-400 uppercase tracking-wider">Customer</th>
                <th className="px-6 py-3 text-xs font-medium text-slate-400 uppercase tracking-wider">Email</th>
                <th className="px-6 py-3 text-xs font-medium text-slate-400 uppercase tracking-wider">Accounts</th>
                <th className="px-6 py-3 text-xs font-medium text-slate-400 uppercase tracking-wider">Total balance</th>
                <th className="px-6 py-3 text-xs font-medium text-slate-400 uppercase tracking-wider">To account</th>
                <th className="px-6 py-3 text-xs font-medium text-slate-400 uppercase tracking-wider">Action</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-700">
              {customers.length === 0 && !loading && (
                <tr><td colSpan={6} className="px-6 py-8 text-slate-500 text-sm">No customers yet. Add a customer or use the mobile app to register.</td></tr>
              )}
              {customers.map((c) => (
                <tr key={c.username} className="hover:bg-slate-800/80 cursor-pointer" onClick={() => onSelectCustomer(c.username)}>
                  <td className="px-6 py-4">
                    <p className="text-slate-200 font-medium">{c.full_name || c.username}</p>
                    <p className="text-slate-500 text-xs">{c.username}</p>
                  </td>
                  <td className="px-6 py-4 text-slate-300 text-sm">{c.email || "—"}</td>
                  <td className="px-6 py-4 text-slate-300 text-sm">{c.account_count}</td>
                  <td className="px-6 py-4 text-slate-200">{Number(c.total_balance).toLocaleString()} USD</td>
                  <td className="px-6 py-4 text-slate-400 text-sm">{c.last_transfer_to ? `To: ${c.last_transfer_to}` : "—"}</td>
                  <td className="px-6 py-4">
                    <button type="button" onClick={(e) => { e.stopPropagation(); onSelectCustomer(c.username); }} className="text-amber-400 hover:text-amber-300 text-sm">View</button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </>
  );
}

function CustomerDetail({ username, onBack, refresh }) {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [updating, setUpdating] = useState(null);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      setLoading(true);
      try {
        const res = await fetch(`${API}/api/admin/customers/${encodeURIComponent(username)}`);
        if (!res.ok) throw new Error(await res.text());
        const json = await res.json();
        if (!cancelled) setData(json);
      } catch (e) {
        if (!cancelled) setData(null);
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => { cancelled = true; };
  }, [username, refresh]);

  const setFraudLabel = async (transactionId, fraudLabel) => {
    setUpdating(transactionId);
    try {
      const res = await fetch(`${API}/api/admin/transactions/${encodeURIComponent(transactionId)}/fraud-label`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ fraud_label: fraudLabel }),
      });
      if (!res.ok) throw new Error(await res.text());
      setData((prev) => ({
        ...prev,
        transactions: prev.transactions.map((t) =>
          t.transaction_id === transactionId ? { ...t, fraud_label: fraudLabel } : t
        ),
      }));
    } finally {
      setUpdating(null);
    }
  };

  if (loading || !data) {
    return (
      <div>
        <button type="button" onClick={onBack} className="text-slate-400 hover:text-slate-200 text-sm mb-6">← Back to customers</button>
        <div className="text-slate-400">Loading…</div>
      </div>
    );
  }

  return (
    <div>
      <button type="button" onClick={onBack} className="text-slate-400 hover:text-slate-200 text-sm mb-6">← Back to customers</button>
      <div className="mb-8">
        <h1 className="text-xl font-semibold text-slate-100">{data.full_name || data.username}</h1>
        <p className="text-slate-500 text-sm">{data.username} · {data.email || "—"} · {data.country || "—"}</p>
      </div>
      <div className="rounded-xl border border-slate-600 bg-slate-800/50 p-6 mb-8">
        <h2 className="text-slate-300 text-sm font-medium mb-4">Accounts</h2>
        <div className="flex flex-wrap gap-4">
          {data.accounts.map((a) => (
            <div key={a.account_id} className="rounded-lg border border-slate-600 bg-slate-900/50 px-4 py-3 min-w-[200px]">
              <p className="text-slate-400 text-xs">{a.name || a.account_id}</p>
              <p className="text-slate-200 font-medium">{Number(a.balance).toLocaleString()} {a.currency}</p>
              <p className="text-slate-500 text-xs">{a.account_id}</p>
            </div>
          ))}
        </div>
      </div>
      <div className="rounded-xl border border-slate-600 bg-slate-800/50 overflow-hidden">
        <h2 className="px-6 py-3 text-slate-300 text-sm font-medium border-b border-slate-600">Transactions</h2>
        <div className="overflow-x-auto">
          <table className="w-full text-left">
            <thead>
              <tr className="border-b border-slate-600">
                <th className="px-6 py-3 text-xs font-medium text-slate-400 uppercase">Date</th>
                <th className="px-6 py-3 text-xs font-medium text-slate-400 uppercase">Description</th>
                <th className="px-6 py-3 text-xs font-medium text-slate-400 uppercase">Account</th>
                <th className="px-6 py-3 text-xs font-medium text-slate-400 uppercase">Amount</th>
                <th className="px-6 py-3 text-xs font-medium text-slate-400 uppercase">Type</th>
                <th className="px-6 py-3 text-xs font-medium text-slate-400 uppercase">Model Decision</th>
                <th className="px-6 py-3 text-xs font-medium text-slate-400 uppercase">Fraud label</th>
                <th className="px-6 py-3 text-xs font-medium text-slate-400 uppercase">Actions</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-700">
              {data.transactions.length === 0 && (
                <tr>
                  <td colSpan={8} className="px-6 py-8 text-slate-500 text-sm">No transactions.</td>
                </tr>
              )}
              {data.transactions.map((t) => (
                <tr key={`${t.transaction_id}-${t.account_id}-${t.at}`} className="hover:bg-slate-800/50">
                  <td className="px-6 py-3 text-slate-300 text-sm">{t.at ? new Date(t.at).toLocaleString() : "—"}</td>
                  <td className="px-6 py-3 text-slate-200 text-sm">{t.merchant || "—"}</td>
                  <td className="px-6 py-3 text-slate-400 text-xs">{t.account_id}</td>
                  <td className="px-6 py-3">
                    <span className={t.amount < 0 ? "text-red-400" : "text-emerald-400"}>
                      {t.amount < 0 ? "" : "+"}{t.amount} {t.currency}
                    </span>
                  </td>
                  <td className="px-6 py-3 text-slate-400 text-xs">{t.type || "payment"}</td>
                  <td className="px-6 py-3">
                    <span className={`text-sm font-medium ${
                      t.decision === "APPROVE" ? "text-emerald-400" :
                      t.decision === "LIMITED_APPROVAL" ? "text-amber-400" :
                      t.decision === "REQUEST_OTP" ? "text-orange-400" :
                      t.decision === "BLOCK" ? "text-red-400" : "text-slate-500"
                    }`}>
                      {t.decision ?? "—"}
                    </span>
                  </td>
                  <td className="px-6 py-3">
                    <span className={
                      t.fraud_label === "fraud" ? "text-red-400 font-medium" :
                      t.fraud_label === "not_fraud" ? "text-emerald-400" : "text-slate-500"
                    }>
                      {t.fraud_label === "fraud" ? "Fraud" : t.fraud_label === "not_fraud" ? "Not fraud" : "—"}
                    </span>
                  </td>
                  <td className="px-6 py-3">
                    {updating === t.transaction_id ? (
                      <span className="text-slate-500 text-xs">Updating…</span>
                    ) : (
                      <span className="flex items-center gap-2">
                        <button
                          type="button"
                          onClick={() => setFraudLabel(t.transaction_id, "fraud")}
                          className="text-xs px-2 py-1 rounded border border-red-500/50 text-red-400 hover:bg-red-500/10"
                        >
                          Mark fraud
                        </button>
                        <button
                          type="button"
                          onClick={() => setFraudLabel(t.transaction_id, "not_fraud")}
                          className="text-xs px-2 py-1 rounded border border-emerald-500/50 text-emerald-400 hover:bg-emerald-500/10"
                        >
                          Not fraud
                        </button>
                      </span>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}

function ManageUsers({ onBack, onCreated }) {
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [fullName, setFullName] = useState("");
  const [email, setEmail] = useState("");
  const [phone, setPhone] = useState("");
  const [country, setCountry] = useState("GH");
  const [loading, setLoading] = useState(false);
  const [message, setMessage] = useState(null);

  const handleSubmit = async (e) => {
    e.preventDefault();
    if (!username.trim() || !password.trim() || !fullName.trim()) {
      setMessage({ error: "Username, password and full name required" });
      return;
    }
    setLoading(true);
    setMessage(null);
    try {
      const res = await fetch(`${API}/api/auth/register`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          username: username.trim(),
          password,
          full_name: fullName.trim(),
          email: email.trim() || "user@example.com",
          phone: phone.trim(),
          country: country.trim() || "GH",
        }),
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(data.detail || res.statusText);
      setMessage({ ok: true, text: `Created ${data.username} with account ${data.account_id}` });
      setUsername("");
      setPassword("");
      setFullName("");
      setEmail("");
      setPhone("");
      onCreated();
    } catch (err) {
      setMessage({ error: err.message });
    } finally {
      setLoading(false);
    }
  };

  return (
    <div>
      <button type="button" onClick={onBack} className="text-slate-400 hover:text-slate-200 text-sm mb-6">← Back</button>
      <h1 className="text-xl font-semibold text-slate-100 mb-6">Add customer</h1>
      <form onSubmit={handleSubmit} className="max-w-md space-y-4">
        <div>
          <label className="block text-xs text-slate-500 uppercase tracking-wider mb-1.5">Username</label>
          <input type="text" value={username} onChange={(e) => setUsername(e.target.value)} required className="w-full rounded-lg border border-slate-600 bg-slate-900 px-4 py-2.5 text-slate-200" />
        </div>
        <div>
          <label className="block text-xs text-slate-500 uppercase tracking-wider mb-1.5">Password</label>
          <input type="password" value={password} onChange={(e) => setPassword(e.target.value)} required className="w-full rounded-lg border border-slate-600 bg-slate-900 px-4 py-2.5 text-slate-200" />
        </div>
        <div>
          <label className="block text-xs text-slate-500 uppercase tracking-wider mb-1.5">Full name</label>
          <input type="text" value={fullName} onChange={(e) => setFullName(e.target.value)} required className="w-full rounded-lg border border-slate-600 bg-slate-900 px-4 py-2.5 text-slate-200" />
        </div>
        <div>
          <label className="block text-xs text-slate-500 uppercase tracking-wider mb-1.5">Email</label>
          <input type="email" value={email} onChange={(e) => setEmail(e.target.value)} className="w-full rounded-lg border border-slate-600 bg-slate-900 px-4 py-2.5 text-slate-200" />
        </div>
        <div>
          <label className="block text-xs text-slate-500 uppercase tracking-wider mb-1.5">Phone</label>
          <input type="text" value={phone} onChange={(e) => setPhone(e.target.value)} className="w-full rounded-lg border border-slate-600 bg-slate-900 px-4 py-2.5 text-slate-200" />
        </div>
        <div>
          <label className="block text-xs text-slate-500 uppercase tracking-wider mb-1.5">Country</label>
          <input type="text" value={country} onChange={(e) => setCountry(e.target.value)} className="w-full rounded-lg border border-slate-600 bg-slate-900 px-4 py-2.5 text-slate-200" />
        </div>
        {message && (
          <div className={`rounded-lg border px-4 py-3 text-sm ${message.error ? "border-red-500/50 bg-red-500/10 text-red-200" : "border-emerald-500/50 bg-emerald-500/10 text-emerald-200"}`}>
            {message.error || message.text}
          </div>
        )}
        <button type="submit" disabled={loading} className="w-full py-2.5 rounded-lg bg-amber-600 hover:bg-amber-500 disabled:opacity-50 text-slate-900 font-medium">
          {loading ? "Creating…" : "Create customer"}
        </button>
      </form>
    </div>
  );
}

export default function App() {
  const [view, setView] = useState("transactions");
  const [selectedUsername, setSelectedUsername] = useState(null);
  const [selectedTransactionId, setSelectedTransactionId] = useState(null);
  const [customers, setCustomers] = useState([]);
  const [customersLoading, setCustomersLoading] = useState(true);
  const [transactions, setTransactions] = useState([]);
  const [transactionsLoading, setTransactionsLoading] = useState(true);
  const [refresh, setRefresh] = useState(0);
  const [transactionsError, setTransactionsError] = useState(null);
  const [transactionsAccountFilter, setTransactionsAccountFilter] = useState("");
  const [transactionsPage, setTransactionsPage] = useState(1);
  const TRANSACTIONS_PAGE_SIZE = 20;

  useEffect(() => {
    let cancelled = false;
    (async () => {
      setCustomersLoading(true);
      try {
        const res = await fetch(`${API}/api/admin/customers`);
        if (!res.ok) throw new Error(await res.text());
        const data = await res.json();
        if (!cancelled) setCustomers(data.customers || []);
      } catch {
        if (!cancelled) setCustomers([]);
      } finally {
        if (!cancelled) setCustomersLoading(false);
      }
    })();
    return () => { cancelled = true; };
  }, [refresh, view === "transactions" || view === "customers" || view === "manage"]);

  useEffect(() => {
    if (view !== "transactions") return;
    let cancelled = false;
    setTransactionsError(null);
    (async () => {
      setTransactionsLoading(true);
      try {
        const params = new URLSearchParams({ limit: "200" });
        if (transactionsAccountFilter.trim()) params.set("account_id", transactionsAccountFilter.trim());
        const res = await fetch(`${API}/api/admin/fraud/transactions?${params}`);
        const text = await res.text();
        if (!res.ok) {
          let msg = text;
          try { const j = JSON.parse(text); msg = j.detail || text; } catch (_) {}
          throw new Error(msg);
        }
        const data = text ? JSON.parse(text) : [];
        if (!cancelled) {
          setTransactions(Array.isArray(data) ? data : []);
          setTransactionsPage(1);
        }
      } catch (e) {
        if (!cancelled) {
          setTransactions([]);
          setTransactionsError(e.message || "Failed to load transactions");
        }
      } finally {
        if (!cancelled) setTransactionsLoading(false);
      }
    })();
    return () => { cancelled = true; };
  }, [view, refresh]);

  const sidebarView = selectedTransactionId ? "transactions" : view === "customer" ? "customers" : view;
  const handleNav = (id) => {
    setView(id);
    if (id === "customers") setSelectedUsername(null);
    if (id === "transactions") setSelectedTransactionId(null);
  };

  return (
    <div className="min-h-screen flex bg-slate-950">
      <AdminSidebar currentView={sidebarView} onNavigate={handleNav} />
      <main className="flex-1 overflow-auto p-4 md:p-8">
        {selectedTransactionId ? (
          <TransactionDetail transactionId={selectedTransactionId} onBack={() => setSelectedTransactionId(null)} />
        ) : view === "customer" && selectedUsername ? (
          <CustomerDetail username={selectedUsername} onBack={() => { setView("customers"); setSelectedUsername(null); }} refresh={refresh} />
        ) : view === "manage" ? (
          <ManageUsers onBack={() => setView("transactions")} onCreated={() => { setRefresh((r) => r + 1); setView("customers"); }} />
        ) : view === "transactions" ? (
          <TransactionsScreen
            transactions={transactions}
            loading={transactionsLoading}
            error={transactionsError}
            onSelectTransaction={setSelectedTransactionId}
            accountFilter={transactionsAccountFilter}
            setAccountFilter={setTransactionsAccountFilter}
            onRefresh={() => setRefresh((r) => r + 1)}
            page={transactionsPage}
            setPage={setTransactionsPage}
            pageSize={TRANSACTIONS_PAGE_SIZE}
          />
        ) : (
          <CustomersScreen customers={customers} loading={customersLoading} onSelectCustomer={(username) => { setSelectedUsername(username); setView("customer"); }} />
        )}
      </main>
    </div>
  );
}
