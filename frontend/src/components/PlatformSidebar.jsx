const NAV_ITEMS = [
  { id: "onboard", label: "Onboard bank" },
  { id: "care", label: "Customer care health" },
  { id: "policy", label: "Fraud policy & training" },
  { id: "fraud-ops", label: "Fraud ops" },
];

export default function PlatformSidebar({ activeView, onChange }) {
  return (
    <aside className="w-60 shrink-0 border-r border-slate-800 bg-slate-950/80 flex flex-col">
      <div className="px-4 py-4 border-b border-slate-800">
        <p className="text-[11px] tracking-[0.18em] uppercase text-slate-500">Navigation</p>
      </div>

      <nav className="p-2 flex-1 space-y-1.5">
        {NAV_ITEMS.map(({ id, label }) => {
          const active = activeView === id;
          return (
            <button
              key={id}
              type="button"
              onClick={() => onChange(id)}
              className={`group relative w-full text-left px-3 py-2.5 rounded-lg text-sm font-medium transition-colors ${
                active
                  ? "bg-cyan-400/90 text-slate-900"
                  : "text-slate-300 hover:bg-slate-800/80 hover:text-slate-100"
              }`}
            >
              <span
                className={`absolute left-0 top-1/2 -translate-y-1/2 h-5 w-1 rounded-r ${
                  active ? "bg-slate-900/70" : "bg-transparent group-hover:bg-cyan-400/60"
                }`}
              />
              <span className="pl-1">{label}</span>
            </button>
          );
        })}
      </nav>
    </aside>
  );
}
