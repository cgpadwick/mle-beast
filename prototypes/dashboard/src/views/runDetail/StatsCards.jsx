// Task description card + 4-up stats row (best score, wall time,
// experiments kept, LLM usage).

import { Card } from "../../primitives.jsx";
import { fmtDuration, fmtTokens } from "../../format.js";

function StatsCards({ run, peak, onShowDetails }) {
  return (
    <div style={{ flexShrink: 0, padding: "12px 24px 0" }}>
      <Card style={{ padding: "12px 18px", marginBottom: 8 }}>
        <div style={{
          display: "flex", justifyContent: "space-between", alignItems: "center",
          flexWrap: "wrap", gap: 10,
        }}>
          <div style={{
            display: "flex", alignItems: "center", gap: 10, flex: 1, minWidth: 240,
          }}>
            <span style={{
              fontSize: 9, fontWeight: 700, color: "var(--text-faint)",
              letterSpacing: "1.5px",
              fontFamily: "'JetBrains Mono',monospace",
            }}>TASK</span>
            <span style={{
              fontSize: 12, color: "var(--text-muted)", fontStyle: "italic",
            }}>{run.task}</span>
          </div>
          {run.target_accuracy !== null && (
            <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
              <span style={{
                fontSize: 9, color: "var(--text-faint)",
                fontFamily: "'JetBrains Mono',monospace", fontWeight: 600,
              }}>TARGET</span>
              <span style={{
                background: "rgba(34,211,238,0.1)", color: "#22d3ee",
                fontSize: 10, fontWeight: 600, padding: "2px 8px",
                borderRadius: 4, fontFamily: "'JetBrains Mono',monospace",
              }}>{run.target_accuracy}</span>
            </div>
          )}
          <button onClick={onShowDetails} style={{
            background: "transparent", border: "1px solid var(--border)",
            color: "var(--text-muted)", fontSize: 10, fontWeight: 700,
            padding: "4px 12px", borderRadius: 6, cursor: "pointer",
            fontFamily: "'JetBrains Mono',monospace", letterSpacing: "1px",
            flexShrink: 0,
          }}>DETAILS</button>
        </div>
      </Card>

      <div style={{
        display: "grid", gridTemplateColumns: "repeat(4,1fr)",
        gap: 8, marginBottom: 8,
      }}>
        <StatCard label="BEST SCORE"
                  value={peak ? Number(peak.score).toFixed(4) : "—"}
                  hint={peak && `step ${peak.step} (${peak.lower_is_better ? "lower" : "higher"})`}
        />
        <StatCard label="WALL TIME"
                  value={fmtDuration(run.started_at, run.completed_at)}
                  hint={run.status}
                  hintColor={run.status === "running" ? "#22d3ee" : "var(--text-subtle)"}
        />
        <StatCard label="EXPERIMENTS"
                  value={peak ? `${peak.kept_count}/${peak.kept_count + peak.reverted_count}` : "0"}
                  hint="kept"
        />
        <StatCard label="LLM USAGE"
                  valueColor="#4ade80"
                  value={run.total_cost_usd != null
                    ? `$${Number(run.total_cost_usd).toFixed(3)}`
                    : "$0.000"}
                  hint={`${fmtTokens(
                    (run.total_prompt_tokens || 0)
                    + (run.total_completion_tokens || 0)
                    + (run.total_reasoning_tokens || 0),
                  )} tok · ${run.total_llm_calls || 0} calls`}
        />
      </div>
    </div>
  );
}

// Internal helper — keeps the four stat cards visually consistent.
function StatCard({ label, value, hint, hintColor, valueColor }) {
  return (
    <Card style={{ padding: "12px 16px" }}>
      <div style={{
        fontSize: 8, fontWeight: 700, color: "var(--text-faint)",
        letterSpacing: "1.5px",
        fontFamily: "'JetBrains Mono',monospace", marginBottom: 4,
      }}>{label}</div>
      <span style={{
        fontSize: 24, fontWeight: 700,
        fontFamily: "'JetBrains Mono',monospace",
        color: valueColor || "inherit",
      }}>{value}</span>
      {hint && (
        <span style={{
          fontSize: 10, color: hintColor || "var(--text-subtle)", marginLeft: 8,
        }}>{hint}</span>
      )}
    </Card>
  );
}

export { StatsCards };
