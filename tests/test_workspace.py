# Copyright 2026 Chris Padwick
# SPDX-License-Identifier: Apache-2.0

"""Unit tests for workspace.check_workspace_env.

Validates the brownfield/user-managed venv probe: it must raise a clear
error when .venv/bin/python is missing or pytest can't be imported, and
return cleanly otherwise.
"""

from __future__ import annotations

import stat
from pathlib import Path

import pytest

from mle_beast.workspace import check_workspace_env


def _make_fake_venv(workspace: Path, stub_script: str) -> Path:
    """Create <workspace>/.venv/bin/python as an executable shell stub.

    The stub's body decides what `python -c "import pytest"` does — pass
    in `exit 0` to simulate a working venv, `exit 1` to simulate a missing
    pytest, and so on.
    """
    bin_dir = workspace / ".venv" / "bin"
    bin_dir.mkdir(parents=True)
    py = bin_dir / "python"
    py.write_text(f"#!/bin/sh\n{stub_script}\n")
    py.chmod(py.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    return py


def test_raises_when_venv_missing(tmp_path):
    """No .venv directory at all → friendly error pointing user at the fix."""
    with pytest.raises(RuntimeError, match=r"No venv found"):
        check_workspace_env(tmp_path)


def test_raises_when_venv_dir_exists_but_no_python(tmp_path):
    """`.venv/` present but no bin/python (e.g. half-deleted venv) → same path."""
    (tmp_path / ".venv" / "bin").mkdir(parents=True)
    with pytest.raises(RuntimeError, match=r"No venv found"):
        check_workspace_env(tmp_path)


def test_raises_when_pytest_not_importable(tmp_path):
    """python exists but `import pytest` fails → tells user how to install it."""
    _make_fake_venv(tmp_path, "exit 1")
    with pytest.raises(RuntimeError, match=r"pytest not importable"):
        check_workspace_env(tmp_path)


def test_passes_when_venv_and_pytest_present(tmp_path):
    """Both probes succeed → returns None (no exception)."""
    _make_fake_venv(tmp_path, "exit 0")
    assert check_workspace_env(tmp_path) is None


def test_accepts_string_path(tmp_path):
    """Accepts str as well as Path (matches WorkspaceRegistry's _PathLike)."""
    _make_fake_venv(tmp_path, "exit 0")
    assert check_workspace_env(str(tmp_path)) is None


def test_error_includes_workspace_path(tmp_path):
    """Error message must name the actual missing path so user can act on it."""
    with pytest.raises(RuntimeError) as exc:
        check_workspace_env(tmp_path)
    assert str(tmp_path) in str(exc.value)


def test_brownfield_requires_evaluate_py(tmp_path):
    """mode='existing' fails when evaluate.py is absent."""
    _make_fake_venv(tmp_path, "exit 0")
    with pytest.raises(RuntimeError, match=r"evaluate\.py"):
        check_workspace_env(tmp_path, mode="existing")


def test_brownfield_passes_when_evaluate_py_present(tmp_path):
    """mode='existing' + evaluate.py at workspace root → all good."""
    _make_fake_venv(tmp_path, "exit 0")
    (tmp_path / "evaluate.py").write_text("# stub\n")
    assert check_workspace_env(tmp_path, mode="existing") is None


def test_greenfield_does_not_require_evaluate_py(tmp_path):
    """mode!='existing' (greenfield/None) → no evaluate.py requirement.
    BaselineActor will write it during baseline construction.
    """
    _make_fake_venv(tmp_path, "exit 0")
    assert check_workspace_env(tmp_path, mode="greenfield") is None
    assert check_workspace_env(tmp_path) is None  # mode=None default


# ----------------------------------------------------------------
# validate_workspace_path: fail-fast on un-creatable run workspaces
# ----------------------------------------------------------------

class TestValidateWorkspacePath:
    def test_existing_writable_dir_ok(self, tmp_path):
        from mle_beast.workspace import validate_workspace_path
        assert validate_workspace_path(tmp_path) == tmp_path.resolve()

    def test_creatable_under_writable_parent_ok(self, tmp_path):
        """A not-yet-existing path under a writable dir validates (mkdir -p
        would succeed) without actually being created."""
        from mle_beast.workspace import validate_workspace_path
        target = tmp_path / "deep" / "nested" / "run"
        assert validate_workspace_path(target) == target.resolve()
        assert not target.exists()  # validation must not create it

    def test_empty_path_raises(self):
        from mle_beast.workspace import validate_workspace_path
        with pytest.raises(RuntimeError, match=r"no workspace path"):
            validate_workspace_path("   ")

    def test_path_is_a_file_raises(self, tmp_path):
        from mle_beast.workspace import validate_workspace_path
        f = tmp_path / "afile"
        f.write_text("x")
        with pytest.raises(RuntimeError, match=r"not a directory"):
            validate_workspace_path(f)

    @pytest.mark.skipif(
        hasattr(__import__("os"), "geteuid") and __import__("os").geteuid() == 0,
        reason="root bypasses directory write permissions",
    )
    def test_unwritable_parent_raises(self, tmp_path):
        """Nearest existing ancestor unwritable → can't mkdir → clear error."""
        import os

        from mle_beast.workspace import validate_workspace_path
        locked = tmp_path / "locked"
        locked.mkdir()
        os.chmod(locked, 0o500)  # r-x: can't create children
        try:
            with pytest.raises(RuntimeError, match=r"not writable"):
                validate_workspace_path(locked / "run")
        finally:
            os.chmod(locked, 0o700)  # restore so tmp_path cleanup works


# ----------------------------------------------------------------
# _clone_ml_frameworks: bundled-cache fast path
# ----------------------------------------------------------------

class TestClonesMlFrameworksCache:
    """Verify the Docker-bundle fast path: when
    MLE_BEAST_ML_FRAMEWORKS_CACHE points at a pre-cloned dir,
    WorkspaceCreator copies from there instead of going to git.
    Regression test for the cache-aware path added alongside the
    user-facing Docker image."""

    def test_cache_path_used_when_env_set_and_dir_exists(self, tmp_path, monkeypatch):
        from mle_beast.workspace import WorkspaceCreator

        # Fake "bundled" ml-frameworks at a known location.
        bundled = tmp_path / "bundled-ml-frameworks"
        bundled.mkdir()
        (bundled / "marker.txt").write_text("from-bundle\n")
        (bundled / "stacks").mkdir()
        (bundled / "stacks" / "pytorch-cu126").mkdir()
        (bundled / "stacks" / "pytorch-cu126" / "pyproject.toml").write_text("# fake\n")

        monkeypatch.setenv("MLE_BEAST_ML_FRAMEWORKS_CACHE", str(bundled))

        ws = tmp_path / "workspace"
        ws.mkdir()
        creator = WorkspaceCreator(str(ws), quiet=True)

        dest = ws / "ml-frameworks-venv"
        creator._clone_ml_frameworks(dest)

        # The cp succeeded with the marker file from our bundle, not
        # something git would have produced.
        assert (dest / "marker.txt").read_text() == "from-bundle\n"
        assert (dest / "stacks" / "pytorch-cu126" / "pyproject.toml").exists()

    def test_falls_back_to_git_clone_when_env_unset(self, tmp_path, monkeypatch):
        """Native install (no Docker bundle) → env var unset → use git clone.
        We don't actually do the network clone in the test — just verify
        that the cache-detection branch is NOT taken when env is unset.
        Mocks `_run` to intercept the would-be git clone."""
        from mle_beast.workspace import WorkspaceCreator

        monkeypatch.delenv("MLE_BEAST_ML_FRAMEWORKS_CACHE", raising=False)

        ws = tmp_path / "workspace"
        ws.mkdir()
        creator = WorkspaceCreator(str(ws), quiet=True)

        # Replace _run with a no-op stub so we can detect that it WAS
        # called (i.e., the git-clone fallback fired, not the copy path).
        called = {}

        class _FakeResult:
            returncode = 0
            stdout = ""
            stderr = ""

        def fake_run(*args, **kwargs):
            called["args"] = args
            return _FakeResult()

        creator._run = fake_run
        dest = ws / "ml-frameworks-venv"
        creator._clone_ml_frameworks(dest)

        assert "args" in called, "git clone fallback should have run"
        argv = called["args"][0]
        assert "git" in argv and "clone" in argv, f"expected git clone in {argv}"

    def test_cache_env_set_but_dir_missing_falls_back(self, tmp_path, monkeypatch):
        """If MLE_BEAST_ML_FRAMEWORKS_CACHE points at a non-existent path,
        don't crash — fall back to git clone. Catches the case where
        someone exports the env var pointing at a path that doesn't
        actually exist on their machine."""
        from mle_beast.workspace import WorkspaceCreator

        monkeypatch.setenv("MLE_BEAST_ML_FRAMEWORKS_CACHE", "/does/not/exist")

        ws = tmp_path / "workspace"
        ws.mkdir()
        creator = WorkspaceCreator(str(ws), quiet=True)

        called = {}

        class _FakeResult:
            returncode = 0
            stdout = ""
            stderr = ""

        def fake_run(*args, **kwargs):
            called["args"] = args
            return _FakeResult()

        creator._run = fake_run
        dest = ws / "ml-frameworks-venv"
        creator._clone_ml_frameworks(dest)

        assert "args" in called, "should fall back to git clone when cache dir missing"
