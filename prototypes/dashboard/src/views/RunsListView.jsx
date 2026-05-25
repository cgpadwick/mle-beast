// Runs list page: live runs as cards, archived runs as rows.

import { useState, useEffect, useCallback } from "react";
import { API } from "../api.js";
import { cardBase } from "../constants.js";
import { Card, StatusPill, SectionHeader } from "../primitives.jsx";
import { fmtDuration, fmtScore, fmtTokens } from "../format.js";

const PAGE_SIZE = 50;

const pageBtnStyle = (disabled) => ({
  background: "transparent",
  border: "1px solid var(--border)",
  color: disabled ? "var(--text-faint)" : "var(--text-muted)",
  fontSize: 11, fontWeight: 600,
  padding: "6px 12px", borderRadius: 7,
  cursor: disabled ? "default" : "pointer",
  opacity: disabled ? 0.5 : 1,
  fontFamily: "'JetBrains Mono',monospace",
});

function RunsListView({ onOpen, onNew, onHome }) {
  const [runs, setRuns] = useState([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(0);   // 0-based; page 0 holds the newest runs
  const [loading, setLoading] = useState(true);
  const [version, setVersion] = useState(null);

  const refresh = useCallback(() => {
    setLoading(true);
    API.listRuns(PAGE_SIZE, page * PAGE_SIZE)
      .then(d => { setRuns(d.runs || []); setTotal(d.total || 0); })
      .finally(() => setLoading(false));
  }, [page]);

  useEffect(() => {
    refresh();
    const t = setInterval(refresh, 5000);  // gentle live-refresh of the current page
    return () => clearInterval(t);
  }, [refresh]);

  // Version is static for the session — fetch once.
  useEffect(() => {
    API.getVersion().then(d => setVersion(d?.version)).catch(() => {});
  }, []);

  const pageCount = Math.max(1, Math.ceil(total / PAGE_SIZE));
  // Active runs are the newest, so they only ever appear on page 0.
  const liveCount = page === 0
    ? runs.filter(r => r.status === "running" || r.status === "pending").length
    : 0;

  const handleDelete = useCallback((run) => {
    const label = (run.task || run.id.slice(0, 8)).slice(0, 60);
    if (!confirm(`Delete this run?\n\n${label}\n\nThis removes its history and can't be undone.`)) return;
    API.deleteRun(run.id).then(refresh).catch(() => {});
  }, [refresh]);

  return (
    <div style={{ flex: 1, overflow: "auto" }}>
      {/* Hero banner — wordmark + tagline + run summary. The
          right-hand SS branding image was removed when this project
          went open-source; the banner is now left-aligned only. */}
      <div style={{
        position: "relative",
        height: 144,
        marginBottom: 16,
        background: "var(--hero-bg)",
        borderBottom: "1px solid var(--hero-border)",
        overflow: "hidden",
      }}>
        <div style={{
          position: "relative", zIndex: 1,
          display: "flex", alignItems: "center",
          gap: 20, padding: "0 28px", height: "100%",
        }}>
          {/* Left: logo + mle-beast wordmark + tagline. Logo is the
              gravitational-waves visualization with binary black holes;
              object-fit: cover keeps them visible at this aspect ratio.
              Glow shadow kept from the prior gradient cube. Click →
              navigate to launch page (no-op when already here, but
              keeps the "logo is home" affordance consistent with the
              sidebar logo). */}
          <div style={{ display: "flex", alignItems: "center", gap: 14, minWidth: 0 }}>
            <button
              onClick={onHome}
              title="Go to runs list"
              style={{
                width: 56, height: 56, borderRadius: 14,
                overflow: "hidden",
                boxShadow: "0 4px 16px rgba(139,92,246,0.5)",
                background: "#000",
                flexShrink: 0,
                border: "none",
                padding: 0,
                cursor: "pointer",
              }}
            >
              <img
                src="/logo.jpg"
                alt="mle-beast"
                style={{ width: "100%", height: "100%", objectFit: "cover", display: "block" }}
              />
            </button>

            <div style={{ minWidth: 0, textAlign: "left" }}>
              <h1 style={{
                fontSize: 30, fontWeight: 800,
                letterSpacing: "-0.02em", lineHeight: 1.0,
                marginBottom: 6,
                background: "var(--hero-wordmark)",
                WebkitBackgroundClip: "text",
                WebkitTextFillColor: "transparent",
                backgroundClip: "text",
                color: "transparent",
                textShadow: "var(--hero-text-shadow)",
              }}>mle-beast</h1>
              <div style={{
                fontSize: 11, color: "var(--hero-text)",
                fontFamily: "'JetBrains Mono',monospace",
                letterSpacing: "0.5px",
                display: "flex", alignItems: "center", gap: 8, flexWrap: "nowrap",
                textShadow: "var(--hero-subtext-shadow)",
              }}>
                <span>autonomous ML research agent</span>
                {version && (
                  <>
                    <span style={{ color: "var(--hero-text-faint)" }}>·</span>
                    <span title="mle-beast version">v{version}</span>
                  </>
                )}
                <span style={{ color: "var(--hero-text-faint)" }}>·</span>
                <span>{loading && !total ? "loading…" : `${total} runs`}</span>
                {liveCount > 0 && (
                  <>
                    <span style={{ color: "var(--hero-text-faint)" }}>·</span>
                    <span style={{ color: "var(--accent-info)", fontWeight: 700 }}>
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

      {!loading && total === 0 && (
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
                <SectionHeader label="Active" count={live.length} accent="var(--accent-info)" />
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
                  <RunTableHeader />
                  {archived.map((r, i) => (
                    <RunRowArchived
                      key={r.id} run={r} onOpen={onOpen} onDelete={handleDelete}
                      isLast={i === archived.length - 1}
                    />
                  ))}
                </div>
              </div>
            )}
          </>
        );
      })()}

      {/* Pagination — only when there's more than one page. Page 0 holds the
          newest runs (incl. any active), so paging back browses history. */}
      {total > PAGE_SIZE && (
        <div style={{
          display: "flex", alignItems: "center", justifyContent: "space-between",
          marginTop: 16, fontFamily: "'JetBrains Mono',monospace",
        }}>
          <span style={{ fontSize: 11, color: "var(--text-muted)" }}>
            Showing {page * PAGE_SIZE + 1}–{Math.min((page + 1) * PAGE_SIZE, total)} of {total}
          </span>
          <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
            <button
              onClick={() => setPage(p => Math.max(0, p - 1))}
              disabled={page === 0}
              style={pageBtnStyle(page === 0)}
            >← Prev</button>
            <span style={{ fontSize: 11, color: "var(--text-muted)" }}>
              Page {page + 1} / {pageCount}
            </span>
            <button
              onClick={() => setPage(p => p + 1)}
              disabled={page + 1 >= pageCount}
              style={pageBtnStyle(page + 1 >= pageCount)}
            >Next →</button>
          </div>
        </div>
      )}
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
          background: "linear-gradient(90deg, transparent, var(--accent-info), transparent)",
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
          <span style={{ fontSize: 16, fontWeight: 700, color: "var(--accent-info)", fontFamily: "'JetBrains Mono',monospace" }}>
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
            <span style={{ color: "var(--status-warn-fg)" }}>${Number(run.total_cost_usd).toFixed(2)}</span>
          )}
          <span>{fmtDuration(run.started_at, run.completed_at)}</span>
        </span>
      </div>
    </button>
  );
}

// Column header for the Past-runs table. Widths/gap/padding mirror
// RunRowArchived exactly so the labels line up over their columns.
function RunTableHeader() {
  const base = {
    fontSize: 9, fontWeight: 700, letterSpacing: "1px",
    color: "var(--text-muted)", fontFamily: "'JetBrains Mono',monospace",
    flexShrink: 0,
  };
  return (
    <div style={{
      display: "flex", alignItems: "center", gap: 12,
      padding: "7px 14px", borderBottom: "1px solid var(--border)",
    }}>
      <span style={{ ...base, width: 78 }}>STATUS</span>
      <span style={{ ...base, width: 70 }}>ID</span>
      <span style={{ ...base, flex: 1, minWidth: 0 }}>TASK</span>
      <span style={{ ...base, width: 90, textAlign: "right" }}>PEAK</span>
      <span style={{ ...base, width: 70, textAlign: "right" }}>MODE</span>
      <span style={{ ...base, width: 70, textAlign: "right" }}>TIME</span>
      <span style={{ width: 26, flexShrink: 0 }} />
    </div>
  );
}

function RunRowArchived({ run, onOpen, onDelete, isLast }) {
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
      <span style={{ width: 78, flexShrink: 0, display: "flex", alignItems: "center" }}>
        <StatusPill status={run.status} />
      </span>
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
        color: run.peak ? "var(--accent-info)" : "var(--text-faint)",
        fontFamily: "'JetBrains Mono',monospace", flexShrink: 0, width: 90,
        textAlign: "right",
      }}>
        {run.peak ? Number(run.peak.score).toFixed(4) : "—"}
      </span>
      <span style={{
        fontSize: 11, color: "var(--text-muted)",
        fontFamily: "'JetBrains Mono',monospace", flexShrink: 0, width: 70,
        textAlign: "right",
      }}>{run.mode}</span>
      <span style={{
        fontSize: 11, color: "var(--text-muted)",
        fontFamily: "'JetBrains Mono',monospace", flexShrink: 0, width: 70,
        textAlign: "right",
      }}>{fmtDuration(run.started_at, run.completed_at)}</span>
      {/* Delete affordance. A <span role="button"> (not <button>) so it's
          valid nested inside the row button; stopPropagation keeps the click
          from opening the run. */}
      <span
        role="button"
        tabIndex={0}
        title="Delete this run"
        onClick={(e) => { e.stopPropagation(); onDelete(run); }}
        onKeyDown={(e) => { if (e.key === "Enter" || e.key === " ") { e.stopPropagation(); e.preventDefault(); onDelete(run); } }}
        onMouseEnter={(e) => { e.currentTarget.style.color = "var(--status-fail-fg)"; e.currentTarget.style.background = "rgba(248,113,113,0.14)"; }}
        onMouseLeave={(e) => { e.currentTarget.style.color = "var(--text-muted)"; e.currentTarget.style.background = "transparent"; }}
        style={{
          flexShrink: 0, display: "flex", alignItems: "center", justifyContent: "center",
          width: 26, height: 26, borderRadius: 6, cursor: "pointer",
          color: "var(--text-muted)", background: "transparent", transition: "all 0.12s",
        }}
      >
        <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor"
             strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
          <path d="M3 6h18M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2" />
          <line x1="10" y1="11" x2="10" y2="17" />
          <line x1="14" y1="11" x2="14" y2="17" />
        </svg>
      </span>
    </button>
  );
}

// ---------------------------------------------------------------------
// New run view
// ---------------------------------------------------------------------

export { RunsListView };
