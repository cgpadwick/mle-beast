# Copyright 2026 Chris Padwick
# SPDX-License-Identifier: Apache-2.0

"""Tests for mle_beast.events — event models + EventBus."""

from __future__ import annotations

import asyncio

import pytest

from mle_beast import events as events_mod
from mle_beast.events import (
    EventBus,
    EventType,
    ExperimentRecorded,
    LLMCall,
    LogMessage,
    PipelineEvent,
    RetryOccurred,
    RunStateChanged,
    StageCompleted,
    StageStarted,
    ToolExecuted,
    get_current_run_id,
    get_event_bus,
    set_current_run_id,
)

# ---------------------------------------------------------------------------
# Event models
# ---------------------------------------------------------------------------


class TestEventModels:
    def test_pipeline_event_sets_timestamp_and_serializes(self):
        e = StageStarted(run_id="r1", stage="coding")
        assert e.run_id == "r1"
        assert e.timestamp > 0
        assert e.event_type == EventType.STAGE_STARTED
        data = e.to_sse_data()
        assert '"run_id":"r1"' in data
        assert '"stage":"coding"' in data

    @pytest.mark.parametrize("event_cls,kwargs,expected_type", [
        (
            RunStateChanged,
            {"run_id": "r", "old_state": "pending", "new_state": "running"},
            EventType.RUN_STATE_CHANGED,
        ),
        (
            StageStarted,
            {"run_id": "r", "stage": "coding"},
            EventType.STAGE_STARTED,
        ),
        (
            StageCompleted,
            {"run_id": "r", "stage": "coding", "outcome": "pass"},
            EventType.STAGE_COMPLETED,
        ),
        (
            ToolExecuted,
            {"run_id": "r", "stage": "coding", "iteration": 1,
             "tool_name": "write_file", "result_preview": "ok"},
            EventType.TOOL_EXECUTED,
        ),
        (
            RetryOccurred,
            {"run_id": "r", "stage": "testing", "attempt": 1,
             "max_attempts": 3, "feedback": "try again"},
            EventType.RETRY_OCCURRED,
        ),
        (
            LogMessage,
            {"run_id": "r", "message": "hello"},
            EventType.LOG_MESSAGE,
        ),
        (
            LLMCall,
            {"run_id": "r", "model": "gpt-5"},
            EventType.LLM_CALL,
        ),
        (
            ExperimentRecorded,
            {"run_id": "r", "step": 1},
            EventType.EXPERIMENT_RECORDED,
        ),
    ])
    def test_subclass_event_types(self, event_cls, kwargs, expected_type):
        e = event_cls(**kwargs)
        assert e.event_type == expected_type
        # Every subclass must be JSON-serializable for SSE.
        e.to_sse_data()


# ---------------------------------------------------------------------------
# EventBus — sync subscribers
# ---------------------------------------------------------------------------


class TestEventBusSync:
    def test_subscribe_and_emit(self):
        bus = EventBus()
        received: list[PipelineEvent] = []
        bus.subscribe("r1", received.append)
        bus.emit(StageStarted(run_id="r1", stage="coding"))
        assert len(received) == 1
        assert received[0].stage == "coding"

    def test_emit_only_routes_to_matching_run_id(self):
        bus = EventBus()
        got_r1, got_r2 = [], []
        bus.subscribe("r1", got_r1.append)
        bus.subscribe("r2", got_r2.append)
        bus.emit(StageStarted(run_id="r1", stage="x"))
        assert len(got_r1) == 1
        assert len(got_r2) == 0

    def test_unsubscribe_removes_callback(self):
        bus = EventBus()
        received = []
        cb = received.append
        bus.subscribe("r1", cb)
        bus.unsubscribe("r1", cb)
        bus.emit(StageStarted(run_id="r1", stage="x"))
        assert received == []

    def test_unsubscribe_unknown_callback_is_noop(self):
        bus = EventBus()
        bus.unsubscribe("never-subscribed", lambda e: None)  # must not raise

    def test_subscriber_exception_does_not_break_bus(self):
        """A bad subscriber must NOT block other subscribers from receiving."""
        bus = EventBus()
        ok = []

        def bad(_e):
            raise RuntimeError("subscriber buggy")

        bus.subscribe("r1", bad)
        bus.subscribe("r1", ok.append)
        bus.emit(StageStarted(run_id="r1", stage="x"))
        assert len(ok) == 1

    def test_cleanup_run_drops_subscribers(self):
        bus = EventBus()
        received = []
        bus.subscribe("r1", received.append)
        bus.cleanup_run("r1")
        bus.emit(StageStarted(run_id="r1", stage="x"))
        assert received == []


# ---------------------------------------------------------------------------
# EventBus — async (SSE) subscribers
# ---------------------------------------------------------------------------


class TestEventBusAsync:
    def test_async_queue_receives_when_loop_is_set(self):
        async def scenario():
            bus = EventBus()
            bus.set_loop(asyncio.get_running_loop())
            queue = bus.subscribe_async("r1")

            # Emit from the same thread — call_soon_threadsafe still works.
            bus.emit(StageStarted(run_id="r1", stage="coding"))

            # Yield so call_soon_threadsafe schedules the put.
            event = await asyncio.wait_for(queue.get(), timeout=1.0)
            assert isinstance(event, StageStarted)
            assert event.stage == "coding"

            bus.unsubscribe_async("r1", queue)
            return True

        assert asyncio.run(scenario()) is True

    def test_emit_with_async_queue_but_no_loop_drops_silently(self):
        """If set_loop was never called, async queues are simply skipped.

        This is intentional: pytest-launched runs share the DB with the web
        server but don't share the event loop, so emits must not blow up.
        """
        bus = EventBus()
        # Subscribe without setting a loop — must not raise on emit.
        bus.subscribe_async("r1")
        bus.emit(StageStarted(run_id="r1", stage="x"))

    def test_unsubscribe_async_unknown_queue_is_noop(self):
        bus = EventBus()
        bus.unsubscribe_async("nobody", asyncio.Queue())  # must not raise


# ---------------------------------------------------------------------------
# Module-level singletons
# ---------------------------------------------------------------------------


class TestSingleton:
    def test_get_event_bus_returns_same_instance(self, monkeypatch):
        monkeypatch.setattr(events_mod, "_global_bus", None)
        bus1 = get_event_bus()
        bus2 = get_event_bus()
        assert bus1 is bus2


class TestThreadLocalRunId:
    def test_set_get_round_trip(self):
        set_current_run_id("abc-123")
        assert get_current_run_id() == "abc-123"

    def test_default_is_none(self, monkeypatch):
        # Reset to a clean thread-local.
        monkeypatch.setattr(events_mod, "_thread_local", events_mod.threading.local())
        assert get_current_run_id() is None

    def test_clearing_via_none(self):
        set_current_run_id("x")
        set_current_run_id(None)
        assert get_current_run_id() is None
