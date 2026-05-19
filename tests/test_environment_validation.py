# Copyright 2026 Chris Padwick
# SPDX-License-Identifier: Apache-2.0

"""Tests for the BYO-environment validator + WorkspaceRegistry env plumbing.

The validator is what guards the user's first run from descending into a
mid-pipeline crash because their venv doesn't have pytest, etc.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

from mle_beast.workspace import (
    WorkspaceRegistry,
    validate_environment_path,
)


def _make_fake_venv(root: Path, *, with_pytest: bool = True) -> Path:
    """Build a minimal directory that looks like a venv to validator.

    The validator only requires:
      <root>/bin/python   — executable that runs Python
      python -c "import pytest"  — succeeds

    We satisfy both by symlinking real sys.executable as <root>/bin/python.
    pytest is already importable in the test's interpreter, so the import
    probe passes (when with_pytest=True).
    """
    bin_dir = root / "bin"
    bin_dir.mkdir(parents=True)
    py = bin_dir / "python"
    os.symlink(sys.executable, py)
    if not with_pytest:
        # Drop a wrapper that hides pytest from sys.path. We can't truly
        # "uninstall" pytest from the test venv — instead we make the
        # bin/python a small shell script that strips pytest from
        # PYTHONPATH and re-execs.
        py.unlink()
        wrapper = bin_dir / "python"
        wrapper.write_text(
            "#!/usr/bin/env bash\n"
            "# Hide site-packages so pytest is not importable.\n"
            f"exec {sys.executable} -S -c 'raise ImportError(\"hidden\")' \"$@\"\n"
        )
        wrapper.chmod(0o755)
    return root


class TestValidateEnvironmentPath:
    def test_accepts_well_formed_env(self, tmp_path):
        env = _make_fake_venv(tmp_path / "myenv")
        resolved = validate_environment_path(env)
        assert resolved == env.resolve()

    def test_expands_user_home(self, tmp_path, monkeypatch):
        # Move HOME to tmp_path and use a ~-prefixed path.
        monkeypatch.setenv("HOME", str(tmp_path))
        env = _make_fake_venv(tmp_path / ".venvs" / "x")
        resolved = validate_environment_path("~/.venvs/x")
        assert resolved == env.resolve()

    def test_rejects_missing_path(self, tmp_path):
        with pytest.raises(RuntimeError, match="does not exist"):
            validate_environment_path(tmp_path / "nope")

    def test_rejects_not_a_directory(self, tmp_path):
        f = tmp_path / "file.txt"
        f.write_text("")
        with pytest.raises(RuntimeError, match="not a directory"):
            validate_environment_path(f)

    def test_rejects_missing_bin_python(self, tmp_path):
        empty = tmp_path / "empty"
        empty.mkdir()
        with pytest.raises(RuntimeError, match="no bin/python"):
            validate_environment_path(empty)

    def test_rejects_non_executable_bin_python(self, tmp_path):
        env = tmp_path / "env"
        (env / "bin").mkdir(parents=True)
        py = env / "bin" / "python"
        py.write_text("")  # plain file, not executable
        # POSIX: clear the executable bits explicitly in case the
        # default umask leaves them on for the user.
        py.chmod(0o644)
        with pytest.raises(RuntimeError, match="not executable"):
            validate_environment_path(env)

    def test_rejects_when_pytest_not_importable(self, tmp_path):
        env = _make_fake_venv(tmp_path / "no_pytest", with_pytest=False)
        with pytest.raises(RuntimeError, match="pytest not importable"):
            validate_environment_path(env)


class TestWorkspaceRegistryEnvironment:
    @pytest.fixture(autouse=True)
    def _isolate(self):
        WorkspaceRegistry.clear_workspace()
        yield
        WorkspaceRegistry.clear_workspace()

    def test_default_is_none(self):
        assert WorkspaceRegistry.get_environment() is None

    def test_set_and_get_resolves_path(self, tmp_path):
        env = tmp_path / "env"
        env.mkdir()
        returned = WorkspaceRegistry.set_environment(env)
        assert returned == env.resolve()
        assert WorkspaceRegistry.get_environment() == env.resolve()

    def test_set_none_clears(self, tmp_path):
        env = tmp_path / "env"
        env.mkdir()
        WorkspaceRegistry.set_environment(env)
        WorkspaceRegistry.set_environment(None)
        assert WorkspaceRegistry.get_environment() is None

    def test_clear_workspace_also_clears_environment(self, tmp_path):
        env = tmp_path / "env"
        env.mkdir()
        WorkspaceRegistry.set_environment(env)
        WorkspaceRegistry.set_workspace(tmp_path)
        WorkspaceRegistry.clear_workspace()
        assert WorkspaceRegistry.get_environment() is None


class TestSetupRunContextHandlesMissingDatasetPath:
    """Regression for the metric_name-without-dataset_path crash.

    Before the fix: setting metric_name in the form (a sensible thing for
    users to do) but leaving dataset_path empty would crash inside
    pipeline_runner._setup_run_context with `Path(None)` -> TypeError, and
    the run would die immediately with no useful UI signal. The user
    couldn't even see the activity feed because the run failed before
    any stage event fired.
    """

    @pytest.fixture(autouse=True)
    def _isolate(self, tmp_path):
        WorkspaceRegistry.clear_workspace()
        yield
        WorkspaceRegistry.clear_workspace()

    def test_runs_without_dataset_path(self, tmp_path):
        from mle_beast.pipeline_runner import _setup_run_context

        ws = tmp_path / "ws"
        ws.mkdir()
        run_row = {
            "workspace": str(ws),
            "metric_name": "accuracy",  # provided
            "dataset_path": None,         # not provided — must NOT crash
        }
        # Should resolve and return the workspace path with no exception.
        result = _setup_run_context(run_row)
        assert result == ws.resolve()
        # No read-path was added since dataset_path was None.
        assert WorkspaceRegistry.get_allowed_read_paths() == []

    def test_adds_allowlist_when_dataset_path_set(self, tmp_path):
        from mle_beast.pipeline_runner import _setup_run_context

        ws = tmp_path / "ws"
        ws.mkdir()
        data = tmp_path / "data"
        data.mkdir()
        # Note: NO metric_name set. The allowlist should still fire
        # because the agent needs read access to the dataset regardless.
        run_row = {"workspace": str(ws), "dataset_path": str(data)}
        _setup_run_context(run_row)
        paths = WorkspaceRegistry.get_allowed_read_paths()
        assert data.resolve() in paths


class TestGetWorkspaceEnvHonorsRegistry:
    """tools/execution._get_workspace_env should pick up the BYO env."""

    @pytest.fixture(autouse=True)
    def _isolate(self, tmp_path):
        WorkspaceRegistry.clear_workspace()
        WorkspaceRegistry.set_workspace(tmp_path)
        yield
        WorkspaceRegistry.clear_workspace()

    def test_falls_back_to_workspace_venv_when_no_override(self, tmp_path):
        from mle_beast.tools.execution import _get_workspace_env

        # No venv anywhere → falls back to "python3"
        _, py, env = _get_workspace_env()
        assert py == "python3"
        # No VIRTUAL_ENV because neither workspace/venv nor an override exists.
        assert "VIRTUAL_ENV" not in env

    def test_uses_registered_environment_when_set(self, tmp_path):
        from mle_beast.tools.execution import _get_workspace_env

        # Build a fake env elsewhere, NOT inside the workspace
        outside = tmp_path.parent / "external_env"
        bin_dir = outside / "bin"
        bin_dir.mkdir(parents=True)
        py = bin_dir / "python"
        os.symlink(sys.executable, py)
        try:
            WorkspaceRegistry.set_environment(outside)
            _, exec_path, env = _get_workspace_env()
            # _get_workspace_env uses .absolute() (no symlink follow), so
            # exec_path is our symlink path, not the resolved target.
            assert exec_path == str((outside / "bin" / "python").absolute())
            assert env["VIRTUAL_ENV"] == str(outside)
            assert str(outside / "bin") in env["PATH"]
        finally:
            # Symlink leaks across tests if we don't clean up — tmp_path
            # only handles its own subtree.
            subprocess.run(["rm", "-rf", str(outside)], check=False)
