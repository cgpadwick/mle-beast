# Copyright 2026 Chris Padwick
# SPDX-License-Identifier: Apache-2.0

"""Discriminated-union ToolCall models per agent role.

Each role has its own union listing only the tools it can use.
This eliminates tool hallucination.
"""

from __future__ import annotations

from typing import Annotated, Literal, Union

from pydantic import BaseModel, Field, model_validator


# ============================================================================
# Tool argument models — shared across roles
# ============================================================================

class WriteFileArgs(BaseModel):
    file_path: str = Field(description="Relative path from workspace root")
    content: str = Field(description="Content to write")
    description: str = Field(default="", description="What this file does")


class ReadFileArgs(BaseModel):
    file_path: str = Field(description="Relative path from workspace root")


class EditFileArgs(BaseModel):
    file_path: str = Field(description="Relative path from workspace root")
    old_text: str = Field(description="Exact text to find")
    new_text: str = Field(description="Replacement text")


class ListFilesArgs(BaseModel):
    directory: str = Field(default="", description="Subdirectory to list")
    pattern: str = Field(default="*", description="Glob pattern")


class CreateDirectoryArgs(BaseModel):
    dir_path: str = Field(description="Relative path for directory")


class DownloadUrlArgs(BaseModel):
    url: str = Field(description="Source URL")
    dest_path: str = Field(description="Destination path relative to workspace")


class RunShellCommandArgs(BaseModel):
    command: str = Field(description="Shell command to execute")
    timeout: int = Field(default=30, description="Timeout in seconds")


class RunPythonFileArgs(BaseModel):
    file_path: str = Field(description="Python file to run")
    args: str = Field(default="", description="CLI arguments")
    timeout: int = Field(default=30, description="Timeout in seconds")


class RunTestsArgs(BaseModel):
    test_file: str = Field(default="", description="Specific test file, or empty for all")
    verbose: bool = Field(default=True)
    timeout: int = Field(default=60)


class RunSingleTestArgs(BaseModel):
    test_file: str = Field(description="Test file path")
    test_name: str = Field(description="Specific test function")
    timeout: int = Field(default=30)


class LaunchTrainingArgs(BaseModel):
    script_path: str = Field(description="Training script path")
    args: str = Field(default="", description="CLI arguments")
    log_file: str = Field(default="logs/training.log")
    timeout: int = Field(
        default=1800,
        description="Training timeout in seconds (default 30 min). Override "
        "only for genuinely long runs; if a small dataset hits this, it's a "
        "runaway iteration (e.g., huge GridSearchCV) that should be fixed.",
    )


class LaunchEvaluateArgs(BaseModel):
    script_path: str = Field(default="evaluate.py", description="Evaluation script path")
    args: str = Field(default="", description="CLI arguments")
    log_file: str = Field(default="logs/eval.log")
    timeout: int = Field(default=300, description="Eval typically much faster than training")


class CheckCudaArgs(BaseModel):
    pass


class GetWorkspaceMetadataArgs(BaseModel):
    pass


class MarkCompleteArgs(BaseModel):
    summary: str = Field(description="Brief summary of what was accomplished")


# ============================================================================
# Coding tool call variants
# ============================================================================

class WriteFileCall(BaseModel):
    tool: Literal["write_file"] = "write_file"
    args: WriteFileArgs

class ReadFileCall(BaseModel):
    tool: Literal["read_file"] = "read_file"
    args: ReadFileArgs

class EditFileCall(BaseModel):
    tool: Literal["edit_file"] = "edit_file"
    args: EditFileArgs

class ListFilesCall(BaseModel):
    tool: Literal["list_files"] = "list_files"
    args: ListFilesArgs

class CreateDirectoryCall(BaseModel):
    tool: Literal["create_directory"] = "create_directory"
    args: CreateDirectoryArgs

class DownloadUrlCall(BaseModel):
    tool: Literal["download_url"] = "download_url"
    args: DownloadUrlArgs

class RunShellCommandCall(BaseModel):
    tool: Literal["run_shell_command"] = "run_shell_command"
    args: RunShellCommandArgs

class RunPythonFileCall(BaseModel):
    tool: Literal["run_python_file"] = "run_python_file"
    args: RunPythonFileArgs

class RunTestsCall(BaseModel):
    tool: Literal["run_tests"] = "run_tests"
    args: RunTestsArgs

class RunSingleTestCall(BaseModel):
    tool: Literal["run_single_test"] = "run_single_test"
    args: RunSingleTestArgs

class GetWorkspaceMetadataCall(BaseModel):
    tool: Literal["get_workspace_metadata"] = "get_workspace_metadata"
    args: GetWorkspaceMetadataArgs

class MarkCompleteCall(BaseModel):
    tool: Literal["mark_complete"] = "mark_complete"
    args: MarkCompleteArgs


# ============================================================================
# Training-only tool call variants
# ============================================================================

class LaunchTrainingCall(BaseModel):
    tool: Literal["launch_training"] = "launch_training"
    args: LaunchTrainingArgs

class LaunchEvaluateCall(BaseModel):
    tool: Literal["launch_evaluate"] = "launch_evaluate"
    args: LaunchEvaluateArgs

class CheckCudaCall(BaseModel):
    tool: Literal["check_cuda"] = "check_cuda"
    args: CheckCudaArgs


# ============================================================================
# Discriminated unions per role
# ============================================================================

CodingToolCallUnion = Annotated[
    Union[
        WriteFileCall,
        ReadFileCall,
        EditFileCall,
        ListFilesCall,
        CreateDirectoryCall,
        DownloadUrlCall,
        RunShellCommandCall,
        RunPythonFileCall,
        RunTestsCall,
        RunSingleTestCall,
        GetWorkspaceMetadataCall,
        MarkCompleteCall,
    ],
    Field(discriminator="tool"),
]


class CodingToolCall(BaseModel):
    """Wrapper for coding agent tool calls."""
    call: CodingToolCallUnion

    @model_validator(mode="before")
    @classmethod
    def accept_flat_format(cls, data):
        """Accept both {"call": {...}} and flat {"tool": ..., "args": ...}."""
        if isinstance(data, dict) and "tool" in data and "call" not in data:
            return {"call": data}
        return data


# Backwards-compat alias — pre-cleanup the existing-code mode had a separate
# union excluding get_or_create_model_version. After deleting that tool the
# unions are identical, so ExistingCodeToolCall is just a name for CodingToolCall.
ExistingCodeToolCall = CodingToolCall


TrainingToolCallUnion = Annotated[
    Union[
        ReadFileCall,
        WriteFileCall,
        EditFileCall,
        ListFilesCall,
        RunPythonFileCall,
        LaunchTrainingCall,
        CheckCudaCall,
        MarkCompleteCall,
    ],
    Field(discriminator="tool"),
]


class TrainingToolCall(BaseModel):
    """Wrapper for training agent tool calls."""
    call: TrainingToolCallUnion

    @model_validator(mode="before")
    @classmethod
    def accept_flat_format(cls, data):
        """Accept both {"call": {...}} and flat {"tool": ..., "args": ...}."""
        if isinstance(data, dict) and "tool" in data and "call" not in data:
            return {"call": data}
        return data


# ============================================================================
# Evaluation actor — runs evaluate.py against a saved checkpoint
# ============================================================================

EvaluateToolCallUnion = Annotated[
    Union[
        ReadFileCall,
        WriteFileCall,
        EditFileCall,
        ListFilesCall,
        RunPythonFileCall,
        LaunchEvaluateCall,
        CheckCudaCall,
        MarkCompleteCall,
    ],
    Field(discriminator="tool"),
]


class EvaluateToolCall(BaseModel):
    """Wrapper for evaluation agent tool calls."""
    call: EvaluateToolCallUnion

    @model_validator(mode="before")
    @classmethod
    def accept_flat_format(cls, data):
        if isinstance(data, dict) and "tool" in data and "call" not in data:
            return {"call": data}
        return data


# ============================================================================
# Finder actor — locates produced artifacts (checkpoints, logs, results) on
# disk after a Training or Evaluation run. Read-only by design: it should
# discover where files are, not modify or recreate them.
# ============================================================================

FinderToolCallUnion = Annotated[
    Union[
        ReadFileCall,
        ListFilesCall,
        RunPythonFileCall,    # only for inspection helpers, e.g. `python --help`
        RunShellCommandCall,  # for `find`, `ls -la`, `head`, etc.
        MarkCompleteCall,
    ],
    Field(discriminator="tool"),
]


class FinderToolCall(BaseModel):
    """Wrapper for finder agent tool calls."""
    call: FinderToolCallUnion

    @model_validator(mode="before")
    @classmethod
    def accept_flat_format(cls, data):
        if isinstance(data, dict) and "tool" in data and "call" not in data:
            return {"call": data}
        return data


# ============================================================================
# Benchmark-specific discriminated unions
# ============================================================================

CompUnderstandingToolCallUnion = Annotated[
    Union[
        ReadFileCall,
        WriteFileCall,
        ListFilesCall,
        RunPythonFileCall,
        RunShellCommandCall,
        GetWorkspaceMetadataCall,
        MarkCompleteCall,
    ],
    Field(discriminator="tool"),
]


class CompUnderstandingToolCall(BaseModel):
    """Wrapper for competition understanding agent tool calls."""
    call: CompUnderstandingToolCallUnion

    @model_validator(mode="before")
    @classmethod
    def accept_flat_format(cls, data):
        """Accept both {"call": {...}} and flat {"tool": ..., "args": ...}."""
        if isinstance(data, dict) and "tool" in data and "call" not in data:
            return {"call": data}
        return data


DataAnalysisToolCallUnion = Annotated[
    Union[
        ReadFileCall,
        WriteFileCall,
        ListFilesCall,
        RunPythonFileCall,
        RunShellCommandCall,
        GetWorkspaceMetadataCall,
        MarkCompleteCall,
    ],
    Field(discriminator="tool"),
]


class DataAnalysisToolCall(BaseModel):
    """Wrapper for data analysis agent tool calls."""
    call: DataAnalysisToolCallUnion

    @model_validator(mode="before")
    @classmethod
    def accept_flat_format(cls, data):
        """Accept both {"call": {...}} and flat {"tool": ..., "args": ...}."""
        if isinstance(data, dict) and "tool" in data and "call" not in data:
            return {"call": data}
        return data


ProposalToolCallUnion = Annotated[
    Union[
        ReadFileCall,
        ListFilesCall,
        RunShellCommandCall,
        GetWorkspaceMetadataCall,
        MarkCompleteCall,
    ],
    Field(discriminator="tool"),
]


class ProposalToolCall(BaseModel):
    """Wrapper for hill-climbing proposal agent tool calls (read-only + mark_complete)."""
    call: ProposalToolCallUnion

    @model_validator(mode="before")
    @classmethod
    def accept_flat_format(cls, data):
        """Accept both {"call": {...}} and flat {"tool": ..., "args": ...}."""
        if isinstance(data, dict) and "tool" in data and "call" not in data:
            return {"call": data}
        return data
