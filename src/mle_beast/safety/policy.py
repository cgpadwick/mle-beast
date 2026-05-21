# Copyright 2026 Chris Padwick
# SPDX-License-Identifier: Apache-2.0

"""Load + enforce the static safety policy.

The policy file (`safety/policy.json`) is loaded once at module import.
Two public entry points:

  - `check_shell_command(cmd: str) -> SafetyDecision`
  - `check_python_file_text(text: str) -> SafetyDecision`

Both return a SafetyDecision with `allow: bool` and a reason. Callers
turn a non-allow into a tool-error string (e.g.
`"ERROR: blocked by safety policy: <reason>"`) so the agent's recovery
loop can see and react to it — the run continues.

Workspace path containment is enforced separately by inspecting
absolute and tilde-paths in the command. The workspace itself is
discovered dynamically via `WorkspaceRegistry.get_workspace()` so each
run automatically gets its own allowed scope without editing the
policy file.

Design notes:
  - Token check uses word boundaries (`\\bsudo\\b`) to avoid false
    positives on names that contain "sudo" as a substring.
  - Pattern check uses re.IGNORECASE because shells are case-insensitive
    on the relevant verbs (rm, etc.) on most platforms.
  - Path-containment only fires when the command shape looks
    destructive (rm/mv/cp/chmod/chown/tee/redirect). Read-only
    commands like `cat /etc/foo` are NOT blocked — the agent
    legitimately needs to inspect system files sometimes.
"""

from __future__ import annotations

import json
import os
import re
import time
from dataclasses import dataclass
from importlib import resources
from pathlib import Path
from typing import Optional

# --------------------------------------------------------------------
# Public types
# --------------------------------------------------------------------

@dataclass(frozen=True)
class SafetyDecision:
    allow: bool
    reason: str = ""
    rule: str = ""    # token name, pattern, or "path-containment"

    def __bool__(self) -> bool:  # convenience: `if check_...():` reads as allow
        return self.allow

    def as_error(self) -> str:
        """Format for direct return as a tool-error string."""
        return f"ERROR: blocked by safety policy: {self.reason}"


_ALLOW = SafetyDecision(allow=True)


# --------------------------------------------------------------------
# Policy loading
# --------------------------------------------------------------------

@dataclass(frozen=True)
class _CompiledPolicy:
    blocked_tokens: tuple[re.Pattern, ...]      # word-boundary regexes
    token_names: tuple[str, ...]                # display name per index
    blocked_patterns: tuple[re.Pattern, ...]
    pattern_sources: tuple[str, ...]            # display name per index
    allow_paths_outside_workspace: tuple[Path, ...]


_CACHED_POLICY: Optional[_CompiledPolicy] = None


def get_policy() -> _CompiledPolicy:
    """Return the compiled policy, loading from JSON on first access."""
    global _CACHED_POLICY
    if _CACHED_POLICY is None:
        _CACHED_POLICY = _load_policy()
    return _CACHED_POLICY


def _load_policy() -> _CompiledPolicy:
    raw = json.loads(_read_policy_text())
    tokens = tuple(raw.get("blocked_tokens", []))
    token_regexes = tuple(
        re.compile(rf"\b{re.escape(t)}\b", re.IGNORECASE) for t in tokens
    )
    pattern_strs = tuple(raw.get("blocked_patterns", []))
    pattern_regexes = tuple(re.compile(p, re.IGNORECASE) for p in pattern_strs)
    allow_paths_raw = raw.get("allow_paths_outside_workspace", [])
    allow_paths = tuple(
        Path(os.path.expanduser(p)).resolve() for p in allow_paths_raw
    )
    return _CompiledPolicy(
        blocked_tokens=token_regexes,
        token_names=tokens,
        blocked_patterns=pattern_regexes,
        pattern_sources=pattern_strs,
        allow_paths_outside_workspace=allow_paths,
    )


def _read_policy_text() -> str:
    """Read policy.json from the package. Single source of truth — no
    per-user / per-project overrides (deliberate simplification)."""
    return (resources.files("mle_beast.safety") / "policy.json").read_text(
        encoding="utf-8",
    )


# --------------------------------------------------------------------
# Path extraction + containment
# --------------------------------------------------------------------

# Tokens that, when present in a command, signal a destructive operation.
# Word-boundary anchored. Caught case-insensitively. Plus shell redirect
# tokens detected separately because they're not whitespace-delimited
# words (`>file`, `2>/path`, etc.).
_DESTRUCTIVE_VERBS = re.compile(
    r"\b(rm|rmdir|mv|chmod|chown|tee|truncate|shred|cp\s+[^\s]+\s+[^\s]+)\b",
    re.IGNORECASE,
)
_REDIRECT_TO_ABS_PATH = re.compile(r"(?:^|\s)\d?>+\s*([/~])")

# Path-shaped tokens to inspect for containment. Captures absolute paths
# (`/foo/bar`), tilde-paths (`~/foo`), and any token containing `..`
# which might be a workspace-escape via relative traversal.
_PATH_TOKEN = re.compile(r"(?<![\w/])([/~][^\s'\";|&]+|\.\.[^\s'\";|&]*)")


def _command_looks_destructive(cmd: str) -> bool:
    if _DESTRUCTIVE_VERBS.search(cmd):
        return True
    if _REDIRECT_TO_ABS_PATH.search(cmd):
        return True
    return False


def _extract_candidate_paths(cmd: str) -> list[str]:
    """Pull path-shaped substrings out of a command line.

    Heuristic, not a real shell parser — adversarial inputs could
    sneak past (`$(echo /etc)`), but we're catching the confused-LLM
    case here, not a hostile one."""
    raw = _PATH_TOKEN.findall(cmd)
    # Also pull redirect targets like `>/etc/foo`.
    raw += re.findall(r"\d?>+\s*([/~][^\s'\";|&]+)", cmd)
    # Strip wrapping quotes if any leaked through.
    return [p.strip("'\"") for p in raw if p]


def _resolve_for_check(path_str: str, workspace: Optional[Path]) -> Path:
    """Expand ~, resolve `..` against the workspace, and normalize."""
    if path_str.startswith("~"):
        return Path(os.path.expanduser(path_str)).resolve(strict=False)
    if path_str.startswith(".."):
        base = workspace if workspace else Path.cwd()
        return (base / path_str).resolve(strict=False)
    return Path(path_str).resolve(strict=False)


def _is_under(child: Path, parent: Path) -> bool:
    """True if `child` is `parent` or any descendant. Path.is_relative_to
    requires 3.9+; we're 3.10+ minimum so it's fine."""
    try:
        return child.is_relative_to(parent)
    except ValueError:
        return False


# --------------------------------------------------------------------
# Public checks
# --------------------------------------------------------------------

def check_shell_command(command: str, workspace: Optional[Path] = None) -> SafetyDecision:
    """Pre-execution check for a shell command string.

    `workspace` is the path that's always allowed (any destructive op
    inside it is fine). When None, falls back to
    `WorkspaceRegistry.get_workspace()` if it's set, otherwise skips
    the path-containment check (no frame of reference).
    """
    policy = get_policy()

    # 1. Blocked tokens (sudo, su, doas, pkexec).
    for token_re, name in zip(policy.blocked_tokens, policy.token_names, strict=True):
        if token_re.search(command):
            return SafetyDecision(
                allow=False,
                reason=f"command uses `{name}` (privilege escalation is not allowed)",
                rule=f"token:{name}",
            )

    # 2. Blocked regex patterns (rm /, mkfs, dd if=of=/dev, etc.).
    for pat_re, src in zip(policy.blocked_patterns, policy.pattern_sources, strict=True):
        if pat_re.search(command):
            return SafetyDecision(
                allow=False,
                reason=f"command matches a blocked pattern: {src!r}",
                rule=f"pattern:{src}",
            )

    # 3. Workspace path containment (only when the command shape looks
    #    destructive — we don't want to block `cat /etc/lsb-release`).
    if _command_looks_destructive(command):
        if workspace is None:
            try:
                from mle_beast.workspace import WorkspaceRegistry
                ws = WorkspaceRegistry.get_workspace()
                workspace = Path(ws).resolve() if ws else None
            except Exception:
                workspace = None

        # If we have a workspace frame, enforce containment. If we
        # don't, skip — early-setup code may legitimately run before
        # the workspace is registered.
        if workspace is not None:
            for path_str in _extract_candidate_paths(command):
                resolved = _resolve_for_check(path_str, workspace)
                if _is_under(resolved, workspace):
                    continue
                if any(
                    _is_under(resolved, allowed)
                    for allowed in policy.allow_paths_outside_workspace
                ):
                    continue
                return SafetyDecision(
                    allow=False,
                    reason=(
                        f"destructive command targets path outside workspace: "
                        f"{resolved}"
                    ),
                    rule="path-containment",
                )

    return _ALLOW


def check_python_file_text(text: str) -> SafetyDecision:
    """Lint a Python source-file's TEXT for the same blocked tokens
    that we apply to shell commands. Catches the obvious case of an
    agent writing `os.system("sudo …")` inside a script it's about
    to run.

    NOT a real Python AST analyzer — just a fast string scan. The agent
    isn't an adversary; this is a guard against the model accidentally
    proposing a sudo-using setup script."""
    policy = get_policy()

    for token_re, name in zip(policy.blocked_tokens, policy.token_names, strict=True):
        if token_re.search(text):
            return SafetyDecision(
                allow=False,
                reason=f"python file references `{name}` (privilege escalation is not allowed)",
                rule=f"token:{name}",
            )
    return _ALLOW


# --------------------------------------------------------------------
# Audit log
# --------------------------------------------------------------------

def log_block(
    command_or_file: str,
    decision: SafetyDecision,
    *,
    kind: str,
    workspace: Optional[Path] = None,
) -> None:
    """Append a one-line block record to `<workspace>/logs/safety.log`.

    No-op when workspace isn't set (pre-setup pipeline state). Best-
    effort — IO errors are swallowed because logging a safety block
    must never itself surface a new error to the agent loop.
    """
    if workspace is None:
        try:
            from mle_beast.workspace import WorkspaceRegistry
            ws = WorkspaceRegistry.get_workspace()
            workspace = Path(ws).resolve() if ws else None
        except Exception:
            workspace = None
    if workspace is None:
        return
    try:
        log_dir = workspace / "logs"
        log_dir.mkdir(parents=True, exist_ok=True)
        log_path = log_dir / "safety.log"
        ts = time.strftime("%Y-%m-%dT%H:%M:%S")
        preview = command_or_file.replace("\n", " ")[:200]
        rule = decision.rule or "-"
        with log_path.open("a", encoding="utf-8") as fh:
            fh.write(f"{ts}\t{kind}\t{rule}\t{preview}\n")
    except Exception:
        pass
