// Sidebar: top-level navigation between views.

function Sidebar({ view, setView }) {
  const items = [
    {
      key: "list",
      label: "Runs",
      icon: (
        <svg width="18" height="18" viewBox="0 0 18 18" fill="none">
          <rect x="3" y="3" width="12" height="3" rx="1" stroke="currentColor" strokeWidth="1.5" />
          <rect x="3" y="7.5" width="12" height="3" rx="1" stroke="currentColor" strokeWidth="1.5" />
          <rect x="3" y="12" width="12" height="3" rx="1" stroke="currentColor" strokeWidth="1.5" />
        </svg>
      ),
    },
    {
      key: "new",
      label: "New Run",
      icon: (
        <svg width="18" height="18" viewBox="0 0 18 18" fill="none">
          <circle cx="9" cy="9" r="7" stroke="currentColor" strokeWidth="1.5" />
          <path d="M9 5.5V12.5M5.5 9H12.5" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
        </svg>
      ),
    },
  ];
  return (
    <div style={{ width: 64, background: "var(--bg-elevated)", borderRight: "1px solid var(--border)", display: "flex", flexDirection: "column", alignItems: "center", paddingTop: 14, flexShrink: 0 }}>
      {/* mle-beast logo — gravitational-waves visualization w/ binary
          black holes. The source image is wider than tall, so object-
          fit: cover keeps the black holes (which sit dead-center)
          visible. Drop shadow preserved from the previous SVG cube
          for visual continuity. Click → navigate to the launch page
          (runs list), the standard "logo is home" convention. */}
      <button
        onClick={() => setView("list")}
        title="Go to runs list"
        style={{
          width: 40, height: 40, borderRadius: 12,
          overflow: "hidden",
          marginBottom: 20,
          boxShadow: "0 4px 12px rgba(99,102,241,0.3)",
          background: "#000",
          border: "none",
          padding: 0,
          cursor: "pointer",
        }}
      >
        <img
          src="/logo.jpg"
          alt="mle-beast"
          style={{ width: "100%", height: "100%", objectFit: "cover", display: "block" }}
        />
      </button>
      {items.map(item => {
        const active = view === item.key || (item.key === "list" && view === "detail");
        return (
          <button key={item.key} title={item.label} onClick={() => setView(item.key)}
            style={{
              width: 42, height: 42, borderRadius: 12, border: "none", cursor: "pointer",
              display: "flex", alignItems: "center", justifyContent: "center", marginBottom: 4,
              background: active ? "rgba(99,102,241,0.15)" : "transparent",
              color: active ? "#a5b4fc" : "var(--text-faint)",
              transition: "all 0.15s", position: "relative",
            }}>
            {item.icon}
            {active && <div style={{ position: "absolute", left: 0, top: 10, width: 3, height: 22, borderRadius: "0 3px 3px 0", background: "#818cf8" }} />}
          </button>
        );
      })}
      <div style={{ flex: 1 }} />
      {/* Theme toggle moved out of the sidebar (lower-left) up to the
          top-right area next to the gear in App.jsx — that's where most
          users expect to find it (Vercel / Linear / etc. all follow
          this convention). */}
      <div style={{ width: 8, height: 8, borderRadius: "50%", background: "var(--status-ok-fg)", marginBottom: 10, boxShadow: "0 0 10px rgba(74,222,128,0.4)" }} />
      <div style={{ writingMode: "vertical-rl", fontSize: 8, fontWeight: 800, letterSpacing: "2.5px", color: "var(--text-faint)", fontFamily: "'JetBrains Mono',monospace", marginBottom: 16 }}>BEAST</div>
    </div>
  );
}

// ---------------------------------------------------------------------
// Runs list view
// ---------------------------------------------------------------------

export { Sidebar };
