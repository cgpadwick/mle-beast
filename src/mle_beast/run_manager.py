# Copyright 2026 Chris Padwick
# SPDX-License-Identifier: Apache-2.0

"""RunManager — central coordinator for pipeline run lifecycle.

Creates runs, starts the pipeline in a background thread, tracks state,
and persists everything to SQLite.
"""

from __future__ import annotations

import json
import os
import threading
import time
import traceback
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional, TextIO

from mle_beast.db import get_database
from mle_beast.events import (
    EventBus,
    LogMessage,
    PipelineEvent,
    RetryOccurred,
    RunStateChanged,
    StageCompleted,
    StageStarted,
    get_event_bus,
)


# Stage rows pre-created at run insert time so the dashboard sees a stable
# skeleton even before any StageStarted events fire. This must match the
# stages the live pipeline actually emits — extras leak as stale "pending"
# rows in the dashboard. The web routes have a richer ordered list (used
# only for display); this one is the upsert seed.
STAGE_ORDER = [
    "setup",
    "data_analysis",
    "data_analysis_critic",
    "baseline",
    "testing",
    "training",
    "train_finder",
    "train_finder_critic",
    "analysis",
    "evaluate",
    "eval_finder",
    "eval_finder_critic",
    "proposal",
    "proposal_critic",
    "implement",
    "hillclimb_test",
]


def console_log_path(run_id: str) -> Path:
    """Per-run console-capture file under ~/.mle-beast/runs/<id>/console.log."""
    base = os.environ.get(
        "MLE_BEAST_RUNS_DIR",
        str(Path.home() / ".mle-beast" / "runs"),
    )
    return Path(base) / run_id / "console.log"


class _Tee:
    """Tiny tee stream: writes go to both an underlying handle and a file.

    Used only inside _run_pipeline to capture everything the pipeline
    thread prints (own prints + library logs + any subprocess output that
    ends up in our Python stdout/stderr) into a per-run console file
    while STILL going to the original terminal stream.

    Note: Python's sys.stdout/sys.stderr are process-global, so installing
    a tee redirects ALL output during the pipeline thread's lifetime —
    including web-server (uvicorn) requests handled in parallel. That's
    a small acceptable cost for v1.
    """

    def __init__(self, primary: TextIO, file: TextIO) -> None:
        self._primary = primary
        self._file = file

    def write(self, data: str) -> int:
        try:
            self._file.write(data)
            self._file.flush()
        except Exception:
            pass
        return self._primary.write(data)

    def flush(self) -> None:
        try:
            self._file.flush()
        except Exception:
            pass
        try:
            self._primary.flush()
        except Exception:
            pass

    def isatty(self) -> bool:
        return False

    def __getattr__(self, name: str):
        return getattr(self._primary, name)


@dataclass
class RunConfig:
    """Configuration for a pipeline run."""
    workspace: str
    task: str
    target_accuracy: Optional[float] = None
    dataset_path: Optional[str] = None
    mode: str = "greenfield"
    # GPU by default when one is detected (select_device auto-detects via
    # nvidia-smi at run start). Flip to True only when you explicitly want
    # to force CPU — e.g., a CI box without a GPU, or known-flaky CUDA.
    force_cpu: bool = False
    setup_workspace: bool = False
    # Metric direction override. None → auto-detect via LLM extractor +
    # keyword heuristic (current default). True → lower-is-better
    # (loss/RMSE/MAE etc). False → higher-is-better (accuracy/F1/AUC etc).
    # Set this when you know your metric — it skips the auto-inference,
    # which can flip the wrong way on ambiguous training logs.
    lower_is_better: Optional[bool] = None
    # Free-text metric name (e.g. "accuracy", "f1_macro", "rmse"). When
    # set, fed to the val-score extractor as authoritative metric info
    # so it picks the correct field out of training logs even when the
    # agent's train.py emphasizes something else.
    metric_name: Optional[str] = None


@dataclass
class RunInfo:
    """Summary of a run's current state."""
    id: str
    status: str
    workspace: str
    task: str
    target_accuracy: Optional[float]
    dataset_path: Optional[str]
    mode: str
    force_cpu: bool
    setup_workspace: bool
    created_at: float
    started_at: Optional[float] = None
    completed_at: Optional[float] = None
    verdict_json: Optional[str] = None
    error_message: Optional[str] = None
    experiment_branch: Optional[str] = None
    lower_is_better: Optional[bool] = None
    metric_name: Optional[str] = None
    total_cost_usd: float = 0.0
    total_prompt_tokens: int = 0
    total_completion_tokens: int = 0
    total_reasoning_tokens: int = 0
    total_llm_calls: int = 0

    @classmethod
    def from_db_row(cls, row: dict) -> RunInfo:
        lib = row.get("lower_is_better")
        return cls(
            id=row["id"],
            status=row["status"],
            workspace=row.get("workspace", ""),
            task=row.get("task", ""),
            target_accuracy=row.get("target_accuracy"),
            dataset_path=row.get("dataset_path"),
            mode=row.get("mode", "greenfield"),
            force_cpu=bool(row.get("force_cpu", False)),
            setup_workspace=bool(row.get("setup_workspace", False)),
            created_at=row.get("created_at", 0),
            started_at=row.get("started_at"),
            completed_at=row.get("completed_at"),
            verdict_json=row.get("verdict_json"),
            error_message=row.get("error_message"),
            experiment_branch=row.get("experiment_branch"),
            lower_is_better=None if lib is None else bool(lib),
            metric_name=row.get("metric_name"),
            total_cost_usd=float(row.get("total_cost_usd") or 0.0),
            total_prompt_tokens=int(row.get("total_prompt_tokens") or 0),
            total_completion_tokens=int(row.get("total_completion_tokens") or 0),
            total_reasoning_tokens=int(row.get("total_reasoning_tokens") or 0),
            total_llm_calls=int(row.get("total_llm_calls") or 0),
        )


@dataclass
class StageInfo:
    """Summary of a stage's current state."""
    stage_name: str
    status: str
    attempt: int
    max_attempts: int
    started_at: Optional[float] = None
    completed_at: Optional[float] = None
    verdict_json: Optional[str] = None

    @classmethod
    def from_db_row(cls, row: dict) -> StageInfo:
        return cls(
            stage_name=row["stage_name"],
            status=row.get("status", "pending"),
            attempt=row.get("attempt", 0),
            max_attempts=row.get("max_attempts", 3),
            started_at=row.get("started_at"),
            completed_at=row.get("completed_at"),
            verdict_json=row.get("verdict_json"),
        )


class RunManager:
    """Manages the lifecycle of pipeline runs.

    - Creates runs in the DB.
    - Starts the pipeline in a background thread.
    - Listens to events and persists stage/event updates.
    - Provides query methods for runs, stages, and events.
    """

    def __init__(self, event_bus: Optional[EventBus] = None) -> None:
        self._db = get_database()
        self._bus = event_bus or get_event_bus()
        self._threads: dict[str, threading.Thread] = {}
        self._cancel_flags: dict[str, threading.Event] = {}

    def create_run(self, config: RunConfig) -> str:
        """Insert a new run as 'pending' and return its ID."""
        run_id = str(uuid.uuid4())
        now = time.time()

        self._db.insert_run({
            "id": run_id,
            "status": "pending",
            "workspace": config.workspace,
            "task": config.task,
            "target_accuracy": config.target_accuracy,
            "dataset_path": config.dataset_path,
            "mode": config.mode,
            "force_cpu": int(config.force_cpu),
            "setup_workspace": int(config.setup_workspace),
            "lower_is_better": (None if config.lower_is_better is None
                                 else int(config.lower_is_better)),
            "metric_name": (config.metric_name.strip() if config.metric_name else None) or None,
            "created_at": now,
        })

        # Pre-create stage rows
        for stage_name in STAGE_ORDER:
            self._db.upsert_stage(run_id, stage_name, status="pending")

        return run_id

    def start_run(self, run_id: str) -> None:
        """Launch the pipeline in a background thread."""
        cancel_event = threading.Event()
        self._cancel_flags[run_id] = cancel_event

        # Subscribe a DB-persisting listener
        self._bus.subscribe(run_id, self._make_db_listener(run_id))

        thread = threading.Thread(
            target=self._run_pipeline,
            args=(run_id, cancel_event),
            name=f"pipeline-{run_id[:8]}",
            daemon=True,
        )
        self._threads[run_id] = thread
        thread.start()

    def cancel_run(self, run_id: str) -> bool:
        """Request cancellation of a running pipeline.

        Works both in-process (sets threading.Event) and cross-process
        (writes 'cancelled' to DB — the pipeline thread polls DB status).
        """
        run = self._db.get_run(run_id)
        if not run or run["status"] not in ("pending", "running"):
            return False

        # Set in-memory flag if available (same-process cancel)
        flag = self._cancel_flags.get(run_id)
        if flag is not None:
            flag.set()

        # Always write to DB (cross-process cancel)
        self._db.update_run(run_id, status="cancelled", completed_at=time.time())
        self._bus.emit(RunStateChanged(
            run_id=run_id, old_state=run["status"], new_state="cancelled",
        ))
        return True

    def get_run(self, run_id: str) -> Optional[RunInfo]:
        row = self._db.get_run(run_id)
        return RunInfo.from_db_row(row) if row else None

    def list_runs(self, status: Optional[str] = None) -> list[RunInfo]:
        rows = self._db.list_runs(status=status)
        return [RunInfo.from_db_row(r) for r in rows]

    def get_stages(self, run_id: str) -> list[StageInfo]:
        rows = self._db.get_stages(run_id)
        return [StageInfo.from_db_row(r) for r in rows]

    def get_events(self, run_id: str, since: Optional[float] = None) -> list[dict]:
        return self._db.get_events(run_id, since=since)

    def list_experiments(self, run_id: str) -> list[dict]:
        """Return the run's experiment rows, ordered by step."""
        return self._db.list_experiments(run_id)

    def get_peak_score(self, run_id: str) -> Optional[dict]:
        """Best score among kept experiments + the step that produced it.

        Returns None when the run has no kept-with-score rows yet (very
        early in a run, or every parse failed). The dashboard treats None
        as "—" rather than rendering an inf sentinel.
        """
        rows = self._db.list_experiments(run_id)
        kept = [r for r in rows if r.get("kept") and r.get("score") is not None]
        if not kept:
            return None
        # Direction comes from the rows themselves — the pipeline records
        # lower_is_better per experiment (it's stable across a run).
        lower = bool(kept[0].get("lower_is_better"))
        best = min(kept, key=lambda r: r["score"]) if lower else max(kept, key=lambda r: r["score"])
        return {
            "score": best["score"],
            "step": best["step"],
            "lower_is_better": lower,
            "kept_count": sum(1 for r in rows if r.get("kept")),
            "reverted_count": sum(1 for r in rows if not r.get("kept")),
        }

    def wait_for_run(self, run_id: str, timeout: Optional[float] = None) -> None:
        """Block until the pipeline thread finishes."""
        thread = self._threads.get(run_id)
        if thread:
            thread.join(timeout=timeout)

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _run_pipeline(self, run_id: str, cancel_event: threading.Event) -> None:
        """Execute the pipeline (runs in background thread)."""
        import sys
        from mle_beast.flows.full_pipeline import build_full_pipeline
        from mle_beast.settings import get_settings
        from mle_beast.workspace import WorkspaceCreator, WorkspaceRegistry, check_workspace_env

        # Snapshot settings for this run
        settings = get_settings()

        # Apply log level
        import logging
        level = getattr(logging, settings.log_level, logging.INFO)
        logging.getLogger("mle_beast").setLevel(level)

        # Tag this thread with the run_id so command_runner._log (and
        # any other low-level utility) can emit LogMessage events to the
        # event bus without us threading run_id through every call site.
        from mle_beast.events import set_current_run_id
        set_current_run_id(run_id)

        # Open a per-run console capture file and tee stdout/stderr into it.
        # The web UI surfaces this file directly so the user sees exactly
        # what the launching terminal would see, in real time.
        orig_stdout, orig_stderr = sys.stdout, sys.stderr
        console_file = None
        try:
            log_path = console_log_path(run_id)
            log_path.parent.mkdir(parents=True, exist_ok=True)
            console_file = log_path.open("a", buffering=1, encoding="utf-8")
            sys.stdout = _Tee(orig_stdout, console_file)
            sys.stderr = _Tee(orig_stderr, console_file)
        except Exception:
            # If we can't open the file, fall back silently to non-tee'd
            # mode — pipeline runs are more important than the console log.
            console_file = None

        # Transition to running
        now = time.time()
        self._db.update_run(run_id, status="running", started_at=now)
        self._bus.emit(RunStateChanged(
            run_id=run_id, old_state="pending", new_state="running",
        ))

        run_row = self._db.get_run(run_id)
        if not run_row:
            self._restore_stdio_and_clear(orig_stdout, orig_stderr, console_file, run_id)
            return

        try:
            # Always make sure the workspace directory itself exists. This
            # is cheap and saves the user from a FileNotFoundError mid-run
            # when they typed a path that doesn't exist yet. The heavier
            # `setup_workspace` flag (which provisions a venv + ML stack)
            # is still opt-in.
            from pathlib import Path
            Path(run_row["workspace"]).mkdir(parents=True, exist_ok=True)

            # Optionally set up workspace
            if run_row["setup_workspace"]:
                self._bus.emit(StageStarted(run_id=run_id, stage="setup"))
                self._bus.emit(LogMessage(
                    run_id=run_id, stage="setup",
                    message=f"Setting up workspace at {run_row['workspace']}...",
                ))
                creator = WorkspaceCreator(run_row["workspace"])
                creator.run()
                self._bus.emit(LogMessage(
                    run_id=run_id, stage="setup",
                    message="Workspace setup complete.",
                ))
                self._bus.emit(StageCompleted(
                    run_id=run_id, stage="setup", outcome="pass",
                ))
            else:
                # User opted out of workspace setup → they own the venv.
                # Verify it's actually present and has pytest before we
                # waste their time running a pipeline that'd fail on the
                # first import. Raises RuntimeError with an actionable
                # message if either check fails.
                check_workspace_env(run_row["workspace"], mode=run_row.get("mode"))
                self._db.upsert_stage(run_id, "setup", status="pass")

            # Register workspace
            ws = WorkspaceRegistry.set_workspace(run_row["workspace"])

            # Pick the training device once. Default is GPU when available;
            # CPU only when no GPU is visible OR force_cpu is set.
            from mle_beast.cuda_detection import select_device
            device = select_device(force_cpu=bool(run_row["force_cpu"]))

            # Build shared dict
            shared: dict = {
                "task": run_row["task"],
                "workspace": str(ws),
                "device": device,
                "event_bus": self._bus,
                "run_id": run_id,
                "_cancel_event": cancel_event,
                "settings": settings,
                # Hill-climb state — runner-level defaults
                "step_count": 0,
                "max_steps": 30,
                "best_score": None,
                "consecutive_failures": 0,
                "max_consecutive_failures": 10,
                "experiments": [],
                "current_proposal": "",
            }
            if run_row.get("mode"):
                shared["mode"] = run_row["mode"]
            if run_row.get("target_accuracy") is not None:
                shared["target_accuracy"] = run_row["target_accuracy"]
            if run_row.get("dataset_path"):
                shared["dataset_path"] = run_row["dataset_path"]
            # Metric direction override: when set, the eval nodes must
            # use this regardless of what the LLM extractor decides.
            # Stored under a distinct key so the existing inferred
            # `lower_is_better` shared field stays untouched.
            if run_row.get("lower_is_better") is not None:
                shared["lower_is_better_override"] = bool(run_row["lower_is_better"])
            # Authoritative metric name → fed to the val-score extractor
            # so it picks the right field even when the training log
            # emphasizes a different metric.
            if run_row.get("metric_name"):
                shared["metric_name"] = run_row["metric_name"]
                WorkspaceRegistry.add_allowed_read_path(run_row["dataset_path"])

            # Run the pipeline
            flow = build_full_pipeline()
            flow.run(shared)

            # Pipeline completed
            verdict = shared.get("verdict")
            verdict_json = None
            if verdict is not None:
                try:
                    verdict_json = verdict.model_dump_json() if hasattr(verdict, "model_dump_json") else json.dumps(str(verdict))
                except Exception:
                    verdict_json = json.dumps(str(verdict))

            from mle_beast.hillclimb import print_pipeline_summary
            print_pipeline_summary(shared)

            self._db.update_run(
                run_id,
                status="completed",
                completed_at=time.time(),
                verdict_json=verdict_json,
                experiment_branch=shared.get("experiment_branch"),
            )
            self._bus.emit(RunStateChanged(
                run_id=run_id, old_state="running", new_state="completed",
            ))

        except Exception as e:
            error_msg = f"{type(e).__name__}: {e}\n{traceback.format_exc()}"
            self._db.update_run(
                run_id,
                status="failed",
                completed_at=time.time(),
                error_message=error_msg,
            )
            self._bus.emit(RunStateChanged(
                run_id=run_id, old_state="running", new_state="failed",
            ))
            self._bus.emit(LogMessage(
                run_id=run_id, level="error",
                message=f"Pipeline failed: {e}",
            ))

        finally:
            self._restore_stdio_and_clear(
                orig_stdout, orig_stderr, console_file, run_id,
            )
            self._cancel_flags.pop(run_id, None)
            self._threads.pop(run_id, None)

    def _restore_stdio_and_clear(
        self,
        orig_stdout,
        orig_stderr,
        console_file,
        run_id: str,
    ) -> None:
        """Undo the per-run stdout/stderr tee and clear the thread-local run_id.

        Both teardown steps are wrapped in their own try/excepts so a
        failure in one doesn't skip the other.
        """
        import sys
        try:
            sys.stdout = orig_stdout
            sys.stderr = orig_stderr
        except Exception:
            pass
        if console_file is not None:
            try:
                console_file.close()
            except Exception:
                pass
        try:
            from mle_beast.events import set_current_run_id
            set_current_run_id(None)
        except Exception:
            pass

    def _make_db_listener(self, run_id: str):
        """Create a sync callback that persists events to the DB."""
        def listener(event: PipelineEvent) -> None:
            # Persist all events
            self._db.insert_event(
                run_id=event.run_id,
                timestamp=event.timestamp,
                event_type=event.event_type.value,
                stage=event.stage,
                data_json=event.to_sse_data(),
            )

            # Update stage table for stage events
            if isinstance(event, StageStarted):
                self._db.deactivate_other_stages(run_id, event.stage)
                self._db.upsert_stage(
                    run_id, event.stage,
                    status="active", started_at=event.timestamp,
                    completed_at=None, verdict_json=None,
                )
            elif isinstance(event, StageCompleted):
                self._db.upsert_stage(
                    run_id, event.stage,
                    status=event.outcome, completed_at=event.timestamp,
                    verdict_json=event.verdict,
                )
            elif isinstance(event, RetryOccurred):
                self._db.upsert_stage(
                    run_id, event.stage,
                    status="fail", attempt=event.attempt,
                    max_attempts=event.max_attempts,
                )
            elif isinstance(event, RunStateChanged) and event.new_state in (
                "completed", "failed", "cancelled",
            ):
                # When a run terminates (target met, budget exhausted,
                # consecutive-failure abort, error, or user cancel), some
                # stage rows can still be 'active' because the eval node
                # returned 'done' without firing a StageCompleted for the
                # surrounding stage. Sweep them so the dashboard's
                # active-stage indicator doesn't lie about a finished run.
                # We mark them 'pass' on a clean completion and 'fail' on
                # a failure/cancel — that matches what the user would have
                # seen had the stage emitted its own completion event.
                outcome = "pass" if event.new_state == "completed" else "fail"
                for s in self._db.get_stages(run_id):
                    if s.get("status") == "active":
                        self._db.upsert_stage(
                            run_id, s["stage_name"],
                            status=outcome,
                            completed_at=event.timestamp,
                        )

        return listener


# Module-level singleton
_global_manager: Optional[RunManager] = None
_manager_lock = threading.Lock()


def get_run_manager() -> RunManager:
    """Get or create the global RunManager singleton."""
    global _global_manager
    if _global_manager is None:
        with _manager_lock:
            if _global_manager is None:
                _global_manager = RunManager()
    return _global_manager
