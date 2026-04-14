import { useEffect, useRef, useState } from "react";

const NAV_ITEMS = [
  { id: "home", label: "Home" },
  { id: "observability", label: "Tenant observability" },
  { id: "onboard", label: "Onboard bank", ownerOnly: true },
  { id: "care", label: "Customer care health" },
  { id: "policy", label: "Fraud policy" },
  
  { id: "fraud-train", label: " Models training" },
  { id: "model-registry", label: "Model registry" },
  { id: "ops-cutover", label: "Ops / cutover", ownerOnly: true },
  { id: "fraud-ops", label: "Fraud ops" },
  { id: "team", label: "Team / users", ownerOnly: true },
  { id: "reports", label: "Reports" },
];

export default function PlatformSidebar({
  activeView,
  onChange,
  isOwner,
  bankLogoUrl,
  canManageBranding = false,
  hasActiveBank = false,
  onUploadLogo,
}) {
  const items = NAV_ITEMS.filter((x) => !x.ownerOnly || isOwner);
  const [logoFile, setLogoFile] = useState(null);
  const [logoUploading, setLogoUploading] = useState(false);
  const [menuOpen, setMenuOpen] = useState(false);
  const [showReplaceForm, setShowReplaceForm] = useState(false);
  const brandingRef = useRef(null);

  async function uploadLogo() {
    if (!logoFile || typeof onUploadLogo !== "function") return;
    setLogoUploading(true);
    try {
      await onUploadLogo(logoFile);
      setLogoFile(null);
      setShowReplaceForm(false);
      setMenuOpen(false);
    } finally {
      setLogoUploading(false);
    }
  }

  useEffect(() => {
    if (!menuOpen) return;
    const onDocClick = (e) => {
      const el = brandingRef.current;
      if (!el) return;
      if (!el.contains(e.target)) {
        setMenuOpen(false);
      }
    };
    const onEsc = (e) => {
      if (e.key === "Escape") setMenuOpen(false);
    };
    document.addEventListener("mousedown", onDocClick);
    document.addEventListener("keydown", onEsc);
    return () => {
      document.removeEventListener("mousedown", onDocClick);
      document.removeEventListener("keydown", onEsc);
    };
  }, [menuOpen]);

  return (
    <aside className="w-60 shrink-0 border-r border-slate-800 bg-slate-950/80 flex flex-col">
      <div className="px-4 py-4 border-b border-slate-800">
        <p className="text-[11px] tracking-[0.18em] uppercase text-slate-500">Bank branding</p>
        <div ref={brandingRef} className="mt-2 rounded-lg border border-slate-800 bg-slate-900/60 p-2">
          {bankLogoUrl ? (
            <div className="mb-2">
              <button
                type="button"
                onClick={() => setMenuOpen((v) => !v)}
                className="w-full flex items-center justify-center py-2"
              >
                <span className="h-20 w-20 rounded-full border-2 border-white/90 bg-slate-950/40 flex items-center justify-center overflow-hidden shadow-[0_0_0_1px_rgba(255,255,255,0.08)]">
                  <img src={bankLogoUrl} alt="Bank logo" className="h-16 w-16 object-contain" />
                </span>
              </button>
              {canManageBranding && hasActiveBank && menuOpen && (
                <div className="mt-2 grid grid-cols-2 gap-2">
                  <button
                    type="button"
                    onClick={() => setShowReplaceForm((v) => !v)}
                    className="px-2 py-1.5 rounded border border-cyan-700/70 text-cyan-300 text-[10px] uppercase"
                  >
                    Replace
                  </button>
                  <button
                    type="button"
                    onClick={async () => {
                      if (typeof onUploadLogo === "function") {
                        await onUploadLogo(null, { remove: true });
                      }
                      setMenuOpen(false);
                    }}
                    className="px-2 py-1.5 rounded border border-red-700/70 text-red-300 text-[10px] uppercase"
                  >
                    Remove
                  </button>
                </div>
              )}
            </div>
          ) : (
            <div className="mb-2 flex items-center justify-center">
              <span className="h-20 w-20 rounded-full border-2 border-white/40 bg-slate-950/40 flex items-center justify-center text-[10px] text-slate-500 text-center px-2">
                No logo
              </span>
            </div>
          )}
          {canManageBranding && hasActiveBank && (!bankLogoUrl || showReplaceForm) && (
            <div className="space-y-2">
              <input
                type="file"
                accept=".png,.jpg,.jpeg,.webp"
                onChange={(e) => setLogoFile(e.target.files?.[0] || null)}
                className="w-full text-[10px] text-slate-300"
              />
              <button
                type="button"
                onClick={uploadLogo}
                disabled={!logoFile || logoUploading}
                className="w-full px-2 py-1.5 rounded border border-cyan-700/70 text-cyan-300 text-[10px] uppercase disabled:opacity-50"
              >
                {logoUploading ? "Uploading..." : bankLogoUrl ? "Replace logo" : "Upload logo"}
              </button>
            </div>
          )}
          {!hasActiveBank && <p className="text-[11px] text-slate-500">Pick a bank to manage branding.</p>}
        </div>
      </div>

      <nav className="p-2 flex-1 space-y-1.5">
        {items.map(({ id, label }) => {
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
