# Copyright 2026 Chris Padwick
# SPDX-License-Identifier: Apache-2.0

"""CUDA version detection and PyTorch stack selection.

Ported from ml_agents.cuda_detection.
"""

import os
import re
import subprocess
from typing import Optional, Tuple

AVAILABLE_STACKS = [
    ("pytorch-cu118", 11, 8),
    ("pytorch-cu121", 12, 1),
    ("pytorch-cu126", 12, 6),
    ("pytorch-cu130", 13, 0),
]

DEFAULT_STACK = "pytorch-cu126"


def detect_cuda_version() -> Optional[Tuple[int, int]]:
    """Detect CUDA version from nvidia-smi.

    Returns:
        Tuple of (major, minor) or None if detection fails.
    """
    try:
        result = subprocess.run(
            ["nvidia-smi"], capture_output=True, text=True, timeout=10,
        )
        if result.returncode != 0:
            return None
        match = re.search(r"CUDA Version:\s*(\d+)\.(\d+)", result.stdout)
        if match:
            return (int(match.group(1)), int(match.group(2)))
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        pass
    return None


def select_pytorch_stack(cuda_version: Optional[Tuple[int, int]] = None) -> str:
    """Select the best PyTorch stack for the detected CUDA version.

    Args:
        cuda_version: Optional override (major, minor). Auto-detects if None.

    Returns:
        Stack name like "pytorch-cu126".
    """
    env_override = os.environ.get("MLE_PYTORCH_STACK")
    if env_override:
        valid_names = [s[0] for s in AVAILABLE_STACKS]
        if env_override in valid_names:
            return env_override

    if cuda_version is None:
        cuda_version = detect_cuda_version()

    if cuda_version is None:
        return DEFAULT_STACK

    major, minor = cuda_version
    best_stack = DEFAULT_STACK
    for stack_name, stack_major, stack_minor in AVAILABLE_STACKS:
        if (stack_major, stack_minor) <= (major, minor):
            best_stack = stack_name
    return best_stack


def select_device(force_cpu: bool = False) -> str:
    """Pick the training device for a run.

    Default is GPU when one is detected. Falls back to CPU when no GPU is
    visible to nvidia-smi. The `force_cpu` flag is the explicit override
    (CLI flag, web config, or test fixture for known-no-GPU environments).

    Returns "cuda" or "cpu".
    """
    if force_cpu:
        return "cpu"
    return "cuda" if detect_cuda_version() is not None else "cpu"


def get_stack_info() -> dict:
    """Get information about CUDA detection and stack selection."""
    cuda_version = detect_cuda_version()
    selected_stack = select_pytorch_stack(cuda_version)
    return {
        "cuda_version": f"{cuda_version[0]}.{cuda_version[1]}" if cuda_version else None,
        "cuda_detected": cuda_version is not None,
        "selected_stack": selected_stack,
        "available_stacks": [s[0] for s in AVAILABLE_STACKS],
    }
