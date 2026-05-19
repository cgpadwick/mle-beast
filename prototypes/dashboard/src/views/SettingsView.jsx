// Settings page — fetches /api/settings, edits in-place, saves back.
//
// Replaces the old Jinja /settings page that was removed when this
// project went open-source. Same fields, modern look. Field types are
// inferred from the JSON value: number inputs for ints, text inputs
// for strings, a dropdown for log_level (small fixed set).

import { useState, useEffect } from "react";

import { Card } from "../primitives.jsx";

// Field metadata: group label + per-field hint + display label override
// (key snake_case can be ugly to read directly).
const FIELD_GROUPS = [
  {
    title: "LLM PROVIDER",
    fields: [
      ["model_provider", "Provider override (leave blank to auto-detect from env vars)"],
      ["model_name",     "Model override (e.g. deepseek/deepseek-v4-flash, gpt-5-mini)"],
      ["max_tokens",     "Max tokens per LLM completion"],
      ["llm_call_retries", "How many times to retry a failed LLM call"],
    ],
  },
  {
    title: "AGENT BUDGETS",
    fields: [
      ["max_tool_iterations", "Inner tool-loop iterations per actor turn"],
      ["max_tool_iterations_training", "Same but for the training actor (smaller — training is one shot)"],
      ["max_code_review_retries", "Testing-critic retry budget per code change"],
      ["max_training_analysis_retries", "Analysis-critic retry budget per training run"],
    ],
  },
  {
    title: "SUBPROCESS TIMEOUTS (seconds)",
    fields: [
      ["shell_command_timeout", "Default for run_shell_command. 180s covers pip install of heavyweights."],
      ["python_file_timeout",   "Default for run_python_file (script execution)"],
      ["test_timeout",          "Default for run_tests (pytest)"],
      ["training_timeout",      "Max wall-clock for one training run"],
    ],
  },
  {
    title: "OUTPUT CAPS (chars)",
    fields: [
      ["command_output_max_chars", "Max chars of stdout returned to the agent per shell/python call"],
      ["test_output_max_chars",    "Max chars of pytest output returned to the agent"],
      ["test_error_max_chars",     "Max chars of pytest stderr returned"],
      ["testing_llm_context_truncation", "Testing critic's context-truncation point"],
      ["review_file_truncation",         "Review critic file-truncation point"],
      ["analysis_log_truncation",        "Analysis critic training-log truncation point"],
    ],
  },
  {
    title: "MISC",
    fields: [
      ["log_level", "Python logger level (INFO, DEBUG, WARNING, ERROR)"],
    ],
  },
];

const LOG_LEVELS = ["DEBUG", "INFO", "WARNING", "ERROR"];


function SettingsView({ onClose }) {
  const [settings, setSettings] = useState(null);
  const [provider, setProvider] = useState("");
  const [saving, setSaving] = useState(false);
  const [savedMsg, setSavedMsg] = useState(null);

  useEffect(() => {
    fetch("/api/settings").then(r => r.json()).then(setSettings).catch(() => {});
    fetch("/api/local-model-name").then(r => r.json()).then(b => setProvider(b.model || "")).catch(() => {});
  }, []);

  if (!settings) {
    return (
      <div style={{ flex: 1, display: "flex", alignItems: "center", justifyContent: "center", color: "var(--text-subtle)" }}>
        Loading settings…
      </div>
    );
  }

  const update = (key) => (e) => {
    const v = e.target.value;
    const isNum = typeof settings[key] === "number";
    setSettings({ ...settings, [key]: isNum ? (v === "" ? 0 : Number(v)) : v });
    setSavedMsg(null);
  };

  const save = async () => {
    setSaving(true);
    setSavedMsg(null);
    try {
      const res = await fetch("/api/settings", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(settings),
      });
      if (res.ok) setSavedMsg({ ok: true, msg: "Settings saved." });
      else setSavedMsg({ ok: false, msg: `Save failed: ${res.status}` });
    } catch (err) {
      setSavedMsg({ ok: false, msg: String(err) });
    } finally {
      setSaving(false);
    }
  };

  const inputStyle = {
    width: "100%", padding: "8px 11px",
    background: "var(--code-bg)", border: "1px solid var(--border)",
    borderRadius: 8, color: "var(--text)", fontSize: 12,
    fontFamily: "'JetBrains Mono',monospace",
  };
  const labelStyle = {
    fontSize: 10, fontWeight: 700, color: "var(--text-muted)",
    letterSpacing: "0.5px",
    fontFamily: "'JetBrains Mono',monospace",
    marginBottom: 4, display: "block",
  };

  return (
    <div style={{ flex: 1, overflow: "auto", padding: "24px 28px", maxWidth: 920 }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 18 }}>
        <div>
          <h2 style={{ fontSize: 20, fontWeight: 700, marginBottom: 4 }}>Settings</h2>
          <div style={{ fontSize: 11, color: "var(--text-subtle)" }}>
            Persisted to <code style={{ fontFamily: "'JetBrains Mono',monospace" }}>~/.mle-beast/mle_beast.db</code>. Applied on the next pipeline run.
          </div>
        </div>
        <button onClick={onClose} style={{
          background: "transparent", border: "1px solid var(--border)",
          color: "var(--text-muted)", fontSize: 11,
          padding: "6px 14px", borderRadius: 6, cursor: "pointer",
          fontFamily: "'JetBrains Mono',monospace",
        }}>← back</button>
      </div>

      {provider && (
        <Card style={{ padding: "10px 14px", marginBottom: 12 }}>
          <span style={{ fontSize: 9, fontWeight: 700, color: "var(--text-faint)", letterSpacing: "1.5px", fontFamily: "'JetBrains Mono',monospace" }}>DETECTED LOCAL MODEL</span>
          <span style={{ fontSize: 11, marginLeft: 10, fontFamily: "'JetBrains Mono',monospace" }}>{provider}</span>
        </Card>
      )}

      {FIELD_GROUPS.map((group) => (
        <Card key={group.title} style={{ padding: 18, marginBottom: 12 }}>
          <div style={{
            fontSize: 9, fontWeight: 700, color: "var(--text-faint)",
            letterSpacing: "1.5px",
            fontFamily: "'JetBrains Mono',monospace",
            marginBottom: 12,
          }}>{group.title}</div>
          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 14 }}>
            {group.fields.map(([key, hint]) => {
              if (!(key in settings)) return null;  // server schema drift
              const val = settings[key];
              return (
                <div key={key}>
                  <label style={labelStyle}>{key}</label>
                  {key === "log_level" ? (
                    <select style={inputStyle} value={val} onChange={update(key)}>
                      {LOG_LEVELS.map(lvl => <option key={lvl} value={lvl}>{lvl}</option>)}
                    </select>
                  ) : typeof val === "number" ? (
                    <input style={inputStyle} type="number" value={val} onChange={update(key)} />
                  ) : (
                    <input style={inputStyle} type="text" value={val} onChange={update(key)} />
                  )}
                  <div style={{ fontSize: 9, color: "var(--text-faint)", marginTop: 4 }}>{hint}</div>
                </div>
              );
            })}
          </div>
        </Card>
      ))}

      <div style={{ display: "flex", alignItems: "center", gap: 12, marginTop: 16 }}>
        <button onClick={save} disabled={saving} style={{
          background: "linear-gradient(135deg,rgba(34,211,238,0.9),rgba(129,140,248,0.9))",
          border: "none", color: "#08090e", fontSize: 13, fontWeight: 700,
          padding: "9px 22px", borderRadius: 9,
          cursor: saving ? "wait" : "pointer", opacity: saving ? 0.5 : 1,
        }}>
          {saving ? "Saving…" : "Save"}
        </button>
        {savedMsg && (
          <span style={{
            fontSize: 11, fontFamily: "'JetBrains Mono',monospace",
            color: savedMsg.ok ? "#4ade80" : "#fca5a5",
          }}>
            {savedMsg.msg}
          </span>
        )}
      </div>
    </div>
  );
}

export { SettingsView };
