# Copyright 2026 Chris Padwick
# SPDX-License-Identifier: Apache-2.0

"""Per-run stdout/stderr capture + console log path management.

Extracted from run_manager.py so the I/O plumbing is independently
testable and the run-lifecycle code stays focused on lifecycle.
"""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, TextIO


def console_log_path(run_id: str) -> Path:
    """Per-run console-capture file under ~/.mle-beast/runs/<id>/console.log."""
    base = os.environ.get(
        "MLE_BEAST_RUNS_DIR",
        str(Path.home() / ".mle-beast" / "runs"),
    )
    return Path(base) / run_id / "console.log"


class _Tee:
    """Tiny tee stream: writes go to both an underlying handle and a file.

    Used inside execute_pipeline() to capture everything the pipeline
    thread prints (own prints + library logs + any subprocess output that
    ends up in our Python stdout/stderr) into a per-run console file
    while STILL going to the original terminal stream.

    Note: Python's sys.stdout/sys.stderr are process-global, so installing
    a tee redirects ALL output during the pipeline thread's lifetime —
    including web-server (uvicorn) requests handled in parallel. That's
    a small acceptable cost for v1.
    """

    def __init__(self, primary: TextIO, file: TextIO) -> None:
        self._primary = primary
        self._file = file

    def write(self, data: str) -> int:
        try:
            self._file.write(data)
            self._file.flush()
        except Exception:
            pass
        return self._primary.write(data)

    def flush(self) -> None:
        try:
            self._file.flush()
        except Exception:
            pass
        try:
            self._primary.flush()
        except Exception:
            pass

    def isatty(self) -> bool:
        return False

    def __getattr__(self, name: str):
        return getattr(self._primary, name)


@dataclass
class StdioCapture:
    """Handle returned by install_stdio_tee; pass to restore_stdio() later.

    `console_file` is None if the open() failed — restore_stdio() handles
    that case so callers can use a single try/finally idiom regardless of
    whether the tee actually got installed.
    """
    orig_stdout: TextIO
    orig_stderr: TextIO
    console_file: Optional[TextIO]


def install_stdio_tee(run_id: str) -> StdioCapture:
    """Open the per-run console file and tee sys.stdout/stderr into it.

    If opening the file fails (permission, no disk, etc.) we silently
    leave stdio unmodified — pipeline runs are more important than
    capturing the console log, so we degrade gracefully.

    Returns a StdioCapture handle that MUST be passed to restore_stdio()
    in a finally block, even on the failure path.
    """
    orig_stdout = sys.stdout
    orig_stderr = sys.stderr
    console_file: Optional[TextIO] = None
    try:
        log_path = console_log_path(run_id)
        log_path.parent.mkdir(parents=True, exist_ok=True)
        console_file = log_path.open("a", buffering=1, encoding="utf-8")
        sys.stdout = _Tee(orig_stdout, console_file)
        sys.stderr = _Tee(orig_stderr, console_file)
    except Exception:
        console_file = None
    return StdioCapture(orig_stdout, orig_stderr, console_file)


def restore_stdio(capture: StdioCapture) -> None:
    """Undo install_stdio_tee. Safe to call even if install failed.

    Both teardown steps are wrapped in their own try/excepts so a
    failure in one doesn't skip the other.
    """
    try:
        sys.stdout = capture.orig_stdout
        sys.stderr = capture.orig_stderr
    except Exception:
        pass
    if capture.console_file is not None:
        try:
            capture.console_file.close()
        except Exception:
            pass
