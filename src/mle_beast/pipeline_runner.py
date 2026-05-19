# Copyright 2026 Chris Padwick
# SPDX-License-Identifier: Apache-2.0

"""execute_pipeline() — runs the PocketFlow pipeline for a single run.

Pulled out of RunManager._run_pipeline so the actual pipeline-execution
flow is independently testable. Takes explicit db / bus / settings /
cancel-event references rather than reaching for module-level singletons.
"""

from __future__ import annotations

import json
import logging
import threading
import time
import traceback
from pathlib import Path

from mle_beast.db import Database
from mle_beast.events import (
    EventBus,
    LogMessage,
    RunStateChanged,
    StageCompleted,
    StageStarted,
    set_current_run_id,
)
from mle_beast.run_io import StdioCapture, install_stdio_tee, restore_stdio
from mle_beast.settings import Settings


def execute_pipeline(
    run_id: str,
    cancel_event: threading.Event,
    db: Database,
    bus: EventBus,
    settings: Settings,
) -> None:
    """Run the pipeline for a row already inserted as 'pending' in the DB.

    Side effects:
      - Updates the run's status through pending → running → (completed|failed).
      - Emits PipelineEvents on the bus.
      - Spawns subprocesses via the inner pipeline nodes.

    Returns when the pipeline terminates (completed, failed, or cancelled).
    Never raises — exceptions are caught and recorded against the run.
    """
    # Apply log level
    level = getattr(logging, settings.log_level, logging.INFO)
    logging.getLogger("mle_beast").setLevel(level)

    # Tag this thread with the run_id so command_runner._log (and any
    # other low-level utility) can emit LogMessage events to the bus
    # without us threading run_id through every call site.
    set_current_run_id(run_id)
    capture = install_stdio_tee(run_id)

    # Transition to running.
    db.update_run(run_id, status="running", started_at=time.time())
    bus.emit(RunStateChanged(
        run_id=run_id, old_state="pending", new_state="running",
    ))

    run_row = db.get_run(run_id)
    if not run_row:
        _teardown(capture)
        return

    try:
        _ensure_workspace(run_row, bus, db, run_id)
        workspace = _setup_run_context(run_row)
        shared = _build_shared_dict(
            run_id, run_row, workspace, bus, cancel_event, settings,
        )

        from mle_beast.flows.full_pipeline import build_full_pipeline
        flow = build_full_pipeline()
        flow.run(shared)

        _finalize_completion(db, bus, run_id, shared)

    except Exception as e:  # noqa: BLE001 — any failure goes into the verdict
        _finalize_failure(db, bus, run_id, e)

    finally:
        _teardown(capture)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _ensure_workspace(run_row: dict, bus: EventBus, db: Database, run_id: str) -> None:
    """Make sure the workspace dir exists and (optionally) is fully provisioned.

    Three cases, in priority order:

    1. `environment` is set — BYO Python env. Validate the user's path,
       skip WorkspaceCreator entirely. Takes precedence over
       `setup_workspace` because if the user gave us a path they want
       us to use it, not download a fresh stack.

    2. `setup_workspace=True` — run WorkspaceCreator, which clones
       ml-frameworks + creates a venv + installs the ML stack. Slow
       (~minutes to hours) but produces a known-good environment.

    3. Default — assume the user manages their own venv at
       `<workspace>/.venv` or `<workspace>/venv`. Probe it via
       check_workspace_env before the pipeline starts so we fail fast
       on missing prereqs.

    Always creates the bare workspace directory — saves the user from
    a FileNotFoundError mid-run when they typed a path that doesn't
    exist yet.
    """
    from mle_beast.workspace import (
        WorkspaceCreator,
        WorkspaceRegistry,
        check_workspace_env,
        validate_environment_path,
    )

    Path(run_row["workspace"]).mkdir(parents=True, exist_ok=True)

    env_path = (run_row.get("environment") or "").strip() or None

    if env_path:
        # BYO env. Validate before doing anything else — if it's bad,
        # raise so _run_pipeline marks the run failed with the message.
        resolved = validate_environment_path(env_path)
        WorkspaceRegistry.set_environment(resolved)
        bus.emit(LogMessage(
            run_id=run_id, stage="setup",
            message=f"Using user-supplied environment: {resolved}",
        ))
        db.upsert_stage(run_id, "setup", status="pass")
        return

    if run_row["setup_workspace"]:
        bus.emit(StageStarted(run_id=run_id, stage="setup"))
        bus.emit(LogMessage(
            run_id=run_id, stage="setup",
            message=f"Setting up workspace at {run_row['workspace']}...",
        ))
        WorkspaceCreator(run_row["workspace"]).run()
        bus.emit(LogMessage(
            run_id=run_id, stage="setup",
            message="Workspace setup complete.",
        ))
        bus.emit(StageCompleted(
            run_id=run_id, stage="setup", outcome="pass",
        ))
    else:
        # User opted out of workspace setup → they own the venv.
        check_workspace_env(run_row["workspace"], mode=run_row.get("mode"))
        db.upsert_stage(run_id, "setup", status="pass")


def _setup_run_context(run_row: dict):
    """Register process-wide state for this run: workspace + read-allowlist.

    Returns the resolved workspace path (a pathlib.Path from
    WorkspaceRegistry.set_workspace). Caller passes this to
    _build_shared_dict so the dict construction can stay side-effect-free.

    The metric_name-gated add_allowed_read_path is preserved from the
    original — it's almost certainly an unrelated bug (the dataset path
    needs to be readable regardless of whether a metric_name is set),
    but fixing that is out of scope for this structural PR.
    """
    from mle_beast.workspace import WorkspaceRegistry

    ws = WorkspaceRegistry.set_workspace(run_row["workspace"])
    if run_row.get("metric_name"):
        WorkspaceRegistry.add_allowed_read_path(run_row["dataset_path"])
    return ws


def _build_shared_dict(
    run_id: str,
    run_row: dict,
    workspace,
    bus: EventBus,
    cancel_event: threading.Event,
    settings: Settings,
) -> dict:
    """Build the PocketFlow shared dict that flows through every node.

    Pure construction — registry mutations live in _setup_run_context;
    device detection runs nvidia-smi but its result goes into the dict
    we return, so it belongs here.
    """
    from mle_beast.cuda_detection import select_device

    device = select_device(force_cpu=bool(run_row["force_cpu"]))

    shared: dict = {
        "task": run_row["task"],
        "workspace": str(workspace),
        "device": device,
        "event_bus": bus,
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
    # Metric direction override: when set, the eval nodes must use this
    # regardless of what the LLM extractor decides. Stored under a
    # distinct key so the existing inferred `lower_is_better` shared
    # field stays untouched.
    if run_row.get("lower_is_better") is not None:
        shared["lower_is_better_override"] = bool(run_row["lower_is_better"])
    # Authoritative metric name → fed to the val-score extractor so it
    # picks the right field even when the training log emphasizes a
    # different metric.
    if run_row.get("metric_name"):
        shared["metric_name"] = run_row["metric_name"]
    return shared


def _finalize_completion(
    db: Database, bus: EventBus, run_id: str, shared: dict,
) -> None:
    """Pipeline finished cleanly — persist verdict + final state."""
    verdict = shared.get("verdict")
    verdict_json = None
    if verdict is not None:
        try:
            verdict_json = (
                verdict.model_dump_json()
                if hasattr(verdict, "model_dump_json")
                else json.dumps(str(verdict))
            )
        except Exception:
            verdict_json = json.dumps(str(verdict))

    from mle_beast.hillclimb import print_pipeline_summary
    print_pipeline_summary(shared)

    db.update_run(
        run_id,
        status="completed",
        completed_at=time.time(),
        verdict_json=verdict_json,
        experiment_branch=shared.get("experiment_branch"),
    )
    bus.emit(RunStateChanged(
        run_id=run_id, old_state="running", new_state="completed",
    ))


def _finalize_failure(
    db: Database, bus: EventBus, run_id: str, exc: BaseException,
) -> None:
    """Pipeline threw — persist the traceback against the run."""
    error_msg = f"{type(exc).__name__}: {exc}\n{traceback.format_exc()}"
    db.update_run(
        run_id,
        status="failed",
        completed_at=time.time(),
        error_message=error_msg,
    )
    bus.emit(RunStateChanged(
        run_id=run_id, old_state="running", new_state="failed",
    ))
    bus.emit(LogMessage(
        run_id=run_id, level="error",
        message=f"Pipeline failed: {exc}",
    ))


def _teardown(capture: StdioCapture) -> None:
    """Restore stdio + clear the thread-local run_id."""
    restore_stdio(capture)
    try:
        set_current_run_id(None)
    except Exception:
        pass
