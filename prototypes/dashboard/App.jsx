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

      <Sidebar view={view} setView={setView} />

      <div style={{ flex: 1, display: "flex", flexDirection: "column", overflow: "hidden", position: "relative" }}>
        {/* Top-right utility cluster — theme toggle + gear. Both are
            fixed-position so they stay reachable from any view without
            the underlying layout needing to make room.

            Two-context styling:
              - On the runs list view, the cluster sits on top of the
                hero banner, which is hardcoded `backgroundColor: "#000"`
                in BOTH themes (design choice — the gravitational-waves
                photo needs the dark canvas). So in light mode the
                normally-dark buttons would vanish on the black hero.
                When view === "list" we force the "dark context" style
                (light frosted button on dark) regardless of theme.
              - On every other view (detail, new, settings) the cluster
                is over the regular page bg and we use theme-aware
                styling. */}
        {(() => {
        // The list view's hero is dark only in dark mode now (it's a light
        // tint in light mode), so only force the light-frosted-on-dark
        // button style when the hero is actually dark. Otherwise the cluster
        // follows the theme like every other view.
        const onHero = view === "list" && theme === "dark";
        const btnBg = onHero
          ? "rgba(255,255,255,0.14)"
          : (theme === "dark" ? "rgba(255,255,255,0.12)" : "rgba(15,23,42,0.06)");
        const btnBorder = onHero
          ? "rgba(255,255,255,0.32)"
          : (theme === "dark" ? "rgba(255,255,255,0.25)" : "rgba(15,23,42,0.20)");
        const btnColor = onHero
          ? "rgba(255,255,255,0.92)"
          : (theme === "dark" ? "rgba(255,255,255,0.85)" : "rgba(15,23,42,0.75)");
        return (
        <div style={{
          position: "absolute", top: 12, right: 16, zIndex: 10,
          display: "flex", alignItems: "center", gap: 8,
        }}>
          <button
            onClick={toggleTheme}
            title={`Switch to ${theme === "dark" ? "light" : "dark"} mode`}
            style={{
              width: 36, height: 36, borderRadius: 10,
              border: `1px solid ${btnBorder}`,
              cursor: "pointer",
              background: btnBg,
              color: btnColor,
              display: "flex", alignItems: "center", justifyContent: "center",
              transition: "all 0.15s",
              backdropFilter: "blur(8px)",
            }}
          >
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
          <button
            onClick={() => setView(view === "settings" ? "list" : "settings")}
            title="Settings &amp; Admin"
            style={{
              width: 36, height: 36, borderRadius: 10,
              border: `1px solid ${btnBorder}`,
              cursor: "pointer",
              background: view === "settings" ? "rgba(99,102,241,0.20)" : btnBg,
              color: view === "settings" ? "#a5b4fc" : btnColor,
              display: "flex", alignItems: "center", justifyContent: "center",
              transition: "all 0.15s",
              backdropFilter: "blur(8px)",
            }}
          >
            {/* Proper gear icon (Lucide "settings"). 8 lobes + center
                hole, no radial spokes — visually distinct from the
                sun/moon theme toggle to its left. */}
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none"
                 stroke="currentColor" strokeWidth="2"
                 strokeLinecap="round" strokeLinejoin="round">
              <path d="M12.22 2h-.44a2 2 0 0 0-2 2v.18a2 2 0 0 1-1 1.73l-.43.25a2 2 0 0 1-2 0l-.15-.08a2 2 0 0 0-2.73.73l-.22.38a2 2 0 0 0 .73 2.73l.15.1a2 2 0 0 1 1 1.72v.51a2 2 0 0 1-1 1.74l-.15.09a2 2 0 0 0-.73 2.73l.22.38a2 2 0 0 0 2.73.73l.15-.08a2 2 0 0 1 2 0l.43.25a2 2 0 0 1 1 1.73V20a2 2 0 0 0 2 2h.44a2 2 0 0 0 2-2v-.18a2 2 0 0 1 1-1.73l.43-.25a2 2 0 0 1 2 0l.15.08a2 2 0 0 0 2.73-.73l.22-.39a2 2 0 0 0-.73-2.73l-.15-.08a2 2 0 0 1-1-1.74v-.5a2 2 0 0 1 1-1.74l.15-.09a2 2 0 0 0 .73-2.73l-.22-.38a2 2 0 0 0-2.73-.73l-.15.08a2 2 0 0 1-2 0l-.43-.25a2 2 0 0 1-1-1.73V4a2 2 0 0 0-2-2z" />
              <circle cx="12" cy="12" r="3" />
            </svg>
          </button>
        </div>
        );
        })()}

        {view === "list" && <RunsListView onOpen={open} onNew={() => setView("new")} onHome={() => setView("list")} />}
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
          /* The "interesting metric" accent used by PEAK / kept / etc.
             On dark this is a glowing cyan that pops against near-black;
             on light we shift to a deeper teal/cyan that still reads on
             near-white. Use the strong variant for filled badges or
             text on a tinted background. */
          --accent-info: #22d3ee;
          --accent-info-strong: #0891b2;
          /* Status pill foregrounds. On dark these are saturated
             lights (the Tailwind 400-shade family) that glow against
             near-black. On light we shift to the 700-shade family
             so they read on white without losing the green / red /
             amber semantic. Backgrounds stay rgba-tinted on both. */
          --status-ok-fg: #4ade80;
          --status-fail-fg: #f87171;
          --status-warn-fg: #fbbf24;
          /* Runs-list hero banner. Dark: the original black canvas the
             gravitational-waves logo + white wordmark were designed for. */
          --hero-bg: #000;
          --hero-wordmark: linear-gradient(135deg, #ffffff 0%, #c4b5fd 100%);
          --hero-text: rgba(255,255,255,0.75);
          --hero-text-faint: rgba(255,255,255,0.4);
          --hero-text-shadow: 0 2px 10px rgba(0,0,0,0.5);
          --hero-subtext-shadow: 0 1px 3px rgba(0,0,0,0.6);
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
          --accent-info: #0891b2;
          --accent-info-strong: #155e75;
          --status-ok-fg: #15803d;
          --status-fail-fg: #b91c1c;
          --status-warn-fg: #b45309;
          /* Light: a soft indigo→violet tint instead of a black slab, with
             the wordmark + tagline darkened to read on it. The logo photo
             keeps its own dark tile (a small contained element). */
          --hero-bg: linear-gradient(135deg, #eef2ff 0%, #faf5ff 100%);
          --hero-wordmark: linear-gradient(135deg, #4f46e5 0%, #7c3aed 100%);
          --hero-text: rgba(15,23,42,0.65);
          --hero-text-faint: rgba(15,23,42,0.4);
          --hero-text-shadow: none;
          --hero-subtext-shadow: none;
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
