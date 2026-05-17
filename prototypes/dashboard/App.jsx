import { useState, useEffect, useRef, useCallback } from "react";

// ---------------------------------------------------------------------
// API client
// ---------------------------------------------------------------------

const API = {
  listRuns: () => fetch("/api/runs").then(r => r.json()),
  getSummary: (id) => fetch(`/api/runs/${id}/summary`).then(r => r.json()),
  createRun: (body) => fetch("/api/runs", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  }).then(r => r.json()),
  cancelRun: (id) => fetch(`/api/runs/${id}/cancel`, { method: "POST" }).then(r => r.json()),
  detectLocalModel: () => fetch("/api/local-model-name").then(r => r.json()),
};

// ---------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------

const STAGES_ORDER = [
  { key: "setup", name: "Setup" },
  { key: "data_analysis", name: "Data Analysis" },
  { key: "data_analysis_critic", name: "Data Analysis Critic" },
  { key: "baseline", name: "Baseline" },
  { key: "testing", name: "Testing" },
  { key: "training", name: "Training" },
  { key: "train_finder", name: "Train Finder" },
  { key: "train_finder_critic", name: "Train Finder Critic" },
  { key: "analysis", name: "Analysis" },
  { key: "evaluate", name: "Evaluate" },
  { key: "eval_finder", name: "Eval Finder" },
  { key: "eval_finder_critic", name: "Eval Finder Critic" },
  { key: "proposal", name: "Proposal" },
  { key: "proposal_critic", name: "Proposal Critic" },
  { key: "implement", name: "Implement" },
  { key: "hillclimb_test", name: "Hill-climb Test" },
];

const TAG_COLORS = {
  MODEL: "#818cf8",
  FEATURE: "#f59e0b",
  HYPERPARAM: "#22d3ee",
  DATA: "#4ade80",
  ENSEMBLE: "#f472b6",
};

const cardBase = {
  background: "var(--surface)",
  border: "1px solid var(--border)",
  borderRadius: 14,
};

// ---------------------------------------------------------------------
// Tiny shared components
// ---------------------------------------------------------------------

function Card({ children, style }) {
  return <div style={{ ...cardBase, ...style }}>{children}</div>;
}

function Row({ label, value, accent }) {
  return (
    <div style={{ display: "flex", justifyContent: "space-between", padding: "7px 0", borderBottom: "1px solid var(--border-subtle)" }}>
      <span style={{ fontSize: 12, color: "var(--text-subtle)" }}>{label}</span>
      <span style={{ fontSize: 12, color: accent ? "#22d3ee" : "var(--text-muted)", fontWeight: accent ? 700 : 400, fontFamily: "'JetBrains Mono',monospace" }}>{value}</span>
    </div>
  );
}

function StatusPill({ status }) {
  const colors = {
    running:   { bg: "rgba(34,211,238,0.1)",  fg: "#22d3ee" },
    pending:   { bg: "var(--surface-strong)", fg: "var(--text-muted)" },
    completed: { bg: "rgba(74,222,128,0.1)",  fg: "#4ade80" },
    failed:    { bg: "rgba(248,113,113,0.1)", fg: "#f87171" },
    cancelled: { bg: "rgba(248,113,113,0.08)", fg: "#fbbf24" },
  };
  const c = colors[status] || colors.pending;
  return (
    <span style={{
      background: c.bg, color: c.fg, fontSize: 9, fontWeight: 700,
      padding: "3px 9px", borderRadius: 5,
      fontFamily: "'JetBrains Mono',monospace",
      letterSpacing: "0.5px",
    }}>{(status || "pending").toUpperCase()}</span>
  );
}

function fmtDuration(start, end) {
  if (!start) return "—";
  const finish = end || Date.now() / 1000;
  const sec = Math.max(0, Math.floor(finish - start));
  const h = Math.floor(sec / 3600);
  const m = Math.floor((sec % 3600) / 60);
  const s = sec % 60;
  return `${String(h).padStart(2, "0")}:${String(m).padStart(2, "0")}:${String(s).padStart(2, "0")}`;
}

function fmtRelTime(ts, runStart) {
  if (!ts || !runStart) return "";
  const sec = Math.max(0, Math.floor(ts - runStart));
  const m = Math.floor(sec / 60);
  const s = sec % 60;
  return `${String(m).padStart(2, "0")}:${String(s).padStart(2, "0")}`;
}

function fmtScore(score) {
  if (score === null || score === undefined) return "—";
  return Number(score).toFixed(4);
}

function fmtTokens(n) {
  if (!n) return "0";
  if (n >= 1_000_000) return (n / 1_000_000).toFixed(2) + "M";
  if (n >= 1_000) return (n / 1_000).toFixed(1) + "K";
  return String(n);
}

// ---------------------------------------------------------------------
// Charts / visualizations (take experiments as a prop now)
// ---------------------------------------------------------------------

function ScoreChart({ experiments }) {
  const kept = experiments.filter(e => e.kept && e.score !== null);
  if (kept.length < 1) {
    return (
      <div style={{ height: 170, display: "flex", alignItems: "center", justifyContent: "center", color: "var(--text-faint)", fontSize: 12 }}>
        No scored experiments yet
      </div>
    );
  }
  const w = 480, h = 170, pL = 48, pR = 20, pT = 18, pB = 28;
  const cw = w - pL - pR, ch = h - pT - pB;
  const allScores = experiments.filter(e => e.score !== null).map(e => e.score);
  const minS = Math.min(...allScores) - 0.02;
  const maxS = Math.max(...allScores) + 0.02;
  const span = Math.max(0.001, maxS - minS);
  const toX = (i) => pL + (kept.length === 1 ? cw / 2 : (i / (kept.length - 1)) * cw);
  const toY = (s) => pT + ch - ((s - minS) / span) * ch;
  const pts = kept.map((e, i) => `${toX(i)},${toY(e.score)}`).join(" ");
  const area = `${toX(0)},${pT + ch} ${pts} ${toX(kept.length - 1)},${pT + ch}`;

  // Grid lines at sensible round values within range.
  const gridStep = span < 0.1 ? 0.02 : span < 0.5 ? 0.05 : 0.1;
  const gridStart = Math.ceil(minS / gridStep) * gridStep;
  const gridLines = [];
  for (let v = gridStart; v <= maxS; v += gridStep) gridLines.push(v);

  return (
    <svg viewBox={`0 0 ${w} ${h}`} style={{ width: "100%" }}>
      <defs>
        <linearGradient id="aGrad" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stopColor="#22d3ee" stopOpacity="0.14" />
          <stop offset="100%" stopColor="#22d3ee" stopOpacity="0" />
        </linearGradient>
      </defs>
      {gridLines.map(t => (
        <g key={t}>
          <line x1={pL} y1={toY(t)} x2={w - pR} y2={toY(t)} style={{ stroke: "var(--border)" }} />
          <text x={pL - 8} y={toY(t) + 3.5} style={{ fill: "var(--text-faint)" }} fontSize="9" textAnchor="end" fontFamily="'JetBrains Mono',monospace">{t.toFixed(2)}</text>
        </g>
      ))}
      <polygon points={area} fill="url(#aGrad)" />
      <polyline points={pts} fill="none" stroke="#22d3ee" strokeWidth="2.5" strokeLinejoin="round" />
      {kept.map((e, i) => (
        <circle key={e.step} cx={toX(i)} cy={toY(e.score)} r="4" fill="#0a0c14" stroke="#22d3ee" strokeWidth="2" />
      ))}
      {experiments.filter(e => !e.kept && e.score !== null).map(e => {
        const pi = kept.findIndex(k => k.step === e.parent_step);
        if (pi < 0) return null;
        return (
          <g key={`rv${e.step}`}>
            <line x1={toX(pi)} y1={toY(kept[pi].score)} x2={toX(pi) + 14} y2={toY(e.score)} stroke="#f87171" strokeWidth="1.5" strokeDasharray="4,3" opacity="0.3" />
            <circle cx={toX(pi) + 14} cy={toY(e.score)} r="3" fill="#140c0c" stroke="#f87171" strokeWidth="1.5" />
          </g>
        );
      })}
    </svg>
  );
}

function ExperimentTree({ experiments, selected, onSelect }) {
  if (experiments.length === 0) {
    return (
      <div style={{ height: 220, display: "flex", alignItems: "center", justifyContent: "center", color: "var(--text-faint)", fontSize: 12 }}>
        No experiments yet
      </div>
    );
  }
  const nW = 110, nH = 42, gX = 16, gY = 10;
  const byStep = Object.fromEntries(experiments.map(e => [e.step, e]));
  function getDepth(step) {
    const n = byStep[step];
    if (!n || n.parent_step === null || n.parent_step === undefined) return 0;
    return getDepth(n.parent_step) + 1;
  }
  const dc = {};
  experiments.forEach(e => {
    const d = getDepth(e.step);
    dc[d] = (dc[d] || 0) + 1;
  });
  const pos = {};
  const di = {};
  experiments.forEach(e => {
    const d = getDepth(e.step);
    di[d] = di[d] || 0;
    const total = dc[d] * nW + (dc[d] - 1) * gX;
    const sx = -total / 2;
    pos[e.step] = { x: sx + di[d] * (nW + gX), y: d * (nH + gY) };
    di[d]++;
  });
  const allX = Object.values(pos).map(p => p.x);
  const allY = Object.values(pos).map(p => p.y);
  const vx = Math.min(...allX) - 10;
  const vy = Math.min(...allY) - 6;
  const vw = Math.max(...allX) + nW + 10 - vx;
  const vh = Math.max(...allY) + nH + 6 - vy;

  return (
    <svg viewBox={`${vx} ${vy} ${vw} ${vh}`} style={{ width: "100%", height: Math.min(vh, 320), minHeight: 220 }}>
      <defs>
        <filter id="glow">
          <feGaussianBlur stdDeviation="4" result="b" />
          <feMerge><feMergeNode in="b" /><feMergeNode in="SourceGraphic" /></feMerge>
        </filter>
      </defs>
      {experiments.filter(e => e.parent_step !== null && e.parent_step !== undefined).map(e => {
        const f = pos[e.parent_step]; const t = pos[e.step];
        if (!f || !t) return null;
        const x1 = f.x + nW / 2, y1 = f.y + nH, x2 = t.x + nW / 2, y2 = t.y, mid = (y1 + y2) / 2;
        return (
          <path key={`edge${e.step}`}
            d={`M${x1} ${y1}C${x1} ${mid},${x2} ${mid},${x2} ${y2}`}
            fill="none" stroke={e.kept ? "#22d3ee" : "#f87171"} strokeWidth={e.kept ? 1.5 : 1}
            strokeDasharray={e.kept ? "none" : "5,4"} opacity={e.kept ? 0.3 : 0.18}
          />
        );
      })}
      {experiments.map(e => {
        const p = pos[e.step];
        const isSel = selected === e.step;
        const name = e.step === 0 ? "Baseline" : `Iter ${e.step}`;
        return (
          <g key={e.step} onClick={() => onSelect(e.step)} style={{ cursor: "pointer" }}>
            <rect x={p.x} y={p.y} width={nW} height={nH} rx={8}
              fill={!e.kept ? "rgba(127,29,29,0.12)" : isSel ? "rgba(34,211,238,0.07)" : "var(--surface)"}
              stroke={!e.kept ? "rgba(248,113,113,0.25)" : isSel ? "rgba(34,211,238,0.4)" : "var(--surface-strong)"}
              strokeWidth={isSel ? 1.5 : 1} filter={isSel ? "url(#glow)" : undefined}
            />
            <text x={p.x + 7} y={p.y + 14} fill={!e.kept ? "#fca5a5" : "var(--text-subtle)"} fontSize="8" fontWeight="600" fontFamily="'JetBrains Mono',monospace">{name}</text>
            <text x={p.x + 7} y={p.y + 30} fill={!e.kept ? "#f87171" : "#22d3ee"} fontSize="13" fontWeight="700" fontFamily="'JetBrains Mono',monospace">{fmtScore(e.score)}</text>
            {!e.kept && <text x={p.x + nW - 7} y={p.y + 14} fill="#f87171" fontSize="7" textAnchor="end" fontFamily="'JetBrains Mono',monospace">x</text>}
            {e.kept && e.step > 0 && <text x={p.x + nW - 7} y={p.y + 14} fill="#4ade80" fontSize="7" textAnchor="end" fontFamily="'JetBrains Mono',monospace">ok</text>}
          </g>
        );
      })}
    </svg>
  );
}

// ---------------------------------------------------------------------
// Activity feed (events table → renderable items)
// ---------------------------------------------------------------------

function parseEventData(ev) {
  try { return JSON.parse(ev.data_json || "{}"); } catch { return {}; }
}

function eventToItem(ev) {
  // ev = { id, run_id, timestamp, event_type, stage, data_json }
  // Returns a display item that also carries the raw ev so a click
  // handler can pop a details modal with the full payload.
  const data = parseEventData(ev);
  const t = ev.timestamp;
  const stage = ev.stage || "system";
  let item;
  switch (ev.event_type) {
    case "stage_started":
      item = { stage, type: "system", msg: `Starting ${stage}` }; break;
    case "stage_completed":
      item = { stage, type: "system", msg: `${stage}: ${data.outcome || "done"}` }; break;
    case "tool_executed":
      item = { stage, type: "actor", msg: `${data.tool_name || "tool"}: ${(data.result_preview || "").slice(0, 100)}` }; break;
    case "retry_occurred":
      item = { stage, type: "critic", msg: `Retry ${data.attempt}/${data.max_attempts}: ${(data.feedback || "").slice(0, 100)}`, verdict: false }; break;
    case "log_message":
      item = { stage, type: "system", msg: data.message || "" }; break;
    case "llm_call":
      const tool = data.response?.tool || data.response?.action || data.response?.type || "";
      item = { stage, type: "actor", msg: `LLM call · ${data.response_model || ""}${tool ? " → " + tool : ""}` }; break;
    case "experiment_recorded":
      const desc = data.kept ? "KEPT" : "REVERTED";
      const score = data.score !== null && data.score !== undefined ? Number(data.score).toFixed(4) : "—";
      item = {
        stage: "hillclimb",
        type: data.kept ? "score" : "critic",
        msg: `Step ${data.step} ${desc}: score=${score}`,
        verdict: data.kept,
      }; break;
    case "run_state_changed":
      item = { stage, type: "system", msg: `${data.old_state} → ${data.new_state}` }; break;
    default:
      item = { stage, type: "system", msg: ev.event_type };
  }
  item.t = t;
  item.ev = ev;
  item.data = data;
  return item;
}

function getColor(item) {
  if (item.type === "critic") return item.verdict ? "#4ade80" : "#f87171";
  if (item.type === "score") {
    if (item.delta && item.delta.startsWith("-")) return "#f87171";
    if (item.msg && item.msg.includes("Final")) return "#fbbf24";
    if (item.delta) return "#22d3ee";
    return "var(--text-muted)";
  }
  if (item.type === "actor") return "#c4b5fd";
  return "var(--text-faint)";
}

function getIcon(type) {
  if (type === "actor") return "A";
  if (type === "critic") return "C";
  if (type === "score") return "S";
  return "i";
}

// ---------------------------------------------------------------------
// JSON viewer — renders structured data with multi-line string values
// shown as actual newline-rendered code blocks instead of escaped \n.
// ---------------------------------------------------------------------

function _stringNeedsBlock(s) {
  return typeof s === "string" && (s.includes("\n") || s.length > 100);
}

function JsonStringInline({ value }) {
  return (
    <span style={{ color: "#a5f3fc" }}>{JSON.stringify(value)}</span>
  );
}

function JsonStringBlock({ value }) {
  return (
    <pre style={{
      margin: "4px 0 4px 16px", padding: "8px 10px",
      background: "var(--code-bg)",
      border: "1px solid var(--border-subtle)",
      borderRadius: 4,
      color: "var(--text)",
      fontSize: 11, lineHeight: 1.45,
      fontFamily: "'JetBrains Mono',monospace",
      whiteSpace: "pre-wrap", wordBreak: "break-word",
      maxHeight: 360, overflow: "auto",
    }}>{value}</pre>
  );
}

function JsonView({ value, depth = 0, fieldKey }) {
  // Primitives
  if (value === null) return <span style={{ color: "var(--text-muted)" }}>null</span>;
  if (typeof value === "boolean") return <span style={{ color: "#fbbf24" }}>{String(value)}</span>;
  if (typeof value === "number") return <span style={{ color: "#fbbf24" }}>{String(value)}</span>;
  if (typeof value === "string") {
    if (_stringNeedsBlock(value)) {
      return <JsonStringBlock value={value} />;
    }
    return <JsonStringInline value={value} />;
  }

  // Arrays
  if (Array.isArray(value)) {
    if (value.length === 0) return <span style={{ color: "var(--text-muted)" }}>[]</span>;
    return (
      <div style={{ marginLeft: depth === 0 ? 0 : 12 }}>
        <span style={{ color: "var(--text-subtle)" }}>[</span>
        {value.map((v, i) => (
          <div key={i} style={{ marginLeft: 12 }}>
            <JsonView value={v} depth={depth + 1} />
            {i < value.length - 1 && <span style={{ color: "var(--text-faint)" }}>,</span>}
          </div>
        ))}
        <span style={{ color: "var(--text-subtle)" }}>]</span>
      </div>
    );
  }

  // Objects
  if (typeof value === "object") {
    const entries = Object.entries(value);
    if (entries.length === 0) return <span style={{ color: "var(--text-muted)" }}>{"{}"}</span>;
    return (
      <div style={{ marginLeft: depth === 0 ? 0 : 12 }}>
        <span style={{ color: "var(--text-subtle)" }}>{"{"}</span>
        {entries.map(([k, v], i) => {
          const valIsBlock = typeof v === "string" && _stringNeedsBlock(v);
          return (
            <div key={k} style={{ marginLeft: 12 }}>
              <span style={{ color: "#c4b5fd", fontWeight: 600 }}>"{k}"</span>
              <span style={{ color: "var(--text-muted)" }}>: </span>
              {valIsBlock ? (
                <JsonView value={v} depth={depth + 1} />
              ) : (
                <JsonView value={v} depth={depth + 1} />
              )}
              {i < entries.length - 1 && <span style={{ color: "var(--text-faint)" }}>,</span>}
            </div>
          );
        })}
        <span style={{ color: "var(--text-subtle)" }}>{"}"}</span>
      </div>
    );
  }

  return <span>{String(value)}</span>;
}


// ---------------------------------------------------------------------
// LLM trace panel — shows each round-trip to the LLM as a card with
// the prompt context (last few messages) and the structured response.
// ---------------------------------------------------------------------

function ROLE_COLOR(role) {
  if (role === "system") return "var(--text-muted)";
  if (role === "user") return "#fbbf24";
  if (role === "assistant") return "#a78bfa";
  return "var(--text-muted)";
}

function _findJsonInString(s) {
  // Scan for the first balanced {...} or [...] in `s`. Returns
  // {prefix, value, suffix} where value is the parsed object, or null
  // if nothing parseable was found. Walks character-by-character so
  // multi-line strings inside the JSON don't fool the matcher.
  if (typeof s !== "string") return null;
  const startChars = ["{", "["];
  for (let i = 0; i < s.length; i++) {
    const c = s[i];
    if (!startChars.includes(c)) continue;
    const closer = c === "{" ? "}" : "]";
    let depth = 0;
    let inString = false;
    let escape = false;
    for (let j = i; j < s.length; j++) {
      const cj = s[j];
      if (escape) { escape = false; continue; }
      if (cj === "\\") { escape = true; continue; }
      if (cj === "\"") { inString = !inString; continue; }
      if (inString) continue;
      if (cj === c) depth++;
      else if (cj === closer) {
        depth--;
        if (depth === 0) {
          const candidate = s.slice(i, j + 1);
          try {
            const value = JSON.parse(candidate);
            if (typeof value === "object" && value !== null) {
              return {
                prefix: s.slice(0, i),
                value,
                suffix: s.slice(j + 1),
              };
            }
          } catch {}
          break; // failed parse — try next opening brace
        }
      }
    }
  }
  return null;
}

function _renderTextChunk(text, key) {
  // Plain prose chunk between/around JSON blocks. Rendered as a <pre>
  // because tool results often have meaningful indentation.
  const t = (text || "").replace(/^\s*\n+|\n+\s*$/g, "");
  if (!t) return null;
  return (
    <pre key={key} style={{
      fontSize: 11, lineHeight: 1.5, color: "var(--text-muted)",
      fontFamily: "'JetBrains Mono',monospace",
      background: "var(--code-bg)", padding: 8, borderRadius: 5,
      whiteSpace: "pre-wrap", wordBreak: "break-word",
      margin: 0, maxHeight: 320, overflow: "auto",
    }}>{t}</pre>
  );
}

function _renderJsonChunk(obj, key) {
  return (
    <div key={key} style={{
      fontSize: 11, lineHeight: 1.6,
      fontFamily: "'JetBrains Mono',monospace",
      background: "var(--code-bg)", padding: 10, borderRadius: 5,
      color: "var(--text)",
      maxHeight: 360, overflow: "auto",
    }}>
      <JsonView value={obj} />
    </div>
  );
}

function MessageContent({ content }) {
  // Walk the string and split it into a sequence of (prose|json) chunks.
  // Each JSON object/array gets rendered via JsonView (so embedded \n in
  // string values become readable code blocks), and prose between them
  // stays as preformatted text. This catches both pure-JSON messages
  // (assistant tool calls) and prose-with-embedded-JSON (tool results
  // like "Tool result: {...}" or system-prompt fragments).
  if (typeof content !== "string" || !content) {
    return _renderTextChunk("", "empty");
  }

  const chunks = [];
  let remaining = content;
  let key = 0;
  // Cap iterations so a pathological string can't burn CPU.
  for (let i = 0; i < 32; i++) {
    const match = _findJsonInString(remaining);
    if (!match) {
      const pre = _renderTextChunk(remaining, `t${key++}`);
      if (pre) chunks.push(pre);
      break;
    }
    const pre = _renderTextChunk(match.prefix, `t${key++}`);
    if (pre) chunks.push(pre);
    chunks.push(_renderJsonChunk(match.value, `j${key++}`));
    remaining = match.suffix;
  }

  if (chunks.length === 0) {
    chunks.push(_renderTextChunk(content, "fallback"));
  }

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
      {chunks}
    </div>
  );
}

// ---------------------------------------------------------------------
// Pipeline indicator + DAG modal
// ---------------------------------------------------------------------

// Pipeline phases derived from the actual flow graph in full_pipeline.py.
// Each phase has stages that execute in sequence; the DAG modal renders
// these as columns with arrows between them. The hill-climb loop is its
// own phase because it cycles.
const PIPELINE_PHASES = [
  {
    key: "setup",
    name: "Setup & EDA",
    stages: ["setup", "data_analysis", "data_analysis_critic"],
  },
  {
    key: "baseline",
    name: "Baseline",
    stages: ["baseline", "testing"],
    note: "greenfield only — brownfield skips to training",
  },
  {
    key: "train_eval",
    name: "Train → Evaluate",
    stages: [
      "training", "train_finder", "train_finder_critic", "analysis",
      "evaluate", "eval_finder", "eval_finder_critic",
    ],
  },
  {
    key: "hillclimb",
    name: "Hill-climb loop",
    stages: ["proposal", "proposal_critic", "implement", "hillclimb_test"],
    note: "cycles back to Train → Evaluate each iteration",
  },
];

function PipelineIndicator({ stageMap, activeStageKey, selectedStage, onSelectStage, expanded, onToggle }) {
  // Surface the active stage if there is one; otherwise the last completed
  // stage so the indicator isn't blank at start/end of a run.
  let displayKey = activeStageKey;
  let displayState = "active";
  if (!displayKey) {
    // Walk STAGES_ORDER backwards to find the most-recently-completed.
    for (let i = STAGES_ORDER.length - 1; i >= 0; i--) {
      const k = STAGES_ORDER[i].key;
      const s = stageMap[k];
      if (s?.status === "pass" || s?.status === "fail") {
        displayKey = k;
        displayState = s.status;
        break;
      }
    }
  }
  if (!displayKey) {
    displayKey = STAGES_ORDER[0].key;
    displayState = "idle";
  }

  const displayName = STAGES_ORDER.find(s => s.key === displayKey)?.name || displayKey;
  const isActive = displayState === "active";
  const isFail = displayState === "fail";

  let chipStyle;
  if (isActive) {
    chipStyle = {
      background: "linear-gradient(135deg,rgba(129,140,248,0.32),rgba(167,139,250,0.22))",
      border: "1.5px solid rgba(167,139,250,0.7)",
      color: "#ffffff",
      boxShadow: "0 0 14px rgba(129,140,248,0.45)",
      animation: "pipeBreathe 2s ease-in-out infinite",
    };
  } else if (isFail) {
    chipStyle = { background: "rgba(248,113,113,0.10)", border: "1.5px solid rgba(248,113,113,0.35)", color: "#fca5a5" };
  } else if (displayState === "pass") {
    chipStyle = { background: "rgba(74,222,128,0.08)", border: "1.5px solid rgba(74,222,128,0.25)", color: "#86efac" };
  } else {
    chipStyle = { background: "var(--surface)", border: "1.5px solid var(--border)", color: "var(--text-subtle)" };
  }

  return (
    <div style={{ display: "flex", alignItems: "center", gap: 10, paddingBottom: 12, borderBottom: "1px solid var(--border)" }}>
      <span style={{ fontSize: 8, fontWeight: 700, color: "var(--text-faint)", letterSpacing: "1.5px", fontFamily: "'JetBrains Mono',monospace" }}>STAGE</span>
      <button
        onClick={onToggle}
        title={expanded ? "Collapse pipeline DAG" : "Expand pipeline DAG"}
        style={{
          padding: "8px 16px", borderRadius: 8, cursor: "pointer",
          fontSize: 12, fontWeight: 700, fontFamily: "'JetBrains Mono',monospace",
          display: "flex", alignItems: "center", gap: 8,
          ...chipStyle,
        }}
      >
        {isActive && (
          <span style={{
            width: 8, height: 8, borderRadius: "50%",
            background: "#fafafa",
            boxShadow: "0 0 8px rgba(255,255,255,0.9), 0 0 14px rgba(167,139,250,0.6)",
            animation: "pipePulse 1.2s ease-in-out infinite",
          }} />
        )}
        {!isActive && displayState === "pass" && <span style={{ fontSize: 10, color: "rgba(74,222,128,0.7)" }}>✓</span>}
        {!isActive && isFail && <span style={{ fontSize: 10 }}>✗</span>}
        {displayName.toUpperCase()}
      </button>
      <button
        onClick={onToggle}
        title={expanded ? "Collapse pipeline DAG" : "Expand pipeline DAG"}
        style={{
          background: "transparent", border: "1px solid var(--border)",
          color: "var(--text-subtle)", fontSize: 11, fontWeight: 700,
          padding: "4px 10px", borderRadius: 6, cursor: "pointer",
          fontFamily: "'JetBrains Mono',monospace", letterSpacing: "1px",
          display: "flex", alignItems: "center", gap: 6,
        }}
      >
        <span style={{
          display: "inline-block",
          transition: "transform 0.18s ease",
          transform: expanded ? "rotate(90deg)" : "rotate(0deg)",
          fontSize: 9,
        }}>▶</span>
        DAG
      </button>
    </div>
  );
}

// ---------------------------------------------------------------------
// Pipeline DAG modal — SVG canvas with hand-positioned nodes + bezier
// edges. Layout is column-based (one column per pipeline phase) with
// the hill-climb loop drawn as a sweeping back-arrow.
// ---------------------------------------------------------------------

// Single source of truth for node coordinates. Tweak these and the
// edges below redraw automatically. Coordinates are SVG-space; node
// position is the center of the rectangle.
const NODE_W = 176;
const NODE_H = 34;
const DAG_W = 980;
const DAG_H = 500;

const DAG_NODES = {
  // Column 1 — Setup & EDA (center x=110, fits 0-220 band)
  git_setup:            { x: 110, y:  60, col: 0 },
  data_analysis:        { x: 110, y: 120, col: 0 },
  data_analysis_critic: { x: 110, y: 180, col: 0 },

  // Column 2 — Baseline, greenfield only (center x=340, fits 220-440 band)
  baseline:             { x: 340, y: 220, col: 1 },
  testing:              { x: 340, y: 280, col: 1 },

  // Column 3 — Train → Evaluate (center x=570, fits 440-680 band)
  training:             { x: 570, y:  60, col: 2 },
  train_finder:         { x: 570, y: 120, col: 2 },
  train_finder_critic:  { x: 570, y: 180, col: 2 },
  analysis:             { x: 570, y: 240, col: 2 },
  evaluate:             { x: 570, y: 300, col: 2 },
  eval_finder:          { x: 570, y: 360, col: 2 },
  eval_finder_critic:   { x: 570, y: 420, col: 2 },

  // Column 4 — Hill-climb loop (center x=810, fits 680-980 band)
  proposal:             { x: 810, y: 220, col: 3 },
  proposal_critic:      { x: 810, y: 280, col: 3 },
  implement:            { x: 810, y: 340, col: 3 },
  hillclimb_test:       { x: 810, y: 400, col: 3 },

  // Terminal node (decoration only — no DB stage)
  terminal:             { x: 810, y: 470, col: 3 },
};

// "Happy path" edges drawn solid + thick. Format: [from, to, kind].
// kind is one of: "main" (primary flow), "branch" (gate split),
// "loop" (back-edge), "retry" (small reverse arrow, dashed).
const DAG_EDGES = [
  // Setup chain
  ["git_setup",            "data_analysis",        "main"],
  ["data_analysis",        "data_analysis_critic", "main"],

  // Gate split: brownfield skips to training, greenfield goes through baseline
  ["data_analysis_critic", "training",             "branch"],   // brownfield
  ["data_analysis_critic", "baseline",             "branch"],   // greenfield
  ["baseline",             "testing",              "main"],
  ["testing",              "training",             "main"],

  // Train → Evaluate chain
  ["training",             "train_finder",         "main"],
  ["train_finder",         "train_finder_critic",  "main"],
  ["train_finder_critic",  "analysis",             "main"],
  ["analysis",             "evaluate",             "main"],
  ["evaluate",             "eval_finder",          "main"],
  ["eval_finder",          "eval_finder_critic",   "main"],

  // Hand-off into hill-climb loop
  ["eval_finder_critic",   "proposal",             "main"],

  // Hill-climb loop chain
  ["proposal",             "proposal_critic",      "main"],
  ["proposal_critic",      "implement",            "main"],
  ["implement",            "hillclimb_test",       "main"],

  // Loop back: hillclimb_test → training (the big sweep)
  ["hillclimb_test",       "training",             "loop"],

  // Convergence: hillclimb_test → terminal
  ["hillclimb_test",       "terminal",             "main"],
];

function edgePath(from, to, kind) {
  const fx = from.x + NODE_W / 2;        // right edge of source
  const fxL = from.x;                     // left edge of source
  const fy = from.y + NODE_H / 2;        // bottom of source
  const fyT = from.y - NODE_H / 2;        // top of source
  const tx = to.x - NODE_W / 2;          // left edge of target
  const txR = to.x + NODE_W / 2;          // right edge of target
  const ty = to.y - NODE_H / 2;          // top of target
  const tyB = to.y + NODE_H / 2;          // bottom of target

  // Same column → straight vertical
  if (from.col === to.col) {
    if (to.y > from.y) {
      return `M${from.x},${fy} L${to.x},${ty}`;
    } else {
      return `M${from.x},${fyT} L${to.x},${tyB}`;
    }
  }

  // Loop-back: hillclimb_test → training (sweep right then up-left,
  // entering target from its right side so the curve stays within the
  // viewBox and never crosses the phase-header strip at the top).
  if (kind === "loop") {
    const x1 = from.x + NODE_W / 2;          // right edge of source
    const y1 = from.y;                        // center y of source
    const txR = to.x + NODE_W / 2;           // right edge of target
    const ty2 = to.y;                         // center y of target
    const outX = DAG_W - 20;                  // sweep column near right wall
    return [
      `M${x1},${y1}`,
      `C${outX},${y1} ${outX},${ty2} ${txR + 30},${ty2}`,
      `L${txR},${ty2}`,
    ].join(" ");
  }

  // Horizontal-ish edge between columns: cubic bezier
  const sx = from.x + NODE_W / 2;
  const sy = from.y;
  const tx2 = to.x - NODE_W / 2;
  const ty2 = to.y;
  const dx = tx2 - sx;
  const cx1 = sx + dx * 0.45;
  const cx2 = tx2 - dx * 0.45;
  return `M${sx},${sy} C${cx1},${sy} ${cx2},${ty2} ${tx2},${ty2}`;
}

function PipelineDagPanel({ stageMap, activeStageKey, selectedStage, onSelectStage }) {
  // Which edges land on the active stage? Those get the bright animated stroke.
  const activeKey = activeStageKey || null;
  const isActiveEdge = (toKey) => activeKey && toKey === activeKey;

  const phaseHeaders = [
    { x: 110, label: "1. SETUP & EDA" },
    { x: 340, label: "2. BASELINE" },
    { x: 570, label: "3. TRAIN → EVALUATE" },
    { x: 810, label: "4. HILL-CLIMB LOOP" },
  ];

  return (
    <div style={{
      background: "var(--bg-elevated)", border: "1px solid var(--border)",
      borderRadius: 10, padding: 12, marginTop: 10,
    }}>
      <div style={{ fontSize: 10, color: "var(--text-faint)", fontFamily: "'JetBrains Mono',monospace", marginBottom: 8 }}>
        click a node to select
      </div>

        <svg
          viewBox={`0 0 ${DAG_W} ${DAG_H}`}
          preserveAspectRatio="xMidYMid meet"
          width="100%"
          style={{
            display: "block",
            maxHeight: "55vh",
            background: "var(--surface)",
            borderRadius: 10,
          }}
        >
          <defs>
            {/* Gradients */}
            <linearGradient id="nodeActive" x1="0" y1="0" x2="1" y2="1">
              <stop offset="0%"  stopColor="rgba(129,140,248,0.55)" />
              <stop offset="100%" stopColor="rgba(167,139,250,0.35)" />
            </linearGradient>
            <linearGradient id="nodePass" x1="0" y1="0" x2="1" y2="1">
              <stop offset="0%"  stopColor="rgba(74,222,128,0.18)" />
              <stop offset="100%" stopColor="rgba(74,222,128,0.06)" />
            </linearGradient>
            <linearGradient id="nodeFail" x1="0" y1="0" x2="1" y2="1">
              <stop offset="0%"  stopColor="rgba(248,113,113,0.22)" />
              <stop offset="100%" stopColor="rgba(248,113,113,0.06)" />
            </linearGradient>
            <linearGradient id="nodeSel" x1="0" y1="0" x2="1" y2="1">
              <stop offset="0%"  stopColor="rgba(34,211,238,0.20)" />
              <stop offset="100%" stopColor="rgba(34,211,238,0.05)" />
            </linearGradient>

            {/* Edge gradients */}
            <linearGradient id="edgeMain" x1="0" y1="0" x2="1" y2="0">
              <stop offset="0%"   stopColor="rgba(255,255,255,0.55)" />
              <stop offset="100%" stopColor="rgba(255,255,255,0.85)" />
            </linearGradient>
            <linearGradient id="edgeActive" x1="0" y1="0" x2="1" y2="0">
              <stop offset="0%"   stopColor="rgba(129,140,248,0.4)" />
              <stop offset="100%" stopColor="rgba(167,139,250,1.0)" />
            </linearGradient>
            <linearGradient id="edgeLoop" x1="0" y1="0" x2="1" y2="0">
              <stop offset="0%"   stopColor="rgba(251,191,36,0.55)" />
              <stop offset="100%" stopColor="rgba(251,191,36,0.25)" />
            </linearGradient>

            {/* Drop shadow */}
            <filter id="nodeGlow" x="-50%" y="-50%" width="200%" height="200%">
              <feGaussianBlur stdDeviation="6" result="blur" />
              <feMerge>
                <feMergeNode in="blur" />
                <feMergeNode in="SourceGraphic" />
              </feMerge>
            </filter>

            {/* Arrowhead markers */}
            <marker id="arrowMain" viewBox="0 0 10 10" refX="9" refY="5"
                    markerWidth="6" markerHeight="6" orient="auto">
              <path d="M0,0 L10,5 L0,10 z" fill="rgba(255,255,255,0.85)" />
            </marker>
            <marker id="arrowActive" viewBox="0 0 10 10" refX="9" refY="5"
                    markerWidth="6" markerHeight="6" orient="auto">
              <path d="M0,0 L10,5 L0,10 z" fill="rgba(167,139,250,1)" />
            </marker>
            <marker id="arrowLoop" viewBox="0 0 10 10" refX="9" refY="5"
                    markerWidth="6" markerHeight="6" orient="auto">
              <path d="M0,0 L10,5 L0,10 z" fill="rgba(251,191,36,0.85)" />
            </marker>

            {/* Flowing-dash animation for active edges */}
            <style>{`
              @keyframes dagFlow {
                from { stroke-dashoffset: 24; }
                to   { stroke-dashoffset: 0; }
              }
            `}</style>
          </defs>

          {/* Phase column headers */}
          {phaseHeaders.map(h => (
            <text
              key={h.x}
              x={h.x}
              y={28}
              textAnchor="start"
              style={{
                fontSize: 10,
                fontFamily: "'JetBrains Mono', monospace",
                fontWeight: 700,
                letterSpacing: "1.5px",
                fill: "rgba(255,255,255,0.4)",
              }}
            >
              {h.label}
            </text>
          ))}

          {/* Phase column subtle backgrounds for visual grouping */}
          {[
            { x: 0,   w: 220, fill: "rgba(167,139,250,0.025)" },  // setup
            { x: 220, w: 220, fill: "rgba(34,211,238,0.025)" },   // baseline
            { x: 440, w: 240, fill: "rgba(74,222,128,0.025)" },   // train→eval
            { x: 680, w: 300, fill: "rgba(251,191,36,0.030)" },   // hill-climb
          ].map((b, i) => (
            <rect key={i} x={b.x} y={40} width={b.w} height={DAG_H - 60}
                  fill={b.fill} rx={6} />
          ))}

          {/* Edges */}
          {DAG_EDGES.map(([fromKey, toKey, kind]) => {
            const from = DAG_NODES[fromKey];
            const to = DAG_NODES[toKey];
            if (!from || !to) return null;
            const d = edgePath(from, to, kind);
            const lights = isActiveEdge(toKey);
            let stroke, marker, strokeWidth, dasharray, animation;
            if (kind === "loop") {
              stroke = "rgba(251,191,36,0.7)";  // amber, solid
              marker = "url(#arrowLoop)";
              strokeWidth = 2.25;
              dasharray = "6 5";
            } else if (lights) {
              stroke = "url(#edgeActive)";
              marker = "url(#arrowActive)";
              strokeWidth = 3;
              dasharray = "6 6";
              animation = "dagFlow 0.6s linear infinite";
            } else {
              // Solid stroke (not a gradient) — horizontal gradients
              // collapse to nothing on vertical lines because the bbox has
              // zero width, which is why the shafts went invisible.
              stroke = "rgba(255,255,255,0.75)";
              marker = "url(#arrowMain)";
              strokeWidth = 2.25;
              dasharray = kind === "branch" ? "5 4" : "none";
            }
            return (
              <path
                key={`${fromKey}->${toKey}`}
                d={d}
                fill="none"
                stroke={stroke}
                strokeWidth={strokeWidth}
                strokeDasharray={dasharray}
                markerEnd={marker}
                style={animation ? { animation } : undefined}
              />
            );
          })}

          {/* Nodes */}
          {Object.entries(DAG_NODES).map(([key, pos]) => {
            const meta = STAGES_ORDER.find(s => s.key === key);
            const label = meta?.name || (key === "terminal" ? "DONE" : key);
            const s = stageMap[key];
            const isActive = key === activeStageKey || s?.status === "active";
            const isPass = s?.status === "pass";
            const isFail = s?.status === "fail" || s?.status === "error";
            const isSel = key === selectedStage;
            const isTerminal = key === "terminal";

            let fill, stroke, textColor;
            if (isTerminal) {
              fill = "rgba(255,255,255,0.04)";
              stroke = "rgba(255,255,255,0.15)";
              textColor = "rgba(255,255,255,0.45)";
            } else if (isActive) {
              fill = "url(#nodeActive)";
              stroke = "rgba(167,139,250,0.9)";
              textColor = "#ffffff";
            } else if (isFail) {
              fill = "url(#nodeFail)";
              stroke = "rgba(248,113,113,0.55)";
              textColor = "#fca5a5";
            } else if (isPass) {
              fill = "url(#nodePass)";
              stroke = "rgba(74,222,128,0.5)";
              textColor = "#86efac";
            } else if (isSel) {
              fill = "url(#nodeSel)";
              stroke = "rgba(34,211,238,0.55)";
              textColor = "#22d3ee";
            } else {
              fill = "rgba(255,255,255,0.04)";
              stroke = "rgba(255,255,255,0.18)";
              textColor = "rgba(255,255,255,0.6)";
            }

            const cx = pos.x;
            const cy = pos.y;
            const x = cx - NODE_W / 2;
            const y = cy - NODE_H / 2;

            return (
              <g
                key={key}
                onClick={() => !isTerminal && onSelectStage(key)}
                style={{ cursor: isTerminal ? "default" : "pointer" }}
              >
                {isActive && (
                  // Glow ring under active nodes
                  <rect
                    x={x - 4} y={y - 4}
                    width={NODE_W + 8} height={NODE_H + 8}
                    rx={11}
                    fill="none"
                    stroke="rgba(129,140,248,0.45)"
                    strokeWidth={2}
                    filter="url(#nodeGlow)"
                  >
                    <animate
                      attributeName="stroke-opacity"
                      values="0.45;0.85;0.45"
                      dur="1.8s"
                      repeatCount="indefinite"
                    />
                  </rect>
                )}
                <rect
                  x={x} y={y}
                  width={NODE_W} height={NODE_H}
                  rx={8}
                  fill={fill}
                  stroke={stroke}
                  strokeWidth={isActive ? 1.5 : 1}
                />
                {/* Status indicator on the left side */}
                {!isTerminal && isActive && (
                  <circle cx={x + 12} cy={cy} r={4} fill="#ffffff">
                    <animate attributeName="opacity" values="0.4;1;0.4"
                             dur="1.2s" repeatCount="indefinite" />
                  </circle>
                )}
                {!isTerminal && isPass && (
                  <text x={x + 12} y={cy + 3} textAnchor="middle"
                        style={{ fontSize: 11, fill: "rgba(74,222,128,0.85)", fontFamily: "'JetBrains Mono',monospace", fontWeight: 700 }}>
                    ✓
                  </text>
                )}
                {!isTerminal && isFail && (
                  <text x={x + 12} y={cy + 3} textAnchor="middle"
                        style={{ fontSize: 11, fill: "rgba(248,113,113,0.85)", fontFamily: "'JetBrains Mono',monospace", fontWeight: 700 }}>
                    ✗
                  </text>
                )}
                <text
                  x={x + (isTerminal ? NODE_W / 2 : 26)}
                  y={cy + 4}
                  textAnchor={isTerminal ? "middle" : "start"}
                  style={{
                    fontSize: 11,
                    fontFamily: "'JetBrains Mono', monospace",
                    fontWeight: isActive ? 700 : 600,
                    fill: textColor,
                    pointerEvents: "none",
                  }}
                >
                  {label}
                </text>
              </g>
            );
          })}

          {/* Branch labels */}
          <text x={140} y={195} style={{ fontSize: 9, fill: "rgba(255,255,255,0.45)", fontFamily: "'JetBrains Mono',monospace" }}>
            greenfield
          </text>
          <text x={300} y={95} style={{ fontSize: 9, fill: "rgba(255,255,255,0.45)", fontFamily: "'JetBrains Mono',monospace" }}>
            brownfield
          </text>
          <text x={DAG_W - 180} y={DAG_H - 20} style={{ fontSize: 9, fill: "rgba(251,191,36,0.65)", fontFamily: "'JetBrains Mono',monospace", fontWeight: 700 }}>
            ⟲ loop back to training
          </text>
        </svg>

        <div style={{ marginTop: 12, display: "flex", justifyContent: "space-between", alignItems: "center", flexWrap: "wrap", gap: 10, flexShrink: 0 }}>
          <div style={{ fontSize: 10, color: "var(--text-faint)", fontFamily: "'JetBrains Mono',monospace", lineHeight: 1.6 }}>
            Convergence: target met · max_steps reached · max_consecutive_failures.
          </div>
          <div style={{ display: "flex", alignItems: "center", gap: 14, fontSize: 9, fontFamily: "'JetBrains Mono',monospace", color: "var(--text-faint)" }}>
            <span><span style={{ display: "inline-block", width: 10, height: 10, borderRadius: 2, background: "rgba(129,140,248,0.55)", marginRight: 6, verticalAlign: "middle" }} />active</span>
            <span><span style={{ display: "inline-block", width: 10, height: 10, borderRadius: 2, background: "rgba(74,222,128,0.4)", marginRight: 6, verticalAlign: "middle" }} />pass</span>
            <span><span style={{ display: "inline-block", width: 10, height: 10, borderRadius: 2, background: "rgba(248,113,113,0.4)", marginRight: 6, verticalAlign: "middle" }} />fail</span>
            <span><span style={{ display: "inline-block", width: 14, height: 1.5, background: "rgba(251,191,36,0.65)", marginRight: 6, verticalAlign: "middle" }} />loop</span>
          </div>
        </div>
    </div>
  );
}

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
          <div style={{ fontSize: 9, fontWeight: 700, color: "#22d3ee", letterSpacing: "1.5px", fontFamily: "'JetBrains Mono',monospace", marginTop: 12, marginBottom: 6 }}>RESPONSE</div>
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
  // Pull just the llm_call events; ordered oldest → newest for natural reading
  // but we'll display newest first to match the activity feed convention.
  const calls = events
    .filter(e => e.event_type === "llm_call")
    .map(e => {
      let data = {};
      try { data = JSON.parse(e.data_json || "{}"); } catch {}
      return { ...data, timestamp: e.timestamp };
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
      {calls.map((c, i) => (
        <LLMCallCard
          key={`${c.timestamp}-${i}`}
          call={c}
          runStart={runStart}
          defaultExpanded={i === 0}
        />
      ))}
    </div>
  );
}


// ---------------------------------------------------------------------
// Training panel — tails workspace/training.log and plots metrics live
// ---------------------------------------------------------------------

function _parseTrainingLog(text) {
  // training.log accumulates runs across hill-climb iterations — each
  // call to train.py either appends a new "Epoch 1/..." block or
  // overwrites. Tracking all iterations and labeling them turned out to
  // be brittle (cross-iteration overwrites, partial logs) so we just
  // plot the *latest* training run. Heuristic: find the last "Epoch 1"
  // line in the log and parse from there to the end.
  const lines = (text || "").split("\n");
  const epochRe = /\bepoch\s+(\d+)(?:\s*\/\s*(\d+))?/i;
  const kvRe = /([A-Za-z][A-Za-z0-9_]*)\s*[:=]\s*(-?\d+(?:\.\d+)?(?:[eE][+-]?\d+)?)/g;

  // Locate the start of the most recent training run.
  let startIdx = 0;
  for (let i = lines.length - 1; i >= 0; i--) {
    const m = lines[i].match(epochRe);
    if (m && parseInt(m[1], 10) === 1) {
      startIdx = i;
      break;
    }
  }

  const series = {};
  const epochs = [];
  let lastEpoch = 0;

  for (let i = startIdx; i < lines.length; i++) {
    const line = lines[i];
    const em = line.match(epochRe);
    if (em) {
      lastEpoch = parseInt(em[1], 10);
      if (!epochs.includes(lastEpoch)) epochs.push(lastEpoch);
    }
    let m;
    kvRe.lastIndex = 0;
    while ((m = kvRe.exec(line)) !== null) {
      const name = m[1];
      const value = parseFloat(m[2]);
      if (/^(epoch|step|batch|iter|iteration|samples|seen)$/i.test(name)) continue;
      if (!isFinite(value)) continue;
      if (!series[name]) series[name] = [];
      const x = lastEpoch > 0 ? lastEpoch : series[name].length + 1;
      const last = series[name][series[name].length - 1];
      if (last && last.x === x) last.y = value;
      else series[name].push({ x, y: value });
    }
  }

  return { series, epochs };
}

function MetricChart({ series }) {
  const names = Object.keys(series).filter(n => series[n].length > 0);
  if (names.length === 0) return null;

  const w = 480, h = 160, pL = 44, pR = 16, pT = 12, pB = 24;
  const cw = w - pL - pR, ch = h - pT - pB;

  // Group metrics by approximate range so loss (0–2) and accuracy (0–1) plot
  // sanely without one squashing the other. Heuristic: split by name —
  // anything with "loss" / "error" goes on left axis; rest on right axis.
  const lossNames = names.filter(n => /loss|error|nll/i.test(n));
  const otherNames = names.filter(n => !lossNames.includes(n));

  const allX = [].concat(...names.map(n => series[n].map(p => p.x)));
  const minX = Math.min(...allX), maxX = Math.max(...allX);
  const xSpan = Math.max(1, maxX - minX);
  const toX = (x) => pL + ((x - minX) / xSpan) * cw;

  const yRange = (groupNames) => {
    const ys = [].concat(...groupNames.map(n => series[n].map(p => p.y)));
    if (ys.length === 0) return null;
    let lo = Math.min(...ys), hi = Math.max(...ys);
    if (lo === hi) { lo -= 0.05; hi += 0.05; }
    const pad = (hi - lo) * 0.1;
    return { lo: lo - pad, hi: hi + pad };
  };
  const lossY = yRange(lossNames);
  const otherY = yRange(otherNames);
  const toY = (y, group) => {
    const r = group === "loss" ? lossY : otherY;
    if (!r) return pT + ch;
    return pT + ch - ((y - r.lo) / (r.hi - r.lo)) * ch;
  };

  // Stable per-name color so train_loss / val_loss are distinguishable.
  // Loss-family metrics share the left y-axis but each gets its own color
  // from a warm sub-palette; other metrics get cool colors.
  // Visually distinct hues — train_loss vs val_loss should never look similar.
  const lossPalette = ["#f59e0b", "#ef4444", "#facc15", "#ec4899", "#f97316"]; // amber, red, yellow, pink, deep-orange
  const otherPalette = ["#22d3ee", "#a78bfa", "#4ade80", "#a5b4fc", "#67e8f9", "#fda4af", "#34d399"]; // cyan, purple, green, lavender, sky, rose, emerald
  const colorOf = (name) => {
    if (/loss|error|nll/i.test(name)) {
      const i = lossNames.indexOf(name);
      return lossPalette[(i < 0 ? 0 : i) % lossPalette.length];
    }
    const i = otherNames.indexOf(name);
    return otherPalette[(i < 0 ? 0 : i) % otherPalette.length];
  };

  return (
    <svg viewBox={`0 0 ${w} ${h}`} style={{ width: "100%" }}>
      {/* Y-axis grid (left = loss group when present, else right group) */}
      {(lossY || otherY) && (() => {
        const ref = lossY || otherY;
        const lines = [];
        const step = (ref.hi - ref.lo) / 4;
        for (let i = 0; i <= 4; i++) {
          const v = ref.lo + step * i;
          const y = pT + ch - (i / 4) * ch;
          lines.push(
            <g key={`grid${i}`}>
              <line x1={pL} y1={y} x2={w - pR} y2={y} style={{ stroke: "var(--border)" }} />
              <text x={pL - 6} y={y + 3} style={{ fill: "var(--text-faint)" }} fontSize="9" textAnchor="end" fontFamily="'JetBrains Mono',monospace">{v.toFixed(2)}</text>
            </g>
          );
        }
        return lines;
      })()}
      {names.map((n) => {
        const points = series[n];
        const group = /loss|error|nll/i.test(n) ? "loss" : "other";
        const color = colorOf(n);
        const pathStr = points.map((p, j) => `${j === 0 ? "M" : "L"}${toX(p.x)},${toY(p.y, group)}`).join(" ");
        return (
          <g key={n}>
            <path d={pathStr} fill="none" stroke={color} strokeWidth="2" strokeLinejoin="round" />
            {points.map(p => (
              <circle key={`${n}-${p.x}`} cx={toX(p.x)} cy={toY(p.y, group)} r="2.5" fill="#0a0c14" stroke={color} strokeWidth="1.5" />
            ))}
          </g>
        );
      })}
    </svg>
  );
}

function TrainingPanel({ runId, isRunning }) {
  const [text, setText] = useState("");
  const [exists, setExists] = useState(true);
  const offsetRef = useRef(0);
  const preRef = useRef(null);
  const stickyBottomRef = useRef(true);

  useEffect(() => {
    setText(""); setExists(true); offsetRef.current = 0;
  }, [runId]);

  useEffect(() => {
    if (!runId) return;
    let cancelled = false;
    let timer = null;
    const poll = async () => {
      try {
        const res = await fetch(`/api/runs/${runId}/training-log?offset=${offsetRef.current}`);
        const data = await res.json();
        if (cancelled) return;
        setExists(data.exists !== false);
        if (data.text) {
          const el = preRef.current;
          if (el) {
            const dist = el.scrollHeight - el.scrollTop - el.clientHeight;
            stickyBottomRef.current = dist < 40;
          }
          setText(prev => prev + data.text);
          offsetRef.current = data.size;
        } else if (typeof data.size === "number" && data.size < offsetRef.current) {
          offsetRef.current = 0;
          setText("");
        }
      } catch {}
      if (!cancelled) timer = setTimeout(poll, isRunning ? 1500 : 5000);
    };
    poll();
    return () => { cancelled = true; if (timer) clearTimeout(timer); };
  }, [runId, isRunning]);

  useEffect(() => {
    const el = preRef.current;
    if (el && stickyBottomRef.current) el.scrollTop = el.scrollHeight;
  }, [text]);

  const parsed = _parseTrainingLog(text);
  const seriesNames = Object.keys(parsed.series).filter(n => parsed.series[n].length > 0);

  if (!exists) {
    return (
      <div style={{ padding: 18, color: "var(--text-faint)", fontSize: 11, lineHeight: 1.6 }}>
        No training.log yet.
        <br /><br />
        Each agent's train.py writes to <code style={{ color: "var(--text-muted)" }}>&lt;workspace&gt;/training.log</code> as it trains.
        Once the pipeline reaches the training stage you'll see epoch-by-epoch
        loss + validation metrics here, charted live.
      </div>
    );
  }

  return (
    <div style={{ flex: 1, display: "flex", flexDirection: "column", overflow: "hidden" }}>
      {seriesNames.length > 0 && (
        <div style={{ padding: "10px 12px 8px", borderBottom: "1px solid var(--border-subtle)" }}>
          <div style={{ display: "flex", flexWrap: "wrap", gap: 10, marginBottom: 6 }}>
            {(() => {
              const lossNames = seriesNames.filter(n => /loss|error|nll/i.test(n));
              const otherNames = seriesNames.filter(n => !lossNames.includes(n));
              const lossPalette = ["#f59e0b", "#ef4444", "#facc15", "#ec4899", "#f97316"];
              const otherPalette = ["#22d3ee", "#a78bfa", "#4ade80", "#a5b4fc", "#67e8f9", "#fda4af", "#34d399"];
              return seriesNames.slice(0, 8).map(n => {
                const isLoss = /loss|error|nll/i.test(n);
                const color = isLoss
                  ? lossPalette[lossNames.indexOf(n) % lossPalette.length]
                  : otherPalette[otherNames.indexOf(n) % otherPalette.length];
                const last = parsed.series[n][parsed.series[n].length - 1];
                return (
                  <span key={n} style={{
                    fontSize: 9, fontFamily: "'JetBrains Mono',monospace",
                    color: "var(--text-muted)", display: "flex", alignItems: "center", gap: 4,
                  }}>
                    <span style={{ width: 8, height: 2, background: color, borderRadius: 1 }} />
                    {n}: <span style={{ color, fontWeight: 700 }}>{last.y.toFixed(4)}</span>
                  </span>
                );
              });
            })()}
          </div>
          <MetricChart series={parsed.series} />
        </div>
      )}
      {!text ? (
        <div style={{ padding: 18, color: "var(--text-faint)", fontSize: 11 }}>
          Waiting for training output…
        </div>
      ) : (
        <pre ref={preRef} style={{
          flex: 1, overflow: "auto", margin: 0, padding: "10px 14px",
          fontSize: 10.5, lineHeight: 1.45,
          fontFamily: "'JetBrains Mono',monospace",
          color: "var(--text)",
          background: "var(--code-bg)",
          whiteSpace: "pre-wrap", wordBreak: "break-word",
        }}>{text}</pre>
      )}
    </div>
  );
}


// ---------------------------------------------------------------------
// Research log panel — renders the agent's research_log.md
// ---------------------------------------------------------------------

function _renderMarkdownLite(text) {
  // Tiny markdown-ish renderer good enough for research_log.md, which
  // sticks to headings, bullets, bold, and code blocks. Returns an
  // array of React elements.
  const lines = (text || "").split("\n");
  const out = [];
  let codeBuf = null;
  let codeLang = "";
  let key = 0;

  const pushPara = (paraLines) => {
    if (paraLines.length === 0) return;
    const paraText = paraLines.join("\n").trim();
    if (!paraText) return;
    out.push(
      <p key={`p${key++}`} style={{
        fontSize: 12, lineHeight: 1.6, color: "var(--text-muted)",
        margin: "6px 0", whiteSpace: "pre-wrap",
      }} dangerouslySetInnerHTML={{ __html: _inlineMd(paraText) }} />
    );
  };

  let para = [];
  for (const raw of lines) {
    const line = raw;
    if (codeBuf !== null) {
      if (line.trim().startsWith("```")) {
        out.push(
          <pre key={`c${key++}`} style={{
            fontSize: 11, lineHeight: 1.5,
            color: "var(--text)",
            background: "var(--code-bg)",
            border: "1px solid var(--border)",
            borderRadius: 5, padding: 10, margin: "8px 0",
            fontFamily: "'JetBrains Mono',monospace",
            whiteSpace: "pre-wrap", wordBreak: "break-word",
            maxHeight: 360, overflow: "auto",
          }}>{codeBuf.join("\n")}</pre>
        );
        codeBuf = null;
      } else {
        codeBuf.push(line);
      }
      continue;
    }
    if (line.trim().startsWith("```")) {
      pushPara(para); para = [];
      codeBuf = []; codeLang = line.trim().slice(3);
      continue;
    }
    const h = line.match(/^(#{1,6})\s+(.+)/);
    if (h) {
      pushPara(para); para = [];
      const level = h[1].length;
      const sizes = [16, 14, 13, 12, 12, 11];
      out.push(
        <div key={`h${key++}`} style={{
          fontSize: sizes[level - 1] || 12, fontWeight: 700,
          color: level <= 2 ? "#a5b4fc" : "var(--text)",
          marginTop: level === 1 ? 18 : 14, marginBottom: 6,
          letterSpacing: level <= 2 ? "0.5px" : "0",
        }} dangerouslySetInnerHTML={{ __html: _inlineMd(h[2]) }} />
      );
      continue;
    }
    const bullet = line.match(/^(\s*)[-*]\s+(.+)/);
    if (bullet) {
      pushPara(para); para = [];
      const indent = (bullet[1] || "").length;
      out.push(
        <div key={`l${key++}`} style={{
          fontSize: 12, lineHeight: 1.55, color: "var(--text-muted)",
          margin: "2px 0", paddingLeft: 14 + indent * 14, position: "relative",
        }}>
          <span style={{ position: "absolute", left: indent * 14, color: "#818cf8", fontWeight: 700 }}>•</span>
          <span dangerouslySetInnerHTML={{ __html: _inlineMd(bullet[2]) }} />
        </div>
      );
      continue;
    }
    para.push(line);
  }
  pushPara(para);
  return out;
}

function _inlineMd(s) {
  // Escape HTML, then promote inline markdown.
  let safe = s
    .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
  // **bold**
  safe = safe.replace(/\*\*(.+?)\*\*/g, '<strong style="color:var(--text);">$1</strong>');
  // `code`
  safe = safe.replace(/`([^`]+)`/g, '<code style="background:var(--surface-strong);padding:1px 5px;border-radius:3px;font-family:\'JetBrains Mono\',monospace;font-size:0.9em;color:#a5f3fc;">$1</code>');
  return safe;
}

function ResearchLogPanel({ runId, isRunning }) {
  const [text, setText] = useState("");
  const [exists, setExists] = useState(true);

  useEffect(() => {
    setText(""); setExists(true);
  }, [runId]);

  useEffect(() => {
    if (!runId) return;
    let cancelled = false;
    let timer = null;
    const poll = async () => {
      try {
        const res = await fetch(`/api/runs/${runId}/research-log`);
        const data = await res.json();
        if (cancelled) return;
        setExists(data.exists !== false);
        setText(data.text || "");
      } catch {}
      if (!cancelled) timer = setTimeout(poll, isRunning ? 5000 : 30000);
    };
    poll();
    return () => { cancelled = true; if (timer) clearTimeout(timer); };
  }, [runId, isRunning]);

  if (!exists) {
    return (
      <div style={{ padding: 18, color: "var(--text-faint)", fontSize: 11, lineHeight: 1.6 }}>
        No research_log.md yet.
        <br /><br />
        BaselineEvalNode and HillClimbEvalNode each append a section here
        as they evaluate experiments. You'll see the agent's own narrative
        of what it tried and why once the pipeline reaches the eval stages.
      </div>
    );
  }
  if (!text) {
    return <div style={{ padding: 18, color: "var(--text-faint)", fontSize: 11 }}>Empty research log.</div>;
  }
  return (
    <div style={{ flex: 1, overflow: "auto", padding: "14px 18px" }}>
      {_renderMarkdownLite(text)}
    </div>
  );
}


// ---------------------------------------------------------------------
// Git log panel — list of commits on the workspace's experiment branch
// ---------------------------------------------------------------------

function GitLogPanel({ runId, isRunning }) {
  const [data, setData] = useState({ commits: [], branches: [], head_branch: "", exists: true });

  useEffect(() => {
    if (!runId) return;
    let cancelled = false;
    let timer = null;
    const poll = async () => {
      try {
        const res = await fetch(`/api/runs/${runId}/git-log`);
        const d = await res.json();
        if (!cancelled) setData(d);
      } catch {}
      if (!cancelled) timer = setTimeout(poll, isRunning ? 5000 : 30000);
    };
    poll();
    return () => { cancelled = true; if (timer) clearTimeout(timer); };
  }, [runId, isRunning]);

  if (!data.exists) {
    return (
      <div style={{ padding: 18, color: "var(--text-faint)", fontSize: 11, lineHeight: 1.6 }}>
        Workspace doesn't have a git repo yet — GitSetup hasn't run.
      </div>
    );
  }
  if ((data.commits || []).length === 0) {
    return <div style={{ padding: 18, color: "var(--text-faint)", fontSize: 11 }}>No commits yet.</div>;
  }

  return (
    <div style={{ flex: 1, overflow: "auto", padding: "10px 14px" }}>
      {data.head_branch && (
        <div style={{
          fontSize: 9, fontWeight: 700, color: "var(--text-muted)",
          letterSpacing: "1.5px", fontFamily: "'JetBrains Mono',monospace",
          padding: "6px 0 10px",
        }}>HEAD: <span style={{ color: "#a5b4fc" }}>{data.head_branch}</span></div>
      )}
      {data.commits.map(c => (
        <div key={c.sha} style={{
          display: "flex", gap: 10, padding: "7px 8px", alignItems: "flex-start",
          borderLeft: "2px solid rgba(34,211,238,0.25)",
          marginBottom: 2, marginLeft: 4,
          background: "var(--surface)",
          borderRadius: "0 6px 6px 0",
        }}>
          <span style={{
            fontSize: 10, color: "#22d3ee", fontFamily: "'JetBrains Mono',monospace",
            flexShrink: 0, paddingTop: 1,
          }}>{c.short}</span>
          <div style={{ flex: 1, minWidth: 0 }}>
            <div style={{
              fontSize: 11, color: "var(--text)",
              lineHeight: 1.45, wordBreak: "break-word",
            }}>{c.subject}</div>
            <div style={{
              fontSize: 9, color: "var(--text-faint)",
              fontFamily: "'JetBrains Mono',monospace", marginTop: 2,
            }}>
              {c.author} · {(c.date || "").replace("T", " ").slice(0, 16)}
            </div>
          </div>
        </div>
      ))}
    </div>
  );
}


// ---------------------------------------------------------------------
// Console panel — tails the per-run console.log file via offset polling
// ---------------------------------------------------------------------

function ConsolePanel({ runId, isRunning }) {
  const [text, setText] = useState("");
  const [exists, setExists] = useState(true);
  const offsetRef = useRef(0);
  const preRef = useRef(null);
  const stickyBottomRef = useRef(true);

  useEffect(() => {
    // Reset state when switching runs.
    setText("");
    setExists(true);
    offsetRef.current = 0;
  }, [runId]);

  useEffect(() => {
    if (!runId) return;

    let cancelled = false;
    let timer = null;

    const poll = async () => {
      try {
        const res = await fetch(`/api/runs/${runId}/console?offset=${offsetRef.current}`);
        const data = await res.json();
        if (cancelled) return;
        setExists(data.exists !== false);
        if (data.text) {
          // Detect "stuck to bottom" before we mutate, so we can preserve
          // user-scrolled-up state but auto-scroll when they're tailing.
          const el = preRef.current;
          if (el) {
            const dist = el.scrollHeight - el.scrollTop - el.clientHeight;
            stickyBottomRef.current = dist < 40;
          }
          setText(prev => prev + data.text);
          offsetRef.current = data.size;
        } else if (typeof data.size === "number") {
          // Server may have truncated; sync offset just in case.
          if (data.size < offsetRef.current) {
            offsetRef.current = 0;
            setText("");
          }
        }
      } catch {
        // dev server occasionally hiccups; just retry on next tick
      }
      if (!cancelled) {
        // Poll faster while the run is running, slower when it's done so
        // an open tab on a finished run isn't pinging forever.
        timer = setTimeout(poll, isRunning ? 1500 : 5000);
      }
    };
    poll();
    return () => {
      cancelled = true;
      if (timer) clearTimeout(timer);
    };
  }, [runId, isRunning]);

  // Pin to bottom when content arrives if the user was tailing.
  useEffect(() => {
    const el = preRef.current;
    if (el && stickyBottomRef.current) {
      el.scrollTop = el.scrollHeight;
    }
  }, [text]);

  if (!exists) {
    return (
      <div style={{ padding: 18, color: "var(--text-faint)", fontSize: 11 }}>
        Pipeline hasn't started writing console output yet.
        <br /><br />
        The per-run console capture file is created when the pipeline thread
        first prints. If you just clicked "Start Run", it should appear within
        a few seconds.
      </div>
    );
  }
  if (!text) {
    return (
      <div style={{ padding: 18, color: "var(--text-faint)", fontSize: 11 }}>
        Waiting for output…
      </div>
    );
  }

  return (
    <pre ref={preRef} style={{
      flex: 1, overflow: "auto", margin: 0,
      padding: "10px 14px",
      fontSize: 10.5, lineHeight: 1.45,
      fontFamily: "'JetBrains Mono',monospace",
      color: "var(--text)",
      background: "var(--code-bg)",
      whiteSpace: "pre-wrap", wordBreak: "break-word",
    }}>{text}</pre>
  );
}


// ---------------------------------------------------------------------
// SSE hook
// ---------------------------------------------------------------------

function useRunSSE(runId, onMessage) {
  useEffect(() => {
    if (!runId) return;
    const es = new EventSource(`/api/runs/${runId}/events`);
    const types = ["stage_update", "log_entry", "experiment", "llm_call", "run_complete"];
    types.forEach(type => {
      es.addEventListener(type, (e) => {
        try {
          const data = JSON.parse(e.data);
          onMessage(type, data);
        } catch {}
      });
    });
    es.onerror = () => { /* will reconnect; ignore in dev */ };
    return () => es.close();
  }, [runId, onMessage]);
}

// ---------------------------------------------------------------------
// Sidebar
// ---------------------------------------------------------------------

function Sidebar({ view, setView, theme, onToggleTheme }) {
  const items = [
    {
      key: "list",
      label: "Runs",
      icon: (
        <svg width="18" height="18" viewBox="0 0 18 18" fill="none">
          <rect x="3" y="3" width="12" height="3" rx="1" stroke="currentColor" strokeWidth="1.5" />
          <rect x="3" y="7.5" width="12" height="3" rx="1" stroke="currentColor" strokeWidth="1.5" />
          <rect x="3" y="12" width="12" height="3" rx="1" stroke="currentColor" strokeWidth="1.5" />
        </svg>
      ),
    },
    {
      key: "new",
      label: "New Run",
      icon: (
        <svg width="18" height="18" viewBox="0 0 18 18" fill="none">
          <circle cx="9" cy="9" r="7" stroke="currentColor" strokeWidth="1.5" />
          <path d="M9 5.5V12.5M5.5 9H12.5" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
        </svg>
      ),
    },
  ];
  return (
    <div style={{ width: 64, background: "var(--bg-elevated)", borderRight: "1px solid var(--border)", display: "flex", flexDirection: "column", alignItems: "center", paddingTop: 14, flexShrink: 0 }}>
      <div style={{ width: 40, height: 40, borderRadius: 12, background: "linear-gradient(135deg,#6366f1,#818cf8)", display: "flex", alignItems: "center", justifyContent: "center", marginBottom: 20, boxShadow: "0 4px 12px rgba(99,102,241,0.3)" }}>
        <svg width="20" height="20" viewBox="0 0 20 20" fill="none">
          <path d="M10 2L18 7V13L10 18L2 13V7L10 2Z" fill="white" opacity="0.9" />
          <path d="M10 7L14 9.5V14L10 16.5L6 14V9.5L10 7Z" fill="#6366f1" />
        </svg>
      </div>
      {items.map(item => {
        const active = view === item.key || (item.key === "list" && view === "detail");
        return (
          <button key={item.key} title={item.label} onClick={() => setView(item.key)}
            style={{
              width: 42, height: 42, borderRadius: 12, border: "none", cursor: "pointer",
              display: "flex", alignItems: "center", justifyContent: "center", marginBottom: 4,
              background: active ? "rgba(99,102,241,0.15)" : "transparent",
              color: active ? "#a5b4fc" : "var(--text-faint)",
              transition: "all 0.15s", position: "relative",
            }}>
            {item.icon}
            {active && <div style={{ position: "absolute", left: 0, top: 10, width: 3, height: 22, borderRadius: "0 3px 3px 0", background: "#818cf8" }} />}
          </button>
        );
      })}
      <div style={{ flex: 1 }} />
      <button onClick={onToggleTheme} title={`Switch to ${theme === "dark" ? "light" : "dark"} mode`} style={{
        width: 42, height: 42, borderRadius: 12, border: "none", cursor: "pointer",
        display: "flex", alignItems: "center", justifyContent: "center",
        background: "transparent", color: "var(--text-faint)", marginBottom: 4,
      }}>
        {theme === "dark" ? (
          // Sun icon — switching to light
          <svg width="18" height="18" viewBox="0 0 18 18" fill="none">
            <circle cx="9" cy="9" r="3" stroke="currentColor" strokeWidth="1.5" />
            <path d="M9 1.5V3M9 15V16.5M1.5 9H3M15 9H16.5M3.4 3.4L4.5 4.5M13.5 13.5L14.6 14.6M14.6 3.4L13.5 4.5M4.5 13.5L3.4 14.6" stroke="currentColor" strokeWidth="1.4" strokeLinecap="round" />
          </svg>
        ) : (
          // Moon icon — switching to dark
          <svg width="18" height="18" viewBox="0 0 18 18" fill="none">
            <path d="M14.5 11.5C13.4 11.9 12.2 12.1 11 12.1C7 12.1 3.7 8.8 3.7 4.8C3.7 4 3.8 3.2 4.1 2.5C2.4 3.4 1.2 5.2 1.2 7.3C1.2 10.6 3.9 13.3 7.2 13.3C9.4 13.3 11.4 12.1 12.5 10.3" stroke="currentColor" strokeWidth="1.4" strokeLinecap="round" strokeLinejoin="round" />
          </svg>
        )}
      </button>
      <a href="/settings" target="_blank" rel="noreferrer" title="Settings (legacy page)" style={{
        width: 42, height: 42, borderRadius: 12, display: "flex", alignItems: "center", justifyContent: "center",
        background: "transparent", color: "var(--text-faint)", marginBottom: 8, textDecoration: "none",
      }}>
        <svg width="18" height="18" viewBox="0 0 18 18" fill="none">
          <circle cx="9" cy="9" r="2.5" stroke="currentColor" strokeWidth="1.5" />
          <path d="M9 2V4M9 14V16M2 9H4M14 9H16M4.22 4.22L5.64 5.64M12.36 12.36L13.78 13.78M13.78 4.22L12.36 5.64M5.64 12.36L4.22 13.78" stroke="currentColor" strokeWidth="1.3" strokeLinecap="round" />
        </svg>
      </a>
      <div style={{ width: 8, height: 8, borderRadius: "50%", background: "#4ade80", marginBottom: 10, boxShadow: "0 0 10px rgba(74,222,128,0.4)" }} />
      <div style={{ writingMode: "vertical-rl", fontSize: 8, fontWeight: 800, letterSpacing: "2.5px", color: "var(--text-faint)", fontFamily: "'JetBrains Mono',monospace", marginBottom: 16 }}>BEAST</div>
    </div>
  );
}

// ---------------------------------------------------------------------
// Runs list view
// ---------------------------------------------------------------------

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
      {/* Hero banner — wordmark left, Singularity Software logo right.
          Doubled height (144) from the previous 72 so the brand assets
          have room to breathe. New Run button moved out of the banner
          and sits at the top of the runs content area below. */}
      <div style={{
        position: "relative",
        height: 144,
        marginBottom: 16,
        backgroundColor: "#000",
        overflow: "hidden",
      }}>
        <div style={{
          position: "relative", zIndex: 1,
          display: "flex", alignItems: "center", justifyContent: "space-between",
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

          {/* Right: Singularity Software logo */}
          <img
            src="/ss_logo.png"
            alt="Singularity Software"
            style={{
              height: "100%",
              width: "auto",
              maxHeight: 144,
              objectFit: "contain",
              flexShrink: 0,
              display: "block",
            }}
          />
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

function SectionHeader({ label, count, accent }) {
  return (
    <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 10 }}>
      {accent && (
        <span style={{
          width: 8, height: 8, borderRadius: "50%", background: accent,
          boxShadow: `0 0 8px ${accent}80`,
          animation: "pipePulse 1.5s ease-in-out infinite",
        }} />
      )}
      <h3 style={{
        fontSize: 11, fontWeight: 700, letterSpacing: "1.5px",
        color: accent || "var(--text-subtle)",
        fontFamily: "'JetBrains Mono',monospace",
        textTransform: "uppercase",
      }}>{label}</h3>
      <span style={{
        fontSize: 10, color: "var(--text-faint)",
        fontFamily: "'JetBrains Mono',monospace",
      }}>· {count}</span>
      <div style={{ flex: 1, height: 1, background: "var(--border-subtle)" }} />
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

function NewRunView({ onCreated, onCancel }) {
  const [form, setForm] = useState({
    workspace: "",
    task: "",
    target_accuracy: "",
    dataset_path: "",
    mode: "greenfield",
    force_cpu: false,
    setup_workspace: false,
    // Metric direction: "auto" lets the LLM/heuristic infer; "higher" /
    // "lower" override that. Default to auto so the form behaves as
    // before unless the user is opinionated about their metric.
    direction: "auto",
    // Free-text metric name. When set, the val-score extractor pins on it.
    metric_name: "",
  });
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState(null);

  const update = (key) => (e) => setForm({ ...form, [key]: e.target.type === "checkbox" ? e.target.checked : e.target.value });

  const submit = async (e) => {
    e.preventDefault();
    setError(null);
    setSubmitting(true);
    // direction: "auto" → null (server auto-detects), "higher" → false,
    // "lower" → true. The boolean is "is the metric lower-is-better?"
    const lowerIsBetter =
      form.direction === "lower"  ? true
      : form.direction === "higher" ? false
      : null;
    const body = {
      workspace: form.workspace.trim(),
      task: form.task.trim(),
      target_accuracy: form.target_accuracy ? parseFloat(form.target_accuracy) : null,
      dataset_path: form.dataset_path.trim() || null,
      mode: form.mode,
      force_cpu: form.force_cpu,
      setup_workspace: form.setup_workspace,
      lower_is_better: lowerIsBetter,
      metric_name: form.metric_name.trim() || null,
    };
    try {
      const res = await API.createRun(body);
      if (res.id) onCreated(res.id);
      else setError(JSON.stringify(res));
    } catch (err) {
      setError(String(err));
    } finally {
      setSubmitting(false);
    }
  };

  const inputStyle = {
    width: "100%", padding: "9px 11px",
    background: "var(--code-bg)", border: "1px solid var(--border)",
    borderRadius: 8, color: "var(--text)", fontSize: 12,
    fontFamily: "'JetBrains Mono',monospace",
  };
  const labelStyle = { fontSize: 10, fontWeight: 700, color: "var(--text-muted)", letterSpacing: "1px", fontFamily: "'JetBrains Mono',monospace", marginBottom: 5, display: "block" };

  return (
    <div style={{ flex: 1, overflow: "auto", padding: "20px 28px", maxWidth: 720 }}>
      <h2 style={{ fontSize: 18, fontWeight: 700, marginBottom: 4 }}>New Run</h2>
      <div style={{ fontSize: 11, color: "var(--text-subtle)", marginBottom: 18 }}>
        Configure and start a new mle-beast pipeline run.
      </div>
      <form onSubmit={submit}>
        <Card style={{ padding: 18, marginBottom: 12 }}>
          <label style={labelStyle}>WORKSPACE PATH</label>
          <input style={inputStyle} value={form.workspace} onChange={update("workspace")} placeholder="/tmp/my-workspace" required />
          <div style={{ fontSize: 9, color: "var(--text-faint)", marginTop: 4 }}>
            Where the pipeline writes code, models, and the experiment branch.
          </div>
        </Card>

        <Card style={{ padding: 18, marginBottom: 12 }}>
          <label style={labelStyle}>TASK DESCRIPTION</label>
          <textarea style={{ ...inputStyle, minHeight: 80, fontFamily: "inherit" }}
            value={form.task} onChange={update("task")}
            placeholder='e.g. "Predict customer churn from the data in ./data/. Optimize F1-score."'
            required
          />
        </Card>

        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 10, marginBottom: 12 }}>
          <Card style={{ padding: 14 }}>
            <label style={labelStyle}>TARGET (optional)</label>
            <input style={inputStyle} value={form.target_accuracy} onChange={update("target_accuracy")}
              placeholder="0.85" type="number" step="0.001" min="0" max="1"
            />
          </Card>
          <Card style={{ padding: 14 }}>
            <label style={labelStyle}>DATASET PATH (optional)</label>
            <input style={inputStyle} value={form.dataset_path} onChange={update("dataset_path")}
              placeholder="/path/to/data"
            />
          </Card>
        </div>

        <Card style={{ padding: 18, marginBottom: 12 }}>
          <label style={labelStyle}>MODE</label>
          <div style={{ display: "flex", gap: 8 }}>
            {["greenfield", "existing"].map(m => (
              <button key={m} type="button" onClick={() => setForm({ ...form, mode: m })}
                style={{
                  flex: 1, padding: "10px 16px", borderRadius: 8, fontSize: 12, fontWeight: 600, cursor: "pointer",
                  fontFamily: "'JetBrains Mono',monospace",
                  background: form.mode === m ? "rgba(99,102,241,0.12)" : "transparent",
                  border: form.mode === m ? "1px solid rgba(99,102,241,0.4)" : "1px solid var(--border)",
                  color: form.mode === m ? "#a5b4fc" : "var(--text-muted)",
                }}>
                {m}
              </button>
            ))}
          </div>
          <div style={{ fontSize: 10, color: "var(--text-faint)", marginTop: 6 }}>
            <strong>greenfield</strong>: build from scratch. <strong>existing</strong>: hill-climb over your existing model.py / train.py.
          </div>
        </Card>

        <Card style={{ padding: 18, marginBottom: 12 }}>
          <label style={labelStyle}>METRIC NAME (optional)</label>
          <input style={inputStyle} value={form.metric_name} onChange={update("metric_name")}
            placeholder="accuracy, f1_macro, rmse, log_loss, …"
            list="metric-name-suggestions"
          />
          <datalist id="metric-name-suggestions">
            {["accuracy", "f1", "f1_macro", "f1_micro", "auc", "roc_auc",
              "precision", "recall", "map", "ndcg", "rmse", "rmsle", "mae",
              "mse", "log_loss", "nll"].map(m => <option key={m} value={m} />)}
          </datalist>
          {/* Quick-pick chips for the most common values, since most users
              will want one of these and shouldn't have to type. */}
          <div style={{ display: "flex", gap: 6, marginTop: 8, flexWrap: "wrap" }}>
            {["accuracy", "f1", "auc", "rmse", "mae", "log_loss"].map(m => (
              <button key={m} type="button"
                onClick={() => setForm({ ...form, metric_name: m })}
                style={{
                  fontSize: 10, fontFamily: "'JetBrains Mono',monospace",
                  padding: "3px 9px", borderRadius: 12, cursor: "pointer",
                  background: form.metric_name === m ? "rgba(99,102,241,0.18)" : "var(--surface)",
                  border: form.metric_name === m ? "1px solid rgba(99,102,241,0.45)" : "1px solid var(--border)",
                  color: form.metric_name === m ? "#a5b4fc" : "var(--text-muted)",
                }}>{m}</button>
            ))}
          </div>
          <div style={{ fontSize: 10, color: "var(--text-faint)", marginTop: 8 }}>
            Tells the val-score extractor exactly which metric to pull from
            the training log. Skips the LLM/heuristic guesswork.
          </div>

          <label style={{ ...labelStyle, marginTop: 16 }}>METRIC DIRECTION</label>
          <div style={{ display: "flex", gap: 8 }}>
            {[
              { key: "auto",   label: "Auto-detect", hint: "LLM + keyword inference" },
              { key: "higher", label: "Higher = better", hint: "accuracy, F1, AUC, R²" },
              { key: "lower",  label: "Lower = better",  hint: "loss, RMSE, MAE, NLL" },
            ].map(d => (
              <button key={d.key} type="button" onClick={() => setForm({ ...form, direction: d.key })}
                title={d.hint}
                style={{
                  flex: 1, padding: "10px 12px", borderRadius: 8, fontSize: 11, fontWeight: 600, cursor: "pointer",
                  fontFamily: "'JetBrains Mono',monospace",
                  background: form.direction === d.key ? "rgba(99,102,241,0.12)" : "transparent",
                  border: form.direction === d.key ? "1px solid rgba(99,102,241,0.4)" : "1px solid var(--border)",
                  color: form.direction === d.key ? "#a5b4fc" : "var(--text-muted)",
                }}>
                {d.label}
              </button>
            ))}
          </div>
          <div style={{ fontSize: 10, color: "var(--text-faint)", marginTop: 6 }}>
            Tells the eval node which way is "better". Override <strong>auto</strong> when
            you know your metric — eliminates the rare case where the
            inference flips on ambiguous training logs.
          </div>
        </Card>

        <Card style={{ padding: 14, marginBottom: 14 }}>
          <label style={{ display: "flex", alignItems: "center", gap: 10, cursor: "pointer", marginBottom: 8 }}>
            <input type="checkbox" checked={form.setup_workspace} onChange={update("setup_workspace")} />
            <span style={{ fontSize: 12 }}>Set up workspace (install ml-frameworks)</span>
          </label>
          <label style={{ display: "flex", alignItems: "center", gap: 10, cursor: "pointer" }}>
            <input type="checkbox" checked={form.force_cpu} onChange={update("force_cpu")} />
            <span style={{ fontSize: 12 }}>Force CPU (skip GPU auto-detect)</span>
          </label>
        </Card>

        {error && (
          <div style={{ background: "rgba(248,113,113,0.1)", border: "1px solid rgba(248,113,113,0.3)", borderRadius: 8, padding: 12, marginBottom: 12, fontSize: 12, color: "#fca5a5", fontFamily: "'JetBrains Mono',monospace" }}>
            {error}
          </div>
        )}

        <div style={{ display: "flex", gap: 10 }}>
          <button type="submit" disabled={submitting || !form.workspace || !form.task}
            style={{
              background: "linear-gradient(135deg,rgba(34,211,238,0.9),rgba(129,140,248,0.9))",
              border: "none", color: "#08090e", fontSize: 13, fontWeight: 700,
              padding: "10px 22px", borderRadius: 9,
              cursor: submitting ? "wait" : "pointer", opacity: submitting ? 0.5 : 1,
            }}>
            {submitting ? "Starting…" : "Start Run"}
          </button>
          <button type="button" onClick={onCancel} style={{
            background: "transparent", border: "1px solid var(--border)", color: "var(--text-muted)",
            fontSize: 13, fontWeight: 500, padding: "10px 18px", borderRadius: 9, cursor: "pointer",
          }}>Cancel</button>
        </div>
      </form>
    </div>
  );
}

// ---------------------------------------------------------------------
// Details modal — full job attribute card
// ---------------------------------------------------------------------

function DetailRow({ label, value, mono = false, copyable = false, valueColor }) {
  if (value === null || value === undefined || value === "") return null;
  return (
    <div style={{ display: "flex", padding: "8px 0", borderBottom: "1px solid var(--border-subtle)", gap: 12, alignItems: "flex-start" }}>
      <span style={{
        fontSize: 9, fontWeight: 700, color: "var(--text-subtle)",
        letterSpacing: "1.5px", fontFamily: "'JetBrains Mono',monospace",
        width: 140, flexShrink: 0, paddingTop: 2,
      }}>{label}</span>
      <span
        title={copyable ? "Click to copy" : undefined}
        onClick={copyable ? () => navigator.clipboard?.writeText(String(value)) : undefined}
        style={{
          fontSize: 12, color: valueColor || "var(--text-muted)",
          fontFamily: mono ? "'JetBrains Mono',monospace" : "inherit",
          cursor: copyable ? "pointer" : "default",
          flex: 1, wordBreak: "break-all",
        }}
      >{String(value)}</span>
    </div>
  );
}

function fmtAbsTime(ts) {
  if (!ts) return null;
  const d = new Date(ts * 1000);
  return d.toLocaleString();
}

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

// ---------------------------------------------------------------------
// App shell
// ---------------------------------------------------------------------

export default function App() {
  const [view, setView] = useState("list");
  const [currentRunId, setCurrentRunId] = useState(null);
  // Theme: persisted in localStorage so the choice survives reloads.
  const [theme, setTheme] = useState(() => {
    try { return localStorage.getItem("mle-beast-theme") || "dark"; }
    catch { return "dark"; }
  });
  const toggleTheme = () => {
    setTheme(prev => {
      const next = prev === "dark" ? "light" : "dark";
      try { localStorage.setItem("mle-beast-theme", next); } catch {}
      return next;
    });
  };

  const open = (id) => { setCurrentRunId(id); setView("detail"); };

  return (
    <div className={`theme-${theme}`} style={{ display: "flex", height: "100vh", background: "var(--bg)", color: "var(--text)", fontFamily: "'DM Sans',system-ui,sans-serif", overflow: "hidden" }}>
      <link href="https://fonts.googleapis.com/css2?family=DM+Sans:wght@400;500;600;700&family=JetBrains+Mono:wght@400;500;600;700&display=swap" rel="stylesheet" />

      <Sidebar view={view} setView={setView} theme={theme} onToggleTheme={toggleTheme} />

      <div style={{ flex: 1, display: "flex", flexDirection: "column", overflow: "hidden" }}>
        {view === "list" && <RunsListView onOpen={open} onNew={() => setView("new")} />}
        {view === "new" && <NewRunView onCreated={open} onCancel={() => setView("list")} />}
        {view === "detail" && currentRunId && <RunDetailView runId={currentRunId} onBack={() => setView("list")} />}
      </div>

      <style>{`
        /* Theme tokens — only the surfaces / text shades / borders flip
           between dark and light. Accent colors (cyan, purple, green,
           amber, etc) stay constant since they're tuned to read well
           on either background. */
        .theme-dark {
          --bg: #0a0c14;
          --bg-elevated: #07080c;
          --text: #e2e8f0;
          --text-muted: rgba(255,255,255,0.55);
          --text-subtle: rgba(255,255,255,0.3);
          --text-faint: rgba(255,255,255,0.16);
          --surface: rgba(255,255,255,0.025);
          --surface-strong: rgba(255,255,255,0.05);
          --border: rgba(255,255,255,0.06);
          --border-subtle: rgba(255,255,255,0.04);
          --code-bg: rgba(0,0,0,0.25);
          --shadow: 0 4px 12px rgba(0,0,0,0.4);
        }
        .theme-light {
          --bg: #f5f7fb;
          --bg-elevated: #ffffff;
          --text: #0f172a;
          --text-muted: rgba(15,23,42,0.7);
          --text-subtle: rgba(15,23,42,0.5);
          --text-faint: rgba(15,23,42,0.32);
          --surface: rgba(15,23,42,0.04);
          --surface-strong: rgba(15,23,42,0.08);
          --border: rgba(15,23,42,0.1);
          --border-subtle: rgba(15,23,42,0.06);
          --code-bg: rgba(15,23,42,0.05);
          --shadow: 0 4px 12px rgba(15,23,42,0.08);
        }
        ::-webkit-scrollbar { width: 4px; height: 4px; }
        ::-webkit-scrollbar-track { background: transparent; }
        ::-webkit-scrollbar-thumb { background: var(--border); border-radius: 2px; }
        * { box-sizing: border-box; margin: 0; }
        button:focus { outline: none; }
        input:focus, textarea:focus { outline: 1px solid rgba(99,102,241,0.4); }
        @keyframes pipePulse {
          0%, 100% { transform: scale(1);   opacity: 1; }
          50%      { transform: scale(1.4); opacity: 0.6; }
        }
        @keyframes pipeBreathe {
          0%, 100% { box-shadow: 0 0 14px rgba(129,140,248,0.45), inset 0 0 0 1px var(--border); }
          50%      { box-shadow: 0 0 22px rgba(129,140,248,0.75), inset 0 0 0 1px rgba(99,102,241,0.18); }
        }
        @keyframes shimmer {
          0%   { background-position: -200% 0; }
          100% { background-position:  200% 0; }
        }
      `}</style>
    </div>
  );
}
