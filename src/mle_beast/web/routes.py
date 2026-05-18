# Copyright 2026 Chris Padwick
# SPDX-License-Identifier: Apache-2.0

"""JSON + SSE endpoints consumed by the React dashboard."""

from __future__ import annotations

import asyncio
import time
from typing import Optional

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from starlette.responses import StreamingResponse

from mle_beast.events import PipelineEvent, get_event_bus
from mle_beast.run_manager import RunConfig, RunInfo, StageInfo, get_run_manager
from mle_beast.settings import Settings, get_settings, reload_settings, save_settings


# ---------------------------------------------------------------------------
# Request/response models
# ---------------------------------------------------------------------------

class CreateRunRequest(BaseModel):
    workspace: str
    task: str
    target_accuracy: Optional[float] = None
    dataset_path: Optional[str] = None
    mode: str = "greenfield"
    force_cpu: bool = False
    setup_workspace: bool = False
    # None → auto-detect (LLM/heuristic), True → lower-is-better (loss/RMSE),
    # False → higher-is-better (accuracy/F1/AUC).
    lower_is_better: Optional[bool] = None
    # Free-text metric name like "accuracy" / "f1_macro" / "rmse".
    metric_name: Optional[str] = None


class RunResponse(BaseModel):
    id: str
    status: str
    workspace: str
    task: str
    target_accuracy: Optional[float]
    dataset_path: Optional[str]
    mode: str
    force_cpu: bool
    created_at: float
    started_at: Optional[float]
    completed_at: Optional[float]
    verdict_json: Optional[str]
    error_message: Optional[str]
    experiment_branch: Optional[str] = None
    lower_is_better: Optional[bool] = None
    metric_name: Optional[str] = None
    total_cost_usd: float = 0.0
    total_prompt_tokens: int = 0
    total_completion_tokens: int = 0
    total_reasoning_tokens: int = 0
    total_llm_calls: int = 0

    @classmethod
    def from_info(cls, info: RunInfo) -> RunResponse:
        return cls(
            id=info.id,
            status=info.status,
            workspace=info.workspace,
            task=info.task,
            target_accuracy=info.target_accuracy,
            dataset_path=info.dataset_path,
            mode=info.mode,
            force_cpu=info.force_cpu,
            created_at=info.created_at,
            started_at=info.started_at,
            completed_at=info.completed_at,
            verdict_json=info.verdict_json,
            error_message=info.error_message,
            experiment_branch=info.experiment_branch,
            lower_is_better=info.lower_is_better,
            metric_name=info.metric_name,
            total_cost_usd=info.total_cost_usd,
            total_prompt_tokens=info.total_prompt_tokens,
            total_completion_tokens=info.total_completion_tokens,
            total_reasoning_tokens=info.total_reasoning_tokens,
            total_llm_calls=info.total_llm_calls,
        )


class StageResponse(BaseModel):
    stage_name: str
    status: str
    attempt: int
    max_attempts: int
    started_at: Optional[float]
    completed_at: Optional[float]
    verdict_json: Optional[str]

    @classmethod
    def from_info(cls, info: StageInfo) -> StageResponse:
        return cls(
            stage_name=info.stage_name,
            status=info.status,
            attempt=info.attempt,
            max_attempts=info.max_attempts,
            started_at=info.started_at,
            completed_at=info.completed_at,
            verdict_json=info.verdict_json,
        )


# ---------------------------------------------------------------------------
# Route registration
# ---------------------------------------------------------------------------

def register_routes(app: FastAPI) -> None:
    """Register the JSON + SSE routes consumed by the React dashboard."""

    # ------------------------------------------------------------------
    # REST API
    # ------------------------------------------------------------------

    @app.get("/api/runs")
    async def api_list_runs(status: Optional[str] = Query(None)):
        manager = get_run_manager()
        runs = manager.list_runs(status=status)
        # Attach the peak score per run so the list view can show
        # at-a-glance "what did this achieve?" without a per-card fetch.
        # Cheap with the experiments table indexed on run_id.
        results = []
        for r in runs:
            d = RunResponse.from_info(r).model_dump()
            d["peak"] = manager.get_peak_score(r.id)
            results.append(d)
        return results

    @app.post("/api/runs")
    async def api_create_run(req: CreateRunRequest):
        manager = get_run_manager()
        config = RunConfig(
            workspace=req.workspace,
            task=req.task,
            target_accuracy=req.target_accuracy,
            dataset_path=req.dataset_path,
            mode=req.mode,
            force_cpu=req.force_cpu,
            setup_workspace=req.setup_workspace,
            lower_is_better=req.lower_is_better,
            metric_name=req.metric_name,
        )
        run_id = manager.create_run(config)
        manager.start_run(run_id)
        return JSONResponse(
            {"id": run_id, "status": "running", "redirect": f"/runs/{run_id}"},
            status_code=201,
        )

    @app.get("/api/runs/{run_id}")
    async def api_get_run(run_id: str):
        manager = get_run_manager()
        run = manager.get_run(run_id)
        if not run:
            raise HTTPException(status_code=404, detail="Run not found")
        stages = manager.get_stages(run_id)
        return {
            "run": RunResponse.from_info(run).model_dump(),
            "stages": [StageResponse.from_info(s).model_dump() for s in stages],
        }

    @app.post("/api/runs/{run_id}/cancel")
    async def api_cancel_run(run_id: str):
        manager = get_run_manager()
        ok = manager.cancel_run(run_id)
        if not ok:
            raise HTTPException(status_code=400, detail="Run not cancellable")
        return {"status": "cancelled"}

    @app.get("/api/runs/{run_id}/logs")
    async def api_get_logs(run_id: str, since: Optional[float] = Query(None)):
        manager = get_run_manager()
        events = manager.get_events(run_id, since=since)
        return events

    @app.get("/api/runs/{run_id}/experiments")
    async def api_get_experiments(run_id: str):
        """Return the run's experiments in step order.

        Each row: id, step, parent_step, proposal, score, lower_is_better,
        kept, tag, commit_sha, created_at. Score is null when the val-score
        parser couldn't extract a number from the training log (the dash
        renders this as an unscored attempt rather than a hard-coded
        sentinel like inf).
        """
        manager = get_run_manager()
        run = manager.get_run(run_id)
        if not run:
            raise HTTPException(status_code=404, detail="Run not found")
        return manager.list_experiments(run_id)

    @app.get("/api/runs/{run_id}/summary")
    async def api_get_summary(run_id: str):
        """One-shot bundle for the dashboard: run + stages + experiments
        + peak score + recent events. Lets the React app populate the
        whole detail view from a single fetch on initial load and rely
        on SSE for incremental updates after that.
        """
        manager = get_run_manager()
        run = manager.get_run(run_id)
        if not run:
            raise HTTPException(status_code=404, detail="Run not found")
        stages = manager.get_stages(run_id)
        experiments = manager.list_experiments(run_id)
        peak = manager.get_peak_score(run_id)
        events = manager.get_events(run_id)
        return {
            "run": RunResponse.from_info(run).model_dump(),
            "stages": [StageResponse.from_info(s).model_dump() for s in stages],
            "experiments": experiments,
            "peak": peak,
            "events": events,
        }

    @app.get("/api/runs/{run_id}/research-log")
    async def api_get_research_log(run_id: str):
        """Return the agent's research_log.md — its own narrative of which
        experiments it tried, what it expected, and what worked. Each
        BaselineEvalNode / HillClimbEvalNode iteration appends a section.
        """
        from pathlib import Path
        from fastapi.responses import JSONResponse
        manager = get_run_manager()
        run = manager.get_run(run_id)
        if not run:
            raise HTTPException(status_code=404, detail="Run not found")
        path = Path(run.workspace) / "research_log.md"
        if not path.exists():
            return JSONResponse({"text": "", "exists": False})
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except Exception as e:
            return JSONResponse({"text": "", "exists": False, "error": str(e)})
        return JSONResponse({"text": text, "exists": True, "path": str(path)})

    @app.get("/api/runs/{run_id}/git-log")
    async def api_get_git_log(run_id: str, limit: int = Query(100)):
        """Return the workspace's git log as parsed commit rows.

        Each kept experiment is a commit; reverted ones never land. So
        this is effectively the run's "what survived" history.
        """
        import subprocess
        from pathlib import Path
        from fastapi.responses import JSONResponse
        manager = get_run_manager()
        run = manager.get_run(run_id)
        if not run:
            raise HTTPException(status_code=404, detail="Run not found")
        ws = Path(run.workspace)
        if not (ws / ".git").exists():
            return JSONResponse({"commits": [], "exists": False})
        # %x1f is unit-separator; safer than tabs/colons inside subjects.
        fmt = "%H%x1f%h%x1f%cI%x1f%an%x1f%s"
        try:
            res = subprocess.run(
                ["git", "log", f"--max-count={limit}", f"--format={fmt}", "--all"],
                cwd=str(ws), capture_output=True, text=True, timeout=10,
            )
        except Exception as e:
            return JSONResponse({"commits": [], "exists": True, "error": str(e)})
        if res.returncode != 0:
            return JSONResponse({"commits": [], "exists": True, "error": res.stderr.strip()})
        commits = []
        for line in (res.stdout or "").splitlines():
            parts = line.split("\x1f")
            if len(parts) == 5:
                sha, short, date, author, subject = parts
                commits.append({
                    "sha": sha, "short": short, "date": date,
                    "author": author, "subject": subject,
                })
        # Branches → list, plus the current HEAD branch for context.
        branches: list[str] = []
        try:
            br = subprocess.run(
                ["git", "branch", "--all", "--format=%(refname:short)"],
                cwd=str(ws), capture_output=True, text=True, timeout=5,
            )
            if br.returncode == 0:
                branches = [b.strip() for b in br.stdout.splitlines() if b.strip()]
        except Exception:
            pass
        head_branch = ""
        try:
            hb = subprocess.run(
                ["git", "branch", "--show-current"],
                cwd=str(ws), capture_output=True, text=True, timeout=5,
            )
            if hb.returncode == 0:
                head_branch = hb.stdout.strip()
        except Exception:
            pass
        return JSONResponse({
            "commits": commits, "branches": branches,
            "head_branch": head_branch, "exists": True,
        })

    @app.get("/api/runs/{run_id}/training-log")
    async def api_get_training_log(run_id: str, offset: int = Query(0)):
        """Tail the workspace's training.log file with offset polling.

        Each agent's train.py is supposed to write epoch lines like
        "Epoch 1/10 - loss: 0.42, val_acc: 0.85" to <workspace>/training.log
        (or <workspace>/logs/training.log). The dashboard's Training tab
        consumes this so users can watch training advance live and we
        can parse metrics out for the chart.

        If the file doesn't exist yet (training hasn't started), returns
        exists=false so the UI can show a friendly "waiting" state.
        """
        from pathlib import Path
        from fastapi.responses import JSONResponse
        manager = get_run_manager()
        run = manager.get_run(run_id)
        if not run:
            raise HTTPException(status_code=404, detail="Run not found")
        candidates = [
            Path(run.workspace) / "training.log",
            Path(run.workspace) / "logs" / "training.log",
        ]
        for path in candidates:
            if path.exists():
                size = path.stat().st_size
                if offset > size:
                    offset = 0
                with open(path, "r", encoding="utf-8", errors="replace") as f:
                    f.seek(offset)
                    text = f.read()
                return JSONResponse({
                    "text": text, "size": size, "exists": True,
                    "path": str(path),
                })
        return JSONResponse({"text": "", "size": 0, "exists": False})

    @app.get("/api/runs/{run_id}/console")
    async def api_get_console(run_id: str, offset: int = Query(0)):
        """Serve the per-run console capture file as plain text.

        `offset` (in bytes) lets the client poll for incremental updates:
        send the previous file size, get back only the new bytes plus the
        new size. The web UI uses this to do an efficient `tail -f`-style
        live view without reloading the whole log on every poll.
        """
        from mle_beast.run_manager import console_log_path
        from fastapi.responses import JSONResponse

        path = console_log_path(run_id)
        if not path.exists():
            return JSONResponse({"text": "", "size": 0, "exists": False})

        size = path.stat().st_size
        if offset > size:
            # File got truncated/rotated since the last poll — just resend it all.
            offset = 0
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            f.seek(offset)
            text = f.read()
        return JSONResponse({"text": text, "size": size, "exists": True})

    # ------------------------------------------------------------------
    # Settings
    # ------------------------------------------------------------------

    @app.get("/api/settings")
    async def api_get_settings():
        return get_settings().to_dict()

    @app.get("/api/local-model-name")
    async def api_local_model_name():
        """Auto-discover the model name from a local LLM server."""
        import os
        from mle_beast.llm import _auto_detect_local_model
        base_url = os.environ.get("LOCAL_LLM_BASE_URL", "http://localhost:8000/v1")
        model = _auto_detect_local_model(base_url)
        return {"model": model}

    @app.post("/api/settings")
    async def api_save_settings(request: Request):
        from mle_beast.db import get_database
        body = await request.json()
        # Build Settings from submitted data, falling back to defaults
        defaults = Settings()
        data = {}
        for field_name in defaults.to_dict():
            if field_name in body:
                val = body[field_name]
                default_val = getattr(defaults, field_name)
                if isinstance(default_val, int):
                    data[field_name] = int(val)
                else:
                    data[field_name] = str(val)
            else:
                data[field_name] = getattr(defaults, field_name)
        settings = Settings.from_dict(data)
        save_settings(get_database(), settings)
        reload_settings()
        return {"status": "ok"}

    # ------------------------------------------------------------------
    # Admin
    # ------------------------------------------------------------------

    @app.get("/api/admin/stats")
    async def api_admin_stats():
        from mle_beast.db import get_database
        return get_database().get_stats()

    @app.post("/api/admin/delete-old-runs")
    async def api_delete_old_runs(request: Request):
        from mle_beast.db import get_database
        body = await request.json()
        days = int(body.get("days", 30))
        count = get_database().delete_runs_older_than(days)
        return {"status": "ok", "deleted": count}

    @app.post("/api/admin/reset-database")
    async def api_reset_database(request: Request):
        from mle_beast.db import get_database
        body = await request.json()
        if body.get("confirm") != "RESET":
            return JSONResponse(
                {"error": "Type RESET to confirm"}, status_code=400
            )
        get_database().reset_database()
        return {"status": "ok"}

    @app.delete("/api/admin/runs/{run_id}")
    async def api_delete_run(run_id: str):
        from mle_beast.db import get_database
        get_database().delete_run(run_id)
        return {"status": "ok"}

    # ------------------------------------------------------------------
    # SSE endpoint
    # ------------------------------------------------------------------

    @app.get("/api/runs/{run_id}/events")
    async def api_sse_events(run_id: str):
        """Server-Sent Events stream for real-time pipeline updates."""
        bus = get_event_bus()
        queue = bus.subscribe_async(run_id)

        async def event_generator():
            try:
                while True:
                    try:
                        event: PipelineEvent = await asyncio.wait_for(
                            queue.get(), timeout=15.0,
                        )
                        # Determine SSE event type
                        from mle_beast.events import (
                            EventType,
                            ExperimentRecorded,
                            LLMCall,
                            RunStateChanged,
                            StageCompleted,
                            StageStarted,
                        )
                        if isinstance(event, (StageStarted, StageCompleted)):
                            sse_type = "stage_update"
                        elif isinstance(event, ExperimentRecorded):
                            sse_type = "experiment"
                        elif isinstance(event, LLMCall):
                            sse_type = "llm_call"
                        elif isinstance(event, RunStateChanged):
                            sse_type = "run_complete" if event.new_state in ("completed", "failed", "cancelled") else "stage_update"
                        else:
                            sse_type = "log_entry"

                        yield f"event: {sse_type}\ndata: {event.to_sse_data()}\n\n"

                        # Stop streaming when run finishes
                        if isinstance(event, RunStateChanged) and event.new_state in ("completed", "failed", "cancelled"):
                            break

                    except asyncio.TimeoutError:
                        # Heartbeat
                        yield f": heartbeat {time.time()}\n\n"

            finally:
                bus.unsubscribe_async(run_id, queue)

        return StreamingResponse(
            event_generator(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",
            },
        )
