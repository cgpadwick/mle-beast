// Structured JSON pretty-printer + LLM message renderer.

import { useState } from "react";
import { _stringNeedsBlock, ROLE_COLOR } from "./format.js";

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

export { JsonView, MessageContent };
