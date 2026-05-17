# Copyright 2026 Chris Padwick
# SPDX-License-Identifier: Apache-2.0

"""Metadata tools: CUDA check, workspace metadata, model version.

Ported from ml_agents.shared_tools metadata section.
"""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

from mle_beast.command_runner import run_command
from mle_beast.workspace import WorkspaceRegistry


def check_cuda() -> str:
    """Return 'true' or 'false' for CUDA availability in workspace venv."""
    base_path = Path(WorkspaceRegistry.get_workspace()).absolute()
    venv_python = base_path / "venv" / "bin" / "python"
    if not venv_python.exists():
        return "false"

    code = "import torch\nprint('true' if torch.cuda.is_available() else 'false')\n"
    env = os.environ.copy()
    env["PYTHONPATH"] = str(base_path)

    try:
        result = run_command(
            [str(venv_python), "-c", code],
            capture_output=True, text=True, timeout=20,
            cwd=str(base_path), env=env,
            description="Check CUDA",
        )
        if result.returncode == 0:
            out = (result.stdout or "").strip().lower()
            return "true" if out == "true" else "false"
    except Exception:
        pass
    return "false"


def get_workspace_metadata() -> str:
    """Return JSON string with workspace metadata."""
    base_path = Path(WorkspaceRegistry.get_workspace()).absolute()
    metadata: dict = {
        "workspace_path": str(base_path),
        "exists": base_path.exists(),
    }
    if not base_path.exists():
        return json.dumps(metadata)

    venv_path = base_path / "venv"
    metadata["has_venv"] = venv_path.exists()

    if venv_path.exists():
        venv_python = venv_path / "bin" / "python"
        if venv_python.exists():
            result = run_command(
                [str(venv_python), "--version"],
                capture_output=True, text=True,
            )
            if result.returncode == 0:
                metadata["python_version"] = result.stdout.strip()

    expected_dirs = ["models", "tests", "data", "logs", "experiments"]
    metadata["directories"] = {d: (base_path / d).exists() for d in expected_dirs}
    return json.dumps(metadata, indent=2)


