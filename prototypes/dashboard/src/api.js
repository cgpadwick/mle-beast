// API client for the FastAPI backend.

const API = {
  listRuns: () => fetch("/api/runs").then(r => r.json()),
  getSummary: (id) => fetch(`/api/runs/${id}/summary`).then(r => r.json()),
  createRun: (body) => fetch("/api/runs", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  }).then(r => r.json()),
  cancelRun: (id) => fetch(`/api/runs/${id}/cancel`, { method: "POST" }).then(r => r.json()),
  generateReport: (id) => fetch(`/api/runs/${id}/report`, { method: "POST" }).then(r => r.json()),
  detectLocalModel: () => fetch("/api/local-model-name").then(r => r.json()),
};

export { API };
