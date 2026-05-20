// Pipeline indicator (stage chips) + interactive DAG panel.

import { STAGES_ORDER } from "./constants.js";

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

  // The pill IS the DAG toggle — click anywhere on it to expand or
  // collapse the workflow panel below. The chevron at the right edge
  // signals the affordance (▶ collapsed → rotates to ▼ expanded).
  // There is no separate "DAG" button; that paradigm got dropped
  // because the pill already conveys all the same intent.
  return (
    <div style={{ display: "flex", alignItems: "center", gap: 10, paddingBottom: 12, borderBottom: "1px solid var(--border)" }}>
      <span style={{ fontSize: 8, fontWeight: 700, color: "var(--text-faint)", letterSpacing: "1.5px", fontFamily: "'JetBrains Mono',monospace" }}>STAGE</span>
      <button
        onClick={onToggle}
        title={expanded ? "Click to collapse the pipeline DAG" : "Click to expand the pipeline DAG"}
        style={{
          padding: "8px 16px", borderRadius: 8, cursor: "pointer",
          fontSize: 12, fontWeight: 700, fontFamily: "'JetBrains Mono',monospace",
          display: "flex", alignItems: "center", gap: 10,
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
        <span>{displayName.toUpperCase()}</span>
        <span style={{
          display: "inline-block",
          transition: "transform 0.18s ease",
          transform: expanded ? "rotate(90deg)" : "rotate(0deg)",
          fontSize: 9,
          opacity: 0.7,
          marginLeft: 2,
        }}>▶</span>
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

export { PipelineIndicator, PipelineDagPanel };
