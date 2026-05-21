// Sidebar: top-level navigation between views.

function Sidebar({ view, setView, theme, onToggleTheme }) {
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
          for visual continuity. */}
      <div style={{
        width: 40, height: 40, borderRadius: 12,
        overflow: "hidden",
        marginBottom: 20,
        boxShadow: "0 4px 12px rgba(99,102,241,0.3)",
        background: "#000",
      }}>
        <img
          src="/logo.jpg"
          alt="mle-beast"
          style={{ width: "100%", height: "100%", objectFit: "cover", display: "block" }}
        />
      </div>
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
      <button onClick={onToggleTheme} title={`Switch to ${theme === "dark" ? "light" : "dark"} mode`} style={{
        width: 42, height: 42, borderRadius: 12, border: "none", cursor: "pointer",
        display: "flex", alignItems: "center", justifyContent: "center",
        background: "transparent", color: "var(--text-faint)", marginBottom: 4,
      }}>
        {theme === "dark" ? (
          // Sun icon — switching to light
          <svg width="18" height="18" viewBox="0 0 18 18" fill="none">
            <circle cx="9" cy="9" r="3" stroke="currentColor" strokeWidth="1.5" />
            <path d="M9 1.5V3M9 15V16.5M1.5 9H3M15 9H16.5M3.4 3.4L4.5 4.5M13.5 13.5L14.6 14.6M14.6 3.4L13.5 4.5M4.5 13.5L3.4 14.6" stroke="currentColor" strokeWidth="1.4" strokeLinecap="round" />
          </svg>
        ) : (
          // Moon icon — switching to dark
          <svg width="18" height="18" viewBox="0 0 18 18" fill="none">
            <path d="M14.5 11.5C13.4 11.9 12.2 12.1 11 12.1C7 12.1 3.7 8.8 3.7 4.8C3.7 4 3.8 3.2 4.1 2.5C2.4 3.4 1.2 5.2 1.2 7.3C1.2 10.6 3.9 13.3 7.2 13.3C9.4 13.3 11.4 12.1 12.5 10.3" stroke="currentColor" strokeWidth="1.4" strokeLinecap="round" strokeLinejoin="round" />
          </svg>
        )}
      </button>
      <div style={{ width: 8, height: 8, borderRadius: "50%", background: "var(--status-ok-fg)", marginBottom: 10, boxShadow: "0 0 10px rgba(74,222,128,0.4)" }} />
      <div style={{ writingMode: "vertical-rl", fontSize: 8, fontWeight: 800, letterSpacing: "2.5px", color: "var(--text-faint)", fontFamily: "'JetBrains Mono',monospace", marginBottom: 16 }}>BEAST</div>
    </div>
  );
}

// ---------------------------------------------------------------------
// Runs list view
// ---------------------------------------------------------------------

export { Sidebar };
