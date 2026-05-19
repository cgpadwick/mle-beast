// Score chart + experiment tree (hill-climb visualization).

import { fmtScore } from "./format.js";

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

export { ScoreChart, ExperimentTree };
