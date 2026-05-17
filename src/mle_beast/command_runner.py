# Copyright 2026 Chris Padwick
# SPDX-License-Identifier: Apache-2.0

"""Centralized subprocess execution with logging.

Ported from ml_agents.command_runner — simplified for PocketFlow usage.
"""

import os
import shlex
import subprocess
import sys
from enum import Enum
from pathlib import Path
from typing import Dict, List, Optional, Union


class LogLevel(Enum):
    SILENT = 0
    ERROR = 1
    INFO = 2
    DEBUG = 3
    VERBOSE = 4


class CommandConfig:
    """Global configuration for command execution."""

    log_level: LogLevel = LogLevel.INFO
    dry_run: bool = False

    @classmethod
    def set_log_level(cls, level: LogLevel) -> None:
        cls.log_level = level

    @classmethod
    def set_dry_run(cls, dry_run: bool) -> None:
        cls.dry_run = dry_run


def _log(message: str, level: LogLevel = LogLevel.INFO) -> None:
    if CommandConfig.log_level.value >= level.value:
        prefix = {
            LogLevel.ERROR: "ERROR",
            LogLevel.INFO: "INFO",
            LogLevel.DEBUG: "DEBUG",
            LogLevel.VERBOSE: "VERBOSE",
        }.get(level, "")
        output = f"[{prefix}] {message}" if prefix else message
        print(output, file=sys.stderr)

    # If a pipeline thread is running, also push this through the event bus
    # so the web dashboard's run-detail log can show it scrolling by, not
    # just the terminal that launched the run.
    try:
        from mle_beast.events import (
            LogMessage,
            get_current_run_id,
            get_event_bus,
        )
        run_id = get_current_run_id()
        if run_id:
            level_str = {
                LogLevel.ERROR: "error",
                LogLevel.INFO: "info",
                LogLevel.DEBUG: "debug",
                LogLevel.VERBOSE: "debug",
            }.get(level, "info")
            get_event_bus().emit(
                LogMessage(run_id=run_id, level=level_str, message=message)
            )
    except Exception:
        # Never let observability errors break command execution.
        pass


def _format_command(cmd: Union[str, List[str]]) -> str:
    if isinstance(cmd, list):
        return " ".join(shlex.quote(arg) for arg in cmd)
    return cmd


def run_command(
    cmd: Union[str, List[str]],
    cwd: Optional[Union[str, Path]] = None,
    env: Optional[Dict[str, str]] = None,
    timeout: Optional[int] = None,
    shell: bool = False,
    capture_output: bool = True,
    text: bool = True,
    description: Optional[str] = None,
    check: bool = False,
    **kwargs,
) -> subprocess.CompletedProcess:
    """Execute a command with logging.

    Args:
        cmd: Command to execute (string or list of arguments).
        cwd: Working directory.
        env: Environment variables.
        timeout: Timeout in seconds.
        shell: Whether to execute through shell.
        capture_output: Whether to capture stdout/stderr.
        text: Whether to decode output as text.
        description: Human-readable description.
        check: Whether to raise on non-zero exit code.
        **kwargs: Additional arguments passed to subprocess.run.

    Returns:
        CompletedProcess with results.
    """
    cmd_display = _format_command(cmd)

    if description:
        _log(f"Executing: {description}", LogLevel.INFO)
    _log(f"Command: {cmd_display}", LogLevel.DEBUG)
    if cwd:
        _log(f"cwd: {cwd}", LogLevel.DEBUG)

    if CommandConfig.dry_run:
        _log("DRY RUN - Command not executed", LogLevel.INFO)
        return subprocess.CompletedProcess(
            args=cmd,
            returncode=0,
            stdout="[DRY RUN]" if text else b"[DRY RUN]",
            stderr="" if text else b"",
        )

    try:
        result = subprocess.run(
            cmd,
            cwd=cwd,
            env=env,
            timeout=timeout,
            shell=shell,
            capture_output=capture_output,
            text=text,
            check=check,
            **kwargs,
        )

        # When capture_output=True the subprocess writes go into the result
        # buffer instead of our stdio, so the tee in run_manager doesn't see
        # them — and neither does the web Console tab. Dump them through
        # sys.stdout/stderr after the fact so the tee captures the actual
        # command output (poetry/pip/pytest/training stdout/stderr), not
        # just the brief "Executing: ..." description.
        if capture_output and text:
            try:
                if result.stdout:
                    sys.stdout.write(result.stdout)
                    if not result.stdout.endswith("\n"):
                        sys.stdout.write("\n")
                    sys.stdout.flush()
                if result.stderr:
                    sys.stderr.write(result.stderr)
                    if not result.stderr.endswith("\n"):
                        sys.stderr.write("\n")
                    sys.stderr.flush()
            except Exception:
                pass

        if result.returncode == 0:
            _log(f"Command succeeded (exit code: 0)", LogLevel.DEBUG)
        else:
            _log(f"Command failed (exit code: {result.returncode})", LogLevel.ERROR)
            # stderr was already dumped above when capture_output is set, so
            # don't re-emit it here.

        return result

    except subprocess.TimeoutExpired:
        _log(f"Command timed out after {timeout}s", LogLevel.ERROR)
        raise
    except subprocess.CalledProcessError:
        raise
    except Exception as e:
        _log(f"Unexpected error: {e}", LogLevel.ERROR)
        raise


def check_command_exists(command: str) -> bool:
    """Check if a command exists in the system PATH."""
    try:
        which_cmd = ["which", command] if os.name != "nt" else ["where", command]
        result = run_command(which_cmd, capture_output=True, text=True)
        return result.returncode == 0
    except Exception:
        return False


def run_with_retry(
    cmd: Union[str, List[str]],
    max_retries: int = 3,
    retry_on_codes: Optional[List[int]] = None,
    **kwargs,
) -> subprocess.CompletedProcess:
    """Run a command with automatic retry on failure."""
    result = None
    for attempt in range(max_retries):
        result = run_command(cmd, **kwargs)
        if result.returncode == 0:
            return result
        if retry_on_codes is not None and result.returncode not in retry_on_codes:
            return result
        if attempt < max_retries - 1:
            _log(f"Retrying ({attempt + 1}/{max_retries})...", LogLevel.INFO)
    return result  # type: ignore[return-value]
