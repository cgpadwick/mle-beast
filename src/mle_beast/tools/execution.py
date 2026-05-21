# Copyright 2026 Chris Padwick
# SPDX-License-Identifier: Apache-2.0

"""Execution tools: shell commands, Python files, pytest, training launch.

Ported from ml_agents.shared_tools and training_agent.
"""

from __future__ import annotations

import os
import re
import shlex
import subprocess
import time
from pathlib import Path
from typing import List, Optional

from mle_beast.command_runner import run_command
from mle_beast.safety import check_python_file_text, check_shell_command
from mle_beast.safety.policy import log_block
from mle_beast.workspace import WorkspaceRegistry


def _parse_epoch_score(line: str) -> Optional[float]:
    """Parse validation score/accuracy from a training log line.

    Looks for common patterns like:
    - val_score=0.7934 or val_score: 0.7934
    - val_acc=0.7934 or val_acc: 0.7934
    - Val Score=0.7934, Val Score: 0.7934
    - val_score (acc): 0.0087

    Returns the score as a float, or None if not found.
    """
    # Common patterns for validation metrics in training logs
    patterns = [
        r'val_score[=:\s]+([0-9.]+)',
        r'val_acc[=:\s]+([0-9.]+)',
        r'Val Score[=:\s]+([0-9.]+)',
        r'Val Acc[=:\s]+([0-9.]+)',
        r'val_score \([^)]+\)[=:\s]+([0-9.]+)',
    ]

    for pattern in patterns:
        match = re.search(pattern, line, re.IGNORECASE)
        if match:
            try:
                return float(match.group(1))
            except ValueError:
                continue
    return None


def _get_workspace_env() -> tuple[Path, str, dict]:
    """Return (base_path, python_executable, env) for workspace commands.

    Resolution order for the Python executable:
      1. A user-pinned env via WorkspaceRegistry.get_environment() —
         set by RunConfig.environment (BYO env path). Takes precedence.
      2. `<workspace>/venv/bin/python` if it exists (default greenfield).
      3. Fall back to system `python3` (means the subprocess will use
         whatever python3 is on PATH — not ideal but not catastrophic).
    """
    base_path = Path(WorkspaceRegistry.get_workspace()).absolute()
    env_override = WorkspaceRegistry.get_environment()

    if env_override is not None:
        venv_path = env_override
    else:
        venv_path = base_path / "venv"
    venv_python = venv_path / "bin" / "python"

    if not venv_python.exists():
        python_exec = "python3"
    else:
        python_exec = str(venv_python.absolute())

    env = os.environ.copy()
    env["PYTHONPATH"] = str(base_path)
    if venv_path.exists():
        env["VIRTUAL_ENV"] = str(venv_path)
        env["PATH"] = f"{venv_path / 'bin'}{os.pathsep}" + env.get("PATH", "")
        env.pop("PYTHONHOME", None)
    # Force matplotlib into a headless backend. Otherwise scripts that call
    # plt.show() open a Qt/Wayland window that blocks until the subprocess
    # timeout kills it — the kill can cascade through the WSL graphics stack
    # and silently take the parent pipeline down.
    env["MPLBACKEND"] = "Agg"
    return base_path, python_exec, env


def _truncate(text: str, max_chars: int = 4000) -> str:
    if not text or len(text) <= max_chars:
        return text
    return "... [TRUNCATED] ...\n" + text[-max_chars:]


# Substrings that, if present in a shell-output line, indicate the line
# is housekeeping (venv internals, git plumbing, pytest cache) and not
# useful for the agent. Stripped before truncation so the agent's 4000-char
# observation window isn't consumed by 50K paths under .venv when it
# really only wants logs/checkpoints/results.
_NOISE_PATH_FRAGMENTS = (
    "/.venv/",
    "/venv/",
    "/.git/",
    "/node_modules/",
    "/.pytest_cache/",
    "/__pycache__/",
    "/site-packages/",
    "/dist-info/",
    ".egg-info/",
)


def _filter_noise_paths(text: str) -> str:
    """Drop lines referencing housekeeping directories.

    `find` / `ls -R` from a workspace root can produce tens of MB of
    output once it descends into `.venv` or `site-packages`. The agent
    only sees the truncated tail, so the actually-useful paths
    (`logs/`, `checkpoints/`, `results/`) get pushed out of the window
    by venv noise. Filtering at the tool layer guarantees the agent's
    observation focuses on its own workspace artifacts regardless of
    how broad its `find` was.
    """
    if not text:
        return text
    if not any(frag in text for frag in _NOISE_PATH_FRAGMENTS):
        return text
    kept, dropped = [], 0
    for line in text.splitlines():
        if any(frag in line for frag in _NOISE_PATH_FRAGMENTS):
            dropped += 1
        else:
            kept.append(line)
    if dropped:
        kept.append(f"[{dropped} lines under venv/.git/cache directories filtered]")
    return "\n".join(kept)


# Cap subprocess stdout/stderr bytes before any further processing. A
# single shell tool call producing 25MB of file paths is never useful and
# burns memory + downstream LLM tokens for no signal. 512KB is plenty to
# carry the tail of any legitimate `find` or training log.
_MAX_RAW_OUTPUT_BYTES = 512 * 1024


def _cap_raw(text: str) -> str:
    if not text or len(text) <= _MAX_RAW_OUTPUT_BYTES:
        return text
    return text[-_MAX_RAW_OUTPUT_BYTES:]


def run_shell_command(command: str, timeout: int = 30, max_chars: int = 4000) -> str:
    base_path, _, env = _get_workspace_env()

    # Safety check the RAW command — before we wrap it with `. activate
    # && …`. If we checked the wrapped form we'd false-positive on the
    # activate path (which can legitimately be outside the workspace
    # when a BYO env is in use), and we'd miss any tokens the user
    # genuinely typed since they're now buried after the && operator.
    decision = check_shell_command(command, workspace=base_path)
    if not decision.allow:
        log_block(command, decision, kind="shell", workspace=base_path)
        return decision.as_error()

    try:
        # If the user supplied a BYO environment, source THAT activate
        # script. Otherwise source <workspace>/venv/bin/activate (the
        # default greenfield venv) when it exists. Without this branch
        # a leftover <workspace>/venv from a prior run would shadow the
        # user's chosen environment and the agent would silently run
        # against the wrong interpreter.
        env_override = WorkspaceRegistry.get_environment()
        if env_override is not None:
            byo_activate = env_override / "bin" / "activate"
            if byo_activate.exists():
                command = f". {byo_activate} && {command}"
        else:
            venv_activate = base_path / "venv" / "bin" / "activate"
            if venv_activate.exists():
                command = f". {venv_activate} && {command}"

        result = run_command(
            command, shell=True, capture_output=True, text=True,
            timeout=timeout, cwd=str(base_path), env=env,
            description="Shell command",
        )
        output = []
        stdout = _filter_noise_paths(_cap_raw(result.stdout))
        stderr = _filter_noise_paths(_cap_raw(result.stderr))
        if stdout:
            output.append(f"Output:\n{_truncate(stdout, max_chars)}")
        if stderr:
            output.append(f"Errors:\n{_truncate(stderr, max_chars)}")
        output.append(f"Exit code: {result.returncode}")
        return "\n".join(output)
    except subprocess.TimeoutExpired:
        return f"ERROR: Command timed out after {timeout}s"
    except Exception as e:
        return f"ERROR: {e}"


def run_python_file(file_path: str, args: str = "", timeout: int = 30, max_chars: int = 4000) -> str:
    base_path, python_exec, env = _get_workspace_env()
    full_path = base_path / file_path
    if not full_path.exists():
        return f"ERROR: File not found: {file_path}"

    # Lint the script's TEXT for blocked tokens (e.g.
    # `os.system("sudo …")`) before we shell out to python. Not an AST
    # check — just a fast string scan that catches the obvious case of
    # an agent dropping sudo-using code into a script it's about to run.
    try:
        script_text = full_path.read_text(encoding="utf-8", errors="replace")
    except OSError as e:
        return f"ERROR: Could not read {file_path}: {e}"
    decision = check_python_file_text(script_text)
    if not decision.allow:
        # Preview is just the file path — `decision.rule` already
        # carries the offending token, and embedding the full reason
        # made the log lines less stable/greppable (each line could
        # contain arbitrary punctuation from the reason).
        log_block(
            file_path,
            decision,
            kind="python_file",
            workspace=base_path,
        )
        return decision.as_error()
    # Add script's parent dir to PYTHONPATH so sibling imports work
    # (e.g., iterations/v1/train.py can do "from model import MyModel")
    script_dir = str(full_path.parent.absolute())
    if script_dir != str(base_path):
        env["PYTHONPATH"] = f"{script_dir}{os.pathsep}{env['PYTHONPATH']}"
    try:
        cmd = [python_exec, str(full_path)]
        if args:
            cmd.extend(args.split())
        result = run_command(
            cmd, capture_output=True, text=True, timeout=timeout,
            cwd=str(base_path), env=env,
            description=f"Running: {file_path}",
        )
        output = []
        if result.stdout:
            output.append(f"Output:\n{_truncate(result.stdout, max_chars)}")
        if result.stderr:
            output.append(f"Errors:\n{_truncate(result.stderr, max_chars)}")
        output.append(f"Exit code: {result.returncode}")
        return "\n".join(output)
    except subprocess.TimeoutExpired:
        return f"ERROR: Timed out after {timeout}s"
    except Exception as e:
        return f"ERROR: {e}"


def run_tests(
    test_file: str = "",
    verbose: bool = True,
    timeout: int = 60,
    test_dir: str = "",
    test_output_max_chars: int = 2000,
    test_error_max_chars: int = 1000,
) -> str:
    base_path, python_exec, env = _get_workspace_env()
    # If test_dir specified, add its parent to PYTHONPATH so test imports resolve
    if test_dir:
        parent_path = str((base_path / test_dir).parent.absolute())
        if parent_path != str(base_path):
            env["PYTHONPATH"] = f"{parent_path}{os.pathsep}{env['PYTHONPATH']}"
    try:
        cmd = [python_exec, "-m", "pytest"]
        if verbose:
            cmd.extend(["-v", "--tb=short"])
        if test_file:
            test_path = base_path / test_file
            if not test_path.exists():
                return f"ERROR: Test file not found: {test_file}"
            cmd.append(str(test_path))
        elif test_dir:
            td = base_path / test_dir
            if td.exists():
                cmd.append(str(td))
            else:
                return f"ERROR: No tests directory found at {test_dir}"
        else:
            tests_dir = base_path / "tests"
            if tests_dir.exists():
                cmd.append(str(tests_dir))
            else:
                return "ERROR: No tests directory found"

        result = run_command(
            cmd, capture_output=True, text=True, timeout=timeout,
            cwd=str(base_path), env=env,
            description=f"pytest: {test_file or 'all'}",
        )
        output = []
        if result.stdout:
            output.append(f"Test Output:\n{result.stdout[:test_output_max_chars]}")
        if result.stderr and "warning" not in result.stderr.lower():
            output.append(f"Errors:\n{result.stderr[:test_error_max_chars]}")
        if result.returncode == 0:
            output.append("\nAll tests passed!")
        elif result.returncode == 5:
            output.append("\nNo tests were collected")
        else:
            output.append(f"\nTests failed (exit code: {result.returncode})")
        return "\n".join(output)
    except subprocess.TimeoutExpired:
        return f"ERROR: Tests timed out after {timeout}s"
    except Exception as e:
        return f"ERROR: {e}"


def run_single_test(test_file: str, test_name: str, timeout: int = 30) -> str:
    base_path, python_exec, env = _get_workspace_env()
    try:
        test_path = f"{test_file}::{test_name}"
        cmd = [python_exec, "-m", "pytest", "-v", test_path]
        result = run_command(
            cmd, capture_output=True, text=True, timeout=timeout,
            cwd=str(base_path), env=env,
            description=f"Single test: {test_name}",
        )
        output = []
        if result.stdout:
            output.append(f"Output:\n{_truncate(result.stdout)}")
        if result.stderr:
            output.append(f"Errors:\n{_truncate(result.stderr)}")
        output.append(f"Exit code: {result.returncode}")
        return "\n".join(output)
    except Exception as e:
        return f"ERROR: {e}"


def launch_training(
    script_path: str,
    args: str = "",
    log_file: str = "logs/training.log",
    timeout: int = 1800,
    baseline_score: Optional[float] = None,
    baseline_threshold: float = 0.1,
) -> str:
    """Launch a training script in the foreground, streaming and logging output.

    Args:
        script_path: Path to the training script.
        args: CLI arguments to pass to the script.
        log_file: Path for the training log output.
        timeout: Maximum runtime in seconds.
        baseline_score: If provided, training will be terminated early if the
            validation score falls below baseline_score * baseline_threshold.
            This prevents wasting GPU time on obviously broken training runs.
        baseline_threshold: Minimum fraction of baseline_score required to
            continue training. Default 0.1 (10% of baseline).

    Returns:
        Summary string with training status and log tail.
    """
    base_path, python_exec, env = _get_workspace_env()
    full_script = base_path / script_path
    if not full_script.exists():
        return f"ERROR: Training script not found: {script_path}"
    # Add script's parent dir to PYTHONPATH so sibling imports work
    script_dir = str(full_script.parent.absolute())
    if script_dir != str(base_path):
        env["PYTHONPATH"] = f"{script_dir}{os.pathsep}{env['PYTHONPATH']}"

    log_path = base_path / log_file
    log_path.parent.mkdir(parents=True, exist_ok=True)

    command: list[str] = [python_exec]
    if full_script.suffix == ".py":
        command.append("-u")  # unbuffered
    command.append(str(full_script))
    if args:
        command.extend(shlex.split(args))

    # Calculate baseline threshold for early termination
    min_acceptable_score = None
    if baseline_score is not None and baseline_score > 0:
        min_acceptable_score = baseline_score * baseline_threshold
        print(f"  [TrainingMonitor] Baseline score: {baseline_score:.4f}, "
              f"min acceptable: {min_acceptable_score:.4f}")

    try:
        with open(log_path, "w", encoding="utf-8", errors="ignore") as lf:
            process = subprocess.Popen(
                command,
                cwd=str(base_path),
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
                env={**env, "PYTHONUNBUFFERED": "1"},
            )
            output_lines: List[str] = []
            assert process.stdout is not None

            start_time = time.time()
            epochs_seen = 0
            baseline_violation_detected = False

            for line in process.stdout:
                line = line.rstrip("\n")
                lf.write(line + "\n")
                lf.flush()
                output_lines.append(line)

                # Check for timeout
                if time.time() - start_time > timeout:
                    process.kill()
                    raise subprocess.TimeoutExpired(command, timeout)

                # Check baseline if provided (only after seeing at least one epoch)
                if min_acceptable_score is not None:
                    score = _parse_epoch_score(line)
                    if score is not None:
                        epochs_seen += 1
                        if score < min_acceptable_score:
                            print(f"  [TrainingMonitor] BASELINE VIOLATION at epoch "
                                  f"{epochs_seen}: score {score:.4f} < "
                                  f"threshold {min_acceptable_score:.4f}")
                            print("  [TrainingMonitor] Terminating training early.")
                            process.kill()
                            baseline_violation_detected = True
                            break

            process.wait()

        summary: List[str] = []

        if baseline_violation_detected:
            summary.append(
                f"ERROR: Training terminated - score below baseline threshold.\n"
                f"Baseline: {baseline_score:.4f}, Threshold: {min_acceptable_score:.4f}\n"
                f"The model is not learning properly. Check that:\n"
                f"- Pretrained weights are being loaded correctly\n"
                f"- Learning rate is appropriate\n"
                f"- Data preprocessing matches the pretrained model's requirements"
            )
        elif process.returncode == 0:
            summary.append("Training completed (exit code: 0)")
        else:
            summary.append(f"Training FAILED (exit code: {process.returncode})")

        summary.append(f"Log: {log_path.relative_to(base_path)}")

        tail_count = 25 if process.returncode != 0 or baseline_violation_detected else 10
        tail_lines = [ln for ln in output_lines if ln.strip()][-tail_count:]
        if tail_lines:
            summary.append("\n--- Last lines ---")
            summary.extend(tail_lines)

        return "\n".join(summary)

    except subprocess.TimeoutExpired:
        return (
            f"ERROR: Training timed out after {timeout}s\n"
            f"Partial output in: {log_path.relative_to(base_path)}"
        )
    except Exception as e:
        return f"ERROR: Failed to run training: {e}"


def launch_evaluate(
    script_path: str = "evaluate.py",
    args: str = "",
    log_file: str = "logs/eval.log",
    timeout: int = 300,
) -> str:
    """Launch an evaluation script in the foreground, streaming + logging.

    Mirror of launch_training without baseline-violation early-termination.
    Eval is comparatively fast and the whole point is to see it through to
    a metric value, so we don't want to bail on intermediate output.

    Returns a summary string with exit status, log path, and tail lines.
    """
    base_path, python_exec, env = _get_workspace_env()
    full_script = base_path / script_path
    if not full_script.exists():
        return f"ERROR: Evaluation script not found: {script_path}"
    script_dir = str(full_script.parent.absolute())
    if script_dir != str(base_path):
        env["PYTHONPATH"] = f"{script_dir}{os.pathsep}{env['PYTHONPATH']}"

    log_path = base_path / log_file
    log_path.parent.mkdir(parents=True, exist_ok=True)

    command: list[str] = [python_exec]
    if full_script.suffix == ".py":
        command.append("-u")
    command.append(str(full_script))
    if args:
        command.extend(shlex.split(args))

    try:
        with open(log_path, "w", encoding="utf-8", errors="ignore") as lf:
            process = subprocess.Popen(
                command,
                cwd=str(base_path),
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
                env={**env, "PYTHONUNBUFFERED": "1"},
            )
            output_lines: List[str] = []
            assert process.stdout is not None

            start_time = time.time()
            for line in process.stdout:
                line = line.rstrip("\n")
                lf.write(line + "\n")
                lf.flush()
                output_lines.append(line)
                if time.time() - start_time > timeout:
                    process.kill()
                    raise subprocess.TimeoutExpired(command, timeout)

            process.wait()

        summary: List[str] = []
        if process.returncode == 0:
            summary.append("Evaluation completed (exit code: 0)")
        else:
            summary.append(f"Evaluation FAILED (exit code: {process.returncode})")
        summary.append(f"Log: {log_path.relative_to(base_path)}")

        tail_count = 30 if process.returncode != 0 else 15
        tail_lines = [ln for ln in output_lines if ln.strip()][-tail_count:]
        if tail_lines:
            summary.append("\n--- Last lines ---")
            summary.extend(tail_lines)

        return "\n".join(summary)
    except subprocess.TimeoutExpired:
        return (
            f"ERROR: Evaluation timed out after {timeout}s\n"
            f"Partial output in: {log_path.relative_to(base_path)}"
        )
    except Exception as e:
        return f"ERROR: Failed to run evaluation: {e}"
