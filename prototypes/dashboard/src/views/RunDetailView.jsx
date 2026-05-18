// Run detail page: stage status, experiments, training, logs, LLM trace.

import { useState, useEffect, useCallback } from "react";
import { API } from "../api.js";
import { STAGES_ORDER, TAG_COLORS } from "../constants.js";
import { Card, Row, StatusPill } from "../primitives.jsx";
import { ScoreChart, ExperimentTree } from "../Experiments.jsx";
import { PipelineIndicator, PipelineDagPanel } from "../PipelineDag.jsx";
import { LLMTracePanel } from "../LLMTrace.jsx";
import { TrainingPanel } from "../TrainingPanel.jsx";
import { ResearchLogPanel, GitLogPanel, ConsolePanel } from "../LogPanels.jsx";
import { DetailsModal, EventDetailsModal } from "../modals.jsx";
import { useRunSSE } from "../useRunSSE.js";
import {
  fmtDuration, fmtRelTime, fmtScore, fmtTokens,
  parseEventData, eventToItem, getColor, getIcon,
} from "../format.js";

function RunDetailView({ runId, onBack }) {
  const [summary, setSummary] = useState(null);
  const [stage, setStage] = useState("hillclimb");
  const [selStep, setSelStep] = useState(null);
  // "activity" = structured event feed, "console" = raw stdout/stderr tail.
  // Default to "console" because the activity feed is sparse during setup
  // and the console gives the strongest "something is happening" signal.
  const [feedTab, setFeedTab] = useState("console");
  const [showDetails, setShowDetails] = useState(false);
  const [selectedEvent, setSelectedEvent] = useState(null);
  const [dagExpanded, setDagExpanded] = useState(false);
  // Tick once a second so the wall-time display counts up live for runs
  // that are still going. We don't actually read `now` anywhere — the
  // state change is just there to force a re-render so fmtDuration's
  // internal Date.now() picks up.
  const [, setNow] = useState(Date.now());
  useEffect(() => {
    if (summary?.run?.status !== "running") return;
    const t = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(t);
  }, [summary?.run?.status]);

  const fetchSummary = useCallback(() => {
    API.getSummary(runId).then(setSummary).catch(() => {});
  }, [runId]);

  useEffect(() => { fetchSummary(); }, [fetchSummary]);

  const handleSse = useCallback((type, _data) => {
    // For all event types just refetch the bundle. Cheap on localhost,
    // and avoids any merge-state bugs in the prototype.
    fetchSummary();
  }, [fetchSummary]);

  useRunSSE(runId, handleSse);

  // SSE-fallback polling. The EventBus is process-local — runs launched
  // outside the web server's process (e.g. via pytest or another shell)
  // never publish to the bus this dashboard is subscribed to, so SSE only
  // gets heartbeats. Poll the summary every 3s while the run is active so
  // the DAG / stages still reflect SQLite truth in near-real-time.
  useEffect(() => {
    if (summary?.run?.status !== "running") return;
    const t = setInterval(fetchSummary, 3000);
    return () => clearInterval(t);
  }, [summary?.run?.status, fetchSummary]);

  if (!summary) {
    return (
      <div style={{ flex: 1, display: "flex", alignItems: "center", justifyContent: "center", color: "var(--text-subtle)" }}>
        Loading run…
      </div>
    );
  }

  const { run, stages, experiments, peak, events } = summary;
  const stageMap = Object.fromEntries(stages.map(s => [s.stage_name, s]));
  const activeStageKey = (() => {
    for (const s of STAGES_ORDER) {
      if (stageMap[s.key]?.status === "active") return s.key;
    }
    return stage;  // user-selected, falls back if no active
  })();

  // Activity feed for the currently selected stage
  const activity = events
    .filter(ev => ev.stage === stage || (stage === "hillclimb" && (ev.event_type === "experiment_recorded" || ev.stage === "hillclimb_test" || ev.stage === "proposal" || ev.stage === "implement")))
    .map(eventToItem)
    .reverse();

  const selExp = selStep !== null ? experiments.find(e => e.step === selStep) : (experiments.length ? experiments[experiments.length - 1] : null);

  return (
    <div style={{
      flex: 1, display: "flex", flexDirection: "column",
      // When the inline DAG is expanded the header section grows tall enough
      // to push the body below the viewport — switch to page-level scrolling
      // so the user can scroll past the DAG to reach the body underneath.
      overflow: dagExpanded ? "auto" : "hidden",
    }}>
      {showDetails && <DetailsModal run={run} peak={peak} onClose={() => setShowDetails(false)} />}
      {selectedEvent && <EventDetailsModal event={selectedEvent} runStart={run.started_at} onClose={() => setSelectedEvent(null)} />}
      {/* Top bar */}
      <div style={{ padding: "9px 24px", borderBottom: "1px solid var(--border)", display: "flex", alignItems: "center", justifyContent: "space-between", flexShrink: 0 }}>
        <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
          <button onClick={onBack} style={{
            background: "transparent", border: "1px solid var(--border)",
            color: "var(--text-muted)", fontSize: 11, padding: "4px 10px",
            borderRadius: 6, cursor: "pointer", fontFamily: "'JetBrains Mono',monospace",
          }}>← back</button>
          <StatusPill status={run.status} />
          <span style={{ fontSize: 14, fontWeight: 600 }}>{run.id.slice(0, 8)}…</span>
          <span style={{ fontSize: 11, color: "var(--text-muted)", fontFamily: "'JetBrains Mono',monospace" }}>
            {run.mode}
          </span>
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
          <span style={{ fontSize: 11, color: "var(--text-faint)", fontFamily: "'JetBrains Mono',monospace" }}>
            PEAK: <span style={{ color: "#22d3ee", fontWeight: 700, fontSize: 14 }}>
              {peak ? Number(peak.score).toFixed(4) : "—"}
            </span>
          </span>
          {run.status === "running" && (
            <button onClick={() => API.cancelRun(runId).then(fetchSummary)} style={{
              background: "rgba(248,113,113,0.1)", border: "1px solid rgba(248,113,113,0.3)",
              color: "#fca5a5", fontSize: 12, fontWeight: 600,
              padding: "6px 14px", borderRadius: 8, cursor: "pointer",
            }}>Cancel Run</button>
          )}
        </div>
      </div>

      {/* Task + Stats */}
      <div style={{ flexShrink: 0, padding: "12px 24px 0" }}>
        <Card style={{ padding: "12px 18px", marginBottom: 8 }}>
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", flexWrap: "wrap", gap: 10 }}>
            <div style={{ display: "flex", alignItems: "center", gap: 10, flex: 1, minWidth: 240 }}>
              <span style={{ fontSize: 9, fontWeight: 700, color: "var(--text-faint)", letterSpacing: "1.5px", fontFamily: "'JetBrains Mono',monospace" }}>TASK</span>
              <span style={{ fontSize: 12, color: "var(--text-muted)", fontStyle: "italic" }}>{run.task}</span>
            </div>
            {run.target_accuracy !== null && (
              <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
                <span style={{ fontSize: 9, color: "var(--text-faint)", fontFamily: "'JetBrains Mono',monospace", fontWeight: 600 }}>TARGET</span>
                <span style={{ background: "rgba(34,211,238,0.1)", color: "#22d3ee", fontSize: 10, fontWeight: 600, padding: "2px 8px", borderRadius: 4, fontFamily: "'JetBrains Mono',monospace" }}>{run.target_accuracy}</span>
              </div>
            )}
            <button onClick={() => setShowDetails(true)} style={{
              background: "transparent", border: "1px solid var(--border)",
              color: "var(--text-muted)", fontSize: 10, fontWeight: 700,
              padding: "4px 12px", borderRadius: 6, cursor: "pointer",
              fontFamily: "'JetBrains Mono',monospace", letterSpacing: "1px",
              flexShrink: 0,
            }}>DETAILS</button>
          </div>
        </Card>

        <div style={{ display: "grid", gridTemplateColumns: "repeat(4,1fr)", gap: 8, marginBottom: 8 }}>
          <Card style={{ padding: "12px 16px" }}>
            <div style={{ fontSize: 8, fontWeight: 700, color: "var(--text-faint)", letterSpacing: "1.5px", fontFamily: "'JetBrains Mono',monospace", marginBottom: 4 }}>BEST SCORE</div>
            <span style={{ fontSize: 24, fontWeight: 700, fontFamily: "'JetBrains Mono',monospace" }}>
              {peak ? Number(peak.score).toFixed(4) : "—"}
            </span>
            {peak && (
              <span style={{ fontSize: 10, color: "var(--text-subtle)", marginLeft: 8 }}>
                step {peak.step} ({peak.lower_is_better ? "lower" : "higher"})
              </span>
            )}
          </Card>
          <Card style={{ padding: "12px 16px" }}>
            <div style={{ fontSize: 8, fontWeight: 700, color: "var(--text-faint)", letterSpacing: "1.5px", fontFamily: "'JetBrains Mono',monospace", marginBottom: 4 }}>WALL TIME</div>
            <span style={{ fontSize: 24, fontWeight: 700, fontFamily: "'JetBrains Mono',monospace" }}>
              {fmtDuration(run.started_at, run.completed_at)}
            </span>
            <span style={{ fontSize: 10, color: run.status === "running" ? "#22d3ee" : "var(--text-subtle)", marginLeft: 8 }}>
              {run.status}
            </span>
          </Card>
          <Card style={{ padding: "12px 16px" }}>
            <div style={{ fontSize: 8, fontWeight: 700, color: "var(--text-faint)", letterSpacing: "1.5px", fontFamily: "'JetBrains Mono',monospace", marginBottom: 4 }}>EXPERIMENTS</div>
            <span style={{ fontSize: 24, fontWeight: 700, fontFamily: "'JetBrains Mono',monospace" }}>
              {peak ? `${peak.kept_count}/${peak.kept_count + peak.reverted_count}` : "0"}
            </span>
            <span style={{ fontSize: 10, color: "var(--text-subtle)", marginLeft: 8 }}>kept</span>
          </Card>
          <Card style={{ padding: "12px 16px" }}>
            <div style={{ fontSize: 8, fontWeight: 700, color: "var(--text-faint)", letterSpacing: "1.5px", fontFamily: "'JetBrains Mono',monospace", marginBottom: 4 }}>LLM USAGE</div>
            <span style={{ fontSize: 24, fontWeight: 700, fontFamily: "'JetBrains Mono',monospace", color: "#4ade80" }}>
              {run.total_cost_usd != null ? `$${Number(run.total_cost_usd).toFixed(3)}` : "$0.000"}
            </span>
            <span style={{ fontSize: 10, color: "var(--text-subtle)", marginLeft: 8 }}>
              {fmtTokens((run.total_prompt_tokens || 0) + (run.total_completion_tokens || 0) + (run.total_reasoning_tokens || 0))} tok · {run.total_llm_calls || 0} calls
            </span>
          </Card>
        </div>

        {/* Pipeline — collapsed by default to a single "current stage"
            chip. Click the toggle to expand the inline DAG panel below
            without disturbing the rest of the layout. */}
        <PipelineIndicator
          stageMap={stageMap}
          activeStageKey={activeStageKey}
          selectedStage={stage}
          onSelectStage={setStage}
          expanded={dagExpanded}
          onToggle={() => setDagExpanded(v => !v)}
        />
        {dagExpanded && (
          <PipelineDagPanel
            stageMap={stageMap}
            activeStageKey={activeStageKey}
            selectedStage={stage}
            onSelectStage={setStage}
          />
        )}
      </div>

      {/* Two-column body. minHeight floor keeps it visible even when the
          inline DAG above it grows tall — the page scrolls instead of
          letting flex squeeze the body to zero. */}
      <div style={{ flex: 1, display: "flex", overflow: "hidden", minHeight: 500 }}>
        <div style={{ width: 380, minWidth: 320, borderRight: "1px solid var(--border)", display: "flex", flexDirection: "column", flexShrink: 0 }}>
          {/* Tabs: Console / LLM / Activity / Research / Git (Training
              graph lives in the right pane when the user selects the
              Training pipeline stage) */}
          <div style={{ display: "flex", padding: "8px 12px 0", gap: 4, borderBottom: "1px solid var(--border-subtle)", flexWrap: "wrap" }}>
            {[
              { key: "console",  label: "Console" },
              { key: "llm",      label: "LLM" },
              { key: "activity", label: "Activity" },
              { key: "research", label: "Research" },
              { key: "git",      label: "Git" },
            ].map(t => {
              const isSel = feedTab === t.key;
              return (
                <button key={t.key} onClick={() => setFeedTab(t.key)} style={{
                  padding: "6px 14px", borderRadius: "6px 6px 0 0",
                  fontSize: 11, fontWeight: 600, cursor: "pointer",
                  fontFamily: "'JetBrains Mono',monospace",
                  border: "none", borderBottom: isSel ? "2px solid #818cf8" : "2px solid transparent",
                  background: "transparent",
                  color: isSel ? "#a5b4fc" : "var(--text-subtle)",
                  marginBottom: -1,
                }}>{t.label}</button>
              );
            })}
            <div style={{ flex: 1 }} />
            {feedTab === "activity" && (
              <div style={{ alignSelf: "center", fontSize: 9, color: "var(--text-faint)", paddingBottom: 6, fontFamily: "'JetBrains Mono',monospace" }}>
                stage: {stage}
              </div>
            )}
          </div>

          {/* Console pane */}
          {feedTab === "console" && (
            <ConsolePanel runId={runId} isRunning={run.status === "running"} />
          )}

          {/* Research log pane */}
          {feedTab === "research" && (
            <ResearchLogPanel runId={runId} isRunning={run.status === "running"} />
          )}

          {/* Git log pane */}
          {feedTab === "git" && (
            <GitLogPanel runId={runId} isRunning={run.status === "running"} />
          )}

          {/* LLM trace pane */}
          {feedTab === "llm" && (
            <LLMTracePanel events={events} runStart={run.started_at} />
          )}

          {/* Activity feed pane */}
          {feedTab === "activity" && <>
          <div style={{ padding: "10px 14px 8px", borderBottom: "1px solid var(--border-subtle)" }}>
            <div style={{ fontSize: 11, fontWeight: 700 }}>Agent Activity — {stage}</div>
            <div style={{ fontSize: 9, color: "var(--text-faint)", marginTop: 2 }}>
              {activity.length} events · latest first
            </div>
          </div>
          <div style={{ flex: 1, overflow: "auto", padding: "4px 0" }}>
            {activity.length === 0 && (
              <div style={{ padding: 18, color: "var(--text-faint)", fontSize: 11 }}>
                No events for this stage yet.
              </div>
            )}
            {activity.map((item, i) => (
              <div key={`${stage}-${i}`}
                onClick={() => setSelectedEvent(item.ev)}
                title="Click for full event payload"
                style={{
                  display: "flex", gap: 7, padding: "5px 14px",
                  borderLeft: `2px solid ${getColor(item)}`, marginLeft: 12,
                  cursor: "pointer",
                  transition: "background 0.1s",
                }}
                onMouseEnter={e => { e.currentTarget.style.background = "var(--surface)"; }}
                onMouseLeave={e => { e.currentTarget.style.background = "transparent"; }}
              >
                <span style={{ fontSize: 9, width: 14, height: 14, borderRadius: 4, display: "flex", alignItems: "center", justifyContent: "center", flexShrink: 0, background: "var(--surface)", color: getColor(item), fontFamily: "'JetBrains Mono',monospace", fontWeight: 700 }}>
                  {getIcon(item.type)}
                </span>
                <div style={{ flex: 1, minWidth: 0 }}>
                  <div style={{
                    fontSize: 11, color: getColor(item), lineHeight: 1.5,
                    fontFamily: item.type === "score" ? "'JetBrains Mono',monospace" : "inherit",
                    fontWeight: (item.type === "score" || item.type === "critic") ? 600 : 400,
                    wordBreak: "break-word",
                  }}>{item.msg}</div>
                </div>
                <span style={{ fontSize: 8, color: "var(--text-faint)", fontFamily: "'JetBrains Mono',monospace", flexShrink: 0 }}>
                  {fmtRelTime(item.t, run.started_at)}
                </span>
              </div>
            ))}
          </div>
          </>}
        </div>

        <div style={{ flex: 1, overflow: "auto", padding: "14px 20px", display: "flex", flexDirection: "column" }}>
          {/* Stage-specific right-pane content:
                Training        → live metrics chart + training.log tail
                Hill-climb etc. → score chart + experiment tree
                everything else → a tiny key/value summary card
          */}
          {stage === "training" ? (
            <Card style={{ padding: 0, flex: 1, overflow: "hidden", display: "flex", flexDirection: "column" }}>
              <div style={{ padding: "14px 18px 8px", borderBottom: "1px solid var(--border)" }}>
                <div style={{ fontSize: 11, fontWeight: 700 }}>TRAINING</div>
                <div style={{ fontSize: 9, color: "var(--text-faint)", marginTop: 2, fontFamily: "'JetBrains Mono',monospace" }}>
                  workspace/training.log · live
                </div>
              </div>
              <TrainingPanel runId={runId} isRunning={run.status === "running"} />
            </Card>
          ) : stage === "hillclimb" || stage === "proposal" || stage === "implement" || stage === "hillclimb_test" ? (
            <>
              <Card style={{ padding: 18, marginBottom: 12 }}>
                <div style={{ fontSize: 11, fontWeight: 700, marginBottom: 8 }}>PERFORMANCE TRAJECTORY</div>
                <ScoreChart experiments={experiments} />
              </Card>
              <Card style={{ padding: 18 }}>
                <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 10 }}>
                  <div style={{ fontSize: 11, fontWeight: 700 }}>EXPERIMENT TREE</div>
                  <div style={{ display: "flex", gap: 10, fontSize: 9, fontFamily: "'JetBrains Mono',monospace" }}>
                    <span style={{ color: "#22d3ee" }}>kept</span>
                    <span style={{ color: "#f87171" }}>reverted</span>
                  </div>
                </div>
                <ExperimentTree experiments={experiments} selected={selStep} onSelect={setSelStep} />
                {selExp && (
                  <div style={{ marginTop: 10, padding: 12, borderRadius: 8, background: "var(--surface)", border: "1px solid var(--border-subtle)" }}>
                    <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 4 }}>
                      <div>
                        <span style={{ fontSize: 11, fontWeight: 700, fontFamily: "'JetBrains Mono',monospace" }}>
                          {selExp.step === 0 ? "Baseline" : `Iter ${selExp.step}`}
                        </span>
                        <span style={{ color: selExp.kept ? "#4ade80" : "#f87171", fontSize: 9, marginLeft: 6 }}>
                          {selExp.kept ? "KEPT" : "REVERTED"}
                        </span>
                        {selExp.tag && (
                          <span style={{ color: TAG_COLORS[selExp.tag] || "#666", fontSize: 8, marginLeft: 6, background: "var(--surface)", padding: "1px 5px", borderRadius: 3 }}>
                            {selExp.tag}
                          </span>
                        )}
                      </div>
                      <div style={{ fontSize: 18, fontWeight: 700, fontFamily: "'JetBrains Mono',monospace", color: selExp.kept ? "#22d3ee" : "#f87171" }}>
                        {fmtScore(selExp.score)}
                      </div>
                    </div>
                    <div style={{ fontSize: 10, color: "var(--text-subtle)", whiteSpace: "pre-wrap" }}>
                      {selExp.proposal || "(no proposal recorded)"}
                    </div>
                  </div>
                )}
              </Card>
            </>
          ) : (
            <div>
              <h3 style={{ fontSize: 14, fontWeight: 700, marginBottom: 12 }}>{stage}</h3>
              <Card style={{ padding: 16 }}>
                <Row label="Status" value={stageMap[stage]?.status || "—"} />
                <Row label="Started" value={stageMap[stage]?.started_at ? fmtRelTime(stageMap[stage].started_at, run.started_at) : "—"} />
                <Row label="Completed" value={stageMap[stage]?.completed_at ? fmtRelTime(stageMap[stage].completed_at, run.started_at) : "—"} />
                {stageMap[stage]?.attempt > 0 && (
                  <Row label="Attempt" value={`${stageMap[stage].attempt} / ${stageMap[stage].max_attempts}`} />
                )}
              </Card>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

export { RunDetailView };
