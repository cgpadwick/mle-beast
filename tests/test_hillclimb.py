# Copyright 2026 Chris Padwick
# SPDX-License-Identifier: Apache-2.0

"""Unit tests for hill-climbing procedural nodes."""

import subprocess

import pytest

from mle_beast.hillclimb import (
    BaselineEvalNode,
    GitSetupNode,
    HillClimbEvalNode,
    ReportNode,
    parse_val_score,
)


@pytest.fixture
def workspace(tmp_path):
    """Create a minimal workspace directory."""
    return tmp_path


@pytest.fixture
def git_workspace(workspace):
    """Create a workspace with git initialized (mimics GitSetupNode)."""
    subprocess.run(["git", "init"], cwd=workspace, capture_output=True)
    subprocess.run(["git", "config", "user.email", "test@test.com"], cwd=workspace, capture_output=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=workspace, capture_output=True)
    (workspace / ".gitignore").write_text("data/\nvenv/\n__pycache__/\n")
    (workspace / "model.py").write_text("# baseline model\n")
    (workspace / "train.py").write_text("# baseline train\n")
    subprocess.run(["git", "add", "-A"], cwd=workspace, capture_output=True)
    subprocess.run(["git", "commit", "-m", "initial"], cwd=workspace, capture_output=True)
    subprocess.run(["git", "checkout", "-b", "experiments"], cwd=workspace, capture_output=True)
    return workspace


class TestParseValScore:
    def test_parses_val_loss(self):
        log = "Epoch 1: train_loss=0.5, val_loss=0.3\nEpoch 2: train_loss=0.3, val_loss=0.2\n"
        assert parse_val_score(log) == 0.2

    def test_parses_validation_loss(self):
        log = "validation_loss: 0.45\nvalidation_loss: 0.35\n"
        assert parse_val_score(log) == 0.35

    def test_parses_val_score_pattern(self):
        log = "val_score=0.85\nval_score=0.75\n"
        assert parse_val_score(log) == 0.75

    def test_parses_val_rmse(self):
        log = "val_rmse=1.5\nval_rmse=1.2\n"
        assert parse_val_score(log) == 1.2

    def test_returns_inf_for_empty(self):
        assert parse_val_score("") == float("inf")

    def test_returns_inf_for_no_match(self):
        assert parse_val_score("Training complete. No validation metrics.") == float("inf")

    def test_returns_best_score(self):
        log = "val_loss=0.5\nval_loss=0.3\nval_loss=0.4\n"
        assert parse_val_score(log) == 0.3


class TestGitSetupNode:
    def test_creates_git_repo(self, workspace):
        node = GitSetupNode()
        shared = {"workspace": str(workspace)}

        # Need at least one file to commit
        (workspace / "dummy.txt").write_text("hello\n")

        prep_res = node.prep(shared)
        exec_res = node.exec(prep_res)
        action = node.post(shared, prep_res, exec_res)

        assert action == "complete"
        assert (workspace / ".git").is_dir()
        assert (workspace / ".gitignore").exists()

    def test_creates_experiment_branch(self, workspace):
        node = GitSetupNode()
        shared = {"workspace": str(workspace)}

        (workspace / "dummy.txt").write_text("hello\n")

        prep_res = node.prep(shared)
        exec_res = node.exec(prep_res)
        node.post(shared, prep_res, exec_res)

        # Branch name is timestamp-based: mle-beast-YYYYMMDD-HHMMSS
        result = subprocess.run(
            ["git", "branch", "--show-current"],
            cwd=workspace, capture_output=True, text=True,
        )
        current = result.stdout.strip()
        assert current.startswith("mle-beast-"), f"got {current!r}"
        assert shared["experiment_branch"] == current
        # Fresh init mode: no original branch, no stash
        assert shared["original_branch"] is None
        assert shared["is_existing_repo"] is False
        assert shared["mle_beast_stashed"] is False

    def test_existing_repo_smart_mode(self, workspace):
        """If .git/ already exists, GitSetup should NOT make an 'initial
        workspace setup' commit. It captures the original branch, branches
        off current HEAD, and stashes any uncommitted work."""
        # Pre-existing repo with one commit on 'main'
        subprocess.run(["git", "init", "-b", "main"], cwd=workspace, capture_output=True)
        subprocess.run(["git", "config", "user.email", "t@t"], cwd=workspace, capture_output=True)
        subprocess.run(["git", "config", "user.name", "t"], cwd=workspace, capture_output=True)
        (workspace / "user_file.txt").write_text("user content\n")
        (workspace / ".gitignore").write_text("user_pattern/\n")
        subprocess.run(["git", "add", "-A"], cwd=workspace, capture_output=True)
        subprocess.run(
            ["git", "commit", "-m", "user's initial commit"],
            cwd=workspace, capture_output=True,
        )
        # Make the working tree dirty so we exercise the stash path.
        (workspace / "user_file.txt").write_text("user content modified\n")

        # Snapshot pre-state
        log_before = subprocess.run(
            ["git", "log", "--oneline"],
            cwd=workspace, capture_output=True, text=True,
        ).stdout

        node = GitSetupNode()
        shared = {"workspace": str(workspace)}
        prep_res = node.prep(shared)
        exec_res = node.exec(prep_res)
        node.post(shared, prep_res, exec_res)

        # Branch name is dated and we're on it
        current = subprocess.run(
            ["git", "branch", "--show-current"],
            cwd=workspace, capture_output=True, text=True,
        ).stdout.strip()
        assert current.startswith("mle-beast-")
        assert current == shared["experiment_branch"]
        assert shared["original_branch"] == "main"
        assert shared["is_existing_repo"] is True
        assert shared["mle_beast_stashed"] is True

        # No "initial workspace setup" commit was created on top of user history
        log_after = subprocess.run(
            ["git", "log", "--oneline"],
            cwd=workspace, capture_output=True, text=True,
        ).stdout
        assert "initial workspace setup" not in log_after, log_after
        # Same number of commits as before (we branched off, we didn't add)
        assert log_before.count("\n") == log_after.count("\n")

        # User's .gitignore was NOT clobbered
        assert (workspace / ".gitignore").read_text() == "user_pattern/\n"

        # User's stashed change is in stash
        stash_list = subprocess.run(
            ["git", "stash", "list"],
            cwd=workspace, capture_output=True, text=True,
        ).stdout
        assert "mle-beast: pre-pipeline stash" in stash_list

    def test_gitignore_excludes_data(self, workspace):
        node = GitSetupNode()
        shared = {"workspace": str(workspace)}

        (workspace / "dummy.txt").write_text("hello\n")

        prep_res = node.prep(shared)
        node.exec(prep_res)

        gitignore = (workspace / ".gitignore").read_text()
        assert "data/" in gitignore
        assert "venv/" in gitignore
        assert "__pycache__/" in gitignore


class TestBaselineEvalNode:
    def test_records_baseline_score(self, git_workspace):
        # Write a training log
        (git_workspace / "training.log").write_text(
            "Epoch 1: train_loss=0.5, val_loss=0.3\n"
            "Epoch 2: train_loss=0.3, val_loss=0.2\n"
        )

        node = BaselineEvalNode()
        shared = {"workspace": str(git_workspace)}

        prep_res = node.prep(shared)
        exec_res = node.exec(prep_res)
        action = node.post(shared, prep_res, exec_res)

        assert action == "complete"
        assert shared["best_score"] == 0.2
        assert shared["step_count"] == 0
        assert shared["consecutive_failures"] == 0

    def test_creates_research_log(self, git_workspace):
        (git_workspace / "training.log").write_text("val_loss=0.5\n")

        node = BaselineEvalNode()
        shared = {"workspace": str(git_workspace)}

        prep_res = node.prep(shared)
        exec_res = node.exec(prep_res)
        node.post(shared, prep_res, exec_res)

        log_path = git_workspace / "research_log.md"
        assert log_path.exists()
        content = log_path.read_text()
        assert "Baseline" in content
        assert "0.5" in content

    def test_handles_missing_log(self, git_workspace):
        node = BaselineEvalNode()
        shared = {"workspace": str(git_workspace)}

        prep_res = node.prep(shared)
        exec_res = node.exec(prep_res)
        action = node.post(shared, prep_res, exec_res)

        assert action == "complete"
        assert shared["best_score"] == float("inf")


class TestHillClimbEvalNode:
    def test_improvement_keeps_changes(self, git_workspace):
        """When score improves, changes are committed."""
        # Set up research log from baseline
        (git_workspace / "research_log.md").write_text("# Research Log\n\n## Baseline\n- **Score**: 0.5\n\n")
        subprocess.run(["git", "add", "-A"], cwd=git_workspace, capture_output=True)
        subprocess.run(["git", "commit", "-m", "baseline"], cwd=git_workspace, capture_output=True)

        # Simulate an experiment that improved
        (git_workspace / "model.py").write_text("# improved model with dropout\n")
        (git_workspace / "training.log").write_text("val_loss=0.3\n")

        node = HillClimbEvalNode()
        shared = {
            "workspace": str(git_workspace),
            "step_count": 0,
            "max_steps": 30,
            "best_score": 0.5,
            "consecutive_failures": 0,
            "max_consecutive_failures": 5,
            "current_proposal": "Add dropout=0.3",
            "experiments": [],
        }

        prep_res = node.prep(shared)
        exec_res = node.exec(prep_res)
        action = node.post(shared, prep_res, exec_res)

        assert action == "iterate"
        assert shared["best_score"] == 0.3
        assert shared["consecutive_failures"] == 0
        assert shared["step_count"] == 1
        assert len(shared["experiments"]) == 1
        assert shared["experiments"][0]["improved"] is True

        # Verify model.py was kept
        assert "improved model" in (git_workspace / "model.py").read_text()

    def test_regression_reverts_changes(self, git_workspace):
        """When score doesn't improve, changes are reverted."""
        (git_workspace / "research_log.md").write_text("# Research Log\n\n## Baseline\n- **Score**: 0.3\n\n")
        subprocess.run(["git", "add", "-A"], cwd=git_workspace, capture_output=True)
        subprocess.run(["git", "commit", "-m", "baseline"], cwd=git_workspace, capture_output=True)

        # Simulate an experiment that made things worse
        (git_workspace / "model.py").write_text("# bad model\n")
        (git_workspace / "training.log").write_text("val_loss=0.5\n")

        node = HillClimbEvalNode()
        shared = {
            "workspace": str(git_workspace),
            "step_count": 0,
            "max_steps": 30,
            "best_score": 0.3,
            "consecutive_failures": 0,
            "max_consecutive_failures": 5,
            "current_proposal": "Bad idea",
            "experiments": [],
        }

        prep_res = node.prep(shared)
        exec_res = node.exec(prep_res)
        action = node.post(shared, prep_res, exec_res)

        assert action == "iterate"
        assert shared["best_score"] == 0.3  # unchanged
        assert shared["consecutive_failures"] == 1
        assert shared["step_count"] == 1
        assert shared["experiments"][0]["improved"] is False

        # Verify model.py was reverted to committed version
        assert "baseline model" in (git_workspace / "model.py").read_text()

    def test_budget_exhaustion_returns_done(self, git_workspace):
        (git_workspace / "research_log.md").write_text("# Research Log\n\n")
        subprocess.run(["git", "add", "-A"], cwd=git_workspace, capture_output=True)
        subprocess.run(["git", "commit", "-m", "setup"], cwd=git_workspace, capture_output=True)

        (git_workspace / "training.log").write_text("val_loss=0.5\n")

        node = HillClimbEvalNode()
        shared = {
            "workspace": str(git_workspace),
            "step_count": 29,  # at budget limit
            "max_steps": 30,
            "best_score": 0.3,
            "consecutive_failures": 0,
            "max_consecutive_failures": 5,
            "current_proposal": "Last try",
            "experiments": [],
        }

        prep_res = node.prep(shared)
        exec_res = node.exec(prep_res)
        action = node.post(shared, prep_res, exec_res)

        assert action == "done"

    def test_convergence_returns_done(self, git_workspace):
        (git_workspace / "research_log.md").write_text("# Research Log\n\n")
        subprocess.run(["git", "add", "-A"], cwd=git_workspace, capture_output=True)
        subprocess.run(["git", "commit", "-m", "setup"], cwd=git_workspace, capture_output=True)

        (git_workspace / "training.log").write_text("val_loss=0.5\n")

        node = HillClimbEvalNode()
        shared = {
            "workspace": str(git_workspace),
            "step_count": 5,
            "max_steps": 30,
            "best_score": 0.3,
            "consecutive_failures": 4,  # one more failure = convergence
            "max_consecutive_failures": 5,
            "current_proposal": "Another attempt",
            "experiments": [],
        }

        prep_res = node.prep(shared)
        exec_res = node.exec(prep_res)
        action = node.post(shared, prep_res, exec_res)

        assert action == "done"
        assert shared["consecutive_failures"] == 5

    def test_research_log_appended(self, git_workspace):
        log_path = git_workspace / "research_log.md"
        log_path.write_text("# Research Log\n\n")
        subprocess.run(["git", "add", "-A"], cwd=git_workspace, capture_output=True)
        subprocess.run(["git", "commit", "-m", "setup"], cwd=git_workspace, capture_output=True)

        (git_workspace / "training.log").write_text("val_loss=0.25\n")

        node = HillClimbEvalNode()
        shared = {
            "workspace": str(git_workspace),
            "step_count": 0,
            "max_steps": 30,
            "best_score": 0.3,
            "consecutive_failures": 0,
            "max_consecutive_failures": 5,
            "current_proposal": "Add batch normalization",
            "experiments": [],
        }

        prep_res = node.prep(shared)
        exec_res = node.exec(prep_res)
        node.post(shared, prep_res, exec_res)

        content = log_path.read_text()
        assert "Experiment 1" in content
        assert "Add batch normalization" in content
        assert "IMPROVED" in content


class TestReportNode:
    def test_generates_report(self, workspace):
        # Create research log
        (workspace / "research_log.md").write_text(
            "# Research Log\n\n## Baseline\n- **Score**: 0.5\n\n"
            "## Experiment 1\n- **Hypothesis**: Add dropout\n- **Result**: IMPROVED\n\n"
        )
        (workspace / "model.py").write_text("class MyModel:\n    pass\n")

        node = ReportNode()
        shared = {
            "workspace": str(workspace),
            "experiments": [
                {"step": 1, "hypothesis": "Add dropout", "score": 0.3, "improved": True},
                {"step": 2, "hypothesis": "Increase LR", "score": 0.35, "improved": False},
            ],
            "best_score": 0.3,
            "step_count": 2,
        }

        prep_res = node.prep(shared)
        exec_res = node.exec(prep_res)
        action = node.post(shared, prep_res, exec_res)

        assert action == "complete"

        report_path = workspace / "REPORT.md"
        assert report_path.exists()

        content = report_path.read_text()
        assert "## Experiment Results" in content
        assert "Add dropout" in content
        assert "YES" in content
        assert "## Final Model Architecture" in content
        assert "class MyModel" in content
        assert "## Full Research Log" in content

    def test_handles_empty_experiments(self, workspace):
        node = ReportNode()
        shared = {
            "workspace": str(workspace),
            "experiments": [],
            "best_score": None,
            "step_count": 0,
        }

        prep_res = node.prep(shared)
        exec_res = node.exec(prep_res)
        action = node.post(shared, prep_res, exec_res)

        assert action == "complete"
        assert (workspace / "REPORT.md").exists()


# ----------------------------------------------------------------
# Regression: git commits must work without global user.email/user.name
# ----------------------------------------------------------------

class TestGitIdentityFlags:
    """The pipeline's `_git` helper must inject `-c user.email=...
    -c user.name=...` so commits succeed on a fresh-user machine that
    hasn't run `git config --global user.email/user.name`. Regression
    test for the bug caught during Ubuntu 22.04 fresh-user docker test
    (where every pipeline commit emitted `fatal: empty ident name`
    warnings)."""

    def test_git_helper_injects_identity_flags(self, monkeypatch):
        """_git() and _git_run() should both prefix the subprocess argv
        with `-c user.email=... -c user.name=...` so the user's global
        config isn't required."""
        from mle_beast import hillclimb as hc

        captured_args = []

        class _FakeResult:
            returncode = 0
            stdout = ""
            stderr = ""

        def fake_run(cmd, **kwargs):
            captured_args.append(list(cmd))
            return _FakeResult()

        monkeypatch.setattr(hc.subprocess, "run", fake_run)

        hc._git("/tmp/whatever", "commit", "-m", "test")
        hc._git_run("/tmp/whatever", "commit", "-m", "test")

        for argv in captured_args:
            # argv = ["git", "-c", "user.email=...", "-c", "user.name=...", "commit", ...]
            assert argv[0] == "git"
            joined = " ".join(argv)
            assert "-c user.email=" in joined, f"missing user.email -c flag in {argv}"
            assert "-c user.name=" in joined, f"missing user.name -c flag in {argv}"
            # And the original command must still be there
            assert "commit" in argv
            assert "test" in argv

    def test_git_commit_succeeds_without_global_config(self, tmp_path, monkeypatch):
        """End-to-end: in a workspace where global git config has no
        user.email/user.name, the pipeline's _git helper should still
        be able to commit. Uses HOME override so the test sees no
        global config regardless of the dev's actual ~/.gitconfig."""
        from mle_beast import hillclimb as hc

        # Empty HOME → no .gitconfig → no global identity.
        clean_home = tmp_path / "clean-home"
        clean_home.mkdir()
        monkeypatch.setenv("HOME", str(clean_home))
        # XDG and GIT_CONFIG_GLOBAL can override HOME — clear them too.
        monkeypatch.delenv("XDG_CONFIG_HOME", raising=False)
        monkeypatch.delenv("GIT_CONFIG_GLOBAL", raising=False)
        # System config could still inject identity; on a typical Linux
        # box it doesn't, but explicitly skip it to keep the test hermetic.
        monkeypatch.setenv("GIT_CONFIG_SYSTEM", "/dev/null")

        workspace = tmp_path / "ws"
        workspace.mkdir()
        # init repo (no commits yet)
        hc._git(workspace, "init", "-q")
        (workspace / "hello.txt").write_text("hi\n")
        hc._git(workspace, "add", "hello.txt")
        # The actual moment of truth — commit without global config:
        rc, _, stderr = hc._git_run(workspace, "commit", "-m", "from-pipeline")
        assert rc == 0, (
            f"git commit failed with no global identity (rc={rc}): {stderr!r}. "
            "The _GIT_IDENTITY_FLAGS injection isn't working."
        )
