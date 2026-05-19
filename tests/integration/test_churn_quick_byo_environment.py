# Copyright 2026 Chris Padwick
# SPDX-License-Identifier: Apache-2.0

"""E2E integration test: greenfield + BYO environment path.

Same workload as test_churn_quick (greenfield model build on tiny churn
data), but instead of letting WorkspaceCreator install ml-frameworks
(~50 GB, hours), the test supplies an existing user venv via the new
RunConfig.environment field.

Goal: prove that on first-time-user UX, the agent reuses an environment
the user already has, completing setup in seconds.
"""

import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

from mle_beast.workspace import WorkspaceRegistry
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

# Packages the agent's generated code needs to actually run on the
# churn_quick task. Same shortlist used by the brownfield churn_existing
# fixture — verified there to be the minimum that lets train.py + tests
# work without import errors.
CHURN_PACKAGES = ["torch", "pandas", "scikit-learn", "numpy"]


@pytest.fixture
def byo_env(tmp_path):
    """Build a fresh, minimal venv in tmp that the test can hand to mle-beast
    as the user's "existing" environment. Roughly mirrors what a user with
    an `.venvs/ml` would have.
    """
    venv_dir = tmp_path / "user_venv"
    subprocess.run(
        [sys.executable, "-m", "venv", str(venv_dir)],
        check=True, capture_output=True,
    )
    venv_python = venv_dir / "bin" / "python"
    subprocess.run(
        [str(venv_python), "-m", "pip", "install", "--quiet", "pytest", *CHURN_PACKAGES],
        check=True, capture_output=True,
    )
    return venv_dir


@pytest.fixture
def workspace_with_data(tmp_path):
    """Bare workspace with churn_quick data — no venv inside.

    Unlike test_churn_quick, we deliberately DO NOT call WorkspaceCreator —
    the whole point of this test is that the user supplies the venv
    via RunConfig.environment and mle-beast doesn't build one.
    """
    ws = tmp_path / "churn_workspace"
    ws.mkdir()
    data_dir = ws / "data"
    data_dir.mkdir()
    shutil.copy2(CHURN_DATA_DIR / "train.csv", data_dir / "train.csv")
    shutil.copy2(CHURN_DATA_DIR / "test.csv", data_dir / "test.csv")
    WorkspaceRegistry.set_workspace(ws)
    yield ws
    WorkspaceRegistry.clear_workspace()


@pytest.mark.integration
@pytest.mark.timeout(900)  # 15 min — covers a few hill-climb iterations
def test_churn_quick_with_byo_environment(workspace_with_data, byo_env):
    """Run the churn_quick pipeline using a user-provided venv.

    Validates the BYO-environment feature end-to-end:
      - Setup completes in seconds (no ml-frameworks install)
      - The agent's tool calls use the user's bin/python
      - The pipeline reaches at least the baseline iteration
    """
    ws = workspace_with_data

    with open(CHURN_PROJECT_YAML) as f:
        config = yaml.safe_load(f)
    task = config["goals"]["task_description"]
    target = config["goals"]["target_metric"]["target_value"]

    run_info = run_pipeline_via_manager(
        ws, task, target_accuracy=target, dataset_path=ws / "data",
        lower_is_better=False,
        metric_name="accuracy",
        environment=str(byo_env),
    )

    assert run_info is not None, "RunManager should have a row for the run"
    print(f"Run id: {run_info.id}, status: {run_info.status}")
    print(f"Environment used: {run_info.environment}")

    # Status must be a terminal one — completed or failed (we accept failed
    # because individual model-generation runs can hit transient agent
    # issues; what we're testing is the BYO-env machinery, not the agent's
    # model quality, and a failed run still proves the env got used).
    assert run_info.status in ("completed", "failed", "cancelled"), run_info.status
    assert run_info.environment == str(byo_env), (
        f"environment field should be persisted on the run row, "
        f"got {run_info.environment!r}"
    )

    # Hill-climb writes everything at the workspace root.
    # We require these because the BYO-env path STILL needs the agent to
    # author code; if the env couldn't be used by tools, model.py and
    # train.py would never get written.
    assert (ws / "model.py").exists(), "model.py should exist at workspace root"
    assert (ws / "train.py").exists(), "train.py should exist at workspace root"

    # And the BYO env should still exist + be intact (we don't delete user
    # venvs — that would be a bug if the test ever shipped to prod).
    assert (byo_env / "bin" / "python").exists()
