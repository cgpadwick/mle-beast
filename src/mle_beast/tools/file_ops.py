# Copyright 2026 Chris Padwick
# SPDX-License-Identifier: Apache-2.0

"""File operation tools: write, read, edit, list, create_directory, download.

All paths are relative to the workspace root.
Ported from ml_agents.shared_tools.
"""

from __future__ import annotations

import os
from pathlib import Path

from mle_beast.workspace import WorkspaceRegistry


def _resolve(file_path: str, read_only: bool = False) -> Path:
    """Resolve a path, checking it falls within allowed directories.

    For writes: must be inside the workspace AND the resolved physical target
        must also be inside the workspace (so a symlink workspace/x -> /etc
        can't be used to escape via write_file('x/passwd', ...)).
    For reads:  workspace (symlink-tolerant — the lexical path stays in the
        workspace, which is enough since reads only expose the linked content)
        OR any registered allowed-read directory.
    """
    base = os.path.abspath(str(WorkspaceRegistry.get_workspace()))
    if os.path.isabs(file_path):
        absolute = os.path.abspath(file_path)
    else:
        absolute = os.path.abspath(os.path.join(base, file_path))

    in_workspace_lexical = absolute.startswith(base + os.sep) or absolute == base

    if in_workspace_lexical:
        if read_only:
            return Path(absolute)
        # For writes, also check the resolved physical path (defeats symlink escape).
        base_real = os.path.realpath(base)
        absolute_real = os.path.realpath(absolute)
        if absolute_real == base_real or absolute_real.startswith(base_real + os.sep):
            return Path(absolute)
        raise ValueError(
            f"Write path traversal blocked: {file_path!r} resolves outside workspace"
        )

    # Outside workspace lexically — only allowed for reads against registered paths.
    if read_only:
        resolved = Path(absolute).resolve()
        for allowed in WorkspaceRegistry.get_allowed_read_paths():
            allowed_str = str(allowed)
            if str(resolved) == allowed_str or str(resolved).startswith(allowed_str + os.sep):
                return resolved

    raise ValueError(f"Path traversal blocked: {file_path!r}")


def write_file(file_path: str, content: str, description: str = "") -> str:
    full_path = _resolve(file_path)
    full_path.parent.mkdir(parents=True, exist_ok=True)
    full_path.write_text(content)
    lines = len(content.splitlines())
    chars = len(content)
    desc = f": {description}" if description else ""
    return f"Created {file_path}{desc} ({lines} lines, {chars} chars)"


MAX_READ_CHARS = 5_000


def read_file(file_path: str) -> str:
    full_path = _resolve(file_path, read_only=True)
    if not full_path.exists():
        return f"ERROR: File not found: {file_path}"
    try:
        content = full_path.read_text()
        if len(content) > MAX_READ_CHARS:
            return (
                content[:MAX_READ_CHARS]
                + f"\n\n... [TRUNCATED — file is {len(content):,} chars, "
                f"showing first {MAX_READ_CHARS:,}] ..."
            )
        return content
    except Exception as e:
        return f"ERROR reading file: {e}"


def edit_file(file_path: str, old_text: str, new_text: str) -> str:
    full_path = _resolve(file_path)
    if not full_path.exists():
        return f"ERROR: File not found: {file_path}. Use write_file to create new files."
    content = full_path.read_text()
    if old_text not in content:
        preview = content[:500] + "..." if len(content) > 500 else content
        return (
            f"ERROR: Could not find the specified text in {file_path}.\n"
            f"File preview:\n{preview}"
        )
    count = content.count(old_text)
    new_content = content.replace(old_text, new_text)
    full_path.write_text(new_content)
    return f"Edited {file_path}: replaced {count} occurrence(s)"


def list_files(directory: str = "", pattern: str = "*") -> str:
    base = WorkspaceRegistry.get_workspace()
    target_dir = base / directory if directory else base
    if not target_dir.exists():
        return f"ERROR: Directory not found: {directory}"
    items = []
    for item in sorted(target_dir.glob(pattern)):
        if item.is_dir():
            items.append(f"[DIR]  {item.relative_to(target_dir)}/")
        else:
            size = item.stat().st_size
            items.append(f"[FILE] {item.relative_to(target_dir)} ({size} bytes)")
    return "\n".join(items) if items else f"No files matching '{pattern}' in {directory or 'root'}"


def create_directory(dir_path: str) -> str:
    full_path = _resolve(dir_path)
    full_path.mkdir(parents=True, exist_ok=True)
    return f"Created directory: {dir_path}"


def download_url(url: str, dest_path: str) -> str:
    base = WorkspaceRegistry.get_workspace().absolute()
    out = base / dest_path
    out.parent.mkdir(parents=True, exist_ok=True)
    try:
        import urllib.request
        total = 0
        with urllib.request.urlopen(url, timeout=60) as resp:  # nosec B310
            with open(out, "wb") as f:
                while True:
                    chunk = resp.read(8192)
                    if not chunk:
                        break
                    f.write(chunk)
                    total += len(chunk)
        mb = total / (1024 * 1024)
        return f"Downloaded {mb:.2f} MB to {out.relative_to(base)}"
    except Exception as e:
        return f"ERROR downloading from {url}: {e}"
