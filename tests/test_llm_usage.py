# Copyright 2026 Chris Padwick
# SPDX-License-Identifier: Apache-2.0

"""Unit tests for LLM usage extraction + per-run aggregation."""

from __future__ import annotations

from unittest.mock import MagicMock

from mle_beast.db import Database
from mle_beast.llm import extract_usage


def _completion_with_usage(**fields):
    """Build a mock OpenAI completion object with a usage namespace."""
    usage = MagicMock(spec=[])
    for k, v in fields.items():
        setattr(usage, k, v)
    completion = MagicMock(spec=[])
    completion.usage = usage
    return completion


def test_extract_usage_full_openrouter():
    """OpenRouter response: tokens + cost + reasoning + cached."""
    ctd = MagicMock(spec=[])
    ctd.reasoning_tokens = 250
    ptd = MagicMock(spec=[])
    ptd.cached_tokens = 100
    completion = _completion_with_usage(
        prompt_tokens=2000,
        completion_tokens=300,
        cost=0.0042,
        completion_tokens_details=ctd,
        prompt_tokens_details=ptd,
    )
    out = extract_usage(completion)
    assert out == {
        "prompt_tokens": 2000,
        "completion_tokens": 300,
        "cost_usd": 0.0042,
        "reasoning_tokens": 250,
        "cached_tokens": 100,
    }


def test_extract_usage_openai_no_cost():
    """OpenAI direct doesn't return cost — should still return tokens."""
    completion = _completion_with_usage(
        prompt_tokens=500, completion_tokens=50,
    )
    out = extract_usage(completion)
    assert out == {"prompt_tokens": 500, "completion_tokens": 50}
    assert "cost_usd" not in out


def test_extract_usage_no_usage_attribute():
    """Defensive: completion with no usage at all → empty dict, no crash."""
    completion = MagicMock(spec=[])
    completion.usage = None
    assert extract_usage(completion) == {}


def test_extract_usage_none_input():
    """Pure defensive — None input must not raise."""
    assert extract_usage(None) == {}


def test_add_run_usage_increments(tmp_path):
    """add_run_usage should sum across calls atomically."""
    db = Database(tmp_path / "test.db")
    run_id = "r1"
    db.insert_run({
        "id": run_id, "status": "running", "workspace": "/tmp",
        "task": "t", "target_accuracy": None, "dataset_path": None,
        "mode": "existing", "force_cpu": 0, "setup_workspace": 0,
        "created_at": 0,
    })
    # 3 calls of varying sizes
    db.add_run_usage(run_id, cost_usd=0.01, prompt_tokens=100, completion_tokens=20)
    db.add_run_usage(run_id, cost_usd=0.02, prompt_tokens=200, completion_tokens=30,
                     reasoning_tokens=15)
    db.add_run_usage(run_id, cost_usd=0.005, prompt_tokens=50, completion_tokens=10)

    row = db.get_run(run_id)
    assert row["total_llm_calls"] == 3
    assert abs(row["total_cost_usd"] - 0.035) < 1e-9
    assert row["total_prompt_tokens"] == 350
    assert row["total_completion_tokens"] == 60
    assert row["total_reasoning_tokens"] == 15


def test_add_run_usage_silent_on_missing_run(tmp_path):
    """Adding usage to a nonexistent run should not crash."""
    db = Database(tmp_path / "test.db")
    db.add_run_usage("nonexistent", cost_usd=1.0, prompt_tokens=100)
    # No exception is the assertion.


def test_add_run_usage_handles_none_inputs(tmp_path):
    """Caller may pass None when a field is unreported."""
    db = Database(tmp_path / "test.db")
    db.insert_run({
        "id": "r2", "status": "running", "workspace": "", "task": "",
        "target_accuracy": None, "dataset_path": None, "mode": "existing",
        "force_cpu": 0, "setup_workspace": 0, "created_at": 0,
    })
    # All optional. Real callers pass ints/floats but defensive code
    # in db.py coerces None → 0.
    db.add_run_usage("r2")  # all defaults
    row = db.get_run("r2")
    assert row["total_llm_calls"] == 1
    assert row["total_cost_usd"] == 0.0
