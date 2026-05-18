// Modal dialogs: run details + event details.

import { useEffect } from "react";

import { Card, Row, DetailRow } from "./primitives.jsx";
import { JsonView } from "./JsonView.jsx";
import { fmtAbsTime, fmtDuration, fmtScore } from "./format.js";

function DetailsModal({ run, peak, onClose }) {
  // Close on Escape
  useEffect(() => {
    const onKey = (e) => { if (e.key === "Escape") onClose(); };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  let verdict = null;
  if (run.verdict_json) {
    try { verdict = JSON.parse(run.verdict_json); } catch { verdict = run.verdict_json; }
  }

  return (
    <div onClick={onClose} style={{
      position: "fixed", inset: 0,
      background: "rgba(0,0,0,0.6)",
      display: "flex", alignItems: "center", justifyContent: "center",
      zIndex: 1000, padding: 20, backdropFilter: "blur(4px)",
    }}>
      <div onClick={e => e.stopPropagation()} style={{
        background: "var(--bg-elevated)", border: "1px solid var(--border)",
        borderRadius: 14, padding: 24, maxWidth: 720, width: "100%",
        maxHeight: "85vh", overflow: "auto",
        boxShadow: "0 20px 60px rgba(0,0,0,0.6)",
      }}>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 18 }}>
          <div>
            <h3 style={{ fontSize: 16, fontWeight: 700, marginBottom: 4 }}>Run Details</h3>
            <div style={{ fontSize: 11, color: "var(--text-subtle)", fontFamily: "'JetBrains Mono',monospace" }}>
              {run.id}
            </div>
          </div>
          <button onClick={onClose} title="Close (Esc)" style={{
            background: "transparent", border: "1px solid var(--border)",
            color: "var(--text-muted)", fontSize: 14, width: 30, height: 30,
            borderRadius: 8, cursor: "pointer", display: "flex",
            alignItems: "center", justifyContent: "center",
          }}>×</button>
        </div>

        <div style={{ marginBottom: 18 }}>
          <div style={{ fontSize: 9, fontWeight: 700, color: "var(--text-muted)", letterSpacing: "1.5px", fontFamily: "'JetBrains Mono',monospace", marginBottom: 6 }}>CONFIGURATION</div>
          <DetailRow label="Status" value={run.status} valueColor={
            run.status === "running" ? "#22d3ee" :
            run.status === "completed" ? "#4ade80" :
            (run.status === "failed" || run.status === "cancelled") ? "#f87171" : undefined
          } />
          <DetailRow label="Mode" value={run.mode} mono />
          <DetailRow label="Task" value={run.task} />
          <DetailRow label="Target" value={run.target_accuracy} mono valueColor="#22d3ee" />
          <DetailRow label="Metric Name" value={run.metric_name || "(auto-detect from log)"} mono />
          <DetailRow
            label="Metric Direction"
            value={
              run.lower_is_better === true  ? "lower-is-better (configured)" :
              run.lower_is_better === false ? "higher-is-better (configured)" :
              "auto-detect"
            }
            mono
          />
          <DetailRow label="Workspace" value={run.workspace} mono copyable />
          <DetailRow label="Dataset Path" value={run.dataset_path} mono copyable />
          <DetailRow label="Force CPU" value={run.force_cpu ? "yes" : "no"} mono />
          {run.setup_workspace !== undefined && (
            <DetailRow label="Setup Workspace" value={run.setup_workspace ? "yes" : "no"} mono />
          )}
          <DetailRow label="Experiment Branch" value={run.experiment_branch} mono copyable />
        </div>

        <div style={{ marginBottom: 18 }}>
          <div style={{ fontSize: 9, fontWeight: 700, color: "var(--text-muted)", letterSpacing: "1.5px", fontFamily: "'JetBrains Mono',monospace", marginBottom: 6 }}>TIMING</div>
          <DetailRow label="Created" value={fmtAbsTime(run.created_at)} mono />
          <DetailRow label="Started" value={fmtAbsTime(run.started_at)} mono />
          <DetailRow label="Completed" value={fmtAbsTime(run.completed_at)} mono />
          <DetailRow label="Wall Time" value={fmtDuration(run.started_at, run.completed_at)} mono />
        </div>

        <div style={{ marginBottom: 18 }}>
          <div style={{ fontSize: 9, fontWeight: 700, color: "var(--text-muted)", letterSpacing: "1.5px", fontFamily: "'JetBrains Mono',monospace", marginBottom: 6 }}>LLM USAGE</div>
          <DetailRow
            label="Total Cost"
            value={(run.total_cost_usd ?? 0) > 0 ? `$${Number(run.total_cost_usd).toFixed(4)}` : "(not reported)"}
            mono
            valueColor={(run.total_cost_usd ?? 0) > 0 ? "#22d3ee" : undefined}
          />
          <DetailRow label="LLM Calls" value={run.total_llm_calls ?? 0} mono />
          <DetailRow label="Prompt Tokens" value={(run.total_prompt_tokens ?? 0).toLocaleString()} mono />
          <DetailRow label="Completion Tokens" value={(run.total_completion_tokens ?? 0).toLocaleString()} mono />
          {(run.total_reasoning_tokens ?? 0) > 0 && (
            <DetailRow label="Reasoning Tokens" value={(run.total_reasoning_tokens).toLocaleString()} mono valueColor="#fbbf24" />
          )}
        </div>

        {peak && (
          <div style={{ marginBottom: 18 }}>
            <div style={{ fontSize: 9, fontWeight: 700, color: "var(--text-muted)", letterSpacing: "1.5px", fontFamily: "'JetBrains Mono',monospace", marginBottom: 6 }}>RESULTS</div>
            <DetailRow label="Best Score" value={Number(peak.score).toFixed(4)} mono valueColor="#22d3ee" />
            <DetailRow label="At Step" value={peak.step} mono />
            <DetailRow label="Direction" value={peak.lower_is_better ? "lower-is-better" : "higher-is-better"} mono />
            <DetailRow label="Kept" value={peak.kept_count} mono valueColor="#4ade80" />
            <DetailRow label="Reverted" value={peak.reverted_count} mono valueColor="#f87171" />
          </div>
        )}

        {(verdict || run.error_message) && (
          <div>
            <div style={{ fontSize: 9, fontWeight: 700, color: "var(--text-muted)", letterSpacing: "1.5px", fontFamily: "'JetBrains Mono',monospace", marginBottom: 6 }}>OUTCOME</div>
            {run.error_message && (
              <DetailRow label="Error" value={run.error_message} valueColor="#f87171" />
            )}
            {verdict && typeof verdict === "object" && (
              <pre style={{
                background: "var(--code-bg)", padding: 10, borderRadius: 6,
                fontSize: 11, color: "var(--text-muted)",
                fontFamily: "'JetBrains Mono',monospace",
                whiteSpace: "pre-wrap", wordBreak: "break-word",
                maxHeight: 200, overflow: "auto",
              }}>{JSON.stringify(verdict, null, 2)}</pre>
            )}
            {verdict && typeof verdict !== "object" && (
              <DetailRow label="Verdict" value={verdict} />
            )}
          </div>
        )}
      </div>
    </div>
  );
}


// ---------------------------------------------------------------------
// Generic event-details modal — shows the parsed JSON payload for any
// event the user clicks in the activity feed. For llm_call events we
// reuse the rich LLMCallCard rendering (already expanded).
// ---------------------------------------------------------------------

function EventDetailsModal({ event, runStart, onClose }) {
  useEffect(() => {
    const onKey = (e) => { if (e.key === "Escape") onClose(); };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  const data = parseEventData(event);
  const isLLM = event.event_type === "llm_call";

  return (
    <div onClick={onClose} style={{
      position: "fixed", inset: 0,
      background: "rgba(0,0,0,0.6)",
      display: "flex", alignItems: "center", justifyContent: "center",
      zIndex: 1000, padding: 20, backdropFilter: "blur(4px)",
    }}>
      <div onClick={e => e.stopPropagation()} style={{
        background: "var(--bg-elevated)", border: "1px solid var(--border)",
        borderRadius: 14, padding: 20, maxWidth: 760, width: "100%",
        maxHeight: "85vh", overflow: "auto",
        boxShadow: "0 20px 60px rgba(0,0,0,0.6)",
      }}>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", marginBottom: 14, gap: 10 }}>
          <div>
            <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 4 }}>
              <span style={{
                fontSize: 9, fontWeight: 700,
                color: "#a78bfa",
                letterSpacing: "1.5px",
                fontFamily: "'JetBrains Mono',monospace",
                background: "rgba(167,139,250,0.1)",
                padding: "3px 8px", borderRadius: 4,
              }}>{(event.event_type || "event").toUpperCase()}</span>
              {event.stage && (
                <span style={{
                  fontSize: 9, fontWeight: 700,
                  color: "var(--text-muted)",
                  letterSpacing: "1.5px",
                  fontFamily: "'JetBrains Mono',monospace",
                }}>{event.stage}</span>
              )}
              <span style={{
                fontSize: 9, color: "var(--text-subtle)",
                fontFamily: "'JetBrains Mono',monospace",
              }}>+{fmtRelTime(event.timestamp, runStart)}</span>
            </div>
            <div style={{
              fontSize: 10, color: "var(--text-faint)",
              fontFamily: "'JetBrains Mono',monospace",
            }}>{new Date(event.timestamp * 1000).toLocaleString()}</div>
          </div>
          <button onClick={onClose} title="Close (Esc)" style={{
            background: "transparent", border: "1px solid var(--border)",
            color: "var(--text-muted)", fontSize: 14, width: 30, height: 30,
            borderRadius: 8, cursor: "pointer", display: "flex",
            alignItems: "center", justifyContent: "center", flexShrink: 0,
          }}>×</button>
        </div>

        {isLLM ? (
          // Reuse the LLM card rendering, pre-expanded.
          <LLMCallCard call={{ ...data, timestamp: event.timestamp }} runStart={runStart} defaultExpanded />
        ) : (
          <div style={{
            fontSize: 11, lineHeight: 1.6,
            fontFamily: "'JetBrains Mono',monospace",
            background: "var(--code-bg)",
            border: "1px solid var(--border-subtle)",
            padding: 12, borderRadius: 6,
            color: "var(--text)",
          }}>
            <JsonView value={data} />
          </div>
        )}
      </div>
    </div>
  );
}


// ---------------------------------------------------------------------
// Run detail view (the main visualization, with real data)
// ---------------------------------------------------------------------

export { DetailsModal, EventDetailsModal };
