// Live training log + parsed metric chart.

import { useState, useEffect, useRef } from "react";
import { _parseTrainingLog } from "./format.js";

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

export { MetricChart, TrainingPanel };
