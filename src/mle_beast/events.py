# Copyright 2026 Chris Padwick
# SPDX-License-Identifier: Apache-2.0

"""Event system for pipeline observability.

Provides typed Pydantic event models and an EventBus that bridges
synchronous pipeline threads to async SSE consumers.
"""

from __future__ import annotations

import asyncio
import threading
import time
import uuid
from enum import Enum
from typing import Any, Callable, Optional

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Event models
# ---------------------------------------------------------------------------

class EventType(str, Enum):
    RUN_STATE_CHANGED = "run_state_changed"
    STAGE_STARTED = "stage_started"
    STAGE_COMPLETED = "stage_completed"
    TOOL_EXECUTED = "tool_executed"
    RETRY_OCCURRED = "retry_occurred"
    LOG_MESSAGE = "log_message"
    EXPERIMENT_RECORDED = "experiment_recorded"
    LLM_CALL = "llm_call"


class PipelineEvent(BaseModel):
    """Base event — every event carries these fields."""
    run_id: str
    timestamp: float = Field(default_factory=time.time)
    event_type: EventType
    stage: Optional[str] = None

    def to_sse_data(self) -> str:
        """Serialize for SSE transmission."""
        return self.model_dump_json()


class RunStateChanged(PipelineEvent):
    event_type: EventType = EventType.RUN_STATE_CHANGED
    old_state: str
    new_state: str


class StageStarted(PipelineEvent):
    event_type: EventType = EventType.STAGE_STARTED
    stage: str


class StageCompleted(PipelineEvent):
    event_type: EventType = EventType.STAGE_COMPLETED
    stage: str
    outcome: str  # "pass", "fail", "error"
    verdict: Optional[str] = None


class ToolExecuted(PipelineEvent):
    event_type: EventType = EventType.TOOL_EXECUTED
    stage: str
    iteration: int
    tool_name: str
    result_preview: str


class RetryOccurred(PipelineEvent):
    event_type: EventType = EventType.RETRY_OCCURRED
    stage: str
    attempt: int
    max_attempts: int
    feedback: str


class LogMessage(PipelineEvent):
    event_type: EventType = EventType.LOG_MESSAGE
    level: str = "info"  # "info", "warning", "error", "debug"
    message: str


class LLMCall(PipelineEvent):
    """One round-trip to the LLM. Emitted by llm.call_llm after a
    successful response so the dashboard can show the actual conversation
    instead of just opaque "tool_executed" rows.

    Includes the FULL conversation sent to the model (every message in
    the request, each capped at 50K chars with original-length annotation)
    plus the structured response (the Pydantic model the LLM picked,
    dumped to a dict). The dashboard can render exactly what the model
    saw, including the system prompt and all tool-result history.

    Usage fields (token counts + cost) are populated when the provider
    surfaces them. OpenRouter returns prompt/completion/reasoning/cached
    tokens and a per-call cost (USD); local LLMs and OpenAI-direct
    typically return tokens only. All are optional so callers from
    providers that don't report usage still emit the event cleanly.
    """
    event_type: EventType = EventType.LLM_CALL
    messages: list = []         # [{role: str, content: str (truncated)}]
    response: dict = {}         # response_model.model_dump()
    response_model: str = ""    # name of the Pydantic class
    model: str = ""             # LLM model name (e.g. "nemotron-3-super:120b")
    duration_ms: int = 0
    prompt_tokens: Optional[int] = None
    completion_tokens: Optional[int] = None
    reasoning_tokens: Optional[int] = None
    cached_tokens: Optional[int] = None
    cost_usd: Optional[float] = None


class ExperimentRecorded(PipelineEvent):
    """Fired by BaselineEvalNode (step=0) and HillClimbEvalNode (step>=1).

    Carries the entire row that was just persisted to the experiments
    table so the dashboard can append to its tree without a follow-up
    fetch. score=None means the val-score parser fell back to the no-score
    sentinel; the dashboard renders this as an unparseable attempt.
    """
    event_type: EventType = EventType.EXPERIMENT_RECORDED
    step: int
    parent_step: Optional[int] = None
    proposal: Optional[str] = None
    score: Optional[float] = None
    lower_is_better: bool = False
    kept: bool = False
    tag: Optional[str] = None
    commit_sha: Optional[str] = None


# ---------------------------------------------------------------------------
# EventBus
# ---------------------------------------------------------------------------

# Type alias for sync callbacks
SyncCallback = Callable[[PipelineEvent], None]


class EventBus:
    """Thread-safe event bus bridging sync pipeline threads to async SSE.

    Usage:
        bus = EventBus()

        # Sync subscriber (e.g. CLI printer)
        bus.subscribe("run-123", my_callback)

        # Async subscriber (e.g. SSE endpoint)
        bus.set_loop(asyncio.get_event_loop())
        queue = bus.subscribe_async("run-123")

        # From pipeline thread (sync)
        bus.emit(StageStarted(run_id="run-123", stage="coding"))
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        # run_id -> list of sync callbacks
        self._sync_subs: dict[str, list[SyncCallback]] = {}
        # run_id -> list of asyncio.Queue
        self._async_queues: dict[str, list[asyncio.Queue]] = {}
        # Optional asyncio event loop for async bridging
        self._loop: Optional[asyncio.AbstractEventLoop] = None

    def set_loop(self, loop: asyncio.AbstractEventLoop) -> None:
        """Register the asyncio event loop (called once when web server starts)."""
        self._loop = loop

    def subscribe(self, run_id: str, callback: SyncCallback) -> None:
        """Register a synchronous subscriber for a run's events."""
        with self._lock:
            self._sync_subs.setdefault(run_id, []).append(callback)

    def unsubscribe(self, run_id: str, callback: SyncCallback) -> None:
        """Remove a synchronous subscriber."""
        with self._lock:
            subs = self._sync_subs.get(run_id, [])
            if callback in subs:
                subs.remove(callback)

    def subscribe_async(self, run_id: str) -> asyncio.Queue:
        """Create and return an async queue for SSE streaming."""
        queue: asyncio.Queue = asyncio.Queue()
        with self._lock:
            self._async_queues.setdefault(run_id, []).append(queue)
        return queue

    def unsubscribe_async(self, run_id: str, queue: asyncio.Queue) -> None:
        """Remove an async queue subscriber."""
        with self._lock:
            queues = self._async_queues.get(run_id, [])
            if queue in queues:
                queues.remove(queue)

    def emit(self, event: PipelineEvent) -> None:
        """Emit an event (safe to call from any thread).

        - Calls sync subscribers directly (same thread).
        - Enqueues to async queues via loop.call_soon_threadsafe().
        """
        with self._lock:
            sync_subs = list(self._sync_subs.get(event.run_id, []))
            async_queues = list(self._async_queues.get(event.run_id, []))

        # Sync subscribers — called in the emitting thread
        for cb in sync_subs:
            try:
                cb(event)
            except Exception:
                pass  # Don't let subscriber errors break the pipeline

        # Async queues — bridge to event loop thread
        if async_queues and self._loop is not None:
            for q in async_queues:
                try:
                    self._loop.call_soon_threadsafe(q.put_nowait, event)
                except Exception:
                    pass

    def cleanup_run(self, run_id: str) -> None:
        """Remove all subscribers for a completed run."""
        with self._lock:
            self._sync_subs.pop(run_id, None)
            self._async_queues.pop(run_id, None)


# Module-level singleton
_global_bus: Optional[EventBus] = None
_bus_lock = threading.Lock()


def get_event_bus() -> EventBus:
    """Get or create the global EventBus singleton."""
    global _global_bus
    if _global_bus is None:
        with _bus_lock:
            if _global_bus is None:
                _global_bus = EventBus()
    return _global_bus


# ---------------------------------------------------------------------------
# Thread-local "current run" — lets low-level utilities (command_runner,
# tool dispatchers, etc.) emit LogMessage events without having to thread
# the run_id and event bus through every call site.
# ---------------------------------------------------------------------------

_thread_local = threading.local()


def set_current_run_id(run_id: Optional[str]) -> None:
    """Set the run_id associated with the calling thread.

    run_manager calls this at the start of each pipeline thread so that any
    `print`-equivalent log inside command_runner can be turned into a
    LogMessage event for the web UI.
    """
    _thread_local.run_id = run_id


def get_current_run_id() -> Optional[str]:
    """Return the run_id associated with the calling thread, if any."""
    return getattr(_thread_local, "run_id", None)
