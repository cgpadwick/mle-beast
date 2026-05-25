# Copyright 2026 Chris Padwick
# SPDX-License-Identifier: Apache-2.0

"""Event-to-DB synchronization for pipeline runs.

The pipeline emits events on the EventBus; we want those events
mirrored into the SQLite events table (for the dashboard) and we want
stage-status events to drive the stages table. This module factors out
the closure that does both jobs.
"""

from __future__ import annotations

import json
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
            # A retry means the critic rejected the stage's output and the
            # actor is having another go — it is NOT a terminal failure (that
            # path emits StageCompleted(outcome="fail") instead). Mark it
            # "retrying" so the dashboard can distinguish it from a hard fail,
            # and persist the critic's feedback into verdict_json so the
            # reason travels with the stage rather than living only in a
            # transient event.
            db.upsert_stage(
                run_id, event.stage,
                status="retrying", attempt=event.attempt,
                max_attempts=event.max_attempts,
                verdict_json=json.dumps({"feedback": event.feedback}),
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
                # Sweep both "active" and "retrying" — a run can terminate
                # mid-retry, and a lingering "retrying" pill would misrepresent
                # the finished run just like a lingering "active" one.
                if s.get("status") in ("active", "retrying"):
                    db.upsert_stage(
                        run_id, s["stage_name"],
                        status=outcome,
                        completed_at=event.timestamp,
                    )

    return listener
