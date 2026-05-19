import { useState } from "react";

import { Sidebar } from "./src/Sidebar.jsx";
import { NewRunView } from "./src/views/NewRunView.jsx";
import { RunDetailView } from "./src/views/RunDetailView.jsx";
import { RunsListView } from "./src/views/RunsListView.jsx";
import { SettingsView } from "./src/views/SettingsView.jsx";


export default function App() {
  const [view, setView] = useState("list");
  const [currentRunId, setCurrentRunId] = useState(null);
  // Theme: persisted in localStorage so the choice survives reloads.
  const [theme, setTheme] = useState(() => {
    try { return localStorage.getItem("mle-beast-theme") || "dark"; }
    catch { return "dark"; }
  });
  const toggleTheme = () => {
    setTheme(prev => {
      const next = prev === "dark" ? "light" : "dark";
      try { localStorage.setItem("mle-beast-theme", next); } catch {}
      return next;
    });
  };

  const open = (id) => { setCurrentRunId(id); setView("detail"); };

  return (
    <div className={`theme-${theme}`} style={{ display: "flex", height: "100vh", background: "var(--bg)", color: "var(--text)", fontFamily: "'DM Sans',system-ui,sans-serif", overflow: "hidden" }}>
      <link href="https://fonts.googleapis.com/css2?family=DM+Sans:wght@400;500;600;700&family=JetBrains+Mono:wght@400;500;600;700&display=swap" rel="stylesheet" />

      <Sidebar view={view} setView={setView} theme={theme} onToggleTheme={toggleTheme} />

      <div style={{ flex: 1, display: "flex", flexDirection: "column", overflow: "hidden", position: "relative" }}>
        {/* Fixed-position gear button — always reachable from any view.
            Stays out of the layout flow so the underlying view doesn't
            need to know about it. Clicking sets view=settings; when
            already in settings, the SettingsView renders its own
            back button so we just leave this gear visible. */}
        <button
          onClick={() => setView(view === "settings" ? "list" : "settings")}
          title="Settings &amp; Admin"
          style={{
            position: "absolute", top: 12, right: 16, zIndex: 10,
            width: 36, height: 36, borderRadius: 10,
            border: "1px solid var(--border)", cursor: "pointer",
            background: view === "settings" ? "rgba(99,102,241,0.15)" : "var(--surface)",
            color: view === "settings" ? "#a5b4fc" : "var(--text-muted)",
            display: "flex", alignItems: "center", justifyContent: "center",
            transition: "all 0.15s",
          }}
        >
          {/* Proper gear icon (Lucide "settings"). 8 lobes + center
              hole, no radial spokes — visually distinct from the
              sun/moon theme toggle in the sidebar. */}
          <svg width="18" height="18" viewBox="0 0 24 24" fill="none"
               stroke="currentColor" strokeWidth="2"
               strokeLinecap="round" strokeLinejoin="round">
            <path d="M12.22 2h-.44a2 2 0 0 0-2 2v.18a2 2 0 0 1-1 1.73l-.43.25a2 2 0 0 1-2 0l-.15-.08a2 2 0 0 0-2.73.73l-.22.38a2 2 0 0 0 .73 2.73l.15.1a2 2 0 0 1 1 1.72v.51a2 2 0 0 1-1 1.74l-.15.09a2 2 0 0 0-.73 2.73l.22.38a2 2 0 0 0 2.73.73l.15-.08a2 2 0 0 1 2 0l.43.25a2 2 0 0 1 1 1.73V20a2 2 0 0 0 2 2h.44a2 2 0 0 0 2-2v-.18a2 2 0 0 1 1-1.73l.43-.25a2 2 0 0 1 2 0l.15.08a2 2 0 0 0 2.73-.73l.22-.39a2 2 0 0 0-.73-2.73l-.15-.08a2 2 0 0 1-1-1.74v-.5a2 2 0 0 1 1-1.74l.15-.09a2 2 0 0 0 .73-2.73l-.22-.38a2 2 0 0 0-2.73-.73l-.15.08a2 2 0 0 1-2 0l-.43-.25a2 2 0 0 1-1-1.73V4a2 2 0 0 0-2-2z" />
            <circle cx="12" cy="12" r="3" />
          </svg>
        </button>

        {view === "list" && <RunsListView onOpen={open} onNew={() => setView("new")} />}
        {view === "new" && <NewRunView onCreated={open} onCancel={() => setView("list")} />}
        {view === "detail" && currentRunId && <RunDetailView runId={currentRunId} onBack={() => setView("list")} />}
        {view === "settings" && <SettingsView onClose={() => setView("list")} />}
      </div>

      <style>{`
        /* Theme tokens — only the surfaces / text shades / borders flip
           between dark and light. Accent colors (cyan, purple, green,
           amber, etc) stay constant since they're tuned to read well
           on either background. */
        .theme-dark {
          --bg: #0a0c14;
          --bg-elevated: #07080c;
          --text: #e2e8f0;
          --text-muted: rgba(255,255,255,0.55);
          --text-subtle: rgba(255,255,255,0.3);
          --text-faint: rgba(255,255,255,0.16);
          --surface: rgba(255,255,255,0.025);
          --surface-strong: rgba(255,255,255,0.05);
          --border: rgba(255,255,255,0.06);
          --border-subtle: rgba(255,255,255,0.04);
          --code-bg: rgba(0,0,0,0.25);
          --shadow: 0 4px 12px rgba(0,0,0,0.4);
        }
        .theme-light {
          --bg: #f5f7fb;
          --bg-elevated: #ffffff;
          --text: #0f172a;
          --text-muted: rgba(15,23,42,0.7);
          --text-subtle: rgba(15,23,42,0.5);
          --text-faint: rgba(15,23,42,0.32);
          --surface: rgba(15,23,42,0.04);
          --surface-strong: rgba(15,23,42,0.08);
          --border: rgba(15,23,42,0.1);
          --border-subtle: rgba(15,23,42,0.06);
          --code-bg: rgba(15,23,42,0.05);
          --shadow: 0 4px 12px rgba(15,23,42,0.08);
        }
        ::-webkit-scrollbar { width: 4px; height: 4px; }
        ::-webkit-scrollbar-track { background: transparent; }
        ::-webkit-scrollbar-thumb { background: var(--border); border-radius: 2px; }
        * { box-sizing: border-box; margin: 0; }
        button:focus { outline: none; }
        input:focus, textarea:focus { outline: 1px solid rgba(99,102,241,0.4); }
        @keyframes pipePulse {
          0%, 100% { transform: scale(1);   opacity: 1; }
          50%      { transform: scale(1.4); opacity: 0.6; }
        }
        @keyframes pipeBreathe {
          0%, 100% { box-shadow: 0 0 14px rgba(129,140,248,0.45), inset 0 0 0 1px var(--border); }
          50%      { box-shadow: 0 0 22px rgba(129,140,248,0.75), inset 0 0 0 1px rgba(99,102,241,0.18); }
        }
        @keyframes shimmer {
          0%   { background-position: -200% 0; }
          100% { background-position:  200% 0; }
        }
      `}</style>
    </div>
  );
}
