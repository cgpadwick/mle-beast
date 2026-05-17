# Copyright 2026 Chris Padwick
# SPDX-License-Identifier: Apache-2.0

"""Unit tests for RunManager's experiment surface — list_experiments and
get_peak_score. Both are pure read-paths over the experiments table.
"""

from __future__ import annotations

import pytest

from mle_beast.db import Database
from mle_beast.run_manager import RunManager


@pytest.fixture
def fresh_db(monkeypatch, tmp_path):
    """Use a temp DB so tests don't see each other's rows."""
    p = tmp_path / "test.db"
    monkeypatch.setenv("MLE_BEAST_DB_PATH", str(p))
    # Rebuild the singleton to pick up the new path.
    import mle_beast.db as db_mod
    db_mod._global_db = None
    return p


@pytest.fixture
def manager(fresh_db):
    return RunManager()


def _seed(manager: RunManager, run_id="r1") -> str:
    manager._db.insert_run({
        "id": run_id, "status": "running",
        "workspace": "/tmp/x", "task": "t",
        "target_accuracy": None, "dataset_path": None,
        "mode": "greenfield", "force_cpu": 0, "setup_workspace": 0,
        "created_at": 0.0,
    })
    return run_id


def test_list_experiments_returns_db_rows(manager):
    rid = _seed(manager)
    manager._db.record_experiment(rid, step=0, parent_step=None, proposal="b",
                                    score=0.5, lower_is_better=False, kept=True)
    rows = manager.list_experiments(rid)
    assert len(rows) == 1
    assert rows[0]["step"] == 0


def test_peak_score_higher_is_better(manager):
    rid = _seed(manager)
    manager._db.record_experiment(rid, step=0, parent_step=None, proposal="b",
                                    score=0.6, lower_is_better=False, kept=True)
    manager._db.record_experiment(rid, step=1, parent_step=0, proposal="x",
                                    score=0.8, lower_is_better=False, kept=True)
    manager._db.record_experiment(rid, step=2, parent_step=1, proposal="y",
                                    score=0.9, lower_is_better=False, kept=False)
    peak = manager.get_peak_score(rid)
    assert peak["score"] == 0.8  # 0.9 was reverted, doesn't count
    assert peak["step"] == 1
    assert peak["lower_is_better"] is False
    assert peak["kept_count"] == 2
    assert peak["reverted_count"] == 1


def test_peak_score_lower_is_better(manager):
    rid = _seed(manager)
    manager._db.record_experiment(rid, step=0, parent_step=None, proposal="b",
                                    score=0.6, lower_is_better=True, kept=True)
    manager._db.record_experiment(rid, step=1, parent_step=0, proposal="x",
                                    score=0.4, lower_is_better=True, kept=True)
    peak = manager.get_peak_score(rid)
    assert peak["score"] == 0.4
    assert peak["step"] == 1
    assert peak["lower_is_better"] is True


def test_peak_score_none_when_no_kept_with_score(manager):
    """All experiments either reverted or score=NULL → peak is None."""
    rid = _seed(manager)
    # Reverted (kept=False)
    manager._db.record_experiment(rid, step=0, parent_step=None, proposal="b",
                                    score=0.5, lower_is_better=False, kept=False)
    # Kept but score parsing failed (None after sentinel-strip)
    manager._db.record_experiment(rid, step=1, parent_step=0, proposal="x",
                                    score=float("inf"), lower_is_better=False, kept=True)
    assert manager.get_peak_score(rid) is None


def test_peak_score_none_for_empty_run(manager):
    rid = _seed(manager)
    assert manager.get_peak_score(rid) is None
