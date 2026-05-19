# Copyright 2026 Chris Padwick
# SPDX-License-Identifier: Apache-2.0

"""Integration test fixtures."""

import os
import subprocess
import sys
from pathlib import Path
from typing import Iterable, Optional

import pytest

# Skip integration tests unless at least one LLM provider is configured
pytestmark = pytest.mark.skipif(
    not (
        os.environ.get("OPENAI_API_KEY")
        or os.environ.get("OPENROUTER_API_KEY")
        or os.environ.get("LOCAL_LLM_BASE_URL")
    ),
    reason="No LLM provider configured — skipping integration tests",
)

CHURN_DATA_DIR = Path(__file__).parent / "churn_quick" / "data"
CHURN_PROJECT_YAML = Path(__file__).parent / "churn_quick" / "project.yaml"


def prep_brownfield_venv(workspace: Path, extra_packages: Iterable[str]) -> Path:
    """Build a minimal user-managed venv at <workspace>/.venv for brownfield tests.

    Brownfield runs expect the user to own the venv. In tests we simulate
    that by creating a fresh, lightweight venv with just pytest + whatever
    each template's model.py/train.py actually imports — typically torch
    plus a tiny extra (pandas, torchvision). This is ~100 MB and a few
    seconds to install, vs. the full ml-frameworks stack (~3-4 GB and
    minutes) that WorkspaceCreator would otherwise produce.

    Returns the path to the venv's python interpreter so callers can
    sanity-check or invoke it directly if needed.
    """
    workspace.mkdir(parents=True, exist_ok=True)
    venv_dir = workspace / ".venv"

    subprocess.run(
        [sys.executable, "-m", "venv", str(venv_dir)],
        check=True, capture_output=True,
    )

    venv_python = venv_dir / "bin" / "python"
    packages = ["pytest", *extra_packages]
    subprocess.run(
        [str(venv_python), "-m", "pip", "install", "--quiet", *packages],
        check=True, capture_output=True,
    )
    return venv_python


def run_pipeline_via_manager(
    workspace: Path,
    task: str,
    target_accuracy: Optional[float],
    dataset_path: Optional[Path],
    mode: str = "greenfield",
    lower_is_better: Optional[bool] = None,
    metric_name: Optional[str] = None,
    environment: Optional[str] = None,
):
    """Drive a pipeline through RunManager so it appears in the web UI.

    Returns the final RunInfo so callers can assert status / verdict.
    Pipeline state, events, and the per-run console capture file are all
    persisted to the same SQLite DB the dashboard reads from, making
    integration runs observable just like REPL/web runs.

    `lower_is_better` overrides the LLM/heuristic direction inference.
    None (default) lets the pipeline auto-detect; True for loss/RMSE-style
    metrics; False for accuracy/F1/AUC. The integration tests all use
    accuracy and pass False so a misclassified metric direction can't
    silently flip the hill-climb.

    `environment` points the pipeline at a user-supplied Python venv
    instead of using WorkspaceCreator. Skips the multi-GB ml-frameworks
    install — see RunConfig.environment.
    """
    from mle_beast.run_manager import RunConfig, get_run_manager

    config = RunConfig(
        workspace=str(workspace),
        task=task,
        target_accuracy=target_accuracy,
        dataset_path=str(dataset_path) if dataset_path else None,
        mode=mode,
        force_cpu=False,  # auto-detect device — let GPU be picked when available
        setup_workspace=False,  # fixtures already set up the workspace
        lower_is_better=lower_is_better,
        metric_name=metric_name,
        environment=environment,
    )
    manager = get_run_manager()
    run_id = manager.create_run(config)
    manager.start_run(run_id)
    manager.wait_for_run(run_id)
    return manager.get_run(run_id)
