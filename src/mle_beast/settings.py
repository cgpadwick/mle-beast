# Copyright 2026 Chris Padwick
# SPDX-License-Identifier: Apache-2.0

"""Global settings with SQLite persistence.

Settings are stored in a single-row ``settings`` table (id=1).
The ``get_settings()`` singleton loads once; ``reload_settings()`` forces a
fresh read (e.g. after the web UI saves).
"""

from __future__ import annotations

import threading
from dataclasses import dataclass, fields


@dataclass
class Settings:
    """All configurable pipeline parameters with their defaults."""

    model_provider: str = ""  # "openai", "openrouter", "local", or "" (auto-detect)
    model_name: str = ""
    max_tokens: int = 65536
    max_tool_iterations: int = 30
    max_tool_iterations_training: int = 15
    max_code_review_retries: int = 10
    max_training_analysis_retries: int = 5
    llm_call_retries: int = 3
    training_timeout: int = 1800
    test_timeout: int = 60
    shell_command_timeout: int = 30
    python_file_timeout: int = 30
    command_output_max_chars: int = 4000
    test_output_max_chars: int = 2000
    test_error_max_chars: int = 1000
    testing_llm_context_truncation: int = 3000
    review_file_truncation: int = 3000
    analysis_log_truncation: int = 5000
    log_level: str = "INFO"

    def to_dict(self) -> dict:
        return {f.name: getattr(self, f.name) for f in fields(self)}

    @classmethod
    def from_dict(cls, data: dict) -> Settings:
        valid = {f.name for f in fields(cls)}
        return cls(**{k: v for k, v in data.items() if k in valid})


# ── persistence helpers ────────────────────────────────────────────

def load_settings(db) -> Settings:
    """Read the single settings row from the database."""
    row = db.get_settings()
    if row is None:
        return Settings()
    return Settings.from_dict(row)


def save_settings(db, settings: Settings) -> None:
    """Write all settings fields to the database."""
    db.update_settings(settings.to_dict())


# ── thread-safe singleton ─────────────────────────────────────────

_settings: Settings | None = None
_settings_lock = threading.Lock()


def get_settings() -> Settings:
    """Return the cached global Settings (loads from DB on first call)."""
    global _settings
    if _settings is None:
        with _settings_lock:
            if _settings is None:
                from mle_beast.db import get_database
                _settings = load_settings(get_database())
    return _settings


def reload_settings() -> Settings:
    """Force a fresh load from the database and return it."""
    global _settings
    with _settings_lock:
        from mle_beast.db import get_database
        _settings = load_settings(get_database())
    return _settings
