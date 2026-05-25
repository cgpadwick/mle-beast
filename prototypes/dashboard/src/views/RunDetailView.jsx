// Run detail page — coordinates state and composes the panels.
//
// Panels live in ./runDetail/:
//   RunHeader    — top bar (back, status, active stage, peak, cancel)
//   StatsCards   — task description + 4 stat cards
//   FeedTabs     — left pane (Console / LLM / Activity / Research / Git)
//   StagePanel   — right pane (training / hill-climb / generic)

import { useState, useEffect, useCallback } from "react";

import { API } from "../api.js";
import { STAGES_ORDER } from "../constants.js";
import { PipelineIndicator, PipelineDagPanel } from "../PipelineDag.jsx";
import { DetailsModal, EventDetailsModal } from "../modals.jsx";
import { useRunSSE } from "../useRunSSE.js";
import { eventToItem } from "../format.js";

import { RunHeader } from "./runDetail/RunHeader.jsx";
import { StatsCards } from "./runDetail/StatsCards.jsx";
import { FeedTabs } from "./runDetail/FeedTabs.jsx";
import { StagePanel } from "./runDetail/StagePanel.jsx";

// Banner shown when a run carries an error_message (failed runs, and the
// rare cancelled-with-cause). Without this the error was captured in the
// DB and returned by the API but never rendered — a failed run looked
// like a status pill and nothing else. The message is often a multi-line
// traceback, so render it in a scrollable monospace block. The heading
// tracks the run's status so a cancelled-with-cause run doesn't claim it
// "failed".
function FailureBanner({ status, message }) {
  if (!message) return null;
  const heading = status === "cancelled" ? "Run cancelled" : "Run failed";
  return (
    <div style={{
      margin: "12px 24px 0", padding: "12px 14px",
      background: "rgba(248,113,113,0.08)",
      border: "1px solid rgba(248,113,113,0.35)",
      borderRadius: 8,
    }}>
      <div style={{
        display: "flex", alignItems: "center", gap: 8,
        color: "var(--status-fail-fg)", fontWeight: 700, fontSize: 12,
        marginBottom: 8,
      }}>
        <span aria-hidden style={{ fontSize: 13 }}>✗</span>
        {heading}
      </div>
      <pre style={{
        margin: 0, maxHeight: 220, overflow: "auto",
        whiteSpace: "pre-wrap", wordBreak: "break-word",
        fontSize: 11, lineHeight: 1.5,
        fontFamily: "'JetBrains Mono',monospace",
        color: "var(--text-muted)",
      }}>{message}</pre>
    </div>
  );
}

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
  // DAG is expanded by default so the first thing a visitor sees is the
  // workflow + active stage in context. The user can collapse it by
  // clicking the stage pill (its chevron flips); there's no separate
  // "DAG" toggle button anymore.
  const [dagExpanded, setDagExpanded] = useState(true);

  // Tick once a second so the wall-time display counts up live while a
  // run is going. The state change forces re-render; fmtDuration reads
  // Date.now() internally.
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

  // SSE: refetch the bundle on any event. Cheap on localhost and avoids
  // merge-state bugs from incremental updates.
  const handleSse = useCallback(() => fetchSummary(), [fetchSummary]);
  useRunSSE(runId, handleSse);

  // SSE-fallback polling. The EventBus is process-local — runs launched
  // outside the web server's process (e.g. via pytest or a separate CLI)
  // never publish to the bus this dashboard is subscribed to, so SSE only
  // delivers heartbeats. Poll the summary every 3s while the run is active
  // so the UI still reflects SQLite truth in near-real-time.
  useEffect(() => {
    if (summary?.run?.status !== "running") return;
    const t = setInterval(fetchSummary, 3000);
    return () => clearInterval(t);
  }, [summary?.run?.status, fetchSummary]);

  if (!summary) {
    return (
      <div style={{
        flex: 1, display: "flex", alignItems: "center", justifyContent: "center",
        color: "var(--text-subtle)",
      }}>
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

  // Activity feed: events for the selected stage. The "hillclimb"
  // pseudo-stage rolls up the proposal/implement/test sub-stages and
  // experiment_recorded events so the user sees the whole iteration.
  const activity = events
    .filter(ev =>
      ev.stage === stage
      || (stage === "hillclimb" && (
        ev.event_type === "experiment_recorded"
        || ev.stage === "hillclimb_test"
        || ev.stage === "proposal"
        || ev.stage === "implement"
      ))
    )
    .map(eventToItem)
    .reverse();

  return (
    <div style={{
      flex: 1, display: "flex", flexDirection: "column",
      // When the inline DAG is expanded the header section grows tall
      // enough to push the body below the viewport — switch to page-level
      // scrolling so the user can scroll past the DAG to reach the body.
      overflow: dagExpanded ? "auto" : "hidden",
    }}>
      {showDetails && (
        <DetailsModal run={run} peak={peak} onClose={() => setShowDetails(false)} />
      )}
      {selectedEvent && (
        <EventDetailsModal
          event={selectedEvent}
          runStart={run.started_at}
          onClose={() => setSelectedEvent(null)}
        />
      )}

      <RunHeader
        run={run}
        runId={runId}
        stageMap={stageMap}
        activeStageKey={activeStageKey}
        peak={peak}
        onBack={onBack}
        onCancel={fetchSummary}
      />

      <FailureBanner status={run.status} message={run.error_message} />

      <StatsCards
        run={run}
        peak={peak}
        onShowDetails={() => setShowDetails(true)}
      />

      {/* Pipeline — DAG expanded by default. Click the stage pill to
          collapse it down to just the current-stage indicator. */}
      <div style={{ flexShrink: 0, padding: "0 24px" }}>
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
          inline DAG above grows tall — the page scrolls instead of
          letting flex squeeze the body to zero. */}
      <div style={{
        flex: 1, display: "flex", overflow: "hidden", minHeight: 500,
      }}>
        <FeedTabs
          runId={runId}
          run={run}
          events={events}
          stage={stage}
          activity={activity}
          feedTab={feedTab}
          onFeedTabChange={setFeedTab}
          onSelectEvent={setSelectedEvent}
        />
        <StagePanel
          runId={runId}
          run={run}
          stage={stage}
          stageMap={stageMap}
          experiments={experiments}
          selStep={selStep}
          onSelectStep={setSelStep}
        />
      </div>
    </div>
  );
}

export { RunDetailView };
