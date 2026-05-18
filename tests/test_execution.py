# Copyright 2026 Chris Padwick
# SPDX-License-Identifier: Apache-2.0

"""Unit tests for mle_beast.tools.execution.

Wraps subprocess interactions: every test mocks either `run_command`
(for the simple capture-output paths) or `subprocess.Popen` (for the
streaming launch_training / launch_evaluate paths) so nothing actually
spawns a real process. The existing test_tools.py covers
_parse_epoch_score and a couple of launch_training baseline scenarios
end-to-end on tiny scripts; this file fills the rest of the wrapper
logic.
"""

from __future__ import annotations

import subprocess
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from mle_beast.tools import execution as exec_mod
from mle_beast.tools.execution import (
    _MAX_RAW_OUTPUT_BYTES,
    _cap_raw,
    _filter_noise_paths,
    _get_workspace_env,
    _truncate,
    launch_evaluate,
    launch_training,
    run_python_file,
    run_shell_command,
    run_single_test,
    run_tests,
)

# ---------------------------------------------------------------------------
# Helper functions
# ---------------------------------------------------------------------------


class TestTruncate:
    def test_short_text_unchanged(self):
        assert _truncate("hello", 100) == "hello"

    def test_empty_unchanged(self):
        assert _truncate("", 100) == ""

    def test_long_text_keeps_tail_with_marker(self):
        out = _truncate("x" * 200, max_chars=50)
        assert "TRUNCATED" in out
        assert out.endswith("x" * 50)


class TestFilterNoisePaths:
    def test_empty_unchanged(self):
        assert _filter_noise_paths("") == ""

    def test_text_without_noise_passes_through(self):
        clean = "logs/train.log\ncheckpoints/best.pt\n"
        assert _filter_noise_paths(clean) == clean

    def test_drops_venv_lines_and_appends_summary(self):
        text = (
            "logs/train.log\n"
            "ws/.venv/lib/python3.10/site-packages/foo/__init__.py\n"
            "ws/.venv/lib/python3.10/site-packages/foo/bar.py\n"
            "checkpoints/best.pt\n"
        )
        out = _filter_noise_paths(text)
        assert "logs/train.log" in out
        assert "checkpoints/best.pt" in out
        assert ".venv" not in out
        assert "[2 lines under venv/.git/cache directories filtered]" in out

    @pytest.mark.parametrize("fragment", [
        "/.venv/", "/venv/", "/.git/", "/node_modules/",
        "/.pytest_cache/", "/__pycache__/", "/site-packages/",
        "/dist-info/", ".egg-info/",
    ])
    def test_each_noise_fragment_dropped(self, fragment):
        text = f"keep.txt\nworkspace{fragment}drop.txt\n"
        out = _filter_noise_paths(text)
        assert "keep.txt" in out
        assert "drop.txt" not in out


class TestCapRaw:
    def test_short_text_unchanged(self):
        assert _cap_raw("hello") == "hello"

    def test_empty_unchanged(self):
        assert _cap_raw("") == ""

    def test_caps_to_tail(self):
        big = "x" * (_MAX_RAW_OUTPUT_BYTES + 1000)
        out = _cap_raw(big)
        assert len(out) == _MAX_RAW_OUTPUT_BYTES
        assert out == "x" * _MAX_RAW_OUTPUT_BYTES


class TestGetWorkspaceEnv:
    def test_falls_back_to_system_python_when_no_venv(self, workspace):
        # workspace fixture creates the dir but not a venv
        base, py, env = _get_workspace_env()
        assert py == "python3"
        assert env["PYTHONPATH"] == str(base)
        assert env["MPLBACKEND"] == "Agg"
        # No VIRTUAL_ENV set since the venv doesn't exist
        assert "VIRTUAL_ENV" not in env

    def test_uses_venv_python_when_present(self, workspace):
        # Stub out a venv/bin/python so the existence check passes.
        venv_python = workspace / "venv" / "bin" / "python"
        venv_python.parent.mkdir(parents=True)
        venv_python.touch()

        base, py, env = _get_workspace_env()
        assert py == str(venv_python.absolute())
        assert env["VIRTUAL_ENV"] == str(workspace / "venv")
        # PATH should be prefixed with the venv's bin dir
        assert str(workspace / "venv" / "bin") in env["PATH"]


# ---------------------------------------------------------------------------
# Fake run_command for the simple capture-output paths
# ---------------------------------------------------------------------------


def _fake_completed(stdout="", stderr="", returncode=0):
    return SimpleNamespace(stdout=stdout, stderr=stderr, returncode=returncode)


@pytest.fixture
def mock_run_command(monkeypatch):
    """Patch run_command and let tests configure its return value per call."""
    mock = MagicMock(return_value=_fake_completed())
    monkeypatch.setattr(exec_mod, "run_command", mock)
    return mock


# ---------------------------------------------------------------------------
# run_shell_command
# ---------------------------------------------------------------------------


class TestRunShellCommand:
    def test_returns_stdout_and_exit_code(self, workspace, mock_run_command):
        mock_run_command.return_value = _fake_completed(
            stdout="hello\n", returncode=0,
        )
        out = run_shell_command("echo hello")
        assert "Output:" in out and "hello" in out
        assert "Exit code: 0" in out

    def test_includes_stderr_when_present(self, workspace, mock_run_command):
        mock_run_command.return_value = _fake_completed(
            stdout="", stderr="warning: x\n", returncode=0,
        )
        out = run_shell_command("ls /etc")
        assert "Errors:" in out and "warning" in out

    def test_filters_venv_noise(self, workspace, mock_run_command):
        mock_run_command.return_value = _fake_completed(
            stdout=(
                "ok.txt\n"
                "ws/.venv/lib/python3.10/site-packages/foo.py\n"
            ),
            returncode=0,
        )
        out = run_shell_command("find .")
        assert "ok.txt" in out
        assert ".venv" not in out
        assert "filtered" in out

    def test_prefixes_venv_activate_when_present(
        self, workspace, mock_run_command,
    ):
        # Touching venv/bin/activate triggers the activation prefix path.
        activate = workspace / "venv" / "bin" / "activate"
        activate.parent.mkdir(parents=True)
        activate.touch()
        run_shell_command("echo hi")
        call_args, _ = mock_run_command.call_args.args, mock_run_command.call_args.kwargs
        # First positional arg is the (rewritten) command string.
        assert ". " in call_args[0] and "&& echo hi" in call_args[0]

    def test_timeout_surfaces_as_error_string(self, workspace, mock_run_command):
        mock_run_command.side_effect = subprocess.TimeoutExpired("echo", 30)
        out = run_shell_command("sleep 999", timeout=30)
        assert "ERROR" in out and "timed out" in out

    def test_exception_surfaces_as_error_string(self, workspace, mock_run_command):
        mock_run_command.side_effect = OSError("nope")
        out = run_shell_command("anything")
        assert out.startswith("ERROR")
        assert "nope" in out


# ---------------------------------------------------------------------------
# run_python_file
# ---------------------------------------------------------------------------


class TestRunPythonFile:
    def test_missing_file_returns_error(self, workspace):
        out = run_python_file("nonexistent.py")
        assert "ERROR" in out and "not found" in out

    def test_passes_args(self, workspace, mock_run_command):
        (workspace / "script.py").write_text("print('x')")
        mock_run_command.return_value = _fake_completed(
            stdout="x\n", returncode=0,
        )
        run_python_file("script.py", args="--foo 1 --bar 2")
        cmd = mock_run_command.call_args.args[0]
        assert "--foo" in cmd and "1" in cmd
        assert "--bar" in cmd and "2" in cmd

    def test_adds_script_dir_to_pythonpath_for_nested_scripts(
        self, workspace, mock_run_command,
    ):
        sub = workspace / "models" / "v1"
        sub.mkdir(parents=True)
        (sub / "train.py").write_text("x = 1")
        mock_run_command.return_value = _fake_completed(returncode=0)
        run_python_file("models/v1/train.py")
        env = mock_run_command.call_args.kwargs["env"]
        # The script's parent dir should now lead the PYTHONPATH chain.
        assert str(sub.absolute()) in env["PYTHONPATH"]

    def test_includes_stdout_stderr_in_output(self, workspace, mock_run_command):
        (workspace / "s.py").write_text("x = 1")
        mock_run_command.return_value = _fake_completed(
            stdout="hi\n", stderr="warn\n", returncode=2,
        )
        out = run_python_file("s.py")
        assert "Output:" in out and "hi" in out
        assert "Errors:" in out and "warn" in out
        assert "Exit code: 2" in out

    def test_timeout_surfaces_as_error(self, workspace, mock_run_command):
        (workspace / "s.py").write_text("x = 1")
        mock_run_command.side_effect = subprocess.TimeoutExpired("python", 5)
        out = run_python_file("s.py", timeout=5)
        assert "ERROR" in out and "Timed out" in out

    def test_other_exceptions_surface(self, workspace, mock_run_command):
        (workspace / "s.py").write_text("x = 1")
        mock_run_command.side_effect = RuntimeError("kaboom")
        out = run_python_file("s.py")
        assert out.startswith("ERROR") and "kaboom" in out


# ---------------------------------------------------------------------------
# run_tests
# ---------------------------------------------------------------------------


class TestRunTests:
    def test_no_tests_directory(self, workspace, mock_run_command):
        # Default branch: no tests/ dir at workspace root.
        # The workspace fixture pre-creates tests/, so remove it first.
        (workspace / "tests").rmdir()
        out = run_tests()
        assert "ERROR" in out and "No tests directory" in out

    def test_specified_test_file_missing(self, workspace, mock_run_command):
        out = run_tests(test_file="missing_test.py")
        assert "ERROR" in out and "not found" in out

    def test_specified_test_dir_missing(self, workspace, mock_run_command):
        out = run_tests(test_dir="not_a_dir")
        assert "ERROR" in out and "No tests directory" in out

    def test_runs_default_tests_dir(self, workspace, mock_run_command):
        (workspace / "tests" / "test_x.py").write_text("def test_x(): pass")
        mock_run_command.return_value = _fake_completed(
            stdout="1 passed\n", returncode=0,
        )
        out = run_tests()
        cmd = mock_run_command.call_args.args[0]
        assert str(workspace / "tests") in cmd
        assert "All tests passed!" in out

    def test_runs_specific_test_file(self, workspace, mock_run_command):
        (workspace / "tests" / "test_a.py").write_text("def test_a(): pass")
        mock_run_command.return_value = _fake_completed(returncode=0)
        run_tests(test_file="tests/test_a.py")
        cmd = mock_run_command.call_args.args[0]
        assert str(workspace / "tests" / "test_a.py") in cmd

    def test_no_collected_tests_returns_5(self, workspace, mock_run_command):
        (workspace / "tests" / "empty.py").write_text("")
        mock_run_command.return_value = _fake_completed(
            stdout="no tests ran\n", returncode=5,
        )
        out = run_tests(test_file="tests/empty.py")
        assert "No tests were collected" in out

    def test_failed_tests_reports_exit_code(self, workspace, mock_run_command):
        (workspace / "tests" / "test_x.py").write_text("def test_x(): assert False")
        mock_run_command.return_value = _fake_completed(
            stdout="failure", returncode=1,
        )
        out = run_tests(test_file="tests/test_x.py")
        assert "Tests failed" in out and "exit code: 1" in out

    def test_custom_test_dir_with_parent_pythonpath(
        self, workspace, mock_run_command,
    ):
        sub = workspace / "iterations" / "v1" / "tests"
        sub.mkdir(parents=True)
        (sub / "test_z.py").write_text("def test_z(): pass")
        mock_run_command.return_value = _fake_completed(returncode=0)
        run_tests(test_dir="iterations/v1/tests")
        env = mock_run_command.call_args.kwargs["env"]
        assert str(workspace / "iterations" / "v1") in env["PYTHONPATH"]

    def test_verbose_adds_flag(self, workspace, mock_run_command):
        (workspace / "tests" / "test_a.py").write_text("def test_a(): pass")
        mock_run_command.return_value = _fake_completed(returncode=0)
        run_tests(test_file="tests/test_a.py", verbose=True)
        cmd = mock_run_command.call_args.args[0]
        assert "-v" in cmd

    def test_non_verbose_skips_flag(self, workspace, mock_run_command):
        (workspace / "tests" / "test_a.py").write_text("def test_a(): pass")
        mock_run_command.return_value = _fake_completed(returncode=0)
        run_tests(test_file="tests/test_a.py", verbose=False)
        cmd = mock_run_command.call_args.args[0]
        assert "-v" not in cmd

    def test_stderr_warnings_are_suppressed(self, workspace, mock_run_command):
        (workspace / "tests" / "test_a.py").write_text("def test_a(): pass")
        mock_run_command.return_value = _fake_completed(
            stdout="pass", stderr="DeprecationWarning: …\n", returncode=0,
        )
        out = run_tests(test_file="tests/test_a.py")
        # The warning-only stderr should NOT appear under an Errors block.
        assert "Errors:" not in out

    def test_timeout_returns_error_string(self, workspace, mock_run_command):
        (workspace / "tests" / "test_a.py").write_text("def test_a(): pass")
        mock_run_command.side_effect = subprocess.TimeoutExpired("pytest", 60)
        out = run_tests(test_file="tests/test_a.py", timeout=60)
        assert "ERROR" in out and "timed out" in out

    def test_other_exception_returns_error_string(
        self, workspace, mock_run_command,
    ):
        (workspace / "tests" / "test_a.py").write_text("def test_a(): pass")
        mock_run_command.side_effect = OSError("nope")
        out = run_tests(test_file="tests/test_a.py")
        assert out.startswith("ERROR")


# ---------------------------------------------------------------------------
# run_single_test
# ---------------------------------------------------------------------------


class TestRunSingleTest:
    def test_builds_pytest_path_with_test_name(
        self, workspace, mock_run_command,
    ):
        mock_run_command.return_value = _fake_completed(
            stdout="ok", returncode=0,
        )
        run_single_test("tests/test_a.py", "test_x")
        cmd = mock_run_command.call_args.args[0]
        assert "tests/test_a.py::test_x" in cmd
        assert "-v" in cmd

    def test_reports_exit_code_in_output(self, workspace, mock_run_command):
        mock_run_command.return_value = _fake_completed(
            stdout="boom", stderr="trace", returncode=1,
        )
        out = run_single_test("tests/x.py", "test_y")
        assert "Output:" in out and "boom" in out
        assert "Errors:" in out and "trace" in out
        assert "Exit code: 1" in out

    def test_exception_surfaces(self, workspace, mock_run_command):
        mock_run_command.side_effect = RuntimeError("explode")
        out = run_single_test("tests/x.py", "test_y")
        assert out.startswith("ERROR") and "explode" in out


# ---------------------------------------------------------------------------
# launch_training / launch_evaluate
#
# These call subprocess.Popen directly, so the mocks live one level deeper.
# ---------------------------------------------------------------------------


class _FakePopen:
    """A minimal Popen stand-in that yields scripted stdout lines and a
    returncode. Lets tests drive the loop in launch_training without
    spawning a real subprocess.
    """

    def __init__(self, lines, returncode=0, raise_on_iter=None):
        self._lines = list(lines)
        self.returncode = returncode
        self._kill_called = False
        self._raise_on_iter = raise_on_iter
        self.stdout = self  # the function iterates `process.stdout`

    def __iter__(self):
        for ln in self._lines:
            if self._raise_on_iter:
                raise self._raise_on_iter
            yield ln if ln.endswith("\n") else ln + "\n"

    def kill(self):
        self._kill_called = True

    def wait(self):
        return self.returncode


@pytest.fixture
def script(workspace):
    """A workspace with a dummy training script at train.py."""
    (workspace / "train.py").write_text("# stub")
    return workspace / "train.py"


class TestLaunchTraining:
    def test_missing_script_returns_error(self, workspace):
        out = launch_training("missing.py")
        assert "ERROR" in out and "not found" in out

    def test_happy_path_exit_zero(self, script, monkeypatch):
        fake = _FakePopen(
            ["Epoch 1: loss=0.5\n", "Epoch 2: loss=0.4\n"],
            returncode=0,
        )
        monkeypatch.setattr(
            "mle_beast.tools.execution.subprocess.Popen", lambda *a, **kw: fake,
        )
        out = launch_training("train.py")
        assert "Training completed" in out
        assert "Last lines" in out
        assert "Epoch 2" in out

    def test_nonzero_exit_reports_failure(self, script, monkeypatch):
        fake = _FakePopen(["Some output\n"], returncode=1)
        monkeypatch.setattr(
            "mle_beast.tools.execution.subprocess.Popen", lambda *a, **kw: fake,
        )
        out = launch_training("train.py")
        assert "Training FAILED" in out
        assert "exit code: 1" in out

    def test_baseline_violation_kills_process(self, script, monkeypatch):
        """When a parsed epoch score falls below baseline*threshold, the
        wrapper kills the process and reports the violation.
        """
        fake = _FakePopen(
            ["Epoch 1: val_score=0.01\n"],  # well below 0.5 * 0.1 = 0.05
            returncode=0,
        )
        monkeypatch.setattr(
            "mle_beast.tools.execution.subprocess.Popen", lambda *a, **kw: fake,
        )
        out = launch_training("train.py", baseline_score=0.5)
        assert "ERROR" in out
        assert "below baseline threshold" in out
        assert fake._kill_called is True

    def test_baseline_score_zero_disables_monitoring(self, script, monkeypatch):
        """baseline_score=0 should NOT trigger early termination — the
        threshold is computed as baseline*0.1=0, and 0 < 0 is False.
        """
        fake = _FakePopen(
            ["Epoch 1: val_score=0.01\n"],
            returncode=0,
        )
        monkeypatch.setattr(
            "mle_beast.tools.execution.subprocess.Popen", lambda *a, **kw: fake,
        )
        out = launch_training("train.py", baseline_score=0.0)
        assert "Training completed" in out
        assert "below baseline threshold" not in out

    def test_args_are_shlex_split(self, script, monkeypatch):
        captured = {}

        def fake_popen(cmd, **kw):
            captured["cmd"] = cmd
            return _FakePopen([], returncode=0)

        monkeypatch.setattr(
            "mle_beast.tools.execution.subprocess.Popen", fake_popen,
        )
        launch_training("train.py", args='--lr 0.001 --batch-size 32')
        # shlex-split: each token is a separate arg.
        cmd = captured["cmd"]
        assert "--lr" in cmd and "0.001" in cmd
        assert "--batch-size" in cmd and "32" in cmd

    def test_timeout_during_streaming_kills(self, script, monkeypatch):
        # Patch time.time so the second call exceeds the timeout.
        times = iter([0.0, 1000.0])
        monkeypatch.setattr(
            "mle_beast.tools.execution.time.time", lambda: next(times),
        )

        fake = _FakePopen(["line 1\n", "line 2\n"], returncode=0)
        monkeypatch.setattr(
            "mle_beast.tools.execution.subprocess.Popen", lambda *a, **kw: fake,
        )
        out = launch_training("train.py", timeout=10)
        assert "ERROR" in out and "timed out" in out
        assert fake._kill_called is True

    def test_unexpected_exception_surfaces(self, script, monkeypatch):
        def raises(*a, **kw):
            raise OSError("disk full")

        monkeypatch.setattr(
            "mle_beast.tools.execution.subprocess.Popen", raises,
        )
        out = launch_training("train.py")
        assert "ERROR: Failed to run training" in out
        assert "disk full" in out


class TestLaunchEvaluate:
    def test_missing_script(self, workspace):
        out = launch_evaluate("missing.py")
        assert "ERROR" in out and "not found" in out

    def test_happy_path(self, workspace, monkeypatch):
        (workspace / "evaluate.py").write_text("# stub")
        fake = _FakePopen(["Test accuracy: 0.93\n"], returncode=0)
        monkeypatch.setattr(
            "mle_beast.tools.execution.subprocess.Popen", lambda *a, **kw: fake,
        )
        out = launch_evaluate()
        assert "Evaluation completed" in out
        assert "0.93" in out

    def test_failure_reports_exit_code(self, workspace, monkeypatch):
        (workspace / "evaluate.py").write_text("# stub")
        fake = _FakePopen(["boom\n"], returncode=2)
        monkeypatch.setattr(
            "mle_beast.tools.execution.subprocess.Popen", lambda *a, **kw: fake,
        )
        out = launch_evaluate()
        assert "Evaluation FAILED" in out and "exit code: 2" in out

    def test_args_shlex_split(self, workspace, monkeypatch):
        (workspace / "evaluate.py").write_text("# stub")
        captured = {}

        def fake_popen(cmd, **kw):
            captured["cmd"] = cmd
            return _FakePopen([], returncode=0)

        monkeypatch.setattr(
            "mle_beast.tools.execution.subprocess.Popen", fake_popen,
        )
        launch_evaluate(args="--checkpoint best.pt --device cuda")
        cmd = captured["cmd"]
        assert "--checkpoint" in cmd and "best.pt" in cmd

    def test_timeout(self, workspace, monkeypatch):
        (workspace / "evaluate.py").write_text("# stub")
        times = iter([0.0, 999.0])
        monkeypatch.setattr(
            "mle_beast.tools.execution.time.time", lambda: next(times),
        )
        fake = _FakePopen(["x\n"], returncode=0)
        monkeypatch.setattr(
            "mle_beast.tools.execution.subprocess.Popen", lambda *a, **kw: fake,
        )
        out = launch_evaluate(timeout=10)
        assert "ERROR" in out and "timed out" in out

    def test_unexpected_exception(self, workspace, monkeypatch):
        (workspace / "evaluate.py").write_text("# stub")

        def raises(*a, **kw):
            raise OSError("permission denied")

        monkeypatch.setattr(
            "mle_beast.tools.execution.subprocess.Popen", raises,
        )
        out = launch_evaluate()
        assert "ERROR: Failed to run evaluation" in out
        assert "permission" in out

    def test_nested_script_pythonpath(self, workspace, monkeypatch):
        sub = workspace / "models" / "v2"
        sub.mkdir(parents=True)
        (sub / "eval.py").write_text("# stub")

        captured = {}

        def fake_popen(cmd, **kw):
            captured["env"] = kw["env"]
            return _FakePopen([], returncode=0)

        monkeypatch.setattr(
            "mle_beast.tools.execution.subprocess.Popen", fake_popen,
        )
        launch_evaluate("models/v2/eval.py")
        assert str(sub.absolute()) in captured["env"]["PYTHONPATH"]
