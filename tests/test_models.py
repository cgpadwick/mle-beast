# Copyright 2026 Chris Padwick
# SPDX-License-Identifier: Apache-2.0

"""Unit tests for Pydantic models."""

import pytest
from pydantic import ValidationError

from mle_beast.models.tool_calls import (
    CodingToolCall,
    ExistingCodeToolCall,
    TrainingToolCall,
)
from mle_beast.models.verdicts import (
    AnalysisVerdict,
    TestVerdict,
)


# ---- tool_calls ----

class TestCodingToolCall:
    def test_write_file_discriminator(self):
        tc = CodingToolCall.model_validate({
            "call": {
                "tool": "write_file",
                "args": {"file_path": "test.py", "content": "print('hi')"},
            }
        })
        assert tc.call.tool == "write_file"
        assert tc.call.args.file_path == "test.py"

    def test_mark_complete(self):
        tc = CodingToolCall.model_validate({
            "call": {
                "tool": "mark_complete",
                "args": {"summary": "Done"},
            }
        })
        assert tc.call.tool == "mark_complete"

    def test_invalid_tool_rejected(self):
        with pytest.raises(ValidationError):
            CodingToolCall.model_validate({
                "call": {
                    "tool": "nonexistent_tool",
                    "args": {},
                }
            })

    def test_get_or_create_model_version_rejected(self):
        """The version-tool was deleted; CodingToolCall must reject it."""
        with pytest.raises(ValidationError):
            CodingToolCall.model_validate({
                "call": {
                    "tool": "get_or_create_model_version",
                    "args": {},
                }
            })


class TestExistingCodeToolCall:
    """ExistingCodeToolCall is now an alias for CodingToolCall — same schema."""

    def test_edit_file_discriminator(self):
        tc = ExistingCodeToolCall.model_validate({
            "call": {
                "tool": "edit_file",
                "args": {
                    "file_path": "model.py",
                    "old_text": "x = 1",
                    "new_text": "x = 2",
                },
            }
        })
        assert tc.call.tool == "edit_file"
        assert tc.call.args.file_path == "model.py"

    def test_write_file_allowed(self):
        tc = ExistingCodeToolCall.model_validate({
            "call": {
                "tool": "write_file",
                "args": {"file_path": "utils.py", "content": "# utils"},
            }
        })
        assert tc.call.tool == "write_file"

    def test_mark_complete(self):
        tc = ExistingCodeToolCall.model_validate({
            "call": {
                "tool": "mark_complete",
                "args": {"summary": "Improved model"},
            }
        })
        assert tc.call.tool == "mark_complete"

    def test_flat_format(self):
        tc = ExistingCodeToolCall.model_validate({
            "tool": "read_file",
            "args": {"file_path": "model.py"},
        })
        assert tc.call.tool == "read_file"
        assert tc.call.args.file_path == "model.py"

    def test_invalid_tool_rejected(self):
        with pytest.raises(ValidationError):
            ExistingCodeToolCall.model_validate({
                "call": {
                    "tool": "nonexistent_tool",
                    "args": {},
                }
            })


class TestTrainingToolCall:
    def test_launch_training(self):
        tc = TrainingToolCall.model_validate({
            "call": {
                "tool": "launch_training",
                "args": {"script_path": "train.py"},
            }
        })
        assert tc.call.tool == "launch_training"

    def test_check_cuda(self):
        tc = TrainingToolCall.model_validate({
            "call": {
                "tool": "check_cuda",
                "args": {},
            }
        })
        assert tc.call.tool == "check_cuda"


# ---- verdicts ----

class TestVerdicts:
    def test_test_verdict(self):
        v = TestVerdict(passed=True, feedback="All good")
        assert v.passed

    def test_analysis_verdict(self):
        v = AnalysisVerdict(
            met_target=True, best_accuracy=0.95,
            recommended_action="accept",
        )
        assert v.met_target
