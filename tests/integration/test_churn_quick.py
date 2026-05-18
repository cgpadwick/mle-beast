# Copyright 2026 Chris Padwick
# SPDX-License-Identifier: Apache-2.0

"""E2E integration test: full pipeline on churn_quick data.

This test:
1. Sets up a workspace with a venv
2. Runs the full hill-climb pipeline via RunManager (so it appears in the
   web dashboard)
3. Asserts the run completed and produced the expected workspace files

Requires at least one LLM provider to be configured.
"""

import os
import shutil
from pathlib import Path

import pytest
import yaml

from mle_beast.workspace import WorkspaceCreator, WorkspaceRegistry
from tests.integration.conftest import run_pipeline_via_manager

pytestmark = pytest.mark.skipif(
    not (
        os.environ.get("OPENAI_API_KEY")
        or os.environ.get("OPENROUTER_API_KEY")
        or os.environ.get("LOCAL_LLM_BASE_URL")
    ),
    reason="No LLM provider configured",
)


CHURN_DATA_DIR = Path(__file__).parent / "churn_quick" / "data"
CHURN_PROJECT_YAML = Path(__file__).parent / "churn_quick" / "project.yaml"


@pytest.fixture
def churn_workspace(tmp_path):
    """Create a workspace for the churn_quick integration test."""
    ws = tmp_path / "churn_workspace"

    # Create workspace (this sets up venv, ML stack, etc.)
    creator = WorkspaceCreator(str(ws), quiet=True)
    creator.run()

    # Copy data files into workspace
    data_dir = ws / "data"
    data_dir.mkdir(exist_ok=True)
    shutil.copy2(CHURN_DATA_DIR / "train.csv", data_dir / "train.csv")
    shutil.copy2(CHURN_DATA_DIR / "test.csv", data_dir / "test.csv")

    WorkspaceRegistry.set_workspace(ws)
    yield ws
    WorkspaceRegistry.clear_workspace()


@pytest.mark.integration
@pytest.mark.timeout(600)  # 10 minute timeout
def test_churn_quick_full_pipeline(churn_workspace):
    """Run full pipeline on churn data and assert accuracy >= 0.55."""
    ws = churn_workspace

    # Load project config
    with open(CHURN_PROJECT_YAML) as f:
        config = yaml.safe_load(f)

    task = config["goals"]["task_description"]
    target = config["goals"]["target_metric"]["target_value"]

    run_info = run_pipeline_via_manager(
        ws, task, target_accuracy=target, dataset_path=ws / "data",
        # All integration test datasets use accuracy → higher-is-better.
        # Pin both the direction and the metric name so the val-score
        # extractor picks the right field even when train.py emphasizes
        # something else (like val_loss in early-stop bookkeeping).
        lower_is_better=False,
        metric_name="accuracy",
    )

    assert run_info is not None, "RunManager should have a row for the run"
    assert run_info.status in ("completed", "failed"), run_info.status
    print(f"Run id: {run_info.id}, status: {run_info.status}")
    print(f"Experiment branch: {run_info.experiment_branch}")
    if run_info.verdict_json:
        print(f"Verdict: {run_info.verdict_json[:500]}")

    # Hill-climb writes everything at the workspace root (no v{N} suffix).
    assert (ws / "model.py").exists(), "model.py should exist at workspace root"
    assert (ws / "train.py").exists(), "train.py should exist at workspace root"

    # No versioned files
    versioned = list(ws.glob("model_v*.py")) + list(ws.glob("scripts/train_v*.py"))
    assert len(versioned) == 0, f"No versioned files expected, found: {versioned}"
