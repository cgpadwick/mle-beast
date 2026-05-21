// Top bar of the run detail page: back, status, run id, active stage,
// peak score, cancel button.

import { useState } from "react";

import { API } from "../../api.js";
import { STAGES_ORDER } from "../../constants.js";
import { ReportModal } from "../../modals.jsx";
import { StatusPill } from "../../primitives.jsx";

function RunHeader({ run, runId, stageMap, activeStageKey, peak, onBack, onCancel }) {
  const [reportBusy, setReportBusy] = useState(false);
  const [reportError, setReportError] = useState(null);
  // null when modal is closed. Holds the {html, saved_path, save_error}
  // response when open so ReportModal can render the report in a
  // sandboxed iframe, show the on-disk save path, and offer an
  // "open in tab ↗" fallback for users who want full screen.
  const [reportData, setReportData] = useState(null);

  const handleShowReport = async () => {
    setReportError(null);
    setReportBusy(true);
    try {
      const res = await API.generateReport(runId);
      if (!res || !res.html) throw new Error("empty response");
      setReportData(res);
    } catch (e) {
      setReportError(String(e?.message || e));
    } finally {
      setReportBusy(false);
    }
  };

  // Reports for in-progress runs are just snapshots — useful sometimes,
  // but the common case is "wrap up a finished run." Show the button
  // for any non-running state.
  const reportable = run.status && run.status !== "running" && run.status !== "pending";
  return (
    <>
    {/* Right padding reserves room for the fixed-position top-right
        cluster in App.jsx — two buttons (theme toggle + gear), each
        36px wide with 8px gap, anchored at right:16. Total cluster
        width ~80px; we leave a small buffer so PEAK / Cancel Run
        don't visually overlap. */}
    <div style={{
      padding: "9px 112px 9px 24px", borderBottom: "1px solid var(--border)",
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
              width: 6, height: 6, borderRadius: "50%",
              // Lavender dot + glow — reads on both themes. Previously
              // a white dot with a white glow, which vanished on light
              // mode against the white dashboard bg.
              background: "#818cf8",
              boxShadow: "0 0 6px rgba(129,140,248,0.9)",
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
          PEAK: <span style={{ color: "var(--accent-info)", fontWeight: 700, fontSize: 14 }}>
            {peak ? Number(peak.score).toFixed(4) : "—"}
          </span>
        </span>
        {reportable && (
          <button
            onClick={handleShowReport}
            disabled={reportBusy}
            title={reportError ? `Last error: ${reportError}` : "Open the run report in a modal. A timestamped HTML copy is also saved to <workspace>/reports/ for offline use."}
            style={{
              background: reportError ? "rgba(248,113,113,0.10)" : "rgba(129,140,248,0.10)",
              border: `1px solid ${reportError ? "rgba(248,113,113,0.35)" : "rgba(129,140,248,0.30)"}`,
              color: reportError ? "#fca5a5" : "#a5b4fc",
              fontSize: 12, fontWeight: 600,
              padding: "6px 14px", borderRadius: 8,
              cursor: reportBusy ? "wait" : "pointer",
              opacity: reportBusy ? 0.6 : 1,
              display: "flex", alignItems: "center", gap: 6,
            }}
          >
            <svg width="13" height="13" viewBox="0 0 16 16" fill="none">
              <path d="M3 2.5C3 2.224 3.224 2 3.5 2H10L13 5V13.5C13 13.776 12.776 14 12.5 14H3.5C3.224 14 3 13.776 3 13.5V2.5Z" stroke="currentColor" strokeWidth="1.4" strokeLinejoin="round"/>
              <path d="M10 2V5H13" stroke="currentColor" strokeWidth="1.4" strokeLinejoin="round"/>
              <path d="M5.5 8H10.5M5.5 10.5H10.5M5.5 5.5H7" stroke="currentColor" strokeWidth="1.4" strokeLinecap="round"/>
            </svg>
            {reportBusy ? "Generating…" : "Show Report"}
          </button>
        )}
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
    {reportData && (
      <ReportModal
        html={reportData.html}
        savedPath={reportData.saved_path}
        saveError={reportData.save_error}
        onClose={() => setReportData(null)}
      />
    )}
    </>
  );
}

export { RunHeader };
