# Copyright 2026 Chris Padwick
# SPDX-License-Identifier: Apache-2.0

"""RunManager — central coordinator for pipeline run lifecycle.

Owns the public API for creating, starting, cancelling, and querying
runs. Delegates the actual pipeline-execution body to
:mod:`mle_beast.pipeline_runner`, stdio teeing to
:mod:`mle_beast.run_io`, and event→DB persistence to
:mod:`mle_beast.db_listener`.
"""

from __future__ import annotations

import threading
import time
import uuid
from dataclasses import dataclass
from typing import Optional

from mle_beast.db import get_database
from mle_beast.db_listener import make_db_listener
from mle_beast.events import (
    EventBus,
    RunStateChanged,
    get_event_bus,
)
from mle_beast.pipeline_runner import execute_pipeline

# Re-export console_log_path so existing callers (web/routes.py) keep working.
from mle_beast.run_io import console_log_path  # noqa: F401

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
    # BYO Python environment. When set, the pipeline reuses this venv/
    # conda env's bin/python instead of creating one via WorkspaceCreator
    # (which downloads the ~50GB ml-frameworks stack). Validated at run
    # start — if bin/python is missing or pytest isn't importable, the
    # run is marked failed with a clear message rather than crashing
    # mid-pipeline. Takes precedence over `setup_workspace`.
    environment: Optional[str] = None


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
    environment: Optional[str] = None
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
            environment=row.get("environment"),
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
    """Lifecycle + queries for pipeline runs.

    Owns the in-process thread + cancel-flag dicts. Delegates the actual
    pipeline execution to :func:`pipeline_runner.execute_pipeline` and
    event→DB persistence to :func:`db_listener.make_db_listener`.
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
            "environment": (config.environment.strip() if config.environment else None) or None,
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
        self._bus.subscribe(run_id, make_db_listener(run_id, self._db))

        thread = threading.Thread(
            target=self._run_thread,
            args=(run_id, cancel_event),
            name=f"pipeline-{run_id[:8]}",
            daemon=True,
        )
        self._threads[run_id] = thread
        thread.start()

    def _run_thread(self, run_id: str, cancel_event: threading.Event) -> None:
        """Pipeline thread target: delegate to execute_pipeline then clean up.

        execute_pipeline never raises (it traps everything into the verdict),
        so the finally is just for the in-memory bookkeeping dicts.
        """
        from mle_beast.settings import get_settings
        try:
            execute_pipeline(
                run_id=run_id,
                cancel_event=cancel_event,
                db=self._db,
                bus=self._bus,
                settings=get_settings(),
            )
        finally:
            self._cancel_flags.pop(run_id, None)
            self._threads.pop(run_id, None)

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

    def list_runs(
        self, status: Optional[str] = None, limit: int = 50, offset: int = 0,
    ) -> list[RunInfo]:
        rows = self._db.list_runs(status=status, limit=limit, offset=offset)
        return [RunInfo.from_db_row(r) for r in rows]

    def count_runs(self, status: Optional[str] = None) -> int:
        return self._db.count_runs(status=status)

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
