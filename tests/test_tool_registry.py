# Copyright 2026 Chris Padwick
# SPDX-License-Identifier: Apache-2.0

"""Targeted tests for mle_beast.tools.registry.

The existing tests/test_tools.py covers some happy paths; this file
fills coverage on the dispatcher itself: timeout overrides, settings-
gated paths, exception handling, and the tools that don't have direct
tests yet (cuda check, workspace metadata, edit_file via dispatcher, etc).
"""

from __future__ import annotations

from dataclasses import dataclass


from mle_beast.models.tool_calls import (
    CreateDirectoryArgs,
    EditFileArgs,
    ListFilesArgs,
    MarkCompleteArgs,
    WriteFileArgs,
)
from mle_beast.settings import Settings
from mle_beast.tools.registry import (
    TOOL_REGISTRY,
    _apply_timeout_override,
    execute_tool,
)


# ---------------------------------------------------------------------------
# Tiny stand-ins so registry tests don't have to touch real subprocesses
# (covered by the live tools tests). Args here only need `.timeout`.
# ---------------------------------------------------------------------------


@dataclass
class _ShellArgs:
    command: str = "echo hi"
    timeout: int = 30


@dataclass
class _PythonArgs:
    file_path: str = "x.py"
    args: str = ""
    timeout: int = 30


@dataclass
class _TestsArgs:
    test_file: str = ""
    verbose: bool = True
    timeout: int = 60


@dataclass
class _TrainArgs:
    script_path: str = "train.py"
    args: str = ""
    log_file: str = "training.log"
    timeout: int = 1800


@dataclass
class _EvalArgs:
    script_path: str = "evaluate.py"
    args: str = ""
    log_file: str = "eval.log"
    timeout: int = 300


# ---------------------------------------------------------------------------
# Tool dispatch via TOOL_REGISTRY entries
# ---------------------------------------------------------------------------


class TestRegistryDispatch:
    def test_every_registered_name_maps_to_callable(self):
        for name, fn in TOOL_REGISTRY.items():
            assert callable(fn), f"tool {name!r} is not callable"

    def test_execute_edit_file(self, workspace):
        (workspace / "f.py").write_text("aaa")
        args = EditFileArgs(file_path="f.py", old_text="aaa", new_text="bbb")
        out = execute_tool("edit_file", args, {})
        assert "Edited" in out
        assert (workspace / "f.py").read_text() == "bbb"

    def test_execute_list_files(self, workspace):
        (workspace / "thing.py").write_text("ok")
        out = execute_tool("list_files", ListFilesArgs(), {})
        assert "thing.py" in out

    def test_execute_create_directory(self, workspace):
        out = execute_tool(
            "create_directory", CreateDirectoryArgs(dir_path="nested/sub"), {}
        )
        assert "Created" in out
        assert (workspace / "nested" / "sub").is_dir()

    def test_execute_download_url(self, workspace, monkeypatch):
        captured = {}

        def fake(url, dest_path):
            captured["url"] = url
            captured["dest_path"] = dest_path
            return "Downloaded 0.00 MB to f.bin"

        import mle_beast.tools.registry as reg
        monkeypatch.setattr(reg, "download_url", fake)

        @dataclass
        class _Args:
            url: str = "http://example.com/foo"
            dest_path: str = "f.bin"

        out = execute_tool("download_url", _Args(), {})
        assert "Downloaded" in out
        assert captured == {"url": "http://example.com/foo", "dest_path": "f.bin"}

    def test_execute_check_cuda(self):
        """check_cuda should run and return a string. We don't care what
        the host actually reports — only that the dispatcher path works.
        """

        @dataclass
        class _Empty:
            pass

        out = execute_tool("check_cuda", _Empty(), {})
        assert isinstance(out, str)

    def test_execute_get_workspace_metadata(self, workspace):
        @dataclass
        class _Empty:
            pass

        out = execute_tool("get_workspace_metadata", _Empty(), {})
        assert isinstance(out, str)

    def test_execute_mark_complete_records_summary(self):
        shared: dict = {}
        out = execute_tool(
            "mark_complete", MarkCompleteArgs(summary="done!"), shared
        )
        assert "MARK_COMPLETE" in out
        assert shared.get("last_mark_complete_summary") == "done!"

    def test_execute_unknown_returns_error_string(self):
        out = execute_tool("not_a_real_tool", WriteFileArgs(file_path="x", content=""), {})
        assert out.startswith("ERROR: Unknown tool")

    def test_execute_traps_tool_exception(self, monkeypatch):
        """An exception inside a tool implementation must surface as a
        string error to the LLM, not propagate.
        """

        def boom(args, shared):
            raise RuntimeError("explode")

        monkeypatch.setitem(TOOL_REGISTRY, "write_file", boom)
        out = execute_tool("write_file", WriteFileArgs(file_path="x", content=""), {})
        assert out.startswith("ERROR executing write_file")
        assert "explode" in out


# ---------------------------------------------------------------------------
# Settings-aware paths inside the tool wrappers (max_chars / timeouts)
# ---------------------------------------------------------------------------


class TestSettingsAwareWrappers:
    def test_run_shell_command_with_settings(self, workspace, monkeypatch):
        captured: dict = {}

        def fake(cmd, timeout, max_chars):
            captured.update(cmd=cmd, timeout=timeout, max_chars=max_chars)
            return "ok"

        import mle_beast.tools.registry as reg
        monkeypatch.setattr(reg, "run_shell_command", fake)

        settings = Settings(command_output_max_chars=9999)
        execute_tool("run_shell_command", _ShellArgs(timeout=7), {"settings": settings})
        assert captured["max_chars"] == 9999
        assert captured["timeout"] == 7

    def test_run_shell_command_without_settings_uses_default_max(self, monkeypatch):
        captured: dict = {}

        def fake(cmd, timeout, max_chars):
            captured.update(max_chars=max_chars)
            return "ok"

        import mle_beast.tools.registry as reg
        monkeypatch.setattr(reg, "run_shell_command", fake)

        execute_tool("run_shell_command", _ShellArgs(), {})
        assert captured["max_chars"] == 4000  # the default fallback

    def test_run_python_file_with_settings(self, monkeypatch):
        captured: dict = {}

        def fake(fp, args, timeout, max_chars):
            captured["max_chars"] = max_chars
            return "ok"

        import mle_beast.tools.registry as reg
        monkeypatch.setattr(reg, "run_python_file", fake)

        settings = Settings(command_output_max_chars=12345)
        execute_tool("run_python_file", _PythonArgs(), {"settings": settings})
        assert captured["max_chars"] == 12345

    def test_run_tests_with_settings(self, monkeypatch):
        captured: dict = {}

        def fake(*a, **kw):
            captured.update(kw)
            return "ok"

        import mle_beast.tools.registry as reg
        monkeypatch.setattr(reg, "run_tests", fake)

        settings = Settings(test_output_max_chars=222, test_error_max_chars=111)
        execute_tool("run_tests", _TestsArgs(), {"settings": settings})
        assert captured["test_output_max_chars"] == 222
        assert captured["test_error_max_chars"] == 111

    def test_run_tests_without_settings_uses_signature_default(self, monkeypatch):
        called_with: list = []

        def fake(*a, **kw):
            called_with.append((a, kw))
            return "ok"

        import mle_beast.tools.registry as reg
        monkeypatch.setattr(reg, "run_tests", fake)

        execute_tool("run_tests", _TestsArgs(), {})
        # No kwargs path: only positional args from the bare signature.
        assert called_with[0][1] == {}

    def test_run_single_test_dispatches(self, monkeypatch):
        called = []

        def fake(test_file, test_name, timeout):
            called.append((test_file, test_name, timeout))
            return "ok"

        import mle_beast.tools.registry as reg
        monkeypatch.setattr(reg, "run_single_test", fake)

        @dataclass
        class _Args:
            test_file: str = "tests/x.py"
            test_name: str = "test_thing"
            timeout: int = 30

        execute_tool("run_single_test", _Args(), {})
        assert called[0][0] == "tests/x.py"

    def test_launch_evaluate_dispatches(self, monkeypatch):
        captured: dict = {}

        def fake(script_path, args, log_file, timeout):
            captured.update(script=script_path, log=log_file)
            return "ok"

        import mle_beast.tools.registry as reg
        monkeypatch.setattr(reg, "launch_evaluate", fake)

        execute_tool("launch_evaluate", _EvalArgs(script_path="my_eval.py"), {})
        assert captured["script"] == "my_eval.py"

    def test_launch_training_drops_inf_baseline(self, monkeypatch):
        captured: dict = {}

        def fake(*a, **kw):
            captured.update(kw)
            return "ok"

        import mle_beast.tools.registry as reg
        monkeypatch.setattr(reg, "launch_training", fake)

        # baseline_score=inf must be sanitized to None so the threshold check
        # in launch_training doesn't fire spuriously.
        execute_tool("launch_training", _TrainArgs(), {"best_score": float("inf")})
        assert captured["baseline_score"] is None

    def test_launch_training_drops_nonpositive_baseline(self, monkeypatch):
        captured: dict = {}

        def fake(*a, **kw):
            captured.update(kw)
            return "ok"

        import mle_beast.tools.registry as reg
        monkeypatch.setattr(reg, "launch_training", fake)

        execute_tool("launch_training", _TrainArgs(), {"best_score": -0.5})
        assert captured["baseline_score"] is None

    def test_launch_training_preserves_real_baseline(self, monkeypatch):
        captured: dict = {}

        def fake(*a, **kw):
            captured.update(kw)
            return "ok"

        import mle_beast.tools.registry as reg
        monkeypatch.setattr(reg, "launch_training", fake)

        execute_tool("launch_training", _TrainArgs(), {"best_score": 0.85})
        assert captured["baseline_score"] == 0.85


# ---------------------------------------------------------------------------
# Timeout override behavior
# ---------------------------------------------------------------------------


class TestTimeoutOverride:
    def test_override_applies_when_args_holds_default(self):
        @dataclass
        class _A:
            timeout: int = 30

        a = _A()
        settings = Settings(shell_command_timeout=999)
        _apply_timeout_override("run_shell_command", a, {"settings": settings})
        assert a.timeout == 999

    def test_no_override_when_user_chose_explicit_timeout(self):
        @dataclass
        class _A:
            timeout: int = 5  # explicitly non-default

        a = _A()
        settings = Settings(shell_command_timeout=999)
        _apply_timeout_override("run_shell_command", a, {"settings": settings})
        assert a.timeout == 5  # preserved

    def test_no_settings_means_no_override(self):
        @dataclass
        class _A:
            timeout: int = 30

        a = _A()
        _apply_timeout_override("run_shell_command", a, {})
        assert a.timeout == 30

    def test_no_op_for_args_without_timeout(self):
        @dataclass
        class _A:
            file_path: str = "x"

        a = _A()
        _apply_timeout_override("write_file", a, {"settings": Settings()})
        # No timeout attr present — must not raise, must not add one.
        assert not hasattr(a, "timeout")

    def test_no_op_for_unknown_tool(self):
        @dataclass
        class _A:
            timeout: int = 30

        a = _A()
        _apply_timeout_override("not_in_defaults_table", a, {"settings": Settings()})
        assert a.timeout == 30

    def test_no_op_when_override_unset(self):
        """If a tool is in _TIMEOUT_TOOL_DEFAULTS but its settings field is
        zero/falsy, no override is applied.
        """

        @dataclass
        class _A:
            timeout: int = 1800  # the launch_training default

        a = _A()
        # Settings field exists but is the same as default — nothing to do.
        settings = Settings(training_timeout=1800)
        _apply_timeout_override("launch_training", a, {"settings": settings})
        assert a.timeout == 1800
