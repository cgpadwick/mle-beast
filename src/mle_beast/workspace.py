# Copyright 2026 Chris Padwick
# SPDX-License-Identifier: Apache-2.0

"""Workspace creation and registry.

Ported from ml_agents workspace_prep.py and workspace_registry.py.
WorkspaceCreator sets up a workspace with venv + ML stack.
WorkspaceRegistry provides a global path reference.
check_workspace_env validates a user-provided venv has the basics.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path
from typing import Optional, Union

from mle_beast.command_runner import check_command_exists, run_command
from mle_beast.cuda_detection import select_pytorch_stack

ML_FRAMEWORKS_REPO = "https://github.com/cgpadwick/ml-frameworks.git"

_PathLike = Union[str, Path]


def check_workspace_env(workspace: _PathLike, mode: Optional[str] = None) -> None:
    """Verify a user-managed workspace has the prerequisites we depend on.

    When `setup_workspace=False` (e.g. brownfield runs against an existing
    repo), the user owns the venv. We don't want to silently fail mid-run
    on a missing import, so probe the hard requirements up front:

    1. `<workspace>/.venv/bin/python` exists and is runnable.
    2. pytest is importable from that venv (smoke tests run via pytest).
    3. (brownfield only) `evaluate.py` exists at the workspace root —
       the EvaluateActor needs to launch it, and we don't want to discover
       its absence half-way through the pipeline.

    Heavier deps (torch, sklearn, etc.) are the user's responsibility —
    their existing model.py/train.py already imports what it needs, and
    the actor's tool-error feedback loop will surface anything genuinely
    missing.

    Raises RuntimeError with an actionable message on any failure.
    """
    ws = Path(workspace).expanduser().resolve()
    venv_python = ws / ".venv" / "bin" / "python"

    if not venv_python.exists():
        raise RuntimeError(
            f"No venv found at {venv_python}.\n"
            f"mle-beast expects a Python venv at <workspace>/.venv when "
            f"setup_workspace is False. Create one with:\n"
            f"  cd {ws} && python -m venv .venv && "
            f".venv/bin/pip install pytest <your other deps>"
        )

    probe = subprocess.run(
        [str(venv_python), "-c", "import pytest"],
        capture_output=True,
        text=True,
    )
    if probe.returncode != 0:
        raise RuntimeError(
            f"pytest not importable from {venv_python}.\n"
            f"The pipeline runs smoke tests via pytest. Install it with:\n"
            f"  {venv_python} -m pip install pytest\n"
            f"(probe stderr: {probe.stderr.strip() or '<empty>'})"
        )

    if mode == "existing":
        evaluate_py = ws / "evaluate.py"
        if not evaluate_py.exists():
            raise RuntimeError(
                f"Brownfield mode requires evaluate.py at {evaluate_py}.\n"
                f"mle-beast measures the run's score by invoking your "
                f"workspace's evaluate.py against the trained checkpoint.\n"
                f"Create one that:\n"
                f"  - accepts --checkpoint, --data-path, --device CLI flags,\n"
                f"  - loads the saved model,\n"
                f"  - runs predictions on a held-out test/val split,\n"
                f"  - prints a clean 'Test accuracy: X.XXXX' line and/or\n"
                f"    writes eval_results.json with "
                f"{{\"metric_name\", \"value\", \"split\"}}.\n"
            )


class WorkspaceRegistry:
    """In-process registry for the current workspace path."""

    _workspace: Optional[Path] = None
    _allowed_read_paths: list[Path] = []

    @classmethod
    def set_workspace(cls, path: _PathLike) -> Path:
        p = Path(path).expanduser().resolve()
        cls._workspace = p
        return p

    @classmethod
    def add_allowed_read_path(cls, path: _PathLike) -> None:
        """Add an additional directory that tools may read from (e.g. dataset)."""
        p = Path(path).expanduser().resolve()
        if p not in cls._allowed_read_paths:
            cls._allowed_read_paths.append(p)

    @classmethod
    def get_allowed_read_paths(cls) -> list[Path]:
        return list(cls._allowed_read_paths)

    @classmethod
    def get_workspace(cls, default: Optional[_PathLike] = None) -> Path:
        if cls._workspace is not None:
            return cls._workspace
        if default is not None:
            return cls.set_workspace(default)
        raise RuntimeError(
            "Workspace not configured. Call WorkspaceRegistry.set_workspace() first."
        )

    @classmethod
    def clear_workspace(cls) -> None:
        cls._workspace = None


class WorkspaceCreator:
    """Create and initialize an ML workspace with venv and ML stack."""

    def __init__(
        self,
        root: str,
        *,
        quiet: bool = False,
        dev_tool_packages: Optional[list[str]] = None,
    ):
        self.root = root
        self.quiet = quiet
        self.dev_tool_packages = ["pytest", "black"]
        if dev_tool_packages:
            self.dev_tool_packages.extend(dev_tool_packages)

        if os.path.exists(self.root):
            shutil.rmtree(self.root)

        os.makedirs(self.root, exist_ok=True)
        self._log(f"Workspace created at {self.root}")

        self.dirs_to_create = [
            "models",
            "scripts",
            "utils",
            "tests",
            "logs",
            "results",
            "experiments",
            "checkpoints",
        ]

    def _log(self, message: str) -> None:
        if not self.quiet:
            print(message)

    def _run(self, *args, **kwargs):
        if self.quiet:
            kwargs.setdefault("capture_output", False)
            kwargs.setdefault("stdout", subprocess.DEVNULL)
            kwargs.setdefault("stderr", subprocess.DEVNULL)
        return run_command(*args, **kwargs)

    def _install_optional_packages(self, python_executable: Path) -> None:
        packages = list(self.dev_tool_packages)
        if not packages:
            return
        res = self._run(
            [str(python_executable), "-m", "pip", "install", *packages],
            description=f"Installing optional packages: {', '.join(packages)}",
            cwd=str(self.root),
            capture_output=False,
        )
        if res.returncode != 0:
            raise RuntimeError(f"pip install failed: {res.stderr or res.stdout}")

    def _clone_ml_frameworks(self, dest_dir: Path) -> Path:
        if dest_dir.exists():
            shutil.rmtree(dest_dir)
        dest_dir.parent.mkdir(parents=True, exist_ok=True)

        if not check_command_exists("git"):
            raise RuntimeError("git is required but not found on PATH.")

        res = self._run(
            ["git", "clone", "--depth", "1", "--branch", "master",
             ML_FRAMEWORKS_REPO, str(dest_dir)],
            description="Cloning ml-frameworks (master)",
        )
        if res.returncode != 0:
            raise RuntimeError(f"git clone failed: {res.stderr or res.stdout}")
        return dest_dir

    def _install_stack_to_venv(self) -> None:
        if not check_command_exists("poetry"):
            raise RuntimeError("poetry is required but not found on PATH.")

        poetry_env = {**os.environ}
        for key in ["VIRTUAL_ENV", "POETRY_ACTIVE", "POETRY_ENV", "PYTHONHOME", "PYTHONPATH"]:
            poetry_env.pop(key, None)
        poetry_env["POETRY_VIRTUALENVS_CREATE"] = "true"
        poetry_env["POETRY_VIRTUALENVS_IN_PROJECT"] = "true"
        poetry_env["POETRY_VIRTUALENVS_PREFER_ACTIVE_PYTHON"] = "false"

        for key, value in [("virtualenvs.in-project", "true"), ("virtualenvs.create", "true")]:
            run_command(
                ["poetry", "config", "--local", key, value],
                description=f"poetry config {key}={value}",
                cwd=str(self.root),
                env=poetry_env,
            )

        self._run(
            ["poetry", "env", "use", "python3"],
            description="Creating workspace virtualenv",
            cwd=str(self.root),
            env=poetry_env,
            capture_output=False,
        )

        # ml-frameworks base now ships scikit-learn, matplotlib, seaborn,
        # joblib, requests, rich. So `-E data` (just dask/polars/pyarrow now)
        # and the old kitchen-sink `-E viz` are no longer needed for sklearn
        # or matplotlib/seaborn. Keep `-E viz` (plotly) for richer EDA;
        # drop `-E data` and `-E viz-app` (bokeh/streamlit/dash/gradio/
        # jupyter/ipython) which the actor doesn't use.
        self._run(
            ["poetry", "install", "--no-root", "-E", "ml", "-E", "vision",
             "-E", "nlp", "-E", "vision-extra", "-E", "viz"],
            description=f"Installing stack into venv at {self.root}",
            cwd=str(self.root),
            env=poetry_env,
            capture_output=False,
        )

        venv_dir = Path(self.root) / ".venv"
        if not venv_dir.exists():
            raise RuntimeError(
                "Poetry did not create an in-project virtualenv (.venv)."
            )

        # Ensure the venv has a python symlink (Poetry doesn't always create one)
        venv_bin = venv_dir / "bin"
        python_link = venv_bin / "python"
        if not python_link.exists():
            # Find any python3.x binary in the venv bin dir
            candidates = sorted(venv_bin.glob("python3.*"))
            if not candidates:
                # Fall back to the system python3 that Poetry used
                import shutil as _shutil
                sys_python = _shutil.which("python3")
                if sys_python:
                    python_link.symlink_to(sys_python)
            else:
                python_link.symlink_to(candidates[0].name)
            # Also ensure python3 symlink exists
            python3_link = venv_bin / "python3"
            if not python3_link.exists() and python_link.exists():
                python3_link.symlink_to(python_link.name)

        # Symlink ./venv -> ./.venv
        link_path = Path(self.root) / "venv"
        if link_path.is_symlink() or link_path.is_file():
            link_path.unlink()
        link_path.symlink_to(venv_dir.name)

    def _check_workspace(self, python_executable: Path) -> str:
        code = (
            "import json\n"
            "out = {}\n"
            "try:\n"
            "  import torch\n"
            "  out['torch_version'] = torch.__version__\n"
            "  out['cuda_available'] = torch.cuda.is_available()\n"
            "except Exception as e:\n"
            "  out['import_error'] = str(e)\n"
            "print(json.dumps(out, indent=2))\n"
        )
        res = run_command(
            [str(python_executable), "-c", code],
            description="Checking torch/cuda status in workspace venv",
        )
        if res.returncode != 0:
            return f"probe failed: {res.stderr or res.stdout}"
        return (res.stdout or "").strip()

    def run(self) -> None:
        mlframeworks_dir = Path(self.root) / "ml-frameworks-venv"
        self._clone_ml_frameworks(mlframeworks_dir)

        stack_name = select_pytorch_stack()
        self._log(f"Selected ML stack: {stack_name}")
        stack_dir = mlframeworks_dir / "stacks" / stack_name
        pyproject_file = stack_dir / "pyproject.toml"
        poetry_lock_file = stack_dir / "poetry.lock"
        if not pyproject_file.exists() or not poetry_lock_file.exists():
            raise RuntimeError(f"Stack files not found under: {stack_dir}")
        shutil.copyfile(pyproject_file, Path(self.root) / "pyproject.toml")
        shutil.copyfile(poetry_lock_file, Path(self.root) / "poetry.lock")

        shutil.rmtree(mlframeworks_dir)

        self._install_stack_to_venv()

        venv_python = Path.cwd() / self.root / "venv" / "bin" / "python"
        if not venv_python.exists():
            raise RuntimeError(f"venv python not found at: {venv_python}")

        self._install_optional_packages(venv_python)

        status = self._check_workspace(venv_python)
        self._log(f"\nTorch/CUDA status:\n{status}")

        for dir_name in self.dirs_to_create:
            dir_path = Path(self.root) / dir_name
            dir_path.mkdir(parents=True, exist_ok=True)
            self._log(f"Created directory: {dir_path}")
