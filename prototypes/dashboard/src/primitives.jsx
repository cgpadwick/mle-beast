// Tiny shared UI primitives.

import { cardBase } from "./constants.js";

function Card({ children, style }) {
  return <div style={{ ...cardBase, ...style }}>{children}</div>;
}

function Row({ label, value, accent }) {
  return (
    <div style={{ display: "flex", justifyContent: "space-between", padding: "7px 0", borderBottom: "1px solid var(--border-subtle)" }}>
      <span style={{ fontSize: 12, color: "var(--text-subtle)" }}>{label}</span>
      <span style={{ fontSize: 12, color: accent ? "var(--accent-info)" : "var(--text-muted)", fontWeight: accent ? 700 : 400, fontFamily: "'JetBrains Mono',monospace" }}>{value}</span>
    </div>
  );
}

function StatusPill({ status }) {
  // Backgrounds stay rgba-tinted (work on both themes); foregrounds
  // come from theme-aware CSS vars so they actually read on white in
  // light mode and stay vivid on near-black in dark mode.
  const colors = {
    running:   { bg: "rgba(34,211,238,0.1)",  fg: "var(--accent-info)" },
    pending:   { bg: "var(--surface-strong)", fg: "var(--text-muted)" },
    completed: { bg: "rgba(74,222,128,0.1)",  fg: "var(--status-ok-fg)" },
    failed:    { bg: "rgba(248,113,113,0.1)", fg: "var(--status-fail-fg)" },
    cancelled: { bg: "rgba(248,113,113,0.08)", fg: "var(--status-warn-fg)" },
  };
  const c = colors[status] || colors.pending;
  return (
    <span style={{
      background: c.bg, color: c.fg, fontSize: 9, fontWeight: 700,
      padding: "3px 9px", borderRadius: 5,
      fontFamily: "'JetBrains Mono',monospace",
      letterSpacing: "0.5px",
    }}>{(status || "pending").toUpperCase()}</span>
  );
}
function SectionHeader({ label, count, accent }) {
  return (
    <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 10 }}>
      {accent && (
        <span style={{
          width: 8, height: 8, borderRadius: "50%", background: accent,
          boxShadow: `0 0 8px ${accent}80`,
          animation: "pipePulse 1.5s ease-in-out infinite",
        }} />
      )}
      <h3 style={{
        fontSize: 11, fontWeight: 700, letterSpacing: "1.5px",
        color: accent || "var(--text-subtle)",
        fontFamily: "'JetBrains Mono',monospace",
        textTransform: "uppercase",
      }}>{label}</h3>
      <span style={{
        fontSize: 10, color: "var(--text-faint)",
        fontFamily: "'JetBrains Mono',monospace",
      }}>· {count}</span>
      <div style={{ flex: 1, height: 1, background: "var(--border-subtle)" }} />
    </div>
  );
}
function DetailRow({ label, value, mono = false, copyable = false, valueColor }) {
  if (value === null || value === undefined || value === "") return null;
  return (
    <div style={{ display: "flex", padding: "8px 0", borderBottom: "1px solid var(--border-subtle)", gap: 12, alignItems: "flex-start" }}>
      <span style={{
        fontSize: 9, fontWeight: 700, color: "var(--text-subtle)",
        letterSpacing: "1.5px", fontFamily: "'JetBrains Mono',monospace",
        width: 140, flexShrink: 0, paddingTop: 2,
      }}>{label}</span>
      <span
        title={copyable ? "Click to copy" : undefined}
        onClick={copyable ? () => navigator.clipboard?.writeText(String(value)) : undefined}
        style={{
          fontSize: 12, color: valueColor || "var(--text-muted)",
          fontFamily: mono ? "'JetBrains Mono',monospace" : "inherit",
          cursor: copyable ? "pointer" : "default",
          flex: 1, wordBreak: "break-all",
        }}
      >{String(value)}</span>
    </div>
  );
}

export { Card, Row, StatusPill, SectionHeader, DetailRow };
