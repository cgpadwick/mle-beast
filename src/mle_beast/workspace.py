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


def validate_environment_path(env_path: _PathLike) -> Path:
    """Validate a user-provided Python environment for use as the run's venv.

    Used by the BYO-environment path (RunConfig.environment): the user
    points at an existing venv/conda env and the pipeline reuses it
    instead of building a fresh one. If the env can't be used, we want a
    clear error BEFORE the run starts rather than mid-pipeline.

    Checks:
      1. Path expansion + exists + is a directory.
      2. `<path>/bin/python` is a real, executable file.
      3. `<path>/bin/python -m pip --version` exits 0 (the agent's
         recovery loop installs missing packages via pip — without
         it, every ModuleNotFoundError is unrecoverable. `uv venv`
         specifically does NOT install pip by default, so this is the
         likely failure mode for uv users).
      4. `<path>/bin/python -c "import pytest"` exits 0 (the pipeline
         smoke-tests via pytest, so this is non-negotiable).

    Returns the resolved Path on success. Raises RuntimeError with an
    actionable message on any failure.
    """
    p = Path(env_path).expanduser().resolve()

    if not p.exists():
        raise RuntimeError(f"environment path does not exist: {p}")
    if not p.is_dir():
        raise RuntimeError(f"environment path is not a directory: {p}")

    python = p / "bin" / "python"
    if not python.exists():
        raise RuntimeError(
            f"no bin/python under {p}.\n"
            f"Expected a Python venv or conda environment root containing "
            f"bin/python. Activate the env once and try `which python` to "
            f"find the right path."
        )
    # is_file() follows symlinks, so a venv's symlinked python passes.
    # A directory named python (rare but possible if someone unzipped a
    # broken archive over their venv) would fail here with a clear
    # message rather than crashing the subprocess probe below.
    if not python.is_file():
        raise RuntimeError(
            f"bin/python is not a regular file: {python}"
        )
    if not os.access(str(python), os.X_OK):
        raise RuntimeError(f"bin/python is not executable: {python}")

    # pip first — without it the agent can't recover from missing-package
    # errors, and uv-created venvs lack pip by default which is the most
    # likely way users hit this.
    probe = subprocess.run(
        [str(python), "-m", "pip", "--version"],
        capture_output=True, text=True, timeout=15,
    )
    if probe.returncode != 0:
        raise RuntimeError(
            f"pip not available in {p}.\n"
            f"The agent installs missing packages via pip during runs, so "
            f"this env needs pip even if you don't use it directly. "
            f"`uv venv` skips pip by default — install it with one of:\n"
            f"  {python} -m ensurepip --upgrade\n"
            f"  uv pip install pip   (if you used uv to create this env)\n"
            f"(probe stderr: {probe.stderr.strip() or '<empty>'})"
        )

    probe = subprocess.run(
        [str(python), "-c", "import pytest"],
        capture_output=True, text=True, timeout=15,
    )
    if probe.returncode != 0:
        raise RuntimeError(
            f"pytest not importable in {p}.\n"
            f"The pipeline runs smoke tests via pytest. Install it with:\n"
            f"  {python} -m pip install pytest\n"
            f"(probe stderr: {probe.stderr.strip() or '<empty>'})"
        )

    return p


def suggested_workspace_root() -> Optional[str]:
    """The mounted, writable directory runs should live under, or None.

    In the Docker image the compose file bind-mounts the host's workspaces
    dir to ``/workspaces`` (see docker-compose.yml). That's the only path
    a containerized user can write to that also persists on the host — but
    they have no way to know that from the dashboard. The web layer surfaces
    this so the New Run form can prefill it and explain the mount. Returns
    None on native installs (no ``/workspaces``), where the user picks an
    arbitrary host path.
    """
    p = Path("/workspaces")
    if p.is_dir() and os.access(str(p), os.W_OK):
        return "/workspaces"
    return None


def validate_workspace_path(workspace: _PathLike) -> Path:
    """Validate that a run's workspace path can actually be created/written.

    The pipeline runner does ``Path(workspace).mkdir(parents=True,
    exist_ok=True)`` at the very start of a run. When the user types a path
    rooted somewhere unwritable (e.g. ``/adffafdka`` — the container user
    can't create dirs under ``/``), that mkdir raises PermissionError mid-run
    and the run flips to failed. Validate up front so the New Run form gets
    an immediate, actionable 400 instead.

    Checks:
      1. Non-empty.
      2. If it exists: it's a directory and is writable.
      3. If it doesn't exist: the nearest existing ancestor is a writable
         directory, so ``mkdir -p`` would succeed.

    Returns the resolved Path on success. Raises RuntimeError with an
    actionable message (steering toward the mounted root when there is one)
    on any failure.
    """
    raw = str(workspace).strip()
    if not raw:
        raise RuntimeError("no workspace path provided")

    p = Path(raw).expanduser()
    try:
        p = p.resolve()
    except OSError:
        # resolve() can raise on pathological inputs; fall back to absolute.
        p = Path(os.path.abspath(str(p)))

    # Steer the user toward the mounted root when we're in a container.
    root = suggested_workspace_root()
    tip = (
        f"\nTip: use a path under {root} — it's mounted to your host so "
        f"results persist (e.g. {root}/my-run)."
        if root else ""
    )

    if p.exists():
        if not p.is_dir():
            raise RuntimeError(
                f"workspace path exists but is not a directory: {p}"
            )
        if not os.access(str(p), os.W_OK):
            raise RuntimeError(f"workspace directory is not writable: {p}{tip}")
        return p

    # Doesn't exist yet — walk up to the nearest existing ancestor and make
    # sure mkdir -p could create the path under it.
    ancestor = p.parent
    while not ancestor.exists() and ancestor != ancestor.parent:
        ancestor = ancestor.parent
    if not ancestor.exists() or not ancestor.is_dir():
        raise RuntimeError(f"cannot create workspace {p}: no usable parent directory.{tip}")
    if not os.access(str(ancestor), os.W_OK):
        raise RuntimeError(
            f"cannot create workspace {p}: the nearest existing parent "
            f"({ancestor}) is not writable.{tip}"
        )
    return p


class WorkspaceRegistry:
    """In-process registry for the current workspace path."""

    _workspace: Optional[Path] = None
    _allowed_read_paths: list[Path] = []
    # When set, tools point at this directory's bin/python instead of
    # <workspace>/venv/. Populated from RunConfig.environment by the
    # pipeline runner before any tool calls.
    _environment: Optional[Path] = None

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
    def set_environment(cls, path: Optional[_PathLike]) -> Optional[Path]:
        """Pin the Python environment the agent's tools should use.

        Pass `None` to clear. Stored as a resolved absolute Path.
        """
        if path is None:
            cls._environment = None
            return None
        p = Path(path).expanduser().resolve()
        cls._environment = p
        return p

    @classmethod
    def get_environment(cls) -> Optional[Path]:
        """Return the user-pinned environment, or None to use workspace/venv."""
        return cls._environment

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
        cls._allowed_read_paths.clear()
        cls._environment = None


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

        # Docker / pre-baked-bundle fast path. When the image ships a
        # pre-cloned ml-frameworks at MLE_BEAST_ML_FRAMEWORKS_CACHE (see
        # the user-facing Dockerfile), `cp -r` from there instead of
        # going to the network. Saves ~30s + hundreds of MB of fetch on
        # every workspace setup. Falls back to git clone if the cache
        # env var isn't set or the path doesn't exist — keeps native
        # installs working unchanged.
        cache_env = os.environ.get("MLE_BEAST_ML_FRAMEWORKS_CACHE")
        if cache_env:
            cache_path = Path(cache_env).expanduser().resolve()
            if cache_path.is_dir():
                self._log(f"Copying ml-frameworks from bundled cache: {cache_path}")
                shutil.copytree(cache_path, dest_dir, symlinks=True)
                return dest_dir

        res = self._run(
            ["git", "clone", "--depth", "1", "--branch", "master",
             ML_FRAMEWORKS_REPO, str(dest_dir)],
            description="Cloning ml-frameworks (master)",
        )
        if res.returncode != 0:
            raise RuntimeError(f"git clone failed: {res.stderr or res.stdout}")
        return dest_dir

    def _check_prereqs(self) -> None:
        # Run BEFORE the ml-frameworks clone so the user doesn't wait
        # through a several-hundred-MB git fetch only to be told
        # poetry isn't installed. Mirrors the up-front probe that
        # check_workspace_env does for brownfield runs.
        if not check_command_exists("git"):
            raise RuntimeError(
                "git is required but not found on PATH.\n"
                "Install git from https://git-scm.com/downloads (or your "
                "system package manager) and re-run."
            )
        if not check_command_exists("poetry"):
            raise RuntimeError(
                "poetry is required but not found on PATH.\n"
                "mle-beast uses poetry to install ml-frameworks's pinned "
                "stack into the workspace venv. Install it with ONE of:\n"
                "  pipx install poetry\n"
                "  curl -sSL https://install.python-poetry.org | python3 -\n"
                "See https://python-poetry.org/docs/#installation for "
                "the official install guide, then re-run."
            )

    def _install_stack_to_venv(self) -> None:
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

        # Base-only install. ml-frameworks's base ships everything most
        # tasks need: torch + torchvision + torchaudio + numpy + scipy
        # + pandas + scikit-learn + joblib + matplotlib + seaborn +
        # pytest. Total ~5.5 GB. If the agent's code needs anything else
        # (e.g. transformers for NLP, ultralytics for YOLO) it adds the
        # appropriate group at run time via `poetry install --no-root
        # -E <group>` against the pyproject.toml we leave at workspace
        # root. The available groups are defined under
        # [tool.poetry.extras] there and the actor system prompts are
        # nudged to prefer that over `pip install <pkg>` (poetry uses
        # the lock file ml-frameworks has already validated). Old
        # kitchen-sink install (-E ml -E vision -E nlp -E vision-extra
        # -E viz, ~8 GB) was removed when ml-frameworks reorganized:
        # the `ml` group no longer exists and lots of what was in it
        # is in base now anyway.
        res = self._run(
            ["poetry", "install", "--no-root"],
            description=f"Installing ml-frameworks BASE into venv at {self.root}",
            cwd=str(self.root),
            env=poetry_env,
            capture_output=False,
        )
        if res.returncode != 0:
            # capture_output=False so stdout/stderr already streamed to the
            # console + per-run log tee; don't try to re-emit them here.
            # `poetry env use` ran earlier (line above) so .venv likely
            # exists but is missing deps — without this fail-fast, the
            # next "venv exists" check passes and the agent silently runs
            # against a broken environment until the first import error.
            raise RuntimeError(
                f"`poetry install` failed (exit {res.returncode}). "
                f"See stdout/stderr above for the underlying error "
                f"(common causes: network failure mid-download, disk "
                f"full, lock-file conflict against the installed "
                f"Python version)."
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
        self._check_prereqs()

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
