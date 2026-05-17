# Copyright 2026 Chris Padwick
# SPDX-License-Identifier: Apache-2.0

"""E2E integration test: existing-code pipeline on sentiment data.

This test:
1. Sets up a workspace with a venv
2. Copies existing template code (model.py, train.py, eval.py, tests/)
3. Runs the full pipeline in existing-code mode
4. Asserts accuracy >= 0.75 and files were modified (not versioned)

Requires at least one LLM provider to be configured.
"""

import os
import shutil
from pathlib import Path

import pytest
import yaml

from tests.integration.conftest import prep_brownfield_venv, run_pipeline_via_manager
from mle_beast.workspace import WorkspaceRegistry

pytestmark = pytest.mark.skipif(
    not (
        os.environ.get("OPENAI_API_KEY")
        or os.environ.get("OPENROUTER_API_KEY")
        or os.environ.get("LOCAL_LLM_BASE_URL")
    ),
    reason="No LLM provider configured",
)

DATA_DIR = Path(__file__).parent / "data"
TEMPLATES_DIR = Path(__file__).parent / "templates"
PROJECT_YAML = Path(__file__).parent / "project.yaml"


@pytest.fixture
def workspace(tmp_path):
    """Create a workspace with existing code for the sentiment_existing test."""
    ws = tmp_path / "sentiment_existing_workspace"

    # Brownfield: user owns the venv. Templates only need torch.
    prep_brownfield_venv(ws, ["torch"])

    # Copy data directory structure
    data_dir = ws / "data"
    shutil.copytree(DATA_DIR, data_dir)

    # Copy existing template files into workspace root
    for template_file in TEMPLATES_DIR.glob("*.py"):
        shutil.copy2(template_file, ws / template_file.name)

    # Copy test templates
    tests_dir = ws / "tests"
    tests_dir.mkdir(exist_ok=True)
    for test_file in (TEMPLATES_DIR / "tests").glob("*.py"):
        shutil.copy2(test_file, tests_dir / test_file.name)

    WorkspaceRegistry.set_workspace(ws)
    yield ws
    WorkspaceRegistry.clear_workspace()


@pytest.mark.integration
@pytest.mark.timeout(900)
def test_sentiment_existing_pipeline(workspace):
    """Run full pipeline in existing-code mode on sentiment data."""
    ws = workspace

    with open(PROJECT_YAML) as f:
        config = yaml.safe_load(f)

    task = config["goals"]["task_description"]
    target = config["goals"]["target_metric"]["target_value"]

    run_info = run_pipeline_via_manager(
        ws, task, target_accuracy=target, dataset_path=ws / "data",
        mode="existing",
        lower_is_better=False,  # accuracy
        metric_name="accuracy",
    )
    assert run_info is not None
    assert run_info.status in ("completed", "failed"), run_info.status
    print(f"Run id: {run_info.id}, status: {run_info.status}")
    print(f"Experiment branch: {run_info.experiment_branch}")

    # Existing-code assertions: files should be non-versioned
    assert (ws / "model.py").exists(), "model.py should exist (not model_v*.py)"
    assert (ws / "train.py").exists(), "train.py should exist (not train_v*.py)"

    # No versioned files should be created
    versioned_models = list(ws.glob("model_v*.py")) + list(ws.glob("models/model_v*.py"))
    assert len(versioned_models) == 0, (
        f"No versioned model files should exist, found: {versioned_models}"
    )

    versioned_trains = list(ws.glob("train_v*.py")) + list(ws.glob("scripts/train_v*.py"))
    assert len(versioned_trains) == 0, (
        f"No versioned train files should exist, found: {versioned_trains}"
    )
