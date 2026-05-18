# Copyright 2026 Chris Padwick
# SPDX-License-Identifier: Apache-2.0

"""Unit tests for tool implementations."""

import pytest
from pathlib import Path

from mle_beast.tools.file_ops import (
    create_directory,
    download_url,
    edit_file,
    list_files,
    read_file,
    write_file,
)
from mle_beast.tools.registry import execute_tool
from mle_beast.workspace import WorkspaceRegistry
from mle_beast.models.tool_calls import (
    WriteFileArgs,
    ReadFileArgs,
    MarkCompleteArgs,
)


class TestWriteFile:
    def test_write_and_read(self, workspace):
        result = write_file("hello.txt", "Hello, world!")
        assert "Created hello.txt" in result
        assert (workspace / "hello.txt").read_text() == "Hello, world!"

    def test_write_creates_parents(self, workspace):
        result = write_file("sub/dir/file.py", "x = 1")
        assert "Created sub/dir/file.py" in result
        assert (workspace / "sub" / "dir" / "file.py").exists()


class TestReadFile:
    def test_read_existing(self, workspace):
        (workspace / "test.txt").write_text("content")
        result = read_file("test.txt")
        assert result == "content"

    def test_read_missing(self, workspace):
        result = read_file("nonexistent.txt")
        assert "ERROR" in result


class TestReadFileExtra:
    def test_truncates_large_files(self, workspace):
        """Reads over MAX_READ_CHARS get a truncation suffix."""
        from mle_beast.tools.file_ops import MAX_READ_CHARS
        big = "x" * (MAX_READ_CHARS + 1000)
        (workspace / "big.txt").write_text(big)
        result = read_file("big.txt")
        assert "TRUNCATED" in result
        assert f"first {MAX_READ_CHARS:,}" in result

    def test_handles_read_exception(self, workspace, monkeypatch):
        """If reading raises, we surface a string ERROR (not an exception)."""
        (workspace / "ok.txt").write_text("ok")

        def boom(*a, **kw):
            raise PermissionError("simulated")

        monkeypatch.setattr(Path, "read_text", boom)
        result = read_file("ok.txt")
        assert "ERROR reading file" in result


class TestEditFile:
    def test_edit_replaces_text(self, workspace):
        (workspace / "edit_me.py").write_text("old_value = 1")
        result = edit_file("edit_me.py", "old_value", "new_value")
        assert "Edited" in result
        assert "new_value" in (workspace / "edit_me.py").read_text()

    def test_edit_missing_text(self, workspace):
        (workspace / "edit_me.py").write_text("x = 1")
        result = edit_file("edit_me.py", "NONEXISTENT", "replacement")
        assert "ERROR" in result

    def test_edit_missing_file(self, workspace):
        result = edit_file("missing.py", "a", "b")
        assert "ERROR" in result

    def test_edit_missing_text_long_file_preview_truncates(self, workspace):
        (workspace / "long.txt").write_text("a" * 800)
        result = edit_file("long.txt", "NOT_THERE", "x")
        assert "ERROR" in result
        # Preview should be capped at ~500 + "..." suffix.
        assert "..." in result


class TestPathResolution:
    """_resolve guards against path traversal and respects allowed-read paths."""

    def test_write_outside_workspace_blocked(self, workspace, tmp_path):
        outside = tmp_path / "elsewhere" / "evil.txt"
        with pytest.raises(ValueError, match="Path traversal"):
            write_file(str(outside), "nope")

    def test_read_outside_workspace_blocked_without_allowlist(self, workspace, tmp_path):
        outside = tmp_path / "secrets.txt"
        outside.write_text("nope")
        with pytest.raises(ValueError, match="Path traversal"):
            read_file(str(outside))

    def test_read_outside_workspace_allowed_with_explicit_path(self, workspace, tmp_path):
        outside_dir = tmp_path / "data"
        outside_dir.mkdir()
        outside_file = outside_dir / "ok.txt"
        outside_file.write_text("permitted")
        WorkspaceRegistry.add_allowed_read_path(outside_dir)
        result = read_file(str(outside_file))
        assert result == "permitted"

    def test_write_via_symlink_escape_blocked(self, workspace, tmp_path):
        """A symlink pointing outside the workspace must not let writes escape.

        Reads via the same symlink are allowed (they only expose the linked
        content, no privilege escalation); writes go through the realpath check.
        """
        outside = tmp_path / "outside"
        outside.mkdir()
        (workspace / "linked").symlink_to(outside)
        with pytest.raises(ValueError, match="path traversal"):
            write_file("linked/evil.txt", "should-be-blocked")


class TestListFiles:
    def test_list_root(self, workspace):
        (workspace / "file1.py").write_text("a")
        (workspace / "file2.py").write_text("b")
        result = list_files()
        assert "file1.py" in result
        assert "file2.py" in result

    def test_list_with_pattern(self, workspace):
        (workspace / "a.py").write_text("a")
        (workspace / "b.txt").write_text("b")
        result = list_files("", "*.py")
        assert "a.py" in result
        assert "b.txt" not in result

    def test_list_missing_directory(self, workspace):
        result = list_files("does/not/exist")
        assert "ERROR" in result and "not found" in result

    def test_list_includes_subdir_entries_and_files(self, workspace):
        (workspace / "sub").mkdir()
        (workspace / "leaf.py").write_text("x")
        result = list_files()
        assert "[DIR]" in result and "sub/" in result
        assert "[FILE]" in result and "leaf.py" in result

    def test_list_no_matches_returns_helpful_message(self, workspace):
        result = list_files("", "*.nothing")
        assert "No files matching" in result


class TestDownloadUrl:
    def test_writes_file_and_reports_size(self, workspace, monkeypatch):
        """download_url chunks into the destination and reports MB transferred.

        We monkeypatch urllib.request.urlopen so the test doesn't make a real
        network call.
        """
        from io import BytesIO

        payload = b"x" * (8192 * 3 + 100)  # exercise the chunk loop

        class _FakeResp:
            def __init__(self, data: bytes):
                self._buf = BytesIO(data)

            def read(self, n: int) -> bytes:
                return self._buf.read(n)

            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

        def fake_urlopen(url, timeout=60):
            return _FakeResp(payload)

        import urllib.request
        monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)

        result = download_url("http://example.com/foo.bin", "downloaded.bin")
        assert "Downloaded" in result and "MB" in result
        assert (workspace / "downloaded.bin").read_bytes() == payload

    def test_reports_error_on_failure(self, workspace, monkeypatch):
        import urllib.request

        def boom(url, timeout=60):
            raise OSError("network unreachable")

        monkeypatch.setattr(urllib.request, "urlopen", boom)
        result = download_url("http://example.com/foo.bin", "f.bin")
        assert "ERROR downloading" in result


class TestCreateDirectory:
    def test_create(self, workspace):
        result = create_directory("new/nested/dir")
        assert "Created" in result
        assert (workspace / "new" / "nested" / "dir").is_dir()


class TestToolRegistry:
    def test_execute_write_file(self, workspace):
        args = WriteFileArgs(file_path="reg_test.txt", content="registry test")
        result = execute_tool("write_file", args, {})
        assert "Created reg_test.txt" in result
        assert (workspace / "reg_test.txt").read_text() == "registry test"

    def test_execute_read_file(self, workspace):
        (workspace / "read_me.txt").write_text("hello")
        args = ReadFileArgs(file_path="read_me.txt")
        result = execute_tool("read_file", args, {})
        assert result == "hello"

    def test_execute_mark_complete(self, workspace):
        args = MarkCompleteArgs(summary="All done")
        result = execute_tool("mark_complete", args, {})
        assert "MARK_COMPLETE" in result
        assert "All done" in result

    def test_execute_unknown_tool(self, workspace):
        result = execute_tool("nonexistent", None, {})
        assert "ERROR" in result


class TestParseEpochScore:
    """Test the _parse_epoch_score function for training log parsing."""

    def test_parse_val_score_equals(self):
        from mle_beast.tools.execution import _parse_epoch_score

        line = "Epoch 1: train_loss=0.5, val_loss=0.3, val_score=0.7934"
        assert _parse_epoch_score(line) == pytest.approx(0.7934)

    def test_parse_val_score_colon(self):
        from mle_beast.tools.execution import _parse_epoch_score

        line = "Epoch 1/100 - train_loss: 4.0648 - val_loss: 1.7038 - val_score: 0.6449"
        assert _parse_epoch_score(line) == pytest.approx(0.6449)

    def test_parse_val_acc(self):
        from mle_beast.tools.execution import _parse_epoch_score

        line = "[efficientnet] Epoch 0: train_loss=2.6040, val_loss=1.8422, val_acc=0.4772"
        assert _parse_epoch_score(line) == pytest.approx(0.4772)

    def test_parse_val_score_with_parens(self):
        from mle_beast.tools.execution import _parse_epoch_score

        line = "Epoch 1 - efficientnet_v2_l: Train Loss=4.9508, Val Loss=4.9365, Val Score=0.0072"
        assert _parse_epoch_score(line) == pytest.approx(0.0072)

    def test_parse_val_score_acc_annotation(self):
        from mle_beast.tools.execution import _parse_epoch_score

        line = "Epoch 1: train_loss=4.8022, val_loss=4.7841, val_score (acc): 0.0094"
        assert _parse_epoch_score(line) == pytest.approx(0.0094)

    def test_no_score_returns_none(self):
        from mle_beast.tools.execution import _parse_epoch_score

        line = "Starting training..."
        assert _parse_epoch_score(line) is None

    def test_cuda_warning_returns_none(self):
        from mle_beast.tools.execution import _parse_epoch_score

        line = "Found GPU0 NVIDIA GB10 which is of cuda capability 12.1."
        assert _parse_epoch_score(line) is None


class TestLaunchTrainingBaseline:
    """Test baseline monitoring in launch_training."""

    def test_launch_training_passes_baseline_from_shared(self, workspace):
        """Test that _tool_launch_training extracts baseline from shared."""
        from mle_beast.tools.registry import _tool_launch_training
        from mle_beast.models.tool_calls import LaunchTrainingArgs

        # Create a simple script that prints an epoch with low score
        script_content = '''
import sys
print("Epoch 1: val_score=0.01")
sys.exit(0)
'''
        (workspace / "test_train.py").write_text(script_content)

        args = LaunchTrainingArgs(
            script_path="test_train.py",
            log_file="logs/test.log",
            timeout=30,
        )

        # With a high baseline, the low score should trigger termination
        shared = {"best_score": 0.80}
        result = _tool_launch_training(args, shared)

        # Should detect baseline violation (0.01 < 0.80 * 0.1 = 0.08)
        assert "ERROR" in result or "baseline" in result.lower()

    def test_launch_training_no_baseline_runs_normally(self, workspace):
        """Test that training runs normally without baseline."""
        from mle_beast.tools.registry import _tool_launch_training
        from mle_beast.models.tool_calls import LaunchTrainingArgs

        script_content = '''
print("Epoch 1: val_score=0.01")
print("Training complete")
'''
        (workspace / "test_train.py").write_text(script_content)

        args = LaunchTrainingArgs(
            script_path="test_train.py",
            log_file="logs/test.log",
            timeout=30,
        )

        # No baseline - should complete normally
        shared = {}
        result = _tool_launch_training(args, shared)

        assert "Training completed" in result or "exit code: 0" in result

    def test_launch_training_ignores_inf_baseline(self, workspace):
        """Test that inf baseline is ignored."""
        from mle_beast.tools.registry import _tool_launch_training
        from mle_beast.models.tool_calls import LaunchTrainingArgs

        script_content = '''
print("Epoch 1: val_score=0.01")
'''
        (workspace / "test_train.py").write_text(script_content)

        args = LaunchTrainingArgs(
            script_path="test_train.py",
            log_file="logs/test.log",
            timeout=30,
        )

        # inf baseline should be ignored
        shared = {"best_score": float("inf")}
        result = _tool_launch_training(args, shared)

        # Should complete normally (inf baseline ignored)
        assert "Training completed" in result or "exit code: 0" in result
