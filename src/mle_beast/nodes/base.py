# Copyright 2026 Chris Padwick
# SPDX-License-Identifier: Apache-2.0

"""Base node classes for Actor (inner tool loop) and Critic (verdict + retry/complete).

BaseActorNode:
  - prep() reads task + feedback from shared
  - exec() runs an inner tool loop (LLM picks tools via discriminated union)
  - post() stores results, returns "evaluate"

BaseCriticNode:
  - prep() gathers evaluation data
  - exec() produces a verdict (procedural checks + LLM feedback)
  - post() returns "retry" or "complete" based on verdict
"""

from __future__ import annotations

import time
from typing import Any, Optional

from pocketflow import Node

from mle_beast.events import (
    EventBus,
    LogMessage,
    RetryOccurred,
    StageCompleted,
    StageStarted,
    ToolExecuted,
)
from mle_beast.llm import (
    emit_llm_call_event,
    get_client,
    get_model_name,
    max_tokens_kwarg,
)
from mle_beast.settings import Settings
from mle_beast.tools.registry import execute_tool

MAX_TOOL_ITERATIONS = 30
MAX_CRITIC_RETRIES = 3
LLM_CALL_RETRIES = 3

# Context management: when total chars exceed this budget, truncate old tool results.
# Note: the instructor library injects the full JSON schema for the tool call model
# into the system prompt (~50K tokens for large discriminated unions). Our char budget
# must account for this invisible overhead to stay under the LLM's context limit.
MAX_CONTEXT_CHARS = 40_000
# When truncating, keep this many chars from the start of each old tool result.
TRUNCATED_RESULT_PREVIEW = 500


def _get_settings(shared: dict) -> Settings:
    """Return settings from shared, falling back to defaults."""
    return shared.get("settings") or Settings()


def _estimate_tokens(char_count: int) -> int:
    """Rough token estimate: ~4 chars per token for English/code."""
    return char_count // 4


def _messages_stats(messages: list[dict]) -> dict:
    """Compute size stats for a message list."""
    total_chars = 0
    per_role: dict[str, int] = {}
    largest_msg = ("", 0, 0)  # (role, index, chars)
    for i, msg in enumerate(messages):
        content = msg.get("content", "")
        n = len(content)
        total_chars += n
        per_role[msg.get("role", "?")] = per_role.get(msg.get("role", "?"), 0) + n
        if n > largest_msg[2]:
            largest_msg = (msg.get("role", "?"), i, n)
    return {
        "num_messages": len(messages),
        "total_chars": total_chars,
        "est_tokens": _estimate_tokens(total_chars),
        "per_role_chars": per_role,
        "largest_msg": {
            "role": largest_msg[0],
            "index": largest_msg[1],
            "chars": largest_msg[2],
            "est_tokens": _estimate_tokens(largest_msg[2]),
        },
    }


def _trim_context(
    messages: list[dict],
    budget: int = MAX_CONTEXT_CHARS,
    shared: Optional[dict] = None,
    run_id: str = "",
    stage: str = "",
) -> None:
    """Trim old tool-result messages in-place to stay within budget.

    Strategy: keep system (idx 0) and initial user prompt (idx 1) intact.
    For remaining messages, if total chars exceed budget, truncate the oldest
    large 'user' (tool result) messages first, preserving only a preview.
    """
    total = sum(len(m.get("content", "")) for m in messages)
    if total <= budget:
        return

    candidates = []
    for i in range(2, len(messages)):
        content = messages[i].get("content", "")
        if messages[i].get("role") == "user" and content.startswith("Tool result:"):
            candidates.append((i, len(content)))

    for idx, size in candidates:
        if total <= budget:
            break
        if size <= TRUNCATED_RESULT_PREVIEW + 100:
            continue
        content = messages[idx]["content"]
        preview = content[:TRUNCATED_RESULT_PREVIEW]
        messages[idx]["content"] = (
            f"{preview}\n\n... [CONTEXT TRIMMED — original was {size:,} chars] ..."
        )
        saved = size - len(messages[idx]["content"])
        total -= saved
        if shared is not None:
            _emit(shared, LogMessage(
                run_id=run_id, stage=stage, level="debug",
                message=f"[CONTEXT] Trimmed msg[{idx}]: {size:,} → {len(messages[idx]['content']):,} chars",
            ))


def _emit(shared: dict, event) -> None:
    """Emit an event via the shared event bus (if present)."""
    bus: Optional[EventBus] = shared.get("event_bus")
    if bus is not None:
        bus.emit(event)


def _get_run_id(shared: dict) -> str:
    return shared.get("run_id", "")


class BaseActorNode(Node):
    """Base class for actor nodes that run an inner tool loop.

    Subclasses must define:
      - system_prompt: str
      - tool_call_model: Pydantic model for discriminated-union tool calls
      - _build_user_prompt(prep_res) -> str
    """

    system_prompt: str = ""
    tool_call_model: Any = None
    max_iterations: int = MAX_TOOL_ITERATIONS
    _stage_name: str = ""

    def prep(self, shared: dict) -> dict:
        return {
            "task": shared.get("task", ""),
            "workspace": str(shared.get("workspace", "")),
            "feedback_history": shared.get("feedback_history", []),
            "shared": shared,
        }

    def _build_user_prompt(self, prep_res: dict) -> str:
        task = prep_res["task"]
        workspace = prep_res["workspace"]
        prompt = f"Task: {task}\nWorkspace root: {workspace}"
        feedback = prep_res.get("feedback_history", [])
        if feedback:
            prompt += "\n\nPrevious feedback (address these issues):\n"
            for i, fb in enumerate(feedback, 1):
                prompt += f"  {i}. {fb}\n"
        return prompt

    def exec(self, prep_res: dict) -> list[str]:
        client = get_client()
        shared = prep_res["shared"]
        run_id = _get_run_id(shared)
        stage = self._stage_name
        settings = _get_settings(shared)

        max_iters = self.max_iterations
        if max_iters == MAX_TOOL_ITERATIONS:
            max_iters = settings.max_tool_iterations
        llm_retries = settings.llm_call_retries
        max_tok = settings.max_tokens
        model = get_model_name(settings)

        # Emit stage started
        _emit(shared, StageStarted(run_id=run_id, stage=stage))

        messages: list[dict] = [
            {"role": "system", "content": self.system_prompt},
            {"role": "user", "content": self._build_user_prompt(prep_res)},
        ]

        # Log initial context size
        stats = _messages_stats(messages)
        ctx_msg = (f"Initial: {stats['num_messages']} msgs, "
                   f"{stats['total_chars']:,} chars (~{stats['est_tokens']:,} tokens) | "
                   f"system: {stats['per_role_chars'].get('system', 0):,} chars, "
                   f"user: {stats['per_role_chars'].get('user', 0):,} chars")
        _emit(shared, LogMessage(
            run_id=run_id, stage=stage, level="debug", message=f"[CONTEXT] {ctx_msg}",
        ))

        tool_log: list[str] = []

        for iteration in range(max_iters):
            # Check cancellation (in-memory flag or DB status)
            cancel_event = shared.get("_cancel_event")
            cancelled = cancel_event is not None and cancel_event.is_set()
            if not cancelled and run_id:
                try:
                    from mle_beast.db import get_database
                    row = get_database().get_run(run_id)
                    if row and row["status"] == "cancelled":
                        cancelled = True
                except Exception:
                    pass
            if cancelled:
                _emit(shared, LogMessage(
                    run_id=run_id, stage=stage, level="warning",
                    message="Cancellation requested — stopping tool loop.",
                ))
                break

            # Trim context if it exceeds the budget
            _trim_context(messages, shared=shared, run_id=run_id, stage=stage)

            # Log context size before each LLM call
            stats = _messages_stats(messages)
            ctx_msg = (f"Iter {iteration + 1}: {stats['num_messages']} msgs, "
                       f"{stats['total_chars']:,} chars (~{stats['est_tokens']:,} tokens) | "
                       f"largest: msg[{stats['largest_msg']['index']}] "
                       f"({stats['largest_msg']['role']}) "
                       f"{stats['largest_msg']['chars']:,} chars")
            _emit(shared, LogMessage(
                run_id=run_id, stage=stage, level="debug", message=f"[CONTEXT] {ctx_msg}",
            ))

            tool_call = None
            llm_failed = False
            # Deep-copy messages so instructor's JSON-mode schema injection
            # doesn't mutate our working list (it appends the response model
            # schema to messages[0]["content"] on each call).
            messages_snapshot = [dict(m) for m in messages]
            for attempt in range(llm_retries):
                try:
                    _t0 = time.time()
                    tool_call, completion = client.chat.completions.create_with_completion(
                        response_model=self.tool_call_model,
                        messages=messages_snapshot,
                        model=model,
                        **max_tokens_kwarg(max_tok),
                    )
                    # Surface this round-trip in the dashboard's LLM tab.
                    # `messages` (not the snapshot) is what we want users to
                    # see — it's the conversation log without instructor's
                    # injected schema noise. `completion` carries usage
                    # (tokens + cost) which we extract and roll up.
                    emit_llm_call_event(
                        messages, tool_call, self.tool_call_model,
                        int((time.time() - _t0) * 1000),
                        completion=completion,
                    )
                    break
                except Exception as e:
                    _emit(shared, LogMessage(
                        run_id=run_id, stage=stage, level="error",
                        message=f"LLM call failed (attempt {attempt + 1}/{llm_retries}): {e!r}",
                    ))
                    if attempt + 1 >= llm_retries:
                        # Don't raise — that crashes the whole pipeline. Treat
                        # repeated LLM failure as the actor giving up: log the
                        # failure, exit the tool loop, and let the downstream
                        # critic decide whether to retry or abandon.
                        llm_failed = True
                        break
                    time.sleep(2 ** attempt)

            if llm_failed:
                tool_log.append(
                    f"[{iteration + 1}] LLM call exhausted retries; ending tool loop."
                )
                shared["last_mark_complete_summary"] = (
                    "(LLM failed to produce a valid tool call after retries)"
                )
                break

            inner = tool_call.call
            tool_name = inner.tool
            result = execute_tool(tool_name, inner.args, shared)
            entry = f"[{iteration + 1}] {tool_name}: {result[:200]}"
            tool_log.append(entry)

            _emit(shared, ToolExecuted(
                run_id=run_id, stage=stage, iteration=iteration + 1,
                tool_name=tool_name, result_preview=result[:200],
            ))

            if tool_name == "mark_complete":
                break

            # Log size of messages being appended
            call_json = inner.model_dump_json()
            call_chars = len(call_json)
            result_chars = len(result)
            _emit(shared, LogMessage(
                run_id=run_id, stage=stage, level="debug",
                message=f"[CONTEXT]   +assistant: {call_chars:,} chars | +user (tool result): {result_chars:,} chars",
            ))

            messages.append({
                "role": "assistant",
                "content": f"Tool call: {call_json}",
            })
            messages.append({
                "role": "user",
                "content": f"Tool result: {result}",
            })

        # Log final context size
        stats = _messages_stats(messages)
        per_role = stats['per_role_chars']
        ctx_msg = (f"Final: {stats['num_messages']} msgs, "
                   f"{stats['total_chars']:,} chars (~{stats['est_tokens']:,} tokens) | "
                   f"system: {per_role.get('system', 0):,} | "
                   f"user: {per_role.get('user', 0):,} | "
                   f"assistant: {per_role.get('assistant', 0):,}")
        _emit(shared, LogMessage(
            run_id=run_id, stage=stage, level="debug", message=f"[CONTEXT] {ctx_msg}",
        ))

        return tool_log

    def post(self, shared: dict, prep_res, exec_res) -> str:
        shared["tool_log"] = exec_res
        run_id = _get_run_id(shared)
        stage = self._stage_name
        _emit(shared, StageCompleted(
            run_id=run_id, stage=stage, outcome="pass",
        ))
        return "evaluate"


class BaseCriticNode(Node):
    """Base class for critic nodes that evaluate and produce verdicts.

    Subclasses must define:
      - _evaluate(prep_res) -> verdict object with .feedback attribute
      - _is_pass(verdict) -> bool

    The retry/complete logic and attempt tracking is handled here.
    """

    critic_max_retries: int = MAX_CRITIC_RETRIES
    _attempt_key: str = "critic_attempt"
    _stage_name: str = ""

    def _evaluate(self, prep_res: dict) -> Any:
        raise NotImplementedError

    def _is_pass(self, verdict: Any) -> bool:
        raise NotImplementedError

    def exec(self, prep_res: dict) -> Any:
        shared = prep_res.get("shared", {})
        run_id = _get_run_id(shared)
        stage = self._stage_name

        _emit(shared, StageStarted(run_id=run_id, stage=stage))
        return self._evaluate(prep_res)

    def post(self, shared: dict, prep_res, verdict) -> str:
        run_id = _get_run_id(shared)
        stage = self._stage_name
        max_retries = self.critic_max_retries

        if self._is_pass(verdict):
            shared["verdict"] = verdict
            _emit(shared, StageCompleted(
                run_id=run_id, stage=stage, outcome="pass",
                verdict=str(verdict),
            ))
            return "complete"

        attempt = shared.get(self._attempt_key, 0) + 1
        shared[self._attempt_key] = attempt

        if attempt >= max_retries:
            _emit(shared, LogMessage(
                run_id=run_id, stage=stage, level="error",
                message=f"Max retries ({max_retries}) reached — stopping pipeline.",
            ))
            _emit(shared, StageCompleted(
                run_id=run_id, stage=stage, outcome="fail",
                verdict=str(verdict),
            ))
            shared["verdict"] = verdict
            feedback = getattr(verdict, "feedback", str(verdict))
            raise RuntimeError(
                f"Stage '{stage}' failed after {max_retries} attempts: {feedback}"
            )

        feedback = getattr(verdict, "feedback", str(verdict))
        shared.setdefault("feedback_history", []).append(feedback)

        _emit(shared, RetryOccurred(
            run_id=run_id, stage=stage, attempt=attempt + 1,
            max_attempts=max_retries, feedback=feedback,
        ))

        return "retry"
