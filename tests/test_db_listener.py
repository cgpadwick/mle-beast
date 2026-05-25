# Copyright 2026 Chris Padwick
# SPDX-License-Identifier: Apache-2.0

"""Tests for db_listener's stage persistence — specifically that a critic
retry is recorded as 'retrying' (not a terminal 'fail') and carries the
critic's feedback so the dashboard can show *why*."""

from __future__ import annotations

import json

import pytest

from mle_beast.db import Database
from mle_beast.db_listener import make_db_listener
from mle_beast.events import RetryOccurred, RunStateChanged


@pytest.fixture
def db(tmp_path):
    return Database(tmp_path / "test.db")


def _seed_run(db, run_id="r-1"):
    db.insert_run({
        "id": run_id, "status": "running", "workspace": "/tmp/ws",
        "task": "t", "target_accuracy": None, "dataset_path": None,
        "mode": "greenfield", "force_cpu": 0, "setup_workspace": 0,
        "created_at": 0.0,
    })
    db.upsert_stage(run_id, "data_analysis_critic", status="active")
    return run_id


def _stage(db, run_id, name):
    return next(s for s in db.get_stages(run_id) if s["stage_name"] == name)


def test_retry_marks_stage_retrying_with_feedback(db):
    rid = _seed_run(db)
    listener = make_db_listener(rid, db)

    listener(RetryOccurred(
        run_id=rid, stage="data_analysis_critic",
        attempt=2, max_attempts=3,
        feedback="data_analysis.md was not written to the workspace root.",
    ))

    s = _stage(db, rid, "data_analysis_critic")
    assert s["status"] == "retrying"          # not "fail"
    assert s["attempt"] == 2 and s["max_attempts"] == 3
    assert json.loads(s["verdict_json"])["feedback"].startswith("data_analysis.md")


def test_run_end_sweep_clears_lingering_retrying(db):
    """A run that terminates mid-retry shouldn't leave a stage stuck on
    'retrying' — the sweep resolves it like it does 'active'."""
    rid = _seed_run(db)
    listener = make_db_listener(rid, db)
    listener(RetryOccurred(
        run_id=rid, stage="data_analysis_critic",
        attempt=2, max_attempts=3, feedback="redo it",
    ))
    listener(RunStateChanged(run_id=rid, old_state="running", new_state="failed"))

    assert _stage(db, rid, "data_analysis_critic")["status"] == "fail"
