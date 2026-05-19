// Top bar of the run detail page: back, status, run id, active stage,
// peak score, cancel button.

import { API } from "../../api.js";
import { STAGES_ORDER } from "../../constants.js";
import { StatusPill } from "../../primitives.jsx";

function RunHeader({ run, runId, stageMap, activeStageKey, peak, onBack, onCancel }) {
  return (
    // Right padding bumped from 24 → 76 to reserve room for the
    // fixed-position gear button in App.jsx (36px wide at right:16).
    // Without this offset the gear visually overlaps Cancel Run /
    // PEAK in the right cluster.
    <div style={{
      padding: "9px 76px 9px 24px", borderBottom: "1px solid var(--border)",
      display: "flex", alignItems: "center", justifyContent: "space-between",
      flexShrink: 0,
    }}>
      <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
        <button onClick={onBack} style={{
          background: "transparent", border: "1px solid var(--border)",
          color: "var(--text-muted)", fontSize: 11, padding: "4px 10px",
          borderRadius: 6, cursor: "pointer",
          fontFamily: "'JetBrains Mono',monospace",
        }}>← back</button>
        <StatusPill status={run.status} />
        <span style={{ fontSize: 14, fontWeight: 600 }}>{run.id.slice(0, 8)}…</span>
        <span style={{
          fontSize: 11, color: "var(--text-muted)",
          fontFamily: "'JetBrains Mono',monospace",
        }}>{run.mode}</span>
        {activeStageKey && stageMap[activeStageKey]?.status === "active" && (
          <span style={{
            display: "flex", alignItems: "center", gap: 6,
            fontSize: 11, fontWeight: 700,
            color: "#a5b4fc",
            fontFamily: "'JetBrains Mono',monospace",
            padding: "3px 10px",
            borderRadius: 6,
            background: "rgba(129,140,248,0.1)",
            border: "1px solid rgba(129,140,248,0.25)",
          }}>
            <span style={{
              width: 6, height: 6, borderRadius: "50%", background: "#fafafa",
              boxShadow: "0 0 6px rgba(255,255,255,0.9)",
              animation: "pipePulse 1.2s ease-in-out infinite",
            }} />
            {(STAGES_ORDER.find(s => s.key === activeStageKey)?.name || activeStageKey).toUpperCase()}
          </span>
        )}
      </div>
      <div style={{ display: "flex", alignItems: "center", gap: 14 }}>
        <span style={{
          fontSize: 11, color: "var(--text-faint)",
          fontFamily: "'JetBrains Mono',monospace",
        }}>
          PEAK: <span style={{ color: "#22d3ee", fontWeight: 700, fontSize: 14 }}>
            {peak ? Number(peak.score).toFixed(4) : "—"}
          </span>
        </span>
        {run.status === "running" && (
          <button onClick={() => API.cancelRun(runId).then(onCancel)} style={{
            background: "rgba(248,113,113,0.1)",
            border: "1px solid rgba(248,113,113,0.3)",
            color: "#fca5a5", fontSize: 12, fontWeight: 600,
            padding: "6px 14px", borderRadius: 8, cursor: "pointer",
          }}>Cancel Run</button>
        )}
      </div>
    </div>
  );
}

export { RunHeader };
