# Copyright 2026 Chris Padwick
# SPDX-License-Identifier: Apache-2.0

"""Instructor wrapper for structured LLM output.

Supports three providers (checked in order):
  1. Local LLM via OpenAI-compatible API (LOCAL_LLM_BASE_URL)
  2. OpenRouter via OpenAI-compatible API (OPENROUTER_API_KEY)
  3. OpenAI directly (OPENAI_API_KEY)

Provider is auto-detected from environment variables, but can be overridden
via settings (model_provider field).
Model can be overridden via MLE_BEAST_MODEL env var or settings.model_name.
"""

from __future__ import annotations

import os
import time

import instructor
from openai import OpenAI

LLM_CALL_RETRIES = 3


def _auto_detect_local_model(base_url: str) -> str:
    """Query the local server's /v1/models endpoint to find the served model."""
    try:
        client = OpenAI(base_url=base_url, api_key="not-needed")
        models = client.models.list()
        if models.data:
            return models.data[0].id
    except Exception:
        pass
    return "local-model"


def _detect_provider() -> tuple[str, str]:
    """Detect provider and default model from environment variables.

    Returns:
        (provider, model) — provider is "local", "openrouter", or "openai".
    """
    model = os.environ.get("MLE_BEAST_MODEL", "")

    if os.environ.get("LOCAL_LLM_BASE_URL"):
        if not model:
            model = _auto_detect_local_model(os.environ["LOCAL_LLM_BASE_URL"])
        return "local", model

    if os.environ.get("OPENROUTER_API_KEY"):
        if not model:
            model = "google/gemini-3-flash-preview"
        return "openrouter", model

    if os.environ.get("OPENAI_API_KEY"):
        if not model:
            model = "gpt-5-mini"
        return "openai", model

    # No provider configured — return a sentinel so imports don't fail.
    # get_client() will raise at call time instead.
    return "none", "none"


PROVIDER, MODEL = _detect_provider()


def _resolve_provider(settings=None) -> str:
    """Return the effective provider: settings override if set, else env-detected."""
    if settings is not None and settings.model_provider:
        return settings.model_provider
    return PROVIDER


def get_model_name(settings=None) -> str:
    """Return the model name: settings override if set, else env-detected MODEL."""
    if settings is not None and settings.model_name:
        return settings.model_name
    return MODEL


def get_client(settings=None) -> instructor.Instructor:
    """Return an Instructor client for the active provider.

    Uses settings.model_provider when set, otherwise falls back to env detection.
    """
    provider = _resolve_provider(settings)
    if provider == "none":
        raise RuntimeError(
            "No LLM provider configured. "
            "Set LOCAL_LLM_BASE_URL, OPENROUTER_API_KEY, or OPENAI_API_KEY."
        )
    if provider == "local":
        base_url = os.environ.get("LOCAL_LLM_BASE_URL", "http://localhost:8000/v1")
        oai = OpenAI(
            base_url=base_url,
            api_key=os.environ.get("LOCAL_LLM_API_KEY", "not-needed"),
        )
        return instructor.from_openai(oai, mode=instructor.Mode.JSON)
    elif provider == "openrouter":
        oai = OpenAI(
            base_url="https://openrouter.ai/api/v1",
            api_key=os.environ.get("OPENROUTER_API_KEY", ""),
            timeout=300.0,
            max_retries=0,
        )
        return instructor.from_openai(oai, mode=instructor.Mode.JSON)
    else:
        model = get_model_name(settings)
        return instructor.from_provider("openai/" + model, mode=instructor.Mode.JSON)


def max_tokens_kwarg(max_tokens: int = 4096, settings=None) -> dict:
    """Return the correct max-tokens kwarg for the current provider.

    gpt-5-mini requires max_completion_tokens; other providers use max_tokens.
    """
    provider = _resolve_provider(settings)
    if provider == "openai":
        return {"max_completion_tokens": max_tokens}
    return {"max_tokens": max_tokens}


def extract_usage(completion) -> dict:
    """Pull token + cost fields out of a raw OpenAI completion object.

    Returns a dict with optional keys: prompt_tokens, completion_tokens,
    reasoning_tokens, cached_tokens, cost_usd. Missing fields are
    omitted (not zeroed) so downstream code can distinguish "unreported"
    from "zero". Safe on any input — returns {} if usage is missing.

    OpenRouter responses include a `usage.cost` field in USD; OpenAI
    direct and most local models do not.
    """
    try:
        usage = getattr(completion, "usage", None)
        if usage is None:
            return {}
        out: dict = {}
        for src, dst in [
            ("prompt_tokens", "prompt_tokens"),
            ("completion_tokens", "completion_tokens"),
        ]:
            val = getattr(usage, src, None)
            if val is not None:
                out[dst] = int(val)
        # cost (OpenRouter only)
        cost = getattr(usage, "cost", None)
        if cost is not None:
            out["cost_usd"] = float(cost)
        # reasoning tokens (deepseek-v4-pro, gpt-5, etc.)
        ctd = getattr(usage, "completion_tokens_details", None)
        if ctd is not None:
            r = getattr(ctd, "reasoning_tokens", None)
            if r is not None:
                out["reasoning_tokens"] = int(r)
        # cached tokens (prompt caching)
        ptd = getattr(usage, "prompt_tokens_details", None)
        if ptd is not None:
            c = getattr(ptd, "cached_tokens", None)
            if c is not None:
                out["cached_tokens"] = int(c)
        return out
    except Exception:
        return {}


def emit_llm_call_event(
    messages: list[dict],
    result,
    response_model,
    duration_ms: int,
    completion=None,
) -> None:
    """Emit an LLMCall event so the dashboard can surface the actual
    conversation (prompt + structured response) for each round-trip.

    Public — meant to be called from any code path that talks to the
    LLM directly (e.g. the actor's tool loop in nodes/base.py uses
    client.chat.completions.create instead of call_llm) so the trace
    is complete.

    `completion` is the raw OpenAI ChatCompletion (from
    create_with_completion). If provided, token counts and cost are
    extracted and persisted to the LLMCall event AND rolled up into
    the per-run aggregates on the runs row.

    Wrapped in try/except — observability must never break a real call.
    """
    try:
        from mle_beast.events import LLMCall, get_current_run_id, get_event_bus
    except Exception:
        return
    rid = get_current_run_id()
    if not rid:
        return  # standalone test / no run context

    # Capture the full conversation for the LLMCall event so the dashboard
    # can render exactly what the model saw. Per-message cap (50K chars) is
    # a safety bound against runaway context — far above typical agent
    # messages but small enough that the events table doesn't balloon if
    # something pastes a giant file into a prompt.
    PER_MSG_CAP = 50_000
    trimmed = []
    for m in messages:
        content = m.get("content") if isinstance(m, dict) else getattr(m, "content", "")
        original_len = len(content) if isinstance(content, str) else len(str(content))
        if isinstance(content, str) and len(content) > PER_MSG_CAP:
            content = content[:PER_MSG_CAP] + f"\n... [truncated, original was {original_len} chars]"
        elif not isinstance(content, str):
            content = str(content)[:PER_MSG_CAP]
        trimmed.append({
            "role": (m.get("role") if isinstance(m, dict) else getattr(m, "role", "user")) or "user",
            "content": content,
            "char_count": original_len,
        })

    # Dump structured response to a JSON-friendly dict.
    response_dict: dict = {}
    try:
        if hasattr(result, "model_dump"):
            response_dict = result.model_dump()
        else:
            response_dict = dict(result) if result is not None else {}
    except Exception:
        response_dict = {"_repr": repr(result)[:2000]}

    usage = extract_usage(completion) if completion is not None else {}

    try:
        bus = get_event_bus()
        bus.emit(LLMCall(
            run_id=rid,
            messages=trimmed,
            response=response_dict,
            response_model=getattr(response_model, "__name__", str(response_model)),
            model=MODEL,
            duration_ms=duration_ms,
            **usage,
        ))
    except Exception:
        pass

    # Roll up into per-run aggregate so the dashboard can show running
    # totals without scanning every event each refresh.
    if usage:
        try:
            from mle_beast.db import get_database
            get_database().add_run_usage(
                rid,
                cost_usd=usage.get("cost_usd", 0.0),
                prompt_tokens=usage.get("prompt_tokens", 0),
                completion_tokens=usage.get("completion_tokens", 0),
                reasoning_tokens=usage.get("reasoning_tokens", 0),
            )
        except Exception:
            pass


def call_llm(response_model, messages: list[dict], **kwargs):
    """Single-shot LLM call returning a validated Pydantic model.

    Retries up to LLM_CALL_RETRIES times on transient failures.
    Emits an LLMCall event after each successful call so the dashboard
    can render the actual conversation.

    Args:
        response_model: Pydantic model class to validate against.
        messages: Chat messages (system + user + assistant).
        **kwargs: Extra kwargs forwarded to the completions call.

    Returns:
        An instance of response_model.
    """
    client = get_client()
    max_tokens = kwargs.pop("max_tokens", 4096)
    for attempt in range(LLM_CALL_RETRIES):
        try:
            t0 = time.time()
            result, completion = client.chat.completions.create_with_completion(
                response_model=response_model,
                messages=messages,
                model=MODEL,
                **max_tokens_kwarg(max_tokens),
                **kwargs,
            )
            duration_ms = int((time.time() - t0) * 1000)
            emit_llm_call_event(
                messages, result, response_model, duration_ms,
                completion=completion,
            )
            return result
        except Exception as e:
            # Capture the chain — InstructorRetryException wraps the
            # underlying validation/HTTP error in __cause__/last_completion.
            cause = getattr(e, "__cause__", None) or getattr(e, "last_completion", None)
            cause_repr = repr(cause)[:300] if cause else "no __cause__"
            print(
                f"  call_llm failed (attempt {attempt + 1}/{LLM_CALL_RETRIES}): "
                f"{type(e).__name__}: {str(e)[:200]} | cause: {cause_repr}"
            )
            if attempt + 1 >= LLM_CALL_RETRIES:
                raise
            time.sleep(2 ** attempt)
