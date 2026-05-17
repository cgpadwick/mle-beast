# Copyright 2026 Chris Padwick
# SPDX-License-Identifier: Apache-2.0

"""Unit tests for workspace.check_workspace_env.

Validates the brownfield/user-managed venv probe: it must raise a clear
error when .venv/bin/python is missing or pytest can't be imported, and
return cleanly otherwise.
"""

from __future__ import annotations

import os
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
