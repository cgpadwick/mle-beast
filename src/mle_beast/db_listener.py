# Copyright 2026 Chris Padwick
# SPDX-License-Identifier: Apache-2.0

"""Event-to-DB synchronization for pipeline runs.

The pipeline emits events on the EventBus; we want those events
mirrored into the SQLite events table (for the dashboard) and we want
stage-status events to drive the stages table. This module factors out
the closure that does both jobs.
"""

from __future__ import annotations

from typing import Callable

from mle_beast.db import Database
from mle_beast.events import (
    PipelineEvent,
    RetryOccurred,
    RunStateChanged,
    StageCompleted,
    StageStarted,
)


def make_db_listener(run_id: str, db: Database) -> Callable[[PipelineEvent], None]:
    """Build a sync subscriber callback that persists events to the DB.

    Register the returned callback via `bus.subscribe(run_id, callback)`.
    It receives every event for that run on the emitting thread and:
      - inserts a row into the `events` table for every event
      - updates the `stages` table when a stage event arrives
      - on a terminal RunStateChanged, sweeps any still-active stage rows
        to a final status so the dashboard's active indicator is honest

    Captures `run_id` and `db` in a closure so the bus only needs a
    callable on its side.
    """
    def listener(event: PipelineEvent) -> None:
        # Persist all events
        db.insert_event(
            run_id=event.run_id,
            timestamp=event.timestamp,
            event_type=event.event_type.value,
            stage=event.stage,
            data_json=event.to_sse_data(),
        )

        # Update stage table for stage events
        if isinstance(event, StageStarted):
            db.deactivate_other_stages(run_id, event.stage)
            db.upsert_stage(
                run_id, event.stage,
                status="active", started_at=event.timestamp,
                completed_at=None, verdict_json=None,
            )
        elif isinstance(event, StageCompleted):
            db.upsert_stage(
                run_id, event.stage,
                status=event.outcome, completed_at=event.timestamp,
                verdict_json=event.verdict,
            )
        elif isinstance(event, RetryOccurred):
            db.upsert_stage(
                run_id, event.stage,
                status="fail", attempt=event.attempt,
                max_attempts=event.max_attempts,
            )
        elif isinstance(event, RunStateChanged) and event.new_state in (
            "completed", "failed", "cancelled",
        ):
            # When a run terminates (target met, budget exhausted,
            # consecutive-failure abort, error, or user cancel), some
            # stage rows can still be 'active' because the eval node
            # returned 'done' without firing a StageCompleted for the
            # surrounding stage. Sweep them so the dashboard's
            # active-stage indicator doesn't lie about a finished run.
            # We mark them 'pass' on a clean completion and 'fail' on
            # a failure/cancel — that matches what the user would have
            # seen had the stage emitted its own completion event.
            outcome = "pass" if event.new_state == "completed" else "fail"
            for s in db.get_stages(run_id):
                if s.get("status") == "active":
                    db.upsert_stage(
                        run_id, s["stage_name"],
                        status=outcome,
                        completed_at=event.timestamp,
                    )

    return listener
