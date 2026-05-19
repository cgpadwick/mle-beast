# Copyright 2026 Chris Padwick
# SPDX-License-Identifier: Apache-2.0

"""SQLite persistence for run history, stages, and events.

Database lives at ~/.mle-beast/mle_beast.db (overridable via MLE_BEAST_DB_PATH).
Uses WAL mode for concurrent read (web server) + write (pipeline thread).
"""

from __future__ import annotations

import os
import sqlite3
import threading
from pathlib import Path
from typing import Any, Optional


def _default_db_path() -> Path:
    override = os.environ.get("MLE_BEAST_DB_PATH")
    if override:
        return Path(override)
    return Path.home() / ".mle-beast" / "mle_beast.db"


class Database:
    """Thread-safe SQLite wrapper with connection-per-thread."""

    def __init__(self, db_path: Optional[Path] = None) -> None:
        self._db_path = db_path or _default_db_path()
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._local = threading.local()
        self._init_schema()

    def _get_conn(self) -> sqlite3.Connection:
        if not hasattr(self._local, "conn") or self._local.conn is None:
            conn = sqlite3.connect(str(self._db_path), timeout=30)
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA foreign_keys=ON")
            conn.row_factory = sqlite3.Row
            self._local.conn = conn
        return self._local.conn

    def _init_schema(self) -> None:
        conn = self._get_conn()
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS runs (
                id TEXT PRIMARY KEY,
                status TEXT NOT NULL DEFAULT 'pending',
                workspace TEXT,
                task TEXT,
                target_accuracy REAL,
                dataset_path TEXT,
                mode TEXT DEFAULT 'greenfield',
                -- GPU by default; runtime auto-detects via nvidia-smi.
                -- 1 = explicit override to force CPU (CI, broken CUDA).
                force_cpu INTEGER DEFAULT 0,
                setup_workspace INTEGER DEFAULT 0,
                -- Metric direction. NULL = auto-detect via the LLM extractor
                -- + keyword heuristic. 1 = lower-is-better (loss/RMSE/etc),
                -- 0 = higher-is-better (accuracy/F1/AUC/etc). When set, the
                -- pipeline trusts it unconditionally and skips inference.
                lower_is_better INTEGER DEFAULT NULL,
                -- Free-text metric name like "accuracy", "f1_macro", "rmse".
                -- When set, fed authoritatively to the val-score extractor
                -- so it picks the right field out of the training log
                -- regardless of which metric the agent's train.py emphasizes.
                metric_name TEXT DEFAULT NULL,
                created_at REAL,
                started_at REAL,
                completed_at REAL,
                verdict_json TEXT,
                error_message TEXT,
                experiment_branch TEXT,
                -- LLM usage rollups, populated incrementally on every
                -- emit_llm_call_event(completion=...) call. Lets the
                -- dashboard show running totals without scanning events.
                total_cost_usd REAL DEFAULT 0,
                total_prompt_tokens INTEGER DEFAULT 0,
                total_completion_tokens INTEGER DEFAULT 0,
                total_reasoning_tokens INTEGER DEFAULT 0,
                total_llm_calls INTEGER DEFAULT 0
            );

            CREATE TABLE IF NOT EXISTS stages (
                run_id TEXT NOT NULL,
                stage_name TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'pending',
                attempt INTEGER DEFAULT 0,
                max_attempts INTEGER DEFAULT 3,
                started_at REAL,
                completed_at REAL,
                verdict_json TEXT,
                PRIMARY KEY (run_id, stage_name),
                FOREIGN KEY (run_id) REFERENCES runs(id)
            );

            CREATE TABLE IF NOT EXISTS events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                run_id TEXT NOT NULL,
                timestamp REAL NOT NULL,
                event_type TEXT NOT NULL,
                stage TEXT,
                data_json TEXT,
                FOREIGN KEY (run_id) REFERENCES runs(id)
            );

            CREATE INDEX IF NOT EXISTS idx_events_run_ts
                ON events(run_id, timestamp);
            CREATE INDEX IF NOT EXISTS idx_stages_run
                ON stages(run_id);
            CREATE INDEX IF NOT EXISTS idx_runs_status
                ON runs(status);

            -- Hill-climb experiments. One row per BaselineEval (step=0) and
            -- per HillClimbEval iteration (step>=1). The dashboard reads
            -- these rows to draw the experiment tree and score trajectory.
            CREATE TABLE IF NOT EXISTS experiments (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                run_id TEXT NOT NULL,
                step INTEGER NOT NULL,
                parent_step INTEGER,
                proposal TEXT,
                score REAL,
                lower_is_better INTEGER DEFAULT 0,
                kept INTEGER NOT NULL,
                tag TEXT,
                commit_sha TEXT,
                created_at REAL NOT NULL,
                FOREIGN KEY (run_id) REFERENCES runs(id) ON DELETE CASCADE,
                UNIQUE (run_id, step)
            );
            CREATE INDEX IF NOT EXISTS idx_experiments_run
                ON experiments(run_id, step);

            CREATE TABLE IF NOT EXISTS settings (
                id INTEGER PRIMARY KEY CHECK (id = 1),
                model_provider TEXT NOT NULL DEFAULT '',
                model_name TEXT NOT NULL DEFAULT '',
                max_tokens INTEGER NOT NULL DEFAULT 65536,
                max_tool_iterations INTEGER NOT NULL DEFAULT 30,
                max_tool_iterations_training INTEGER NOT NULL DEFAULT 15,
                max_code_review_retries INTEGER NOT NULL DEFAULT 10,
                max_training_analysis_retries INTEGER NOT NULL DEFAULT 5,
                llm_call_retries INTEGER NOT NULL DEFAULT 3,
                training_timeout INTEGER NOT NULL DEFAULT 1800,
                test_timeout INTEGER NOT NULL DEFAULT 60,
                shell_command_timeout INTEGER NOT NULL DEFAULT 30,
                python_file_timeout INTEGER NOT NULL DEFAULT 30,
                command_output_max_chars INTEGER NOT NULL DEFAULT 4000,
                test_output_max_chars INTEGER NOT NULL DEFAULT 2000,
                test_error_max_chars INTEGER NOT NULL DEFAULT 1000,
                testing_llm_context_truncation INTEGER NOT NULL DEFAULT 3000,
                review_file_truncation INTEGER NOT NULL DEFAULT 3000,
                analysis_log_truncation INTEGER NOT NULL DEFAULT 5000,
                log_level TEXT NOT NULL DEFAULT 'INFO'
            );
            INSERT OR IGNORE INTO settings (id) VALUES (1);
        """)
        conn.commit()
        # Migrations for older DBs that pre-date columns added later.
        self._ensure_column("runs", "experiment_branch", "TEXT")
        self._ensure_column("runs", "lower_is_better", "INTEGER")
        self._ensure_column("runs", "metric_name", "TEXT")
        self._ensure_column("runs", "total_cost_usd", "REAL DEFAULT 0")
        self._ensure_column("runs", "total_prompt_tokens", "INTEGER DEFAULT 0")
        self._ensure_column("runs", "total_completion_tokens", "INTEGER DEFAULT 0")
        self._ensure_column("runs", "total_reasoning_tokens", "INTEGER DEFAULT 0")
        self._ensure_column("runs", "total_llm_calls", "INTEGER DEFAULT 0")
        # BYO Python environment: path to a venv/conda env to reuse instead
        # of building one via WorkspaceCreator. NULL = use the default.
        self._ensure_column("runs", "environment", "TEXT")

    def _ensure_column(self, table: str, column: str, decl: str) -> None:
        """Add a column if it doesn't already exist. Idempotent."""
        conn = self._get_conn()
        existing = {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}
        if column not in existing:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {decl}")
            conn.commit()

    # ------------------------------------------------------------------
    # Runs
    # ------------------------------------------------------------------

    def insert_run(self, run: dict) -> None:
        conn = self._get_conn()
        # Optional fields default to NULL so old callers keep working
        # without knowing about every new column.
        run = {**run}
        run.setdefault("lower_is_better", None)
        run.setdefault("metric_name", None)
        run.setdefault("environment", None)
        conn.execute(
            """INSERT INTO runs
               (id, status, workspace, task, target_accuracy, dataset_path,
                mode, force_cpu, setup_workspace, lower_is_better,
                metric_name, environment, created_at)
               VALUES (:id, :status, :workspace, :task, :target_accuracy,
                       :dataset_path, :mode, :force_cpu, :setup_workspace,
                       :lower_is_better, :metric_name, :environment,
                       :created_at)""",
            run,
        )
        conn.commit()

    def update_run(self, run_id: str, **fields: Any) -> None:
        if not fields:
            return
        conn = self._get_conn()
        set_clause = ", ".join(f"{k} = :{k}" for k in fields)
        fields["_id"] = run_id
        conn.execute(
            f"UPDATE runs SET {set_clause} WHERE id = :_id",
            fields,
        )
        conn.commit()

    def get_run(self, run_id: str) -> Optional[dict]:
        conn = self._get_conn()
        row = conn.execute("SELECT * FROM runs WHERE id = ?", (run_id,)).fetchone()
        return dict(row) if row else None

    def add_run_usage(
        self,
        run_id: str,
        cost_usd: float = 0.0,
        prompt_tokens: int = 0,
        completion_tokens: int = 0,
        reasoning_tokens: int = 0,
    ) -> None:
        """Increment per-run LLM usage rollups.

        Called from emit_llm_call_event after every successful LLM call.
        Single UPDATE with arithmetic so no read-modify-write race.
        Silent when run_id doesn't exist (e.g., a stray test that didn't
        register a run).
        """
        conn = self._get_conn()
        conn.execute(
            """UPDATE runs SET
                  total_cost_usd          = total_cost_usd          + :c,
                  total_prompt_tokens     = total_prompt_tokens     + :p,
                  total_completion_tokens = total_completion_tokens + :o,
                  total_reasoning_tokens  = total_reasoning_tokens  + :r,
                  total_llm_calls         = total_llm_calls         + 1
               WHERE id = :run_id""",
            {
                "c": float(cost_usd or 0.0),
                "p": int(prompt_tokens or 0),
                "o": int(completion_tokens or 0),
                "r": int(reasoning_tokens or 0),
                "run_id": run_id,
            },
        )
        conn.commit()

    def list_runs(self, status: Optional[str] = None, limit: int = 50) -> list[dict]:
        conn = self._get_conn()
        if status:
            rows = conn.execute(
                "SELECT * FROM runs WHERE status = ? ORDER BY created_at DESC LIMIT ?",
                (status, limit),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM runs ORDER BY created_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [dict(r) for r in rows]

    # ------------------------------------------------------------------
    # Stages
    # ------------------------------------------------------------------

    def upsert_stage(self, run_id: str, stage_name: str, **fields: Any) -> None:
        conn = self._get_conn()
        # Try update first
        existing = conn.execute(
            "SELECT 1 FROM stages WHERE run_id = ? AND stage_name = ?",
            (run_id, stage_name),
        ).fetchone()

        if existing:
            if fields:
                set_clause = ", ".join(f"{k} = :{k}" for k in fields)
                fields["_run_id"] = run_id
                fields["_stage_name"] = stage_name
                conn.execute(
                    f"UPDATE stages SET {set_clause} WHERE run_id = :_run_id AND stage_name = :_stage_name",
                    fields,
                )
        else:
            fields["run_id"] = run_id
            fields["stage_name"] = stage_name
            cols = ", ".join(fields.keys())
            placeholders = ", ".join(f":{k}" for k in fields)
            conn.execute(f"INSERT INTO stages ({cols}) VALUES ({placeholders})", fields)

        conn.commit()

    def deactivate_other_stages(self, run_id: str, active_stage: str) -> None:
        """Mark any other 'active' stage as 'pass'.

        The pipeline only advances out of a stage when its post() returns a
        non-retry action (e.g. 'complete'). So if some prior stage is still
        marked 'active' when a new stage starts, that stage's post() must
        have succeeded — it just didn't emit StageCompleted before the
        graph moved on. Flipping orphaned actives to 'pass' (instead of
        back to 'pending') keeps the dashboard's display state honest.
        """
        conn = self._get_conn()
        conn.execute(
            "UPDATE stages SET status = 'pass' "
            "WHERE run_id = ? AND stage_name != ? AND status = 'active'",
            (run_id, active_stage),
        )
        conn.commit()

    def get_stages(self, run_id: str) -> list[dict]:
        conn = self._get_conn()
        rows = conn.execute(
            "SELECT * FROM stages WHERE run_id = ? ORDER BY started_at",
            (run_id,),
        ).fetchall()
        return [dict(r) for r in rows]

    # ------------------------------------------------------------------
    # Events
    # ------------------------------------------------------------------

    def insert_event(self, run_id: str, timestamp: float, event_type: str,
                     stage: Optional[str], data_json: str) -> None:
        conn = self._get_conn()
        conn.execute(
            """INSERT INTO events (run_id, timestamp, event_type, stage, data_json)
               VALUES (?, ?, ?, ?, ?)""",
            (run_id, timestamp, event_type, stage, data_json),
        )
        conn.commit()

    def get_events(self, run_id: str, since: Optional[float] = None,
                   limit: int = 500) -> list[dict]:
        conn = self._get_conn()
        if since is not None:
            rows = conn.execute(
                """SELECT * FROM events
                   WHERE run_id = ? AND timestamp > ?
                   ORDER BY timestamp LIMIT ?""",
                (run_id, since, limit),
            ).fetchall()
        else:
            rows = conn.execute(
                """SELECT * FROM events
                   WHERE run_id = ?
                   ORDER BY timestamp LIMIT ?""",
                (run_id, limit),
            ).fetchall()
        return [dict(r) for r in rows]

    # ------------------------------------------------------------------
    # Experiments (hill-climb iterations)
    # ------------------------------------------------------------------

    def record_experiment(
        self,
        run_id: str,
        step: int,
        parent_step: Optional[int],
        proposal: Optional[str],
        score: Optional[float],
        lower_is_better: bool,
        kept: bool,
        tag: Optional[str] = None,
        commit_sha: Optional[str] = None,
        created_at: Optional[float] = None,
    ) -> None:
        """Persist one experiment outcome. Idempotent on (run_id, step) — a
        re-emit overwrites the existing row so the pipeline can record
        baseline at step=0 once and hill-climb iterations at steps 1..N.
        """
        import time as _time
        # SQLite rejects float('inf') / float('nan') as REAL. Persist them as
        # NULL so the dashboard treats "no score parsed" the same way the
        # pipeline treats the +/-inf sentinel internally.
        sane_score: Optional[float] = score
        if sane_score is None or sane_score in (float("inf"), float("-inf")):
            sane_score = None
        else:
            try:
                # NaN check that doesn't depend on math import
                if sane_score != sane_score:
                    sane_score = None
            except Exception:
                sane_score = None

        conn = self._get_conn()
        conn.execute(
            """INSERT INTO experiments
                 (run_id, step, parent_step, proposal, score,
                  lower_is_better, kept, tag, commit_sha, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(run_id, step) DO UPDATE SET
                 parent_step = excluded.parent_step,
                 proposal    = excluded.proposal,
                 score       = excluded.score,
                 lower_is_better = excluded.lower_is_better,
                 kept        = excluded.kept,
                 tag         = excluded.tag,
                 commit_sha  = excluded.commit_sha""",
            (run_id, step, parent_step, proposal, sane_score,
             int(lower_is_better), int(kept), tag, commit_sha,
             created_at if created_at is not None else _time.time()),
        )
        conn.commit()

    def list_experiments(self, run_id: str) -> list[dict]:
        conn = self._get_conn()
        rows = conn.execute(
            "SELECT * FROM experiments WHERE run_id = ? ORDER BY step",
            (run_id,),
        ).fetchall()
        return [dict(r) for r in rows]

    # ------------------------------------------------------------------
    # Settings
    # ------------------------------------------------------------------

    def get_settings(self) -> Optional[dict]:
        conn = self._get_conn()
        row = conn.execute("SELECT * FROM settings WHERE id = 1").fetchone()
        if row is None:
            return None
        d = dict(row)
        d.pop("id", None)
        return d

    def update_settings(self, fields: dict) -> None:
        if not fields:
            return
        conn = self._get_conn()
        set_clause = ", ".join(f"{k} = :{k}" for k in fields)
        conn.execute(f"UPDATE settings SET {set_clause} WHERE id = 1", fields)
        conn.commit()

    # ------------------------------------------------------------------
    # Admin / cleanup
    # ------------------------------------------------------------------

    def delete_run(self, run_id: str) -> None:
        """Delete a run and its stages, events, and experiments."""
        conn = self._get_conn()
        conn.execute("DELETE FROM events WHERE run_id = ?", (run_id,))
        conn.execute("DELETE FROM stages WHERE run_id = ?", (run_id,))
        conn.execute("DELETE FROM experiments WHERE run_id = ?", (run_id,))
        conn.execute("DELETE FROM runs WHERE id = ?", (run_id,))
        conn.commit()

    def delete_runs_older_than(self, days: int) -> int:
        """Delete runs created more than *days* ago. Returns count deleted."""
        import time
        cutoff = time.time() - (days * 86400)
        conn = self._get_conn()
        rows = conn.execute(
            "SELECT id FROM runs WHERE created_at < ?", (cutoff,)
        ).fetchall()
        ids = [r["id"] for r in rows]
        if ids:
            placeholders = ",".join("?" * len(ids))
            conn.execute(f"DELETE FROM events WHERE run_id IN ({placeholders})", ids)
            conn.execute(f"DELETE FROM stages WHERE run_id IN ({placeholders})", ids)
            conn.execute(f"DELETE FROM experiments WHERE run_id IN ({placeholders})", ids)
            conn.execute(f"DELETE FROM runs WHERE id IN ({placeholders})", ids)
            conn.commit()
        return len(ids)

    def reset_database(self) -> None:
        """Delete all runs, stages, events, and experiments. Preserves settings."""
        conn = self._get_conn()
        conn.execute("DELETE FROM events")
        conn.execute("DELETE FROM stages")
        conn.execute("DELETE FROM experiments")
        conn.execute("DELETE FROM runs")
        conn.commit()
        conn.execute("VACUUM")

    def get_stats(self) -> dict:
        """Return row counts and DB file size."""
        conn = self._get_conn()
        stats: dict = {}
        for table in ("runs", "stages", "events"):
            row = conn.execute(f"SELECT COUNT(*) as cnt FROM {table}").fetchone()
            stats[f"{table}_count"] = row["cnt"]
        rows = conn.execute(
            "SELECT status, COUNT(*) as cnt FROM runs GROUP BY status"
        ).fetchall()
        stats["runs_by_status"] = {r["status"]: r["cnt"] for r in rows}
        stats["db_size_bytes"] = (
            self._db_path.stat().st_size if self._db_path.exists() else 0
        )
        return stats

    def close(self) -> None:
        if hasattr(self._local, "conn") and self._local.conn:
            self._local.conn.close()
            self._local.conn = None


# Module-level singleton
_global_db: Optional[Database] = None
_db_lock = threading.Lock()


def get_database() -> Database:
    """Get or create the global Database singleton."""
    global _global_db
    if _global_db is None:
        with _db_lock:
            if _global_db is None:
                _global_db = Database()
    return _global_db
