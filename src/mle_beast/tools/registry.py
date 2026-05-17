# Copyright 2026 Chris Padwick
# SPDX-License-Identifier: Apache-2.0

"""Tool registry and dispatch.

Maps tool names to implementation functions. execute_tool() dispatches
a tool call by name with appropriate arguments.
"""

from __future__ import annotations

from typing import Any, Callable, Dict

from mle_beast.tools.file_ops import (
    create_directory,
    download_url,
    edit_file,
    list_files,
    read_file,
    write_file,
)
from mle_beast.tools.execution import (
    launch_evaluate,
    launch_training,
    run_python_file,
    run_shell_command,
    run_single_test,
    run_tests,
)
from mle_beast.tools.metadata import (
    check_cuda,
    get_workspace_metadata,
)


def _tool_write_file(args, shared):
    return write_file(args.file_path, args.content, getattr(args, "description", ""))


def _tool_read_file(args, shared):
    return read_file(args.file_path)


def _tool_edit_file(args, shared):
    return edit_file(args.file_path, args.old_text, args.new_text)


def _tool_list_files(args, shared):
    return list_files(args.directory, args.pattern)


def _tool_create_directory(args, shared):
    return create_directory(args.dir_path)


def _tool_download_url(args, shared):
    return download_url(args.url, args.dest_path)


def _tool_run_shell_command(args, shared):
    settings = shared.get("settings")
    max_chars = settings.command_output_max_chars if settings else 4000
    return run_shell_command(args.command, args.timeout, max_chars=max_chars)


def _tool_run_python_file(args, shared):
    settings = shared.get("settings")
    max_chars = settings.command_output_max_chars if settings else 4000
    return run_python_file(args.file_path, args.args, args.timeout, max_chars=max_chars)


def _tool_run_tests(args, shared):
    settings = shared.get("settings")
    if settings:
        return run_tests(
            args.test_file, args.verbose, args.timeout,
            test_output_max_chars=settings.test_output_max_chars,
            test_error_max_chars=settings.test_error_max_chars,
        )
    return run_tests(args.test_file, args.verbose, args.timeout)


def _tool_run_single_test(args, shared):
    return run_single_test(args.test_file, args.test_name, args.timeout)


def _tool_launch_training(args, shared):
    baseline_score = shared.get("best_score")
    if baseline_score is not None:
        if baseline_score == float("inf") or baseline_score <= 0:
            baseline_score = None

    return launch_training(
        args.script_path,
        args.args,
        args.log_file,
        args.timeout,
        baseline_score=baseline_score,
    )


def _tool_launch_evaluate(args, shared):
    return launch_evaluate(
        args.script_path,
        args.args,
        args.log_file,
        args.timeout,
    )


def _tool_check_cuda(args, shared):
    return check_cuda()


def _tool_get_workspace_metadata(args, shared):
    return get_workspace_metadata()


def _tool_mark_complete(args, shared):
    shared["last_mark_complete_summary"] = args.summary
    return f"MARK_COMPLETE: {args.summary}"


TOOL_REGISTRY: Dict[str, Callable] = {
    "write_file": _tool_write_file,
    "read_file": _tool_read_file,
    "edit_file": _tool_edit_file,
    "list_files": _tool_list_files,
    "create_directory": _tool_create_directory,
    "download_url": _tool_download_url,
    "run_shell_command": _tool_run_shell_command,
    "run_python_file": _tool_run_python_file,
    "run_tests": _tool_run_tests,
    "run_single_test": _tool_run_single_test,
    "launch_training": _tool_launch_training,
    "launch_evaluate": _tool_launch_evaluate,
    "check_cuda": _tool_check_cuda,
    "get_workspace_metadata": _tool_get_workspace_metadata,
    "mark_complete": _tool_mark_complete,
}


_TIMEOUT_TOOL_DEFAULTS = {
    "run_shell_command": 30,
    "run_python_file": 30,
    "run_tests": 60,
    "run_single_test": 30,
    "launch_training": 1800,
    "launch_evaluate": 300,
}


def _apply_timeout_override(tool_name: str, args: Any, shared: dict) -> None:
    """Override default timeouts with settings values when the LLM used the default."""
    settings = shared.get("settings")
    if settings is None or not hasattr(args, "timeout"):
        return

    default_val = _TIMEOUT_TOOL_DEFAULTS.get(tool_name)
    if default_val is None:
        return

    current = getattr(args, "timeout", None)
    if current != default_val:
        # LLM explicitly chose a non-default timeout; preserve it.
        return

    override_map = {
        "run_shell_command": settings.shell_command_timeout,
        "run_python_file": settings.python_file_timeout,
        "run_tests": settings.test_timeout,
        "run_single_test": settings.shell_command_timeout,
        "launch_training": settings.training_timeout,
    }
    override = override_map.get(tool_name)
    if override is not None:
        args.timeout = override


def execute_tool(tool_name: str, args: Any, shared: dict) -> str:
    """Dispatch a tool call by name.

    Args:
        tool_name: Name of the tool to execute.
        args: Pydantic args model for the tool.
        shared: The PocketFlow shared store.

    Returns:
        String result from the tool.
    """
    _apply_timeout_override(tool_name, args, shared)

    fn = TOOL_REGISTRY.get(tool_name)
    if fn is None:
        return f"ERROR: Unknown tool: {tool_name}"
    try:
        return fn(args, shared)
    except Exception as e:
        return f"ERROR executing {tool_name}: {e}"
