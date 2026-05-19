// Settings + Admin page. Two tabs:
//   "Settings" — fetches /api/settings, edits in-place, POSTs to /api/settings.
//   "Admin"    — DB stats + destructive maintenance (delete-old / reset).
//
// Replaces both the old Jinja /settings and /admin pages that were
// removed when the project went open-source. Same fields, modern look.

import { useEffect, useState } from "react";

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
  const [tab, setTab] = useState("settings");
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
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 14 }}>
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

      {/* Tabs: Settings (configurable values) | Admin (destructive DB ops).
          Kept in one page since they're both "server-side state I might
          want to change," but separated by a tab so the destructive
          stuff isn't sitting next to the routine fields. */}
      <div style={{ display: "flex", gap: 4, borderBottom: "1px solid var(--border)", marginBottom: 16 }}>
        {[
          { key: "settings", label: "Settings" },
          { key: "admin",    label: "Admin" },
        ].map(t => (
          <button key={t.key} onClick={() => setTab(t.key)} style={{
            padding: "8px 18px",
            fontSize: 12, fontWeight: 600, cursor: "pointer",
            fontFamily: "'JetBrains Mono',monospace",
            border: "none",
            borderBottom: tab === t.key ? "2px solid #818cf8" : "2px solid transparent",
            background: "transparent",
            color: tab === t.key ? "#a5b4fc" : "var(--text-subtle)",
            marginBottom: -1,
          }}>{t.label}</button>
        ))}
      </div>

      {tab === "settings" && (
        <SettingsTab
          settings={settings}
          provider={provider}
          update={update}
          save={save}
          saving={saving}
          savedMsg={savedMsg}
          inputStyle={inputStyle}
          labelStyle={labelStyle}
        />
      )}

      {tab === "admin" && <AdminTab />}
    </div>
  );
}


function SettingsTab({ settings, provider, update, save, saving, savedMsg, inputStyle, labelStyle }) {
  return (
    <>
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
    </>
  );
}


function AdminTab() {
  const [stats, setStats] = useState(null);
  const [days, setDays] = useState(30);
  const [resetConfirm, setResetConfirm] = useState("");
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState(null);

  const refreshStats = () => {
    fetch("/api/admin/stats").then(r => r.json()).then(setStats).catch(() => {});
  };
  useEffect(refreshStats, []);

  const deleteOld = async () => {
    if (!confirm(`Delete all runs older than ${days} days? This can't be undone.`)) return;
    setBusy(true); setMsg(null);
    try {
      const res = await fetch("/api/admin/delete-old-runs", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ days: Number(days) }),
      });
      const body = await res.json();
      if (res.ok) setMsg({ ok: true, txt: `Deleted ${body.deleted} runs.` });
      else setMsg({ ok: false, txt: `Failed: ${body.error || res.status}` });
      refreshStats();
    } catch (err) {
      setMsg({ ok: false, txt: String(err) });
    } finally {
      setBusy(false);
    }
  };

  const reset = async () => {
    if (resetConfirm !== "RESET") {
      setMsg({ ok: false, txt: 'Type "RESET" in the box to confirm.' });
      return;
    }
    if (!confirm("This will delete ALL runs, stages, events, and experiments. Settings are preserved. Continue?")) return;
    setBusy(true); setMsg(null);
    try {
      const res = await fetch("/api/admin/reset-database", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ confirm: "RESET" }),
      });
      const body = await res.json();
      if (res.ok) {
        setMsg({ ok: true, txt: "Database reset." });
        setResetConfirm("");
      } else {
        setMsg({ ok: false, txt: `Failed: ${body.error || res.status}` });
      }
      refreshStats();
    } catch (err) {
      setMsg({ ok: false, txt: String(err) });
    } finally {
      setBusy(false);
    }
  };

  const danger = {
    background: "rgba(248,113,113,0.1)",
    border: "1px solid rgba(248,113,113,0.35)",
    color: "#fca5a5", fontSize: 12, fontWeight: 600,
    padding: "8px 16px", borderRadius: 8, cursor: busy ? "wait" : "pointer",
    opacity: busy ? 0.5 : 1,
  };
  const inputStyle = {
    width: 120, padding: "7px 10px",
    background: "var(--code-bg)", border: "1px solid var(--border)",
    borderRadius: 8, color: "var(--text)", fontSize: 12,
    fontFamily: "'JetBrains Mono',monospace",
  };

  return (
    <>
      {/* Stats */}
      <Card style={{ padding: 18, marginBottom: 12 }}>
        <div style={{ fontSize: 9, fontWeight: 700, color: "var(--text-faint)", letterSpacing: "1.5px", fontFamily: "'JetBrains Mono',monospace", marginBottom: 12 }}>
          DATABASE
        </div>
        {!stats ? <div style={{ fontSize: 11, color: "var(--text-subtle)" }}>Loading stats…</div> : (
          <div style={{ display: "grid", gridTemplateColumns: "repeat(4,1fr)", gap: 16 }}>
            <Stat label="Runs"   value={stats.runs_count} />
            <Stat label="Stages" value={stats.stages_count} />
            <Stat label="Events" value={stats.events_count} />
            <Stat label="DB size" value={`${(stats.db_size_bytes/1024/1024).toFixed(2)} MB`} />
          </div>
        )}
        {stats?.runs_by_status && Object.keys(stats.runs_by_status).length > 0 && (
          <div style={{ marginTop: 14, fontSize: 11, color: "var(--text-subtle)", fontFamily: "'JetBrains Mono',monospace" }}>
            By status:{" "}
            {Object.entries(stats.runs_by_status).map(([k, v], i) => (
              <span key={k} style={{ marginRight: 12 }}>
                {k}={v}{i < Object.entries(stats.runs_by_status).length - 1 ? "," : ""}
              </span>
            ))}
          </div>
        )}
      </Card>

      {/* Delete old runs */}
      <Card style={{ padding: 18, marginBottom: 12 }}>
        <div style={{ fontSize: 9, fontWeight: 700, color: "var(--text-faint)", letterSpacing: "1.5px", fontFamily: "'JetBrains Mono',monospace", marginBottom: 8 }}>
          DELETE OLD RUNS
        </div>
        <div style={{ fontSize: 11, color: "var(--text-subtle)", marginBottom: 12 }}>
          Removes runs created more than N days ago plus their stages, events, and experiments. Settings are preserved.
        </div>
        <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
          <span style={{ fontSize: 11, fontFamily: "'JetBrains Mono',monospace" }}>older than</span>
          <input style={inputStyle} type="number" min="1" value={days} onChange={e => setDays(e.target.value)} />
          <span style={{ fontSize: 11, fontFamily: "'JetBrains Mono',monospace" }}>days</span>
          <button onClick={deleteOld} disabled={busy} style={danger}>Delete</button>
        </div>
      </Card>

      {/* Full reset */}
      <Card style={{ padding: 18, marginBottom: 12, borderColor: "rgba(248,113,113,0.25)" }}>
        <div style={{ fontSize: 9, fontWeight: 700, color: "#fca5a5", letterSpacing: "1.5px", fontFamily: "'JetBrains Mono',monospace", marginBottom: 8 }}>
          DANGER ZONE — RESET DATABASE
        </div>
        <div style={{ fontSize: 11, color: "var(--text-subtle)", marginBottom: 12 }}>
          Deletes ALL runs, stages, events, and experiments. Your <code style={{ fontFamily: "'JetBrains Mono',monospace" }}>settings</code> row is preserved. Type <code style={{ fontFamily: "'JetBrains Mono',monospace" }}>RESET</code> to confirm.
        </div>
        <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
          <input
            style={{ ...inputStyle, width: 160 }}
            placeholder="type RESET"
            value={resetConfirm}
            onChange={e => setResetConfirm(e.target.value)}
          />
          <button onClick={reset} disabled={busy || resetConfirm !== "RESET"} style={{
            ...danger,
            opacity: (busy || resetConfirm !== "RESET") ? 0.4 : 1,
            cursor: (busy || resetConfirm !== "RESET") ? "not-allowed" : "pointer",
          }}>
            Reset Database
          </button>
        </div>
      </Card>

      {msg && (
        <div style={{
          fontSize: 11, fontFamily: "'JetBrains Mono',monospace", marginTop: 14,
          color: msg.ok ? "#4ade80" : "#fca5a5",
        }}>
          {msg.txt}
        </div>
      )}
    </>
  );
}


function Stat({ label, value }) {
  return (
    <div>
      <div style={{ fontSize: 8, fontWeight: 700, color: "var(--text-faint)", letterSpacing: "1.5px", fontFamily: "'JetBrains Mono',monospace", marginBottom: 4 }}>{label}</div>
      <div style={{ fontSize: 22, fontWeight: 700, fontFamily: "'JetBrains Mono',monospace" }}>{value}</div>
    </div>
  );
}


export { SettingsView };
