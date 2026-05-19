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
      <div style={{ width: 40, height: 40, borderRadius: 12, background: "linear-gradient(135deg,#6366f1,#818cf8)", display: "flex", alignItems: "center", justifyContent: "center", marginBottom: 20, boxShadow: "0 4px 12px rgba(99,102,241,0.3)" }}>
        <svg width="20" height="20" viewBox="0 0 20 20" fill="none">
          <path d="M10 2L18 7V13L10 18L2 13V7L10 2Z" fill="white" opacity="0.9" />
          <path d="M10 7L14 9.5V14L10 16.5L6 14V9.5L10 7Z" fill="#6366f1" />
        </svg>
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
      <a href="/settings" target="_blank" rel="noreferrer" title="Settings (legacy page)" style={{
        width: 42, height: 42, borderRadius: 12, display: "flex", alignItems: "center", justifyContent: "center",
        background: "transparent", color: "var(--text-faint)", marginBottom: 8, textDecoration: "none",
      }}>
        <svg width="18" height="18" viewBox="0 0 18 18" fill="none">
          <circle cx="9" cy="9" r="2.5" stroke="currentColor" strokeWidth="1.5" />
          <path d="M9 2V4M9 14V16M2 9H4M14 9H16M4.22 4.22L5.64 5.64M12.36 12.36L13.78 13.78M13.78 4.22L12.36 5.64M5.64 12.36L4.22 13.78" stroke="currentColor" strokeWidth="1.3" strokeLinecap="round" />
        </svg>
      </a>
      <div style={{ width: 8, height: 8, borderRadius: "50%", background: "#4ade80", marginBottom: 10, boxShadow: "0 0 10px rgba(74,222,128,0.4)" }} />
      <div style={{ writingMode: "vertical-rl", fontSize: 8, fontWeight: 800, letterSpacing: "2.5px", color: "var(--text-faint)", fontFamily: "'JetBrains Mono',monospace", marginBottom: 16 }}>BEAST</div>
    </div>
  );
}

// ---------------------------------------------------------------------
// Runs list view
// ---------------------------------------------------------------------

export { Sidebar };
