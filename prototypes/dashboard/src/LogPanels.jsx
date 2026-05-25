// Read-only tail-style log panels (research_log.md, git log, console).

import { useState, useEffect, useRef } from "react";

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
            fontSize: 10, color: "var(--accent-info)", fontFamily: "'JetBrains Mono',monospace",
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

// Cap the rendered console to its tail. A console.log can grow to many MB
// on a long run; rendering all of it in one <pre> (pre-wrap + break-word)
// forces a full layout reflow of the whole string on every 1.5s poll, which
// freezes the tab. We still tail the whole file via offset polling — we just
// keep the in-DOM text bounded to the most recent slice.
const CONSOLE_MAX_CHARS = 256 * 1024;

function ConsolePanel({ runId, isRunning }) {
  const [text, setText] = useState("");
  const [exists, setExists] = useState(true);
  const [truncated, setTruncated] = useState(false);
  const offsetRef = useRef(0);   // byte offset into the file (server's unit)
  const charsRef = useRef(0);    // total CHARS received (the cap's unit)
  const preRef = useRef(null);
  const stickyBottomRef = useRef(true);

  useEffect(() => {
    // Reset state when switching runs.
    setText("");
    setExists(true);
    setTruncated(false);
    offsetRef.current = 0;
    charsRef.current = 0;
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
          setText(prev => {
            let next = prev + data.text;
            if (next.length > CONSOLE_MAX_CHARS) {
              next = next.slice(next.length - CONSOLE_MAX_CHARS);
              const nl = next.indexOf("\n");      // drop the partial leading line
              if (nl >= 0) next = next.slice(nl + 1);
            }
            return next;
          });
          offsetRef.current = data.size;
          // Drive the trimmed banner from CHARS (the same unit as the cap +
          // the slice above), not the byte-based data.size — otherwise
          // multi-byte UTF-8 output could flag truncation when nothing was
          // actually trimmed. Done outside the updater to keep it pure.
          charsRef.current += data.text.length;
          setTruncated(charsRef.current > CONSOLE_MAX_CHARS);
        } else if (typeof data.size === "number") {
          // Server may have truncated/rotated; resync from the top.
          if (data.size < offsetRef.current) {
            offsetRef.current = 0;
            charsRef.current = 0;
            setText("");
            setTruncated(false);
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
    <div style={{ flex: 1, display: "flex", flexDirection: "column", minHeight: 0 }}>
      {truncated && (
        <div style={{
          fontSize: 9, color: "var(--text-faint)",
          padding: "4px 14px", borderBottom: "1px solid var(--border)",
          fontFamily: "'JetBrains Mono',monospace", flexShrink: 0,
        }}>
          showing the most recent output — older lines trimmed for performance
        </div>
      )}
      <pre ref={preRef} style={{
        flex: 1, overflow: "auto", margin: 0,
        padding: "10px 14px",
        fontSize: 10.5, lineHeight: 1.45,
        fontFamily: "'JetBrains Mono',monospace",
        color: "var(--text)",
        background: "var(--code-bg)",
        whiteSpace: "pre-wrap", wordBreak: "break-word",
      }}>{text}</pre>
    </div>
  );
}


// ---------------------------------------------------------------------
// SSE hook
// ---------------------------------------------------------------------

export { ResearchLogPanel, GitLogPanel, ConsolePanel };
