// Stage-scoped activity event feed (extracted from FeedTabs so the
// rendering logic for an individual event row lives on its own).

import { fmtRelTime, getColor, getIcon } from "../../format.js";

function ActivityFeed({ stage, activity, runStart, onSelectEvent }) {
  return (
    <>
      <div style={{
        padding: "10px 14px 8px",
        borderBottom: "1px solid var(--border-subtle)",
      }}>
        <div style={{ fontSize: 11, fontWeight: 700 }}>
          Agent Activity — {stage}
        </div>
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
            onClick={() => onSelectEvent(item.ev)}
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
            <span style={{
              fontSize: 9, width: 14, height: 14, borderRadius: 4,
              display: "flex", alignItems: "center", justifyContent: "center",
              flexShrink: 0, background: "var(--surface)",
              color: getColor(item),
              fontFamily: "'JetBrains Mono',monospace", fontWeight: 700,
            }}>
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
            <span style={{
              fontSize: 8, color: "var(--text-faint)",
              fontFamily: "'JetBrains Mono',monospace", flexShrink: 0,
            }}>
              {fmtRelTime(item.t, runStart)}
            </span>
          </div>
        ))}
      </div>
    </>
  );
}

export { ActivityFeed };
