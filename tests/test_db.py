# Copyright 2026 Chris Padwick
# SPDX-License-Identifier: Apache-2.0

"""Direct tests for the Database wrapper in mle_beast.db.

Each test gets a fresh SQLite file in a tmp_path so the global singleton
and the user's real ~/.mle-beast database are untouched.
"""

from __future__ import annotations

import time

import pytest

from mle_beast import db as db_mod
from mle_beast.db import Database, _default_db_path, get_database


@pytest.fixture
def db(tmp_path):
    """A fresh Database instance backed by a file in tmp_path."""
    return Database(tmp_path / "test.db")


def _make_run_row(**overrides) -> dict:
    """Build the minimum-required row dict for insert_run."""
    base = {
        "id": "r-1",
        "status": "pending",
        "workspace": "/tmp/ws",
        "task": "do a thing",
        "target_accuracy": 0.85,
        "dataset_path": "/data",
        "mode": "greenfield",
        "force_cpu": 0,
        "setup_workspace": 0,
        "created_at": time.time(),
    }
    base.update(overrides)
    return base


# ---------------------------------------------------------------------------
# Construction / schema / migrations
# ---------------------------------------------------------------------------


class TestConstruction:
    def test_creates_parent_dir(self, tmp_path):
        target = tmp_path / "deeply" / "nested" / "db.sqlite"
        Database(target)
        assert target.exists()
        assert target.parent.is_dir()

    def test_default_path_uses_env_override(self, tmp_path, monkeypatch):
        target = tmp_path / "overridden.sqlite"
        monkeypatch.setenv("MLE_BEAST_DB_PATH", str(target))
        assert _default_db_path() == target

    def test_default_path_falls_back_to_home(self, monkeypatch):
        monkeypatch.delenv("MLE_BEAST_DB_PATH", raising=False)
        p = _default_db_path()
        assert p.name == "mle_beast.db"
        # We don't assert the exact home — just that it's not the test env override.
        assert "overridden" not in str(p)

    def test_ensure_column_is_idempotent(self, db):
        # Re-running init schema should not blow up on the now-existing columns.
        db._ensure_column("runs", "experiment_branch", "TEXT")
        db._ensure_column("runs", "experiment_branch", "TEXT")  # second call is a no-op


# ---------------------------------------------------------------------------
# Runs CRUD
# ---------------------------------------------------------------------------


class TestRuns:
    def test_insert_and_get(self, db):
        db.insert_run(_make_run_row())
        row = db.get_run("r-1")
        assert row is not None
        assert row["task"] == "do a thing"
        assert row["target_accuracy"] == 0.85

    def test_get_missing_returns_none(self, db):
        assert db.get_run("nope") is None

    def test_insert_accepts_optional_fields_default_null(self, db):
        # Older callers may not pass lower_is_better / metric_name / environment.
        db.insert_run(_make_run_row())
        row = db.get_run("r-1")
        assert row["lower_is_better"] is None
        assert row["metric_name"] is None
        assert row["environment"] is None

    def test_insert_persists_environment(self, db):
        db.insert_run(_make_run_row(environment="/path/to/my/venv"))
        assert db.get_run("r-1")["environment"] == "/path/to/my/venv"

    def test_update_run_writes_fields(self, db):
        db.insert_run(_make_run_row())
        db.update_run("r-1", status="running", started_at=123.0)
        row = db.get_run("r-1")
        assert row["status"] == "running"
        assert row["started_at"] == 123.0

    def test_update_run_with_no_fields_is_noop(self, db):
        db.insert_run(_make_run_row())
        db.update_run("r-1")  # must not raise
        assert db.get_run("r-1")["status"] == "pending"

    def test_list_runs_orders_by_created_at_desc(self, db):
        now = time.time()
        db.insert_run(_make_run_row(id="old", created_at=now - 100))
        db.insert_run(_make_run_row(id="new", created_at=now))
        ids = [r["id"] for r in db.list_runs()]
        assert ids[0] == "new"
        assert ids[1] == "old"

    def test_list_runs_filters_by_status(self, db):
        db.insert_run(_make_run_row(id="a", status="completed"))
        db.insert_run(_make_run_row(id="b", status="failed"))
        ids = {r["id"] for r in db.list_runs(status="completed")}
        assert ids == {"a"}

    def test_list_runs_respects_limit(self, db):
        for i in range(5):
            db.insert_run(_make_run_row(id=f"r-{i}", created_at=float(i)))
        assert len(db.list_runs(limit=2)) == 2

    def test_add_run_usage_accumulates(self, db):
        db.insert_run(_make_run_row())
        db.add_run_usage("r-1", cost_usd=0.10, prompt_tokens=100, completion_tokens=20)
        db.add_run_usage("r-1", cost_usd=0.05, prompt_tokens=50, reasoning_tokens=10)
        row = db.get_run("r-1")
        assert row["total_cost_usd"] == pytest.approx(0.15)
        assert row["total_prompt_tokens"] == 150
        assert row["total_completion_tokens"] == 20
        assert row["total_reasoning_tokens"] == 10
        assert row["total_llm_calls"] == 2

    def test_add_run_usage_silent_for_unknown_run(self, db):
        # No exception, no row created — the update just affects 0 rows.
        db.add_run_usage("does-not-exist", cost_usd=1.0)
        assert db.get_run("does-not-exist") is None


# ---------------------------------------------------------------------------
# Stages
# ---------------------------------------------------------------------------


class TestStages:
    def test_upsert_insert_then_update(self, db):
        db.insert_run(_make_run_row())
        db.upsert_stage("r-1", "coding", status="active", attempt=1)
        stages = db.get_stages("r-1")
        assert len(stages) == 1
        assert stages[0]["status"] == "active"

        db.upsert_stage("r-1", "coding", status="pass", attempt=2)
        stages = db.get_stages("r-1")
        assert stages[0]["status"] == "pass"
        assert stages[0]["attempt"] == 2

    def test_upsert_existing_with_no_fields_is_noop(self, db):
        db.insert_run(_make_run_row())
        db.upsert_stage("r-1", "coding", status="active")
        db.upsert_stage("r-1", "coding")  # update with no fields
        assert db.get_stages("r-1")[0]["status"] == "active"

    def test_deactivate_other_stages_flips_orphaned_actives(self, db):
        db.insert_run(_make_run_row())
        db.upsert_stage("r-1", "data_analysis", status="active")
        db.upsert_stage("r-1", "baseline", status="active")
        db.deactivate_other_stages("r-1", active_stage="baseline")
        rows = {s["stage_name"]: s["status"] for s in db.get_stages("r-1")}
        assert rows["data_analysis"] == "pass"
        assert rows["baseline"] == "active"


# ---------------------------------------------------------------------------
# Events
# ---------------------------------------------------------------------------


class TestEvents:
    def test_insert_and_list(self, db):
        db.insert_run(_make_run_row())
        db.insert_event("r-1", 1.0, "stage_started", "coding", '{"x":1}')
        db.insert_event("r-1", 2.0, "log_message", None, '{"msg":"hi"}')
        events = db.get_events("r-1")
        assert [e["event_type"] for e in events] == ["stage_started", "log_message"]

    def test_get_events_filters_by_since(self, db):
        db.insert_run(_make_run_row())
        db.insert_event("r-1", 1.0, "a", None, "{}")
        db.insert_event("r-1", 5.0, "b", None, "{}")
        events = db.get_events("r-1", since=2.0)
        assert [e["event_type"] for e in events] == ["b"]


# ---------------------------------------------------------------------------
# Experiments
# ---------------------------------------------------------------------------


class TestExperiments:
    def test_record_and_list(self, db):
        db.insert_run(_make_run_row())
        db.record_experiment(
            "r-1", step=0, parent_step=None, proposal="baseline",
            score=0.5, lower_is_better=False, kept=True,
        )
        db.record_experiment(
            "r-1", step=1, parent_step=0, proposal="tweak",
            score=0.6, lower_is_better=False, kept=True,
        )
        rows = db.list_experiments("r-1")
        assert [r["step"] for r in rows] == [0, 1]
        assert rows[1]["parent_step"] == 0

    def test_record_idempotent_on_step(self, db):
        db.insert_run(_make_run_row())
        db.record_experiment(
            "r-1", step=0, parent_step=None, proposal="v1",
            score=0.5, lower_is_better=False, kept=True,
        )
        # Same step, different score — should overwrite, not insert.
        db.record_experiment(
            "r-1", step=0, parent_step=None, proposal="v1-corrected",
            score=0.55, lower_is_better=False, kept=True,
        )
        rows = db.list_experiments("r-1")
        assert len(rows) == 1
        assert rows[0]["proposal"] == "v1-corrected"
        assert rows[0]["score"] == 0.55

    @pytest.mark.parametrize("bad_score", [
        float("inf"), float("-inf"), float("nan"),
    ])
    def test_inf_and_nan_scores_persist_as_null(self, db, bad_score):
        db.insert_run(_make_run_row())
        db.record_experiment(
            "r-1", step=0, parent_step=None, proposal="x",
            score=bad_score, lower_is_better=False, kept=False,
        )
        assert db.list_experiments("r-1")[0]["score"] is None

    def test_explicit_none_score_persists_as_null(self, db):
        db.insert_run(_make_run_row())
        db.record_experiment(
            "r-1", step=0, parent_step=None, proposal="x",
            score=None, lower_is_better=False, kept=False,
        )
        assert db.list_experiments("r-1")[0]["score"] is None

    def test_uses_passed_timestamp_when_provided(self, db):
        db.insert_run(_make_run_row())
        db.record_experiment(
            "r-1", step=0, parent_step=None, proposal="x",
            score=0.5, lower_is_better=False, kept=True,
            created_at=42.0,
        )
        assert db.list_experiments("r-1")[0]["created_at"] == 42.0


# ---------------------------------------------------------------------------
# Settings table
# ---------------------------------------------------------------------------


class TestSettingsTable:
    def test_default_row_exists_after_init(self, db):
        row = db.get_settings()
        assert row is not None
        assert row["log_level"] == "INFO"
        assert "id" not in row  # id is stripped

    def test_update_partial(self, db):
        db.update_settings({"log_level": "DEBUG"})
        assert db.get_settings()["log_level"] == "DEBUG"

    def test_update_with_empty_dict_is_noop(self, db):
        before = db.get_settings()
        db.update_settings({})
        assert db.get_settings() == before


# ---------------------------------------------------------------------------
# Admin / cleanup
# ---------------------------------------------------------------------------


class TestAdmin:
    def test_delete_run_cascades(self, db):
        db.insert_run(_make_run_row())
        db.upsert_stage("r-1", "coding", status="active")
        db.insert_event("r-1", 1.0, "stage_started", "coding", "{}")
        db.record_experiment(
            "r-1", 0, None, "x", 0.5, False, True,
        )

        db.delete_run("r-1")
        assert db.get_run("r-1") is None
        assert db.get_stages("r-1") == []
        assert db.get_events("r-1") == []
        assert db.list_experiments("r-1") == []

    def test_delete_runs_older_than_returns_count(self, db):
        now = time.time()
        db.insert_run(_make_run_row(id="old", created_at=now - 86400 * 60))
        db.insert_run(_make_run_row(id="new", created_at=now))
        deleted = db.delete_runs_older_than(days=30)
        assert deleted == 1
        assert db.get_run("old") is None
        assert db.get_run("new") is not None

    def test_delete_runs_older_than_no_matches(self, db):
        db.insert_run(_make_run_row())
        assert db.delete_runs_older_than(days=365) == 0

    def test_reset_database_clears_runs_but_keeps_settings_table(self, db):
        db.insert_run(_make_run_row())
        db.update_settings({"log_level": "DEBUG"})
        db.reset_database()
        assert db.list_runs() == []
        assert db.get_settings()["log_level"] == "DEBUG"

    def test_get_stats_returns_counts_and_size(self, db, tmp_path):
        db.insert_run(_make_run_row())
        db.upsert_stage("r-1", "coding", status="active")
        db.insert_event("r-1", 1.0, "stage_started", "coding", "{}")
        stats = db.get_stats()
        assert stats["runs_count"] == 1
        assert stats["stages_count"] == 1
        assert stats["events_count"] == 1
        assert stats["runs_by_status"] == {"pending": 1}
        assert stats["db_size_bytes"] > 0

    def test_get_stats_db_size_zero_when_file_missing(self, tmp_path, monkeypatch):
        """If the file got removed underneath us, get_stats reports 0 — must
        not raise.
        """
        db = Database(tmp_path / "ephemeral.db")
        db._db_path.unlink()  # yank the file
        stats = db.get_stats()
        assert stats["db_size_bytes"] == 0


# ---------------------------------------------------------------------------
# Connection management + singleton
# ---------------------------------------------------------------------------


class TestConnection:
    def test_close_clears_conn(self, db):
        db._get_conn()  # populate thread-local
        db.close()
        assert getattr(db._local, "conn", None) is None

    def test_close_when_never_opened_is_safe(self, tmp_path):
        db = Database(tmp_path / "x.db")
        # The _init_schema call already opened a connection; closing twice
        # should still be safe.
        db.close()
        db.close()


class TestSingleton:
    def test_get_database_returns_same_instance(self, monkeypatch, tmp_path):
        # Use a tmp path so the singleton doesn't poison ~/.mle-beast.
        monkeypatch.setenv("MLE_BEAST_DB_PATH", str(tmp_path / "single.db"))
        monkeypatch.setattr(db_mod, "_global_db", None)
        a = get_database()
        b = get_database()
        assert a is b
