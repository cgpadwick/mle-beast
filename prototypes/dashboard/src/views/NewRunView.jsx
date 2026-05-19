// New-run wizard.

import { useState, useEffect } from "react";

import { API } from "../api.js";
import { Card } from "../primitives.jsx";

function NewRunView({ onCreated, onCancel }) {
  const [form, setForm] = useState({
    workspace: "",
    task: "",
    target_accuracy: "",
    dataset_path: "",
    mode: "greenfield",
    force_cpu: false,
    setup_workspace: false,
    // Metric direction: "auto" lets the LLM/heuristic infer; "higher" /
    // "lower" override that. Default to auto so the form behaves as
    // before unless the user is opinionated about their metric.
    direction: "auto",
    // Free-text metric name. When set, the val-score extractor pins on it.
    metric_name: "",
  });
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState(null);

  const update = (key) => (e) => setForm({ ...form, [key]: e.target.type === "checkbox" ? e.target.checked : e.target.value });

  const submit = async (e) => {
    e.preventDefault();
    setError(null);
    setSubmitting(true);
    // direction: "auto" → null (server auto-detects), "higher" → false,
    // "lower" → true. The boolean is "is the metric lower-is-better?"
    const lowerIsBetter =
      form.direction === "lower"  ? true
      : form.direction === "higher" ? false
      : null;
    const body = {
      workspace: form.workspace.trim(),
      task: form.task.trim(),
      // Use explicit-empty check so 0 (valid target) isn't treated as unset.
      target_accuracy: form.target_accuracy !== "" ? parseFloat(form.target_accuracy) : null,
      dataset_path: form.dataset_path.trim() || null,
      mode: form.mode,
      force_cpu: form.force_cpu,
      setup_workspace: form.setup_workspace,
      lower_is_better: lowerIsBetter,
      metric_name: form.metric_name.trim() || null,
    };
    try {
      const res = await API.createRun(body);
      if (res.id) onCreated(res.id);
      else setError(JSON.stringify(res));
    } catch (err) {
      setError(String(err));
    } finally {
      setSubmitting(false);
    }
  };

  const inputStyle = {
    width: "100%", padding: "9px 11px",
    background: "var(--code-bg)", border: "1px solid var(--border)",
    borderRadius: 8, color: "var(--text)", fontSize: 12,
    fontFamily: "'JetBrains Mono',monospace",
  };
  const labelStyle = { fontSize: 10, fontWeight: 700, color: "var(--text-muted)", letterSpacing: "1px", fontFamily: "'JetBrains Mono',monospace", marginBottom: 5, display: "block" };

  return (
    <div style={{ flex: 1, overflow: "auto", padding: "20px 28px", maxWidth: 720 }}>
      <h2 style={{ fontSize: 18, fontWeight: 700, marginBottom: 4 }}>New Run</h2>
      <div style={{ fontSize: 11, color: "var(--text-subtle)", marginBottom: 18 }}>
        Configure and start a new mle-beast pipeline run.
      </div>
      <form onSubmit={submit}>
        <Card style={{ padding: 18, marginBottom: 12 }}>
          <label style={labelStyle}>WORKSPACE PATH</label>
          <input style={inputStyle} value={form.workspace} onChange={update("workspace")} placeholder="/tmp/my-workspace" required />
          <div style={{ fontSize: 9, color: "var(--text-faint)", marginTop: 4 }}>
            Where the pipeline writes code, models, and the experiment branch.
          </div>
        </Card>

        <Card style={{ padding: 18, marginBottom: 12 }}>
          <label style={labelStyle}>TASK DESCRIPTION</label>
          <textarea style={{ ...inputStyle, minHeight: 80, fontFamily: "inherit" }}
            value={form.task} onChange={update("task")}
            placeholder='e.g. "Predict customer churn from the data in ./data/. Optimize F1-score."'
            required
          />
        </Card>

        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 10, marginBottom: 12 }}>
          <Card style={{ padding: 14 }}>
            <label style={labelStyle}>TARGET (optional)</label>
            <input style={inputStyle} value={form.target_accuracy} onChange={update("target_accuracy")}
              placeholder="0.85" type="number" step="0.001" min="0" max="1"
            />
          </Card>
          <Card style={{ padding: 14 }}>
            <label style={labelStyle}>DATASET PATH (optional)</label>
            <input style={inputStyle} value={form.dataset_path} onChange={update("dataset_path")}
              placeholder="/path/to/data"
            />
          </Card>
        </div>

        <Card style={{ padding: 18, marginBottom: 12 }}>
          <label style={labelStyle}>MODE</label>
          <div style={{ display: "flex", gap: 8 }}>
            {["greenfield", "existing"].map(m => (
              <button key={m} type="button" onClick={() => setForm({ ...form, mode: m })}
                style={{
                  flex: 1, padding: "10px 16px", borderRadius: 8, fontSize: 12, fontWeight: 600, cursor: "pointer",
                  fontFamily: "'JetBrains Mono',monospace",
                  background: form.mode === m ? "rgba(99,102,241,0.12)" : "transparent",
                  border: form.mode === m ? "1px solid rgba(99,102,241,0.4)" : "1px solid var(--border)",
                  color: form.mode === m ? "#a5b4fc" : "var(--text-muted)",
                }}>
                {m}
              </button>
            ))}
          </div>
          <div style={{ fontSize: 10, color: "var(--text-faint)", marginTop: 6 }}>
            <strong>greenfield</strong>: build from scratch. <strong>existing</strong>: hill-climb over your existing model.py / train.py.
          </div>
        </Card>

        <Card style={{ padding: 18, marginBottom: 12 }}>
          <label style={labelStyle}>METRIC NAME (optional)</label>
          <input style={inputStyle} value={form.metric_name} onChange={update("metric_name")}
            placeholder="accuracy, f1_macro, rmse, log_loss, …"
            list="metric-name-suggestions"
          />
          <datalist id="metric-name-suggestions">
            {["accuracy", "f1", "f1_macro", "f1_micro", "auc", "roc_auc",
              "precision", "recall", "map", "ndcg", "rmse", "rmsle", "mae",
              "mse", "log_loss", "nll"].map(m => <option key={m} value={m} />)}
          </datalist>
          {/* Quick-pick chips for the most common values, since most users
              will want one of these and shouldn't have to type. */}
          <div style={{ display: "flex", gap: 6, marginTop: 8, flexWrap: "wrap" }}>
            {["accuracy", "f1", "auc", "rmse", "mae", "log_loss"].map(m => (
              <button key={m} type="button"
                onClick={() => setForm({ ...form, metric_name: m })}
                style={{
                  fontSize: 10, fontFamily: "'JetBrains Mono',monospace",
                  padding: "3px 9px", borderRadius: 12, cursor: "pointer",
                  background: form.metric_name === m ? "rgba(99,102,241,0.18)" : "var(--surface)",
                  border: form.metric_name === m ? "1px solid rgba(99,102,241,0.45)" : "1px solid var(--border)",
                  color: form.metric_name === m ? "#a5b4fc" : "var(--text-muted)",
                }}>{m}</button>
            ))}
          </div>
          <div style={{ fontSize: 10, color: "var(--text-faint)", marginTop: 8 }}>
            Tells the val-score extractor exactly which metric to pull from
            the training log. Skips the LLM/heuristic guesswork.
          </div>

          <label style={{ ...labelStyle, marginTop: 16 }}>METRIC DIRECTION</label>
          <div style={{ display: "flex", gap: 8 }}>
            {[
              { key: "auto",   label: "Auto-detect", hint: "LLM + keyword inference" },
              { key: "higher", label: "Higher = better", hint: "accuracy, F1, AUC, R²" },
              { key: "lower",  label: "Lower = better",  hint: "loss, RMSE, MAE, NLL" },
            ].map(d => (
              <button key={d.key} type="button" onClick={() => setForm({ ...form, direction: d.key })}
                title={d.hint}
                style={{
                  flex: 1, padding: "10px 12px", borderRadius: 8, fontSize: 11, fontWeight: 600, cursor: "pointer",
                  fontFamily: "'JetBrains Mono',monospace",
                  background: form.direction === d.key ? "rgba(99,102,241,0.12)" : "transparent",
                  border: form.direction === d.key ? "1px solid rgba(99,102,241,0.4)" : "1px solid var(--border)",
                  color: form.direction === d.key ? "#a5b4fc" : "var(--text-muted)",
                }}>
                {d.label}
              </button>
            ))}
          </div>
          <div style={{ fontSize: 10, color: "var(--text-faint)", marginTop: 6 }}>
            Tells the eval node which way is "better". Override <strong>auto</strong> when
            you know your metric — eliminates the rare case where the
            inference flips on ambiguous training logs.
          </div>
        </Card>

        <Card style={{ padding: 14, marginBottom: 14 }}>
          <label style={{ display: "flex", alignItems: "center", gap: 10, cursor: "pointer", marginBottom: 8 }}>
            <input type="checkbox" checked={form.setup_workspace} onChange={update("setup_workspace")} />
            <span style={{ fontSize: 12 }}>Set up workspace (install ml-frameworks)</span>
          </label>
          <label style={{ display: "flex", alignItems: "center", gap: 10, cursor: "pointer" }}>
            <input type="checkbox" checked={form.force_cpu} onChange={update("force_cpu")} />
            <span style={{ fontSize: 12 }}>Force CPU (skip GPU auto-detect)</span>
          </label>
        </Card>

        {error && (
          <div style={{ background: "rgba(248,113,113,0.1)", border: "1px solid rgba(248,113,113,0.3)", borderRadius: 8, padding: 12, marginBottom: 12, fontSize: 12, color: "#fca5a5", fontFamily: "'JetBrains Mono',monospace" }}>
            {error}
          </div>
        )}

        <div style={{ display: "flex", gap: 10 }}>
          <button type="submit" disabled={submitting || !form.workspace || !form.task}
            style={{
              background: "linear-gradient(135deg,rgba(34,211,238,0.9),rgba(129,140,248,0.9))",
              border: "none", color: "#08090e", fontSize: 13, fontWeight: 700,
              padding: "10px 22px", borderRadius: 9,
              cursor: submitting ? "wait" : "pointer", opacity: submitting ? 0.5 : 1,
            }}>
            {submitting ? "Starting…" : "Start Run"}
          </button>
          <button type="button" onClick={onCancel} style={{
            background: "transparent", border: "1px solid var(--border)", color: "var(--text-muted)",
            fontSize: 13, fontWeight: 500, padding: "10px 18px", borderRadius: 9, cursor: "pointer",
          }}>Cancel</button>
        </div>
      </form>
    </div>
  );
}

// ---------------------------------------------------------------------
// Details modal — full job attribute card
// ---------------------------------------------------------------------

export { NewRunView };
