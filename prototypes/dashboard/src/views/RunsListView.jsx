// Runs list page: live runs as cards, archived runs as rows.

import { useState, useEffect, useCallback } from "react";
import { API } from "../api.js";
import { cardBase } from "../constants.js";
import { Card, StatusPill, SectionHeader } from "../primitives.jsx";
import { fmtDuration, fmtScore, fmtTokens } from "../format.js";

function RunsListView({ onOpen, onNew }) {
  const [runs, setRuns] = useState([]);
  const [loading, setLoading] = useState(true);

  const refresh = useCallback(() => {
    setLoading(true);
    API.listRuns().then(setRuns).finally(() => setLoading(false));
  }, []);

  useEffect(() => {
    refresh();
    const t = setInterval(refresh, 5000);  // gentle live-refresh of the list
    return () => clearInterval(t);
  }, [refresh]);

  const liveCount = runs.filter(r => r.status === "running" || r.status === "pending").length;

  return (
    <div style={{ flex: 1, overflow: "auto" }}>
      {/* Hero banner — wordmark + tagline + run summary. The
          right-hand SS branding image was removed when this project
          went open-source; the banner is now left-aligned only. */}
      <div style={{
        position: "relative",
        height: 144,
        marginBottom: 16,
        backgroundColor: "#000",
        overflow: "hidden",
      }}>
        <div style={{
          position: "relative", zIndex: 1,
          display: "flex", alignItems: "center",
          gap: 20, padding: "0 28px", height: "100%",
        }}>
          {/* Left: text cluster (cube + mle-beast wordmark + tagline) */}
          <div style={{ display: "flex", alignItems: "center", gap: 14, minWidth: 0 }}>
            <div style={{
              width: 56, height: 56, borderRadius: 14,
              background: "linear-gradient(135deg, #6366f1 0%, #8b5cf6 50%, #d946ef 100%)",
              display: "flex", alignItems: "center", justifyContent: "center",
              boxShadow: "0 4px 16px rgba(139,92,246,0.5)",
              flexShrink: 0,
            }}>
              <svg width="32" height="32" viewBox="0 0 20 20" fill="none">
                <path d="M10 2L18 7V13L10 18L2 13V7L10 2Z" fill="white" opacity="0.95" />
                <path d="M10 7L14 9.5V14L10 16.5L6 14V9.5L10 7Z" fill="#6366f1" />
              </svg>
            </div>

            <div style={{ minWidth: 0, textAlign: "left" }}>
              <h1 style={{
                fontSize: 30, fontWeight: 800,
                letterSpacing: "-0.02em", lineHeight: 1.0,
                marginBottom: 6,
                background: "linear-gradient(135deg, #ffffff 0%, #c4b5fd 100%)",
                WebkitBackgroundClip: "text",
                WebkitTextFillColor: "transparent",
                backgroundClip: "text",
                color: "transparent",
                textShadow: "0 2px 10px rgba(0,0,0,0.5)",
              }}>mle-beast</h1>
              <div style={{
                fontSize: 11, color: "rgba(255,255,255,0.75)",
                fontFamily: "'JetBrains Mono',monospace",
                letterSpacing: "0.5px",
                display: "flex", alignItems: "center", gap: 8, flexWrap: "nowrap",
                textShadow: "0 1px 3px rgba(0,0,0,0.6)",
              }}>
                <span>autonomous ML research agent</span>
                <span style={{ color: "rgba(255,255,255,0.4)" }}>·</span>
                <span>{loading ? "loading…" : `${runs.length} runs`}</span>
                {liveCount > 0 && (
                  <>
                    <span style={{ color: "rgba(255,255,255,0.4)" }}>·</span>
                    <span style={{ color: "#22d3ee", fontWeight: 700 }}>
                      {liveCount} active
                    </span>
                  </>
                )}
              </div>
            </div>
          </div>

        </div>
      </div>

      <div style={{ padding: "0 28px 24px" }}>
      {/* Top action bar — New Run is the only primary action on this page. */}
      <div style={{
        display: "flex", justifyContent: "flex-end", alignItems: "center",
        marginBottom: 16,
      }}>
        <button onClick={onNew} style={{
          background: "linear-gradient(135deg,rgba(34,211,238,0.95),rgba(129,140,248,0.95))",
          border: "none", color: "#08090e", fontSize: 12, fontWeight: 700,
          padding: "8px 16px", borderRadius: 8, cursor: "pointer",
          boxShadow: "0 3px 10px rgba(34,211,238,0.3)",
        }}>+ New Run</button>
      </div>

      {!loading && runs.length === 0 && (
        <Card style={{ padding: 32, textAlign: "center" }}>
          <div style={{ fontSize: 13, color: "var(--text-muted)", marginBottom: 12 }}>No runs yet.</div>
          <button onClick={onNew} style={{
            background: "rgba(99,102,241,0.15)", color: "#a5b4fc", border: "1px solid rgba(99,102,241,0.3)",
            fontSize: 12, fontWeight: 600, padding: "8px 16px", borderRadius: 8, cursor: "pointer",
          }}>Create your first run →</button>
        </Card>
      )}

      {/* Split runs by status: live ones up top in big cards (with a
          pulse on running ones); everything else collapses into a
          compact row format below. The list page should communicate
          "this is what's happening now" before "here's history". */}
      {(() => {
        const live = runs.filter(r => r.status === "running" || r.status === "pending");
        const archived = runs.filter(r => r.status !== "running" && r.status !== "pending");
        return (
          <>
            {live.length > 0 && (
              <div style={{ marginBottom: 24 }}>
                <SectionHeader label="Active" count={live.length} accent="#22d3ee" />
                <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(380px, 1fr))", gap: 10 }}>
                  {live.map(r => (
                    <RunCardLive key={r.id} run={r} onOpen={onOpen} />
                  ))}
                </div>
              </div>
            )}
            {archived.length > 0 && (
              <div>
                <SectionHeader label="Past" count={archived.length} />
                <div style={{ ...cardBase, padding: 0, overflow: "hidden" }}>
                  {archived.map((r, i) => (
                    <RunRowArchived
                      key={r.id} run={r} onOpen={onOpen}
                      isLast={i === archived.length - 1}
                    />
                  ))}
                </div>
              </div>
            )}
          </>
        );
      })()}
      </div>
    </div>
  );
}
function RunCardLive({ run, onOpen }) {
  const isRunning = run.status === "running";
  const peak = run.peak;
  return (
    <button onClick={() => onOpen(run.id)}
      style={{
        ...cardBase, padding: 14, textAlign: "left",
        cursor: "pointer", color: "inherit", fontFamily: "inherit",
        position: "relative", overflow: "hidden",
        borderColor: isRunning ? "rgba(34,211,238,0.35)" : "var(--border)",
        boxShadow: isRunning ? "0 0 12px rgba(34,211,238,0.15)" : "none",
      }}>
      {isRunning && (
        <div style={{
          position: "absolute", top: 0, left: 0, right: 0, height: 2,
          background: "linear-gradient(90deg, transparent, #22d3ee, transparent)",
          backgroundSize: "200% 100%",
          animation: "shimmer 2s linear infinite",
        }} />
      )}
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 8 }}>
        <span style={{ fontSize: 11, color: "var(--text-subtle)", fontFamily: "'JetBrains Mono',monospace" }}>
          {run.id.slice(0, 8)}…
        </span>
        <StatusPill status={run.status} />
      </div>
      <div style={{ fontSize: 13, fontWeight: 600, lineHeight: 1.4, marginBottom: 8, minHeight: 36 }}>
        {(run.task || "").slice(0, 100) || "(no task description)"}
      </div>
      {peak && (
        <div style={{ display: "flex", alignItems: "baseline", gap: 8, marginBottom: 8 }}>
          <span style={{ fontSize: 9, fontWeight: 700, letterSpacing: "1.5px", color: "var(--text-faint)", fontFamily: "'JetBrains Mono',monospace" }}>BEST</span>
          <span style={{ fontSize: 16, fontWeight: 700, color: "#22d3ee", fontFamily: "'JetBrains Mono',monospace" }}>
            {Number(peak.score).toFixed(4)}
          </span>
          <span style={{ fontSize: 9, color: "var(--text-faint)", fontFamily: "'JetBrains Mono',monospace" }}>
            @ step {peak.step} · {peak.kept_count}k / {peak.reverted_count}r
          </span>
        </div>
      )}
      <div style={{ display: "flex", justifyContent: "space-between", fontSize: 10, color: "var(--text-subtle)", fontFamily: "'JetBrains Mono',monospace" }}>
        <span>{run.mode}</span>
        <span style={{ display: "flex", gap: 10 }}>
          {(run.total_cost_usd ?? 0) > 0 && (
            <span style={{ color: "#fbbf24" }}>${Number(run.total_cost_usd).toFixed(2)}</span>
          )}
          <span>{fmtDuration(run.started_at, run.completed_at)}</span>
        </span>
      </div>
    </button>
  );
}

function RunRowArchived({ run, onOpen, isLast }) {
  // Compact single-line row for completed/failed/cancelled runs. Less
  // visual weight per row so a long history scans quickly.
  return (
    <button onClick={() => onOpen(run.id)} style={{
      width: "100%", padding: "9px 14px", display: "flex", alignItems: "center",
      gap: 12, cursor: "pointer", background: "transparent",
      border: "none", borderBottom: isLast ? "none" : "1px solid var(--border-subtle)",
      color: "inherit", fontFamily: "inherit", textAlign: "left",
    }}
    onMouseEnter={e => { e.currentTarget.style.background = "var(--surface-strong)"; }}
    onMouseLeave={e => { e.currentTarget.style.background = "transparent"; }}
    >
      <StatusPill status={run.status} />
      <span style={{
        fontSize: 11, color: "var(--text-subtle)",
        fontFamily: "'JetBrains Mono',monospace", flexShrink: 0, width: 70,
      }}>{run.id.slice(0, 8)}</span>
      <span style={{
        fontSize: 12, color: "var(--text-muted)", flex: 1, minWidth: 0,
        overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap",
      }}>{run.task || "(no task description)"}</span>
      {/* Peak score column — empty when no kept-with-score experiments. */}
      <span style={{
        fontSize: 11, fontWeight: 700,
        color: run.peak ? "#22d3ee" : "var(--text-faint)",
        fontFamily: "'JetBrains Mono',monospace", flexShrink: 0, width: 90,
        textAlign: "right",
      }}>
        {run.peak ? Number(run.peak.score).toFixed(4) : "—"}
      </span>
      <span style={{
        fontSize: 10, color: "var(--text-faint)",
        fontFamily: "'JetBrains Mono',monospace", flexShrink: 0, width: 70,
        textAlign: "right",
      }}>{run.mode}</span>
      <span style={{
        fontSize: 10, color: "var(--text-faint)",
        fontFamily: "'JetBrains Mono',monospace", flexShrink: 0, width: 70,
        textAlign: "right",
      }}>{fmtDuration(run.started_at, run.completed_at)}</span>
    </button>
  );
}

// ---------------------------------------------------------------------
// New run view
// ---------------------------------------------------------------------

export { RunsListView };
