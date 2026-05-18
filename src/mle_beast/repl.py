# Copyright 2026 Chris Padwick
# SPDX-License-Identifier: Apache-2.0

"""Simple REPL for running the MLE-Beast pipeline.

No TUI — just an input loop that collects workspace path, task description,
target accuracy, and runs the full pipeline via RunManager.

CLI runs are persisted in SQLite and can be viewed on the web UI.
"""

from __future__ import annotations

import sys

from mle_beast.events import LogMessage, PipelineEvent, get_event_bus
from mle_beast.run_manager import RunConfig, get_run_manager


def _cli_event_printer(event: PipelineEvent) -> None:
    """Sync subscriber that prints events to stdout (preserves CLI behavior)."""
    from mle_beast.events import (
        RetryOccurred,
        RunStateChanged,
        StageCompleted,
        StageStarted,
        ToolExecuted,
    )

    if isinstance(event, LogMessage):
        prefix = ""
        if event.stage:
            prefix = f"[{event.stage}] "
        if event.level == "error":
            print(f"  {prefix}ERROR: {event.message}")
        elif event.level == "warning":
            print(f"  {prefix}WARN: {event.message}")
        elif event.level == "debug":
            print(f"  {prefix}{event.message}")
        else:
            print(f"  {prefix}{event.message}")
    elif isinstance(event, ToolExecuted):
        print(f"  [{event.iteration}] {event.tool_name}: {event.result_preview}")
    elif isinstance(event, StageStarted):
        print(f"\n--- Stage: {event.stage} ---")
    elif isinstance(event, StageCompleted):
        print(f"  Stage {event.stage}: {event.outcome}")
    elif isinstance(event, RetryOccurred):
        print(f"  Critic: retry (attempt {event.attempt}/{event.max_attempts})")
    elif isinstance(event, RunStateChanged):
        if event.new_state == "completed":
            print("\n--- Pipeline Complete ---")
        elif event.new_state == "failed":
            print("\n--- Pipeline Failed ---")


_INTRO = """\
============================================================
  MLE-Beast — ML Engineering Pipeline
============================================================

What this does
--------------
MLE-Beast runs a hill-climbing autoresearch loop against a workspace
directory. It writes / improves model.py, train.py, predict.py via an
LLM-driven actor/critic pipeline, evaluates each experiment, and keeps
the improvements (committed to a dedicated git branch) or reverts them.

Two modes
---------
  greenfield (default): the actor writes the first model from scratch,
    then iterates.
  brownfield (mode='existing'): your existing code IS the baseline;
    the actor proposes & implements improvements in place.

What you'll be asked
--------------------
  Workspace path     — directory the pipeline operates in. Created if it
                       doesn't exist. If it's already a git repo, your
                       branch / .gitignore / uncommitted work is preserved
                       (we branch off and stash before any changes).
  Task description   — plain English: what model are we training, what
                       data, what metric to optimize. Be specific about
                       the metric name (accuracy, RMSLE, F1, etc.) — the
                       pipeline auto-infers higher-vs-lower-is-better.
  Target accuracy    — optional. If the baseline / any kept experiment
                       reaches this, the pipeline exits early.
  Dataset path       — optional. If provided, the actor knows where to
                       look for data files.
  Set up workspace   — y to provision a venv + ML stack via poetry
                       (slow, ~5-10min). n if your workspace is already
                       set up (faster).

What to expect
--------------
  - LLM provider auto-detected from env: LOCAL_LLM_BASE_URL >
    OPENROUTER_API_KEY > OPENAI_API_KEY. Override model with
    MLE_BEAST_MODEL.
  - Runs typically take 30 minutes to several hours depending on the
    model and the task. You'll see live event output below.
  - Run state + every event is persisted to ~/.mle-beast/mle_beast.db.
  - For a richer view (filterable event log, raw console tab, browse old
    runs), launch the web dashboard instead:  python -m mle_beast --web

------------------------------------------------------------
"""


def run_repl() -> None:
    """Interactive REPL loop."""
    print(_INTRO)

    # Collect inputs
    workspace_path = input("Workspace path: ").strip()
    if not workspace_path:
        print("Error: workspace path is required.")
        sys.exit(1)

    task = input("Task description: ").strip()
    if not task:
        print("Error: task description is required.")
        sys.exit(1)

    mode_input = input(
        "Mode — (g)reenfield = build from scratch, "
        "(b)rownfield = improve existing code in place [g]: "
    ).strip().lower()
    if mode_input.startswith("b") or mode_input in ("existing", "brownfield"):
        mode = "existing"
    else:
        mode = "greenfield"

    target_str = input("Target accuracy (e.g., 0.55): ").strip()
    target_accuracy = float(target_str) if target_str else None

    dataset_path = input("Dataset path (or empty): ").strip() or None

    setup_workspace = input("Set up new workspace? (y/n) [n]: ").strip().lower() == "y"

    # Create run via RunManager
    manager = get_run_manager()
    bus = get_event_bus()

    config = RunConfig(
        workspace=workspace_path,
        task=task,
        target_accuracy=target_accuracy,
        dataset_path=dataset_path,
        mode=mode,
        setup_workspace=setup_workspace,
    )

    run_id = manager.create_run(config)

    # Subscribe CLI printer to events
    bus.subscribe(run_id, _cli_event_printer)

    print(f"\nRun ID: {run_id}")
    print("--- Starting Full Pipeline ---\n")

    # Start and wait for completion
    manager.start_run(run_id)
    manager.wait_for_run(run_id)

    # Print final results
    run_info = manager.get_run(run_id)
    if run_info and run_info.verdict_json:
        print(f"Final verdict: {run_info.verdict_json}")
    elif run_info and run_info.error_message:
        print(f"Error: {run_info.error_message}")
    else:
        print("No final verdict recorded.")
