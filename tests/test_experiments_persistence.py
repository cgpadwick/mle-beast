# Copyright 2026 Chris Padwick
# SPDX-License-Identifier: Apache-2.0

"""Unit tests for experiment persistence (db + RunManager)."""

from __future__ import annotations

import pytest

from mle_beast.db import Database


@pytest.fixture
def db(monkeypatch, tmp_path):
    """Fresh DB in a temp file."""
    p = tmp_path / "test.db"
    monkeypatch.setenv("MLE_BEAST_DB_PATH", str(p))
    return Database(p)


def _seed_run(db, run_id="r1") -> str:
    """Insert a minimal run row so foreign-key references work."""
    db.insert_run({
        "id": run_id, "status": "running",
        "workspace": "/tmp/x", "task": "t",
        "target_accuracy": None, "dataset_path": None,
        "mode": "greenfield", "force_cpu": 0, "setup_workspace": 0,
        "created_at": 0.0,
    })
    return run_id


def test_record_experiment_persists_full_row(db):
    rid = _seed_run(db)
    db.record_experiment(
        run_id=rid, step=0, parent_step=None,
        proposal="Baseline", score=0.65,
        lower_is_better=False, kept=True,
        tag="MODEL", commit_sha="abc123",
    )
    rows = db.list_experiments(rid)
    assert len(rows) == 1
    r = rows[0]
    assert r["step"] == 0
    assert r["parent_step"] is None
    assert r["proposal"] == "Baseline"
    assert r["score"] == 0.65
    assert r["lower_is_better"] == 0
    assert r["kept"] == 1
    assert r["tag"] == "MODEL"
    assert r["commit_sha"] == "abc123"
    assert r["created_at"] > 0


def test_record_experiment_idempotent_on_run_step(db):
    """Re-recording the same (run_id, step) overwrites instead of duplicating."""
    rid = _seed_run(db)
    db.record_experiment(rid, step=1, parent_step=0, proposal="A", score=0.7,
                          lower_is_better=False, kept=True)
    db.record_experiment(rid, step=1, parent_step=0, proposal="A revised", score=0.8,
                          lower_is_better=False, kept=True)
    rows = db.list_experiments(rid)
    assert len(rows) == 1
    assert rows[0]["proposal"] == "A revised"
    assert rows[0]["score"] == 0.8


def test_inf_score_persisted_as_null(db):
    """+/-inf and NaN come from the no-score sentinels — store as NULL so the
    dashboard can treat them as 'unparsed' rather than rendering an inf."""
    rid = _seed_run(db)
    db.record_experiment(rid, step=0, parent_step=None, proposal="b",
                          score=float("inf"), lower_is_better=True, kept=True)
    db.record_experiment(rid, step=1, parent_step=0, proposal="x",
                          score=float("-inf"), lower_is_better=False, kept=False)
    rows = db.list_experiments(rid)
    assert rows[0]["score"] is None
    assert rows[1]["score"] is None


def test_list_experiments_ordered_by_step(db):
    rid = _seed_run(db)
    for s in (3, 0, 2, 1):
        db.record_experiment(rid, step=s, parent_step=None if s == 0 else s - 1,
                              proposal=f"step {s}", score=float(s),
                              lower_is_better=False, kept=True)
    rows = db.list_experiments(rid)
    assert [r["step"] for r in rows] == [0, 1, 2, 3]


def test_list_experiments_isolated_by_run(db):
    _seed_run(db, "rA")
    _seed_run(db, "rB")
    db.record_experiment("rA", step=0, parent_step=None, proposal="a", score=0.5,
                          lower_is_better=False, kept=True)
    db.record_experiment("rB", step=0, parent_step=None, proposal="b", score=0.6,
                          lower_is_better=False, kept=True)
    assert len(db.list_experiments("rA")) == 1
    assert len(db.list_experiments("rB")) == 1


def test_delete_run_cascades_to_experiments(db):
    rid = _seed_run(db)
    db.record_experiment(rid, step=0, parent_step=None, proposal="b", score=0.5,
                          lower_is_better=False, kept=True)
    db.delete_run(rid)
    assert db.list_experiments(rid) == []


def test_reset_database_drops_experiments(db):
    rid = _seed_run(db)
    db.record_experiment(rid, step=0, parent_step=None, proposal="b", score=0.5,
                          lower_is_better=False, kept=True)
    db.reset_database()
    assert db.list_experiments(rid) == []
