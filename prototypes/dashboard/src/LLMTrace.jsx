// LLM call trace cards.

import { useState } from "react";
import { cardBase } from "./constants.js";
import { Card } from "./primitives.jsx";
import { MessageContent, JsonView } from "./JsonView.jsx";
import { fmtRelTime, fmtTokens, ROLE_COLOR } from "./format.js";

function LLMCallCard({ call, runStart, defaultExpanded }) {
  const [expanded, setExpanded] = useState(!!defaultExpanded);
  const messages = call.messages || [];
  const responseStr = JSON.stringify(call.response || {}, null, 2);

  // Headline: the LLM's chosen action — for tool-call responses we show
  // the discriminator value (tool name) prominently.
  let headline = call.response_model || "response";
  const r = call.response || {};
  if (r.tool) headline = `${call.response_model} → ${r.tool}`;
  else if (r.type) headline = `${call.response_model} → ${r.type}`;
  else if (r.action) headline = `${call.response_model} → ${r.action}`;

  // The single most-interesting bit of context to peek at when the card
  // is collapsed: the latest user message (typically the previous tool
  // result or the original prompt).
  const lastUser = [...messages].reverse().find(m => m.role === "user");
  const peek = lastUser ? lastUser.content : "";
  const peekShort = peek.length > 240 ? peek.slice(0, 240) + "…" : peek;

  return (
    <div style={{
      ...cardBase, padding: 12, marginBottom: 8,
      borderColor: expanded ? "rgba(167,139,250,0.2)" : "var(--border)",
    }}>
      <div onClick={() => setExpanded(!expanded)} style={{
        display: "flex", justifyContent: "space-between", alignItems: "center",
        cursor: "pointer", gap: 10,
      }}>
        <div style={{ flex: 1, minWidth: 0 }}>
          <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 4 }}>
            <span style={{
              fontSize: 9, color: "var(--text-subtle)",
              fontFamily: "'JetBrains Mono',monospace",
            }}>{fmtRelTime(call.timestamp, runStart)}</span>
            <span style={{
              fontSize: 11, fontWeight: 700, color: "#a78bfa",
              fontFamily: "'JetBrains Mono',monospace",
            }}>{headline}</span>
            <span style={{
              fontSize: 9, color: "var(--text-faint)",
              fontFamily: "'JetBrains Mono',monospace",
            }}>{call.duration_ms}ms</span>
          </div>
          {!expanded && peekShort && (
            <div style={{
              fontSize: 11, color: "var(--text-muted)",
              fontStyle: "italic", lineHeight: 1.5,
              overflow: "hidden", textOverflow: "ellipsis",
              display: "-webkit-box", WebkitLineClamp: 2, WebkitBoxOrient: "vertical",
            }}>{peekShort}</div>
          )}
        </div>
        <span style={{ fontSize: 12, color: "var(--text-subtle)", flexShrink: 0 }}>
          {expanded ? "−" : "+"}
        </span>
      </div>

      {expanded && (
        <div style={{ marginTop: 10, paddingTop: 10, borderTop: "1px solid var(--border)" }}>
          {/* Messages */}
          <div style={{ fontSize: 9, fontWeight: 700, color: "var(--text-muted)", letterSpacing: "1.5px", fontFamily: "'JetBrains Mono',monospace", marginBottom: 6 }}>PROMPT (last {messages.length} messages)</div>
          {messages.map((m, i) => (
            <div key={i} style={{ marginBottom: 8 }}>
              <div style={{
                fontSize: 9, fontWeight: 700, color: ROLE_COLOR(m.role),
                letterSpacing: "1px", marginBottom: 3,
                fontFamily: "'JetBrains Mono',monospace",
              }}>{(m.role || "user").toUpperCase()}</div>
              <MessageContent content={m.content || ""} />
            </div>
          ))}

          {/* Response */}
          <div style={{ fontSize: 9, fontWeight: 700, color: "var(--accent-info)", letterSpacing: "1.5px", fontFamily: "'JetBrains Mono',monospace", marginTop: 12, marginBottom: 6 }}>RESPONSE</div>
          <div style={{
            fontSize: 11, lineHeight: 1.6,
            fontFamily: "'JetBrains Mono',monospace",
            background: "rgba(34,211,238,0.04)",
            border: "1px solid rgba(34,211,238,0.15)",
            padding: 10, borderRadius: 5,
            color: "var(--text)",
            maxHeight: 480, overflow: "auto",
          }}>
            <JsonView value={call.response || {}} />
          </div>
        </div>
      )}
    </div>
  );
}

function LLMTracePanel({ events, runStart }) {
  // Pull just the llm_call events; displayed newest-first to match the
  // activity feed convention.
  const calls = events
    .filter(e => e.event_type === "llm_call")
    .map(e => {
      let data = {};
      try { data = JSON.parse(e.data_json || "{}"); } catch {}
      // _eid: the event row's DB primary key — a guaranteed-unique, stable
      // React key (timestamps can collide / round, which would corrupt the
      // per-card expanded state).
      return { ...data, timestamp: e.timestamp, _eid: e.id };
    })
    .reverse();

  if (calls.length === 0) {
    return (
      <div style={{ padding: 18, color: "var(--text-faint)", fontSize: 11, lineHeight: 1.6 }}>
        No LLM calls yet.
        <br /><br />
        Each card here will show what the agent is asking the LLM and the
        structured response it picked — typically a tool call like "read this
        file" or "write model.py". Click a card to expand the full prompt.
      </div>
    );
  }

  return (
    <div style={{ flex: 1, overflow: "auto", padding: "10px 12px" }}>
      {calls.map(c => (
        // Stable per-call key (the event DB id, falling back to timestamp)
        // so a new call streaming in at the top doesn't remount the others
        // and reset their expanded state. All collapsed by default — clicking
        // is the only thing that expands a card, so a new arrival never pops
        // open under you.
        <LLMCallCard
          key={c._eid ?? c.timestamp}
          call={c}
          runStart={runStart}
        />
      ))}
    </div>
  );
}


// ---------------------------------------------------------------------
// Training panel — tails workspace/training.log and plots metrics live
// ---------------------------------------------------------------------

export { LLMCallCard, LLMTracePanel };
