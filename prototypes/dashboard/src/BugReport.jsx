// "Report a bug" affordance: pulls auto-collected diagnostics from
// /api/diagnostics, pre-fills a GitHub issue (so the user only writes
// "what happened"), and offers a clipboard fallback for the full blob —
// GitHub's prefill URL caps around 8 KB, so long error text can't all ride
// in the URL.

import { useEffect, useState } from "react";

import { API } from "./api.js";

const NEW_ISSUE = "https://github.com/cgpadwick/mle-beast/issues/new";
const BODY_LIMIT = 6000;   // keep the prefill URL comfortably under ~8 KB
const ERR_LIMIT = 1500;    // cap the inlined error excerpt

function envBlock(diag) {
  if (!diag) return "(diagnostics unavailable)";
  return [
    `- mle-beast version: ${diag.version}`,
    `- install: ${diag.install}`,
    `- OS: ${diag.os}`,
    `- Python: ${diag.python}`,
    `- GPU: ${diag.gpu}`,
    `- provider / model: ${diag.provider} / ${diag.model}`,
  ].join("\n");
}

// Full markdown body (used verbatim for the clipboard copy).
function buildBody(diag, run) {
  let body = `## What happened
<!-- describe the unexpected behavior -->

## What you expected

## How to reproduce
1.
2.

## Environment (auto-filled)
${envBlock(diag)}
`;
  if (run) {
    const full = run.error_message || "(none)";
    const err = full.slice(0, ERR_LIMIT);
    const trunc = full.length > ERR_LIMIT ? "\n…(truncated — use Copy diagnostics for the full error)" : "";
    body += `
## Failed run (auto-filled)
- run id: ${run.id}
- status: ${run.status}
- error:
\`\`\`
${err}${trunc}
\`\`\`
`;
  }
  return body;
}

function issueUrl(diag, run) {
  const title = run
    ? `[Bug] run ${String(run.id).slice(0, 8)} — ${run.status}`
    : "[Bug] ";
  let body = buildBody(diag, run);
  if (body.length > BODY_LIMIT) {
    body = body.slice(0, BODY_LIMIT) + "\n\n…(truncated — use “Copy diagnostics” and paste the rest)";
  }
  const p = new URLSearchParams({ title, body, labels: "bug" });
  return `${NEW_ISSUE}?${p.toString()}`;
}

/**
 * @param {object} [run] optional run context ({id, status, error_message}).
 *        When present the button reads "Report this run" and includes the
 *        run id + error in the issue.
 */
function copyText(text) {
  // Prefer the async clipboard API; fall back to a hidden textarea +
  // execCommand for non-secure contexts (e.g. the container served over
  // http on a LAN IP, where navigator.clipboard is unavailable).
  if (navigator.clipboard?.writeText) {
    return navigator.clipboard.writeText(text);
  }
  return new Promise((resolve, reject) => {
    const ta = document.createElement("textarea");
    ta.value = text;
    ta.style.position = "fixed";
    ta.style.opacity = "0";
    document.body.appendChild(ta);
    ta.select();
    try {
      // execCommand returns false (rather than throwing) when the copy
      // is rejected — treat that as failure so callers don't show "Copied".
      if (document.execCommand("copy")) resolve();
      else reject(new Error("copy command rejected"));
    } catch (e) {
      reject(e);
    } finally {
      document.body.removeChild(ta);  // always clean up, even on failure
    }
  });
}

function ReportBugButton({ run, compact }) {
  const [diag, setDiag] = useState(null);
  const [copied, setCopied] = useState(false);

  // Prefetch diagnostics on mount so the click handlers stay SYNCHRONOUS.
  // window.open / clipboard writes must happen inside the user gesture — an
  // intervening `await` trips popup blockers and clipboard-permission checks.
  useEffect(() => {
    let cancelled = false;
    API.getDiagnostics().then(d => { if (!cancelled) setDiag(d); }).catch(() => {});
    return () => { cancelled = true; };
  }, []);

  const open = () => {
    if (diag) {
      // Synchronous — same gesture, no popup block.
      window.open(issueUrl(diag, run), "_blank", "noopener,noreferrer");
      return;
    }
    // Diagnostics not back yet (rare): open the tab synchronously now, then
    // navigate it once the fetch resolves so the popup still isn't blocked.
    const w = window.open("about:blank", "_blank", "noopener,noreferrer");
    API.getDiagnostics().catch(() => null).then(d => {
      const url = issueUrl(d, run);
      if (w) w.location = url; else window.open(url, "_blank", "noopener,noreferrer");
    });
  };

  const copy = () => {
    copyText(buildBody(diag, run))
      .then(() => { setCopied(true); setTimeout(() => setCopied(false), 2000); })
      .catch(() => { /* copy unavailable — the GitHub button still works */ });
  };

  const btn = {
    fontSize: compact ? 11 : 12, fontWeight: 600,
    padding: compact ? "5px 10px" : "7px 14px", borderRadius: 8,
    cursor: "pointer", fontFamily: "'JetBrains Mono',monospace",
  };

  return (
    <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
      <button onClick={open} style={{
        ...btn,
        background: "rgba(248,113,113,0.10)",
        border: "1px solid rgba(248,113,113,0.35)",
        color: "var(--status-fail-fg)",
      }}>
        🐞 {run ? "Report this run" : "Report a bug"}
      </button>
      <button onClick={copy} style={{
        ...btn,
        background: "transparent",
        border: "1px solid var(--border)",
        color: "var(--text-muted)",
      }}>
        {copied ? "Copied ✓" : "Copy diagnostics"}
      </button>
    </div>
  );
}

export { ReportBugButton };
