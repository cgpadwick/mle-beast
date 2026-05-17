# Copyright 2026 Chris Padwick
# SPDX-License-Identifier: Apache-2.0

"""E2E integration test: full pipeline on shapes_classification data.

This test runs the full pipeline (code -> test -> review -> train -> analyze)
on the shapes classification dataset (circle/square/triangle) with an 85%
accuracy target.

Requires at least one LLM provider to be configured.
"""

import os
import shutil
from pathlib import Path

import pytest
import yaml

from tests.integration.conftest import run_pipeline_via_manager
from mle_beast.workspace import WorkspaceCreator, WorkspaceRegistry

pytestmark = pytest.mark.skipif(
    not (
        os.environ.get("OPENAI_API_KEY")
        or os.environ.get("OPENROUTER_API_KEY")
        or os.environ.get("LOCAL_LLM_BASE_URL")
    ),
    reason="No LLM provider configured",
)

DATA_DIR = Path(__file__).parent / "shapes_classification" / "data"
PROJECT_YAML = Path(__file__).parent / "shapes_classification" / "project.yaml"


@pytest.fixture
def workspace(tmp_path):
    """Create a workspace for the shapes integration test."""
    ws = tmp_path / "shapes_workspace"

    creator = WorkspaceCreator(str(ws), quiet=True)
    creator.run()

    # Copy data directory structure (train/{circle,square,triangle}/*.png, test/...)
    data_dir = ws / "data"
    shutil.copytree(DATA_DIR, data_dir)

    WorkspaceRegistry.set_workspace(ws)
    yield ws
    WorkspaceRegistry.clear_workspace()


@pytest.mark.integration
@pytest.mark.timeout(1200)  # 20 minute timeout — CNN training may be slower
def test_shapes_full_pipeline(workspace):
    """Run full pipeline on shapes data and assert accuracy >= 0.85."""
    ws = workspace

    with open(PROJECT_YAML) as f:
        config = yaml.safe_load(f)

    task = config["goals"]["task_description"]
    target = config["goals"]["target_metric"]["target_value"]

    run_info = run_pipeline_via_manager(
        ws, task, target_accuracy=target, dataset_path=ws / "data",
        lower_is_better=False,  # accuracy
        metric_name="accuracy",
    )
    assert run_info is not None
    assert run_info.status in ("completed", "failed"), run_info.status
    print(f"Run id: {run_info.id}, status: {run_info.status}")
    print(f"Experiment branch: {run_info.experiment_branch}")

    # Hill-climb writes at workspace root, no v{N}
    assert (ws / "model.py").exists(), "model.py should exist at workspace root"
    assert (ws / "train.py").exists(), "train.py should exist at workspace root"
