# Copyright 2026 Chris Padwick
# SPDX-License-Identifier: Apache-2.0

"""Self-contained HTML report renderer for a finished run.

The output is a single HTML file with all CSS + an inline SVG chart
embedded — no CDN, no JS, no external assets. Designed to be:

  - Opened in a browser (dark mode by default, matches the dashboard).
  - Printed / saved to PDF (@media print overrides to light, full-color
    chart, no awkward page breaks).
  - Dropped into someone else's working dir and still render identically.

The renderer is a pure function: data dict in, HTML string out. The
route handler in routes.py is the only place that touches the filesystem.
"""

from __future__ import annotations

import html as _html
import json
import re
from datetime import datetime, timezone
from typing import Optional

# -----------------------------------------------------------------
# Public entry point
# -----------------------------------------------------------------

def render_report(
    run: dict,
    experiments: list[dict],
    peak: Optional[dict],
    research_log_md: Optional[str] = None,
) -> str:
    """Build a complete, self-contained HTML report for a run."""
    ctx = _build_context(run, experiments, peak)
    body = "\n".join([
        _render_header(ctx),
        _render_stats(ctx),
        _render_chart(ctx),
        _render_experiments_table(ctx),
        _render_research_log(research_log_md) if research_log_md else "",
        _render_config_footer(ctx),
    ])
    title = f"mle-beast report — {ctx['short_id']}"
    return _PAGE_TEMPLATE.format(
        title=_e(title),
        styles=_STYLES,
        body=body,
        generated_at=_e(ctx["generated_at"]),
    )


# -----------------------------------------------------------------
# Context — derived/computed view of the data
# -----------------------------------------------------------------

def _build_context(
    run: dict,
    experiments: list[dict],
    peak: Optional[dict],
) -> dict:
    lower_is_better = bool(run.get("lower_is_better"))
    metric_name = run.get("metric_name") or "score"
    verdict = _parse_json(run.get("verdict_json")) or {}
    findings = verdict.get("findings") or {}

    # Sort once + compute rolling best for the Δ column
    exps = sorted(experiments, key=lambda x: x["step"])
    rolling_best: Optional[float] = None
    best_step: Optional[int] = None
    annotated: list[dict] = []
    for e in exps:
        score = e.get("score")
        delta = None
        if score is not None:
            if rolling_best is None:
                delta = 0.0
                rolling_best = score
                best_step = e["step"]
            else:
                delta = score - rolling_best
                if lower_is_better:
                    if score < rolling_best:
                        rolling_best = score
                        best_step = e["step"]
                else:
                    if score > rolling_best:
                        rolling_best = score
                        best_step = e["step"]
        annotated.append({**e, "delta_vs_prev_best": delta})

    runtime_s = None
    if run.get("started_at") and run.get("completed_at"):
        runtime_s = run["completed_at"] - run["started_at"]
    elif run.get("started_at"):
        runtime_s = None  # ongoing — caller decides what to show

    return {
        "run": run,
        "experiments": annotated,
        "peak": peak,
        "best_step": best_step,
        "best_score": rolling_best,
        "metric_name": metric_name,
        "lower_is_better": lower_is_better,
        "verdict": verdict,
        "findings": findings,
        "runtime_s": runtime_s,
        "short_id": run["id"][:8],
        "generated_at": datetime.now(timezone.utc).astimezone().strftime(
            "%Y-%m-%d %H:%M:%S %Z"
        ),
    }


# -----------------------------------------------------------------
# Sections
# -----------------------------------------------------------------

def _render_header(ctx: dict) -> str:
    run = ctx["run"]
    status = run.get("status", "unknown")
    status_class = {
        "completed": "ok",
        "failed": "fail",
        "cancelled": "warn",
        "running": "info",
    }.get(status, "info")
    task = run.get("task") or "(no task description recorded)"
    mode = run.get("mode", "")
    return f"""
<section class="hero">
  <div class="hero-meta">
    <span class="pill pill--{status_class}">{_e(status)}</span>
    <span class="hero-id">{_e(run["id"])}</span>
    <span class="hero-mode">{_e(mode)}</span>
  </div>
  <h1 class="hero-title">{_e(task)}</h1>
</section>
"""


def _render_stats(ctx: dict) -> str:
    run = ctx["run"]
    cells = []

    best = ctx["best_score"]
    if best is not None:
        sub = f"step {ctx['best_step']} · {_e(ctx['metric_name'])}"
        cells.append(_stat_card("BEST", f"{best:.4f}", sub, kind="highlight"))
    else:
        cells.append(_stat_card("BEST", "—", "no scored experiments"))

    target = run.get("target_accuracy")
    if target is not None:
        sub = "hit ✓" if best is not None and _meets_target(best, target, ctx["lower_is_better"]) else "not reached"
        cells.append(_stat_card("TARGET", f"{target:.4f}", sub))

    cells.append(_stat_card("EXPERIMENTS", str(len(ctx["experiments"])),
                            f"{sum(1 for e in ctx['experiments'] if e.get('kept'))} kept"))

    if ctx["runtime_s"] is not None:
        cells.append(_stat_card("RUNTIME", _fmt_duration(ctx["runtime_s"])))

    cost = run.get("total_cost_usd")
    if cost is not None:
        sub = f"{int(run.get('total_llm_calls') or 0)} calls"
        cells.append(_stat_card("LLM COST", f"${cost:.4f}", sub))

    return f'<section class="stats">{"".join(cells)}</section>'


def _stat_card(label: str, value: str, sub: str = "", kind: str = "") -> str:
    extra_class = f" stat--{kind}" if kind else ""
    sub_html = f'<div class="stat-sub">{_e(sub)}</div>' if sub else ""
    return f"""
<div class="stat{extra_class}">
  <div class="stat-label">{_e(label)}</div>
  <div class="stat-value">{_e(value)}</div>
  {sub_html}
</div>
"""


def _render_chart(ctx: dict) -> str:
    exps = [e for e in ctx["experiments"] if e.get("score") is not None]
    if not exps:
        return ('<section class="chart-wrap">'
                '<h2 class="section-title">Hill-climb</h2>'
                '<div class="empty">No scored experiments to plot.</div>'
                '</section>')
    svg = _build_chart_svg(exps, ctx["metric_name"], ctx["lower_is_better"], ctx["best_step"])
    return f"""
<section class="chart-wrap">
  <h2 class="section-title">Hill-climb</h2>
  <div class="chart">{svg}</div>
  <div class="chart-legend">
    <span class="lg lg--kept"></span> kept
    <span class="lg lg--reverted"></span> reverted
    <span class="lg lg--best"></span> best
  </div>
</section>
"""


def _build_chart_svg(
    exps: list[dict],
    metric_name: str,
    lower_is_better: bool,
    best_step: Optional[int],
) -> str:
    # Layout
    W, H = 760, 320
    PAD_L, PAD_R, PAD_T, PAD_B = 60, 24, 24, 40
    PW, PH = W - PAD_L - PAD_R, H - PAD_T - PAD_B

    xs = [e["step"] for e in exps]
    ys = [e["score"] for e in exps]
    xmin, xmax = min(xs), max(xs)
    ymin, ymax = min(ys), max(ys)
    if xmax == xmin:
        xmin -= 0.5
        xmax += 0.5
    if ymax == ymin:
        pad = abs(ymax) * 0.05 if ymax != 0 else 0.05
        ymin -= pad
        ymax += pad
    # Add 5% headroom so dots don't clip
    y_range = ymax - ymin
    ymin_p = ymin - y_range * 0.08
    ymax_p = ymax + y_range * 0.08

    def sx(x): return PAD_L + (x - xmin) / (xmax - xmin) * PW
    def sy(y): return PAD_T + (1 - (y - ymin_p) / (ymax_p - ymin_p)) * PH

    # Gridlines: 4 horizontal ticks
    grid = []
    ylabels = []
    for i in range(5):
        frac = i / 4
        gy = PAD_T + frac * PH
        yv = ymax_p - frac * (ymax_p - ymin_p)
        grid.append(f'<line x1="{PAD_L}" y1="{gy:.1f}" x2="{PAD_L + PW}" y2="{gy:.1f}" '
                    f'class="grid"/>')
        ylabels.append(f'<text x="{PAD_L - 8}" y="{gy + 4:.1f}" class="axis-label" '
                       f'text-anchor="end">{_fmt_tick(yv)}</text>')

    xlabels = []
    step_count = xmax - xmin
    # Pick reasonable x-tick spacing
    if step_count <= 8:
        ticks = list(range(int(xmin), int(xmax) + 1))
    else:
        stride = max(1, int(round(step_count / 8)))
        ticks = list(range(int(xmin), int(xmax) + 1, stride))
        if ticks[-1] != int(xmax):
            ticks.append(int(xmax))
    for t in ticks:
        tx = sx(t)
        xlabels.append(f'<text x="{tx:.1f}" y="{PAD_T + PH + 18}" class="axis-label" '
                       f'text-anchor="middle">{t}</text>')

    # Line connecting kept experiments only (the actual hill-climb trajectory)
    kept_pts = [(sx(e["step"]), sy(e["score"])) for e in exps if e.get("kept")]
    path = ""
    if len(kept_pts) >= 2:
        d = "M " + " L ".join(f"{x:.1f},{y:.1f}" for x, y in kept_pts)
        path = f'<path d="{d}" class="trajectory"/>'

    # Dots
    dots = []
    for e in exps:
        cx, cy = sx(e["step"]), sy(e["score"])
        is_best = (e["step"] == best_step)
        if is_best:
            # Star
            dots.append(_star_svg(cx, cy, 9, "best"))
        elif e.get("kept"):
            dots.append(f'<circle cx="{cx:.1f}" cy="{cy:.1f}" r="6" class="dot dot--kept"/>')
        else:
            dots.append(f'<circle cx="{cx:.1f}" cy="{cy:.1f}" r="5" class="dot dot--reverted"/>')

    # Axis labels
    metric_lbl = f"{metric_name}{' (lower better)' if lower_is_better else ''}"
    y_axis_title = (
        f'<text x="14" y="{PAD_T + PH/2:.1f}" class="axis-title" '
        f'text-anchor="middle" transform="rotate(-90 14 {PAD_T + PH/2:.1f})">{_e(metric_lbl)}</text>'
    )
    x_axis_title = (
        f'<text x="{PAD_L + PW/2:.1f}" y="{H - 6}" class="axis-title" '
        f'text-anchor="middle">step</text>'
    )

    return (
        f'<svg viewBox="0 0 {W} {H}" xmlns="http://www.w3.org/2000/svg" '
        f'class="chart-svg" preserveAspectRatio="xMidYMid meet">'
        + "".join(grid)
        + path
        + "".join(dots)
        + "".join(ylabels)
        + "".join(xlabels)
        + y_axis_title + x_axis_title
        + "</svg>"
    )


def _star_svg(cx: float, cy: float, r: float, cls: str) -> str:
    import math
    pts = []
    for i in range(10):
        angle = -math.pi / 2 + i * math.pi / 5
        rad = r if i % 2 == 0 else r * 0.45
        pts.append(f"{cx + rad * math.cos(angle):.1f},{cy + rad * math.sin(angle):.1f}")
    return f'<polygon points="{" ".join(pts)}" class="dot dot--{cls}"/>'


def _render_experiments_table(ctx: dict) -> str:
    if not ctx["experiments"]:
        return ('<section><h2 class="section-title">Experiments</h2>'
                '<div class="empty">No experiments recorded.</div></section>')
    rows = []
    for e in ctx["experiments"]:
        kept = bool(e.get("kept"))
        is_best = (e["step"] == ctx["best_step"])
        kept_html = (
            '<span class="badge badge--kept">kept</span>'
            if kept else '<span class="badge badge--reverted">reverted</span>'
        )
        if is_best:
            kept_html = '<span class="badge badge--best">★ best</span>'
        score = e.get("score")
        score_html = f"{score:.4f}" if score is not None else "—"
        delta = e.get("delta_vs_prev_best")
        if delta is None or e["step"] == 0:
            delta_html = "—"
        else:
            sign = "+" if delta >= 0 else ""
            cls = "delta--up" if (
                (delta > 0 and not ctx["lower_is_better"])
                or (delta < 0 and ctx["lower_is_better"])
            ) else "delta--down"
            delta_html = f'<span class="{cls}">{sign}{delta:.4f}</span>'
        sha = e.get("commit_sha")
        sha_html = f'<code>{sha[:8]}</code>' if sha else "—"
        ts = _fmt_timestamp(e.get("created_at"))
        proposal = e.get("proposal") or "—"
        rows.append(f"""
<tr class="{'row--best' if is_best else ''}">
  <td class="num">{e['step']}</td>
  <td class="proposal">{_e(proposal)}</td>
  <td class="num score">{score_html}</td>
  <td class="num">{delta_html}</td>
  <td>{kept_html}</td>
  <td class="mono">{sha_html}</td>
  <td class="ts">{_e(ts)}</td>
</tr>""")
    return f"""
<section>
  <h2 class="section-title">Experiments</h2>
  <div class="table-wrap">
    <table class="exp-table">
      <thead>
        <tr>
          <th>Step</th>
          <th>Hypothesis</th>
          <th>Score</th>
          <th>Δ vs prev best</th>
          <th>Status</th>
          <th>Commit</th>
          <th>When</th>
        </tr>
      </thead>
      <tbody>{"".join(rows)}</tbody>
    </table>
  </div>
</section>
"""


def _render_research_log(md: str) -> str:
    # Lightweight markdown — the agent's research log is mostly headings,
    # lists, and prose. We render with a thin transform rather than a full
    # markdown lib (no extra deps, no surprises).
    rendered = _mini_markdown(md.strip())
    return f"""
<section>
  <h2 class="section-title">Research log</h2>
  <details class="research-log" open>
    <summary>Agent's narrative (click to collapse)</summary>
    <div class="research-body">{rendered}</div>
  </details>
</section>
"""


def _render_config_footer(ctx: dict) -> str:
    run = ctx["run"]
    pairs = [
        ("Run ID", run["id"]),
        ("Mode", run.get("mode") or "—"),
        ("Workspace", run.get("workspace") or "—"),
        ("Dataset", run.get("dataset_path") or "—"),
        ("Metric", run.get("metric_name") or "—"),
        ("Direction", "lower is better" if run.get("lower_is_better") else "higher is better"),
        ("Force CPU", "yes" if run.get("force_cpu") else "no"),
        ("Environment", run.get("environment") or "(framework-managed)"),
        ("Experiment branch", run.get("experiment_branch") or "—"),
        ("Created", _fmt_timestamp(run.get("created_at"))),
        ("Started", _fmt_timestamp(run.get("started_at"))),
        ("Completed", _fmt_timestamp(run.get("completed_at"))),
        ("Total LLM calls", str(int(run.get("total_llm_calls") or 0))),
        ("Prompt tokens", f"{int(run.get('total_prompt_tokens') or 0):,}"),
        ("Completion tokens", f"{int(run.get('total_completion_tokens') or 0):,}"),
    ]
    rows = "".join(
        f'<div class="cfg-row"><span class="cfg-k">{_e(k)}</span>'
        f'<span class="cfg-v">{_e(str(v))}</span></div>'
        for k, v in pairs
    )
    err = run.get("error_message")
    err_html = (
        f'<div class="error-block"><div class="error-label">ERROR</div>'
        f'<pre>{_e(err)}</pre></div>'
        if err else ""
    )
    return f"""
<section class="footer">
  <h2 class="section-title">Run configuration</h2>
  {err_html}
  <div class="cfg-grid">{rows}</div>
</section>
"""


# -----------------------------------------------------------------
# Helpers
# -----------------------------------------------------------------

def _e(s) -> str:
    return _html.escape(str(s)) if s is not None else ""


def _parse_json(s: Optional[str]) -> Optional[dict]:
    if not s:
        return None
    try:
        return json.loads(s)
    except (ValueError, TypeError):
        return None


def _meets_target(score: float, target: float, lower_is_better: bool) -> bool:
    return score <= target if lower_is_better else score >= target


def _fmt_duration(seconds: float) -> str:
    s = int(seconds)
    if s < 60:
        return f"{s}s"
    if s < 3600:
        return f"{s // 60}m {s % 60}s"
    return f"{s // 3600}h {(s % 3600) // 60}m"


def _fmt_timestamp(ts) -> str:
    if not ts:
        return "—"
    try:
        return datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M:%S")
    except (TypeError, ValueError, OSError):
        return "—"


def _fmt_tick(v: float) -> str:
    if abs(v) >= 1000:
        return f"{v:,.0f}"
    if abs(v) >= 1:
        return f"{v:.3f}"
    return f"{v:.4f}"


_HEADING_RE = re.compile(r"^(#{1,6})\s+(.*)$", re.MULTILINE)
_BULLET_RE = re.compile(r"^[-*]\s+(.*)$", re.MULTILINE)
_CODE_FENCE_RE = re.compile(r"```(\w*)\n(.*?)```", re.DOTALL)
_INLINE_CODE_RE = re.compile(r"`([^`]+)`")
_BOLD_RE = re.compile(r"\*\*([^*]+)\*\*")


def _mini_markdown(md: str) -> str:
    # Code fences first so their contents don't get further transformed.
    placeholders: dict[str, str] = {}

    def _stash(match):
        body = _e(match.group(2))
        key = f"\x00CODEBLK{len(placeholders)}\x00"
        placeholders[key] = f"<pre class=\"code-fence\"><code>{body}</code></pre>"
        return key

    md = _CODE_FENCE_RE.sub(_stash, md)
    md = _e(md)
    # Headings
    md = _HEADING_RE.sub(
        lambda m: f'<h{len(m.group(1)) + 2}>{m.group(2)}</h{len(m.group(1)) + 2}>', md
    )
    # Bullets → wrap consecutive bullet lines in <ul>
    lines = md.split("\n")
    out: list[str] = []
    in_ul = False
    for ln in lines:
        m = _BULLET_RE.match(ln)
        if m:
            if not in_ul:
                out.append("<ul>")
                in_ul = True
            out.append(f"<li>{m.group(1)}</li>")
        else:
            if in_ul:
                out.append("</ul>")
                in_ul = False
            out.append(ln)
    if in_ul:
        out.append("</ul>")
    md = "\n".join(out)
    # Inline formatting (after escape, so we re-introduce intentional HTML)
    md = _BOLD_RE.sub(r"<strong>\1</strong>", md)
    md = _INLINE_CODE_RE.sub(r"<code>\1</code>", md)
    # Paragraphs: split on blank lines and wrap non-block lines
    paragraphs = re.split(r"\n{2,}", md)
    rendered: list[str] = []
    for p in paragraphs:
        p_strip = p.strip()
        if not p_strip:
            continue
        # If it already starts with a block tag, don't wrap
        if re.match(r"^<(h\d|ul|pre|details|table)", p_strip):
            rendered.append(p_strip)
        elif "\x00CODEBLK" in p_strip:
            rendered.append(p_strip)
        else:
            rendered.append(f"<p>{p_strip}</p>")
    out_html = "\n".join(rendered)
    # Restore code blocks
    for key, code in placeholders.items():
        out_html = out_html.replace(key, code)
    return out_html


# -----------------------------------------------------------------
# Template + styles
# -----------------------------------------------------------------

_PAGE_TEMPLATE = """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <title>{title}</title>
  <style>{styles}</style>
</head>
<body>
  <main class="container">
{body}
    <footer class="page-footer">
      Generated by mle-beast · {generated_at}
    </footer>
  </main>
</body>
</html>
"""

# Dark by default (matches the dashboard). Print stylesheet flips to a
# paper-friendly palette + tweaks gridlines/dots so a Cmd-P / save-as-PDF
# always produces something readable on white paper.
_STYLES = """
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&family=JetBrains+Mono:wght@400;600&display=swap');

:root {
  --bg: #0d0e10;
  --bg-elevated: #16181c;
  --bg-card: #1a1c20;
  --fg: #e8e9ee;
  --fg-muted: #a1a4ad;
  --fg-faint: #6b6e76;
  --border: #25272d;
  --border-strong: #353841;
  --accent: #818cf8;
  --accent-2: #6366f1;
  --kept: #10b981;
  --kept-bg: rgba(16,185,129,0.12);
  --reverted: #6b6e76;
  --reverted-bg: rgba(107,110,118,0.10);
  --best: #f59e0b;
  --best-bg: rgba(245,158,11,0.14);
  --ok: #22c55e;
  --fail: #ef4444;
  --warn: #f59e0b;
  --info: #818cf8;
  --delta-up: #10b981;
  --delta-down: #f87171;
  --shadow: 0 1px 0 rgba(255,255,255,0.04), 0 8px 24px rgba(0,0,0,0.4);
}

* { box-sizing: border-box; }

html, body {
  margin: 0; padding: 0;
  background: var(--bg);
  color: var(--fg);
  font-family: 'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
  font-size: 14px;
  line-height: 1.5;
  -webkit-font-smoothing: antialiased;
}

.container {
  max-width: 1100px;
  margin: 0 auto;
  padding: 48px 32px 64px;
}

/* ---- hero ---- */
.hero { margin-bottom: 36px; }
.hero-meta {
  display: flex; align-items: center; gap: 12px;
  margin-bottom: 18px;
  font-family: 'JetBrains Mono', monospace;
  font-size: 12px;
}
.hero-id {
  color: var(--fg-faint);
  letter-spacing: 0.5px;
}
.hero-mode {
  color: var(--fg-faint);
  text-transform: uppercase;
  letter-spacing: 1.5px;
  font-size: 10px;
  padding: 3px 8px;
  border: 1px solid var(--border);
  border-radius: 4px;
}
.hero-title {
  font-size: 32px;
  font-weight: 700;
  line-height: 1.25;
  margin: 0;
  letter-spacing: -0.02em;
}

.pill {
  font-family: 'JetBrains Mono', monospace;
  font-size: 11px;
  font-weight: 700;
  text-transform: uppercase;
  letter-spacing: 1px;
  padding: 4px 10px;
  border-radius: 5px;
}
.pill--ok   { color: var(--ok);   background: rgba(34,197,94,0.12);  border: 1px solid rgba(34,197,94,0.30); }
.pill--fail { color: var(--fail); background: rgba(239,68,68,0.12);  border: 1px solid rgba(239,68,68,0.30); }
.pill--warn { color: var(--warn); background: rgba(245,158,11,0.12); border: 1px solid rgba(245,158,11,0.30); }
.pill--info { color: var(--info); background: rgba(129,140,248,0.12); border: 1px solid rgba(129,140,248,0.30); }

/* ---- stats ---- */
.stats {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
  gap: 12px;
  margin-bottom: 40px;
}
.stat {
  background: var(--bg-card);
  border: 1px solid var(--border);
  border-radius: 12px;
  padding: 18px 20px;
  box-shadow: var(--shadow);
}
.stat--highlight {
  background: linear-gradient(135deg, rgba(245,158,11,0.10), rgba(245,158,11,0.02));
  border-color: rgba(245,158,11,0.30);
}
.stat-label {
  font-family: 'JetBrains Mono', monospace;
  font-size: 10px;
  font-weight: 700;
  letter-spacing: 1.5px;
  color: var(--fg-faint);
  margin-bottom: 6px;
}
.stat-value {
  font-family: 'JetBrains Mono', monospace;
  font-size: 26px;
  font-weight: 700;
  color: var(--fg);
  line-height: 1.1;
}
.stat--highlight .stat-value { color: var(--best); }
.stat-sub {
  font-size: 12px;
  color: var(--fg-muted);
  margin-top: 6px;
}

/* ---- sections ---- */
.section-title {
  font-size: 13px;
  font-weight: 700;
  letter-spacing: 2px;
  text-transform: uppercase;
  color: var(--fg-faint);
  margin: 0 0 16px;
}
section { margin-bottom: 40px; }

/* ---- chart ---- */
.chart-wrap { margin-bottom: 36px; }
.chart {
  background: var(--bg-card);
  border: 1px solid var(--border);
  border-radius: 12px;
  padding: 24px;
  box-shadow: var(--shadow);
}
.chart-svg { width: 100%; height: auto; display: block; }
.grid { stroke: var(--border); stroke-width: 1; stroke-dasharray: 2 4; }
.axis-label {
  font-family: 'JetBrains Mono', monospace;
  font-size: 10px;
  fill: var(--fg-faint);
}
.axis-title {
  font-family: 'Inter', sans-serif;
  font-size: 11px;
  font-weight: 600;
  fill: var(--fg-muted);
  letter-spacing: 0.5px;
}
.trajectory {
  fill: none;
  stroke: var(--accent);
  stroke-width: 1.8;
  stroke-linejoin: round;
  stroke-linecap: round;
  opacity: 0.85;
}
.dot--kept     { fill: var(--kept); stroke: #053d2c; stroke-width: 1; }
.dot--reverted { fill: none; stroke: var(--reverted); stroke-width: 2; }
.dot--best     { fill: var(--best); stroke: #5a3d0e; stroke-width: 1; }

.chart-legend {
  display: flex; gap: 18px;
  font-size: 12px;
  color: var(--fg-muted);
  margin-top: 12px;
  padding-left: 4px;
  font-family: 'JetBrains Mono', monospace;
}
.lg {
  display: inline-block;
  width: 12px; height: 12px;
  border-radius: 50%;
  margin-right: 6px;
  vertical-align: middle;
}
.lg--kept     { background: var(--kept); }
.lg--reverted { background: transparent; border: 2px solid var(--reverted); }
.lg--best     { background: var(--best); border-radius: 2px; transform: rotate(45deg); }

/* ---- experiments table ---- */
.table-wrap {
  background: var(--bg-card);
  border: 1px solid var(--border);
  border-radius: 12px;
  overflow: hidden;
  box-shadow: var(--shadow);
}
.exp-table {
  width: 100%;
  border-collapse: collapse;
  font-size: 13px;
}
.exp-table thead th {
  text-align: left;
  font-family: 'JetBrains Mono', monospace;
  font-size: 10px;
  font-weight: 700;
  letter-spacing: 1.5px;
  text-transform: uppercase;
  color: var(--fg-faint);
  padding: 14px 16px;
  background: var(--bg-elevated);
  border-bottom: 1px solid var(--border);
}
.exp-table tbody td {
  padding: 14px 16px;
  border-bottom: 1px solid var(--border);
  vertical-align: top;
}
.exp-table tbody tr:last-child td { border-bottom: none; }
.exp-table tbody tr:hover { background: rgba(255,255,255,0.02); }
.exp-table .row--best { background: var(--best-bg); }
.exp-table .row--best:hover { background: rgba(245,158,11,0.20); }
.exp-table .num {
  font-family: 'JetBrains Mono', monospace;
  white-space: nowrap;
}
.exp-table .score { font-weight: 700; }
.exp-table .proposal {
  max-width: 360px;
  color: var(--fg);
  line-height: 1.45;
}
.exp-table .mono { font-family: 'JetBrains Mono', monospace; }
.exp-table .ts {
  font-family: 'JetBrains Mono', monospace;
  font-size: 11px;
  color: var(--fg-faint);
  white-space: nowrap;
}
.exp-table code {
  background: var(--bg-elevated);
  padding: 2px 6px;
  border-radius: 4px;
  font-size: 11px;
  color: var(--fg-muted);
}
.badge {
  display: inline-block;
  font-family: 'JetBrains Mono', monospace;
  font-size: 10px;
  font-weight: 700;
  letter-spacing: 1px;
  text-transform: uppercase;
  padding: 3px 8px;
  border-radius: 4px;
}
.badge--kept     { color: var(--kept);     background: var(--kept-bg);     border: 1px solid rgba(16,185,129,0.25); }
.badge--reverted { color: var(--reverted); background: var(--reverted-bg); border: 1px solid rgba(107,110,118,0.25); }
.badge--best     { color: var(--best);     background: var(--best-bg);     border: 1px solid rgba(245,158,11,0.35); }
.delta--up   { color: var(--delta-up);   font-weight: 700; }
.delta--down { color: var(--delta-down); font-weight: 700; }

/* ---- research log ---- */
.research-log {
  background: var(--bg-card);
  border: 1px solid var(--border);
  border-radius: 12px;
  padding: 0;
  box-shadow: var(--shadow);
}
.research-log summary {
  cursor: pointer;
  padding: 18px 24px;
  font-family: 'JetBrains Mono', monospace;
  font-size: 12px;
  font-weight: 600;
  letter-spacing: 0.5px;
  color: var(--fg-muted);
  user-select: none;
}
.research-log summary::-webkit-details-marker { color: var(--accent); }
.research-body {
  padding: 0 24px 24px;
  border-top: 1px solid var(--border);
  padding-top: 24px;
}
.research-body h3, .research-body h4, .research-body h5, .research-body h6 {
  margin: 20px 0 10px;
  letter-spacing: -0.01em;
}
.research-body p  { margin: 10px 0; color: var(--fg); }
.research-body ul { padding-left: 20px; }
.research-body li { margin: 4px 0; }
.research-body code {
  background: var(--bg-elevated);
  padding: 2px 6px;
  border-radius: 4px;
  font-family: 'JetBrains Mono', monospace;
  font-size: 12px;
  color: var(--accent);
}
.research-body .code-fence {
  background: var(--bg);
  border: 1px solid var(--border);
  padding: 14px 16px;
  border-radius: 8px;
  overflow-x: auto;
  font-family: 'JetBrains Mono', monospace;
  font-size: 12px;
  line-height: 1.5;
}

/* ---- error block + config footer ---- */
.error-block {
  background: rgba(239,68,68,0.08);
  border: 1px solid rgba(239,68,68,0.30);
  border-radius: 10px;
  padding: 14px 18px;
  margin-bottom: 16px;
}
.error-label {
  font-family: 'JetBrains Mono', monospace;
  font-size: 10px;
  font-weight: 700;
  letter-spacing: 2px;
  color: var(--fail);
  margin-bottom: 6px;
}
.error-block pre {
  margin: 0;
  font-size: 12px;
  white-space: pre-wrap;
  word-break: break-word;
  color: var(--fg);
}
.cfg-grid {
  background: var(--bg-card);
  border: 1px solid var(--border);
  border-radius: 12px;
  overflow: hidden;
  box-shadow: var(--shadow);
}
.cfg-row {
  display: flex;
  justify-content: space-between;
  align-items: baseline;
  gap: 16px;
  padding: 11px 18px;
  border-bottom: 1px solid var(--border);
  font-size: 13px;
}
.cfg-row:last-child { border-bottom: none; }
.cfg-k {
  font-family: 'JetBrains Mono', monospace;
  font-size: 11px;
  font-weight: 600;
  letter-spacing: 0.5px;
  color: var(--fg-faint);
  text-transform: uppercase;
  flex-shrink: 0;
}
.cfg-v {
  color: var(--fg);
  word-break: break-all;
  text-align: right;
  font-family: 'JetBrains Mono', monospace;
  font-size: 12px;
}

.empty {
  color: var(--fg-faint);
  font-style: italic;
  padding: 24px;
  background: var(--bg-card);
  border: 1px dashed var(--border);
  border-radius: 12px;
  text-align: center;
}

.page-footer {
  margin-top: 60px;
  padding-top: 24px;
  border-top: 1px solid var(--border);
  font-family: 'JetBrains Mono', monospace;
  font-size: 10px;
  letter-spacing: 1.5px;
  text-transform: uppercase;
  color: var(--fg-faint);
  text-align: center;
}

/* ---- print: paper-friendly light theme ---- */
@media print {
  :root {
    --bg: #ffffff;
    --bg-elevated: #f7f7f9;
    --bg-card: #ffffff;
    --fg: #111418;
    --fg-muted: #4a4f57;
    --fg-faint: #797f8a;
    --border: #e1e3e8;
    --border-strong: #c8ccd3;
    --kept: #047857;
    --kept-bg: rgba(4,120,87,0.10);
    --reverted: #6b7280;
    --reverted-bg: rgba(107,114,128,0.08);
    --best: #b45309;
    --best-bg: rgba(180,83,9,0.10);
    --shadow: none;
  }
  body { background: #ffffff; }
  .container { padding: 24px; max-width: none; }
  .stat, .chart, .table-wrap, .research-log, .cfg-grid {
    box-shadow: none;
    border-color: #d4d6dd;
  }
  .research-log[open] summary { display: none; }
  .research-body { padding-top: 8px; border-top: none; }
  section { page-break-inside: avoid; }
  .exp-table { page-break-inside: auto; }
  .exp-table tr { page-break-inside: avoid; }
  .hero-title { font-size: 26px; }
  a { color: inherit; text-decoration: none; }
}
"""
