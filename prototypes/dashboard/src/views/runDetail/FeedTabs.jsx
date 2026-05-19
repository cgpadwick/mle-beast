// Left-pane tabbed feeds: Console / LLM / Activity / Research / Git.
// The Training metric chart lives in the right pane (StagePanel) since
// it's keyed by the selected pipeline stage, not by this tab.

import { LLMTracePanel } from "../../LLMTrace.jsx";
import { ResearchLogPanel, GitLogPanel, ConsolePanel } from "../../LogPanels.jsx";
import { ActivityFeed } from "./ActivityFeed.jsx";

const TABS = [
  { key: "console",  label: "Console" },
  { key: "llm",      label: "LLM" },
  { key: "activity", label: "Activity" },
  { key: "research", label: "Research" },
  { key: "git",      label: "Git" },
];

function FeedTabs({
  runId, run, events, stage, activity, feedTab, onFeedTabChange, onSelectEvent,
}) {
  const isRunning = run.status === "running";

  return (
    <div style={{
      width: 380, minWidth: 320, borderRight: "1px solid var(--border)",
      display: "flex", flexDirection: "column", flexShrink: 0,
    }}>
      <div style={{
        display: "flex", padding: "8px 12px 0", gap: 4,
        borderBottom: "1px solid var(--border-subtle)", flexWrap: "wrap",
      }}>
        {TABS.map(t => {
          const isSel = feedTab === t.key;
          return (
            <button key={t.key} onClick={() => onFeedTabChange(t.key)} style={{
              padding: "6px 14px", borderRadius: "6px 6px 0 0",
              fontSize: 11, fontWeight: 600, cursor: "pointer",
              fontFamily: "'JetBrains Mono',monospace",
              border: "none",
              borderBottom: isSel ? "2px solid #818cf8" : "2px solid transparent",
              background: "transparent",
              color: isSel ? "#a5b4fc" : "var(--text-subtle)",
              marginBottom: -1,
            }}>{t.label}</button>
          );
        })}
        <div style={{ flex: 1 }} />
        {feedTab === "activity" && (
          <div style={{
            alignSelf: "center", fontSize: 9, color: "var(--text-faint)",
            paddingBottom: 6, fontFamily: "'JetBrains Mono',monospace",
          }}>
            stage: {stage}
          </div>
        )}
      </div>

      {feedTab === "console"  && <ConsolePanel  runId={runId} isRunning={isRunning} />}
      {feedTab === "research" && <ResearchLogPanel runId={runId} isRunning={isRunning} />}
      {feedTab === "git"      && <GitLogPanel   runId={runId} isRunning={isRunning} />}
      {feedTab === "llm"      && <LLMTracePanel events={events} runStart={run.started_at} />}
      {feedTab === "activity" && (
        <ActivityFeed
          stage={stage}
          activity={activity}
          runStart={run.started_at}
          onSelectEvent={onSelectEvent}
        />
      )}
    </div>
  );
}

export { FeedTabs };
