# Copyright 2026 Chris Padwick
# SPDX-License-Identifier: Apache-2.0

"""E2E integration test: pipeline against a pre-initialized git workspace.

Mirrors test_churn_quick but the workspace is pre-`git init`-ed with
existing content + an uncommitted dirty state, so we exercise the
GitSetupNode "smart mode" path:
- captures the user's original branch
- stashes uncommitted work
- branches off current HEAD into mle-beast-<ts>
- doesn't touch their .gitignore
- doesn't make a synthetic "initial workspace setup" commit on top of
  their history

This is a deliberately separate file (not a parametrize on
test_churn_quick) so the assertions can be specific to smart mode.
"""

import os
import shutil
import subprocess
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


CHURN_DATA_DIR = Path(__file__).parent / "churn_quick" / "data"
CHURN_PROJECT_YAML = Path(__file__).parent / "churn_quick" / "project.yaml"


def _run(cmd, cwd):
    result = subprocess.run(
        cmd, cwd=str(cwd), capture_output=True, text=True, timeout=30,
    )
    if result.returncode != 0:
        raise RuntimeError(f"{' '.join(cmd)} failed: {result.stderr}")
    return result.stdout.strip()


@pytest.fixture
def preinitialized_workspace(tmp_path):
    """Create a workspace + venv, then `git init` and commit a fake user
    file + .gitignore. Leave the working tree dirty so we exercise the
    stash path."""
    ws = tmp_path / "preinit_workspace"

    # Standard workspace setup (venv + ML stack).
    creator = WorkspaceCreator(str(ws), quiet=True)
    creator.run()

    # Copy training data.
    data_dir = ws / "data"
    data_dir.mkdir(exist_ok=True)
    shutil.copy2(CHURN_DATA_DIR / "train.csv", data_dir / "train.csv")
    shutil.copy2(CHURN_DATA_DIR / "test.csv", data_dir / "test.csv")

    # Pre-existing user repo on `main` with their own .gitignore + a file.
    _run(["git", "init", "-b", "main"], cwd=ws)
    _run(["git", "config", "user.email", "user@example.com"], cwd=ws)
    _run(["git", "config", "user.name", "Test User"], cwd=ws)

    user_gitignore = "# user's gitignore\nmy_secret/\n"
    (ws / ".gitignore").write_text(user_gitignore, encoding="utf-8")
    (ws / "USER_README.md").write_text(
        "# My existing project\nThis was here before mle-beast ran.\n",
        encoding="utf-8",
    )

    _run(["git", "add", "-A"], cwd=ws)
    _run(["git", "commit", "-m", "user's initial commit"], cwd=ws)

    # Leave the working tree dirty (uncommitted change to USER_README.md
    # plus a new untracked file). Exercises the stash branch.
    (ws / "USER_README.md").write_text(
        "# My existing project (with my unsaved edits)\n", encoding="utf-8",
    )
    (ws / "scratch_notes.txt").write_text("WIP notes\n", encoding="utf-8")

    # Snapshot pre-state so the test can assert nothing got clobbered.
    pre_log = _run(["git", "log", "--oneline"], cwd=ws)
    pre_gitignore = (ws / ".gitignore").read_text(encoding="utf-8")
    pre_branch = _run(["git", "branch", "--show-current"], cwd=ws)

    WorkspaceRegistry.set_workspace(ws)
    yield {
        "ws": ws,
        "pre_log": pre_log,
        "pre_gitignore": pre_gitignore,
        "pre_branch": pre_branch,
        "user_gitignore": user_gitignore,
    }
    WorkspaceRegistry.clear_workspace()


@pytest.mark.integration
@pytest.mark.timeout(900)
def test_smart_mode_preserves_user_repo(preinitialized_workspace):
    """The smart-mode GitSetup must not clobber the user's existing repo."""
    ctx = preinitialized_workspace
    ws = ctx["ws"]

    with open(CHURN_PROJECT_YAML) as f:
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

    # --- smart-mode invariants (read from DB + filesystem instead of shared) ---

    # 1. GitSetup recorded a dated branch — persisted to runs.experiment_branch.
    assert run_info.experiment_branch and run_info.experiment_branch.startswith(
        "mle-beast-"
    ), run_info.experiment_branch

    # 2. User's .gitignore is preserved.
    assert (ws / ".gitignore").read_text(encoding="utf-8") == ctx["user_gitignore"]

    # 3. User's main branch is unchanged: no "initial workspace setup"
    #    commit on top, same number of commits as before the run.
    main_log = _run(["git", "log", "main", "--oneline"], cwd=ws)
    assert "initial workspace setup" not in main_log, main_log
    assert main_log.count("\n") == ctx["pre_log"].count("\n"), (
        f"main branch changed: before={ctx['pre_log']!r}, after={main_log!r}"
    )

    # 4. Pipeline commits live on the dated branch.
    branch_log = _run(
        ["git", "log", run_info.experiment_branch, "--oneline"], cwd=ws,
    )
    assert "baseline" in branch_log.lower(), branch_log

    # 5. Stash entry exists.
    stash_list = _run(["git", "stash", "list"], cwd=ws)
    assert "mle-beast: pre-pipeline stash" in stash_list

    # 6. Hill-climb produced the expected files at workspace root.
    assert (ws / "model.py").exists()
    assert (ws / "train.py").exists()
