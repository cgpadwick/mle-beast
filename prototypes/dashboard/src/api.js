// API client for the FastAPI backend.

const API = {
  listRuns: (limit = 50, offset = 0) =>
    fetch(`/api/runs?limit=${limit}&offset=${offset}`).then(r => r.json()),
  getSummary: (id) => fetch(`/api/runs/${id}/summary`).then(r => r.json()),
  // Surfaces the server's `detail` message on a non-2xx (e.g. the 400 the
  // preflight returns for a missing workspace venv) so the New Run form
  // can show it verbatim instead of a raw {"detail":...} blob.
  createRun: async (body) => {
    const r = await fetch("/api/runs", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    const data = await r.json().catch(() => ({}));
    if (!r.ok) {
      const msg = data?.detail || `Request failed (${r.status})`;
      throw new Error(typeof msg === "string" ? msg : JSON.stringify(msg));
    }
    return data;
  },
  cancelRun: (id) => fetch(`/api/runs/${id}/cancel`, { method: "POST" }).then(r => r.json()),
  // Throw on a non-2xx so callers' .catch() actually fires (fetch resolves
  // on HTTP errors), instead of silently treating a 404/500 as success.
  deleteRun: async (id) => {
    const r = await fetch(`/api/admin/runs/${id}`, { method: "DELETE" });
    const data = await r.json().catch(() => ({}));
    if (!r.ok) throw new Error(data?.detail || data?.error || `Delete failed (${r.status})`);
    return data;
  },
  generateReport: (id) => fetch(`/api/runs/${id}/report`, { method: "POST" }).then(r => r.json()),
  detectLocalModel: () => fetch("/api/local-model-name").then(r => r.json()),
  getVersion: () => fetch("/api/version").then(r => r.json()),
  getDiagnostics: () => fetch("/api/diagnostics").then(r => r.json()),
};

export { API };
