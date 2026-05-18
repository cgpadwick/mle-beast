// SSE subscription hook for live run events.

import { useEffect } from "react";

function useRunSSE(runId, onMessage) {
  useEffect(() => {
    if (!runId) return;
    const es = new EventSource(`/api/runs/${runId}/events`);
    const types = ["stage_update", "log_entry", "experiment", "llm_call", "run_complete"];
    types.forEach(type => {
      es.addEventListener(type, (e) => {
        try {
          const data = JSON.parse(e.data);
          onMessage(type, data);
        } catch {}
      });
    });
    es.onerror = () => { /* will reconnect; ignore in dev */ };
    return () => es.close();
  }, [runId, onMessage]);
}

// ---------------------------------------------------------------------
// Sidebar
// ---------------------------------------------------------------------

export { useRunSSE };
