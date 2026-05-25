// Pure formatting helpers — no React, no JSX, no DOM.

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
      item = { stage, type: "critic", msg: `Retry ${data.attempt}/${data.max_attempts}: ${(data.feedback || "").slice(0, 280)}`, verdict: false }; break;
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
  if (item.type === "critic") return item.verdict ? "var(--status-ok-fg)" : "var(--status-fail-fg)";
  if (item.type === "score") {
    if (item.delta && item.delta.startsWith("-")) return "var(--status-fail-fg)";
    if (item.msg && item.msg.includes("Final")) return "var(--status-warn-fg)";
    if (item.delta) return "var(--accent-info)";
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
function ROLE_COLOR(role) {
  if (role === "system") return "var(--text-muted)";
  if (role === "user") return "var(--status-warn-fg)";
  if (role === "assistant") return "#a78bfa";
  return "var(--text-muted)";
}
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
function fmtAbsTime(ts) {
  if (!ts) return null;
  const d = new Date(ts * 1000);
  return d.toLocaleString();
}

export {
  fmtDuration, fmtRelTime, fmtScore, fmtTokens, fmtAbsTime,
  parseEventData, eventToItem, getColor, getIcon,
  _stringNeedsBlock, ROLE_COLOR,
  _parseTrainingLog,
};
