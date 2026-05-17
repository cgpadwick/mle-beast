# Copyright 2026 Chris Padwick
# SPDX-License-Identifier: Apache-2.0

"""AnalysisCriticNode — reads training logs, LLM produces verdict.

This is a CRITIC node: no tool loop.
- prep(): reads training log file
- exec(): single LLM call for AnalysisVerdict
- post(): returns "retry" or "complete"
"""

from __future__ import annotations

from pathlib import Path

from mle_beast.events import LogMessage, RetryOccurred, StageCompleted
from mle_beast.llm import call_llm
from mle_beast.models.verdicts import AnalysisVerdict
from mle_beast.nodes.base import BaseCriticNode, _emit, _get_run_id
from mle_beast.prompts.analysis import ANALYSIS_SYSTEM_PROMPT
from mle_beast.tools.file_ops import read_file


class AnalysisCriticNode(BaseCriticNode):
    """Read training log and produce an AnalysisVerdict."""

    _stage_name = "analysis"
    _attempt_key = "analysis_attempt"

    def prep(self, shared: dict) -> dict:
        from mle_beast.settings import Settings
        settings: Settings = shared.get("settings") or Settings()
        self.critic_max_retries = settings.max_training_analysis_retries

        # Prefer the path the TrainFinder discovered. Fall back to common
        # default locations if no findings exist (e.g., the finder couldn't
        # produce a valid result and we're in degraded mode).
        train_findings = shared.get("train_findings") or {}
        log_file = train_findings.get("training_log_path")
        if not log_file:
            log_file = shared.get("log_file", "logs/training.log")
        log_content = read_file(log_file)
        # If the discovered path doesn't exist on disk after all (race or
        # bad finder claim), try the conventional fallbacks before giving
        # up — we'd rather analyze SOME log than no log.
        if log_content.startswith("ERROR"):
            for candidate in ("logs/training.log", "training.log"):
                if candidate == log_file:
                    continue
                fallback = read_file(candidate)
                if not fallback.startswith("ERROR"):
                    log_file = candidate
                    log_content = fallback
                    break

        target_accuracy = shared.get("target_accuracy")

        return {
            "log_file": log_file,
            "log_content": log_content,
            "target_accuracy": target_accuracy,
            "shared": shared,
        }

    def _evaluate(self, prep_res: dict) -> AnalysisVerdict:
        from mle_beast.settings import Settings
        shared = prep_res.get("shared", {})
        settings: Settings = shared.get("settings") or Settings()
        trunc_limit = settings.analysis_log_truncation

        log_content = prep_res["log_content"]
        target = prep_res.get("target_accuracy")

        if log_content.startswith("ERROR"):
            return AnalysisVerdict(
                met_target=False,
                recommended_action="continue_iteration",
                feedback=f"Could not read training log: {log_content}",
                analysis_summary="Training log not found or unreadable.",
            )

        # Truncate log for LLM context
        truncated = log_content[-trunc_limit:] if len(log_content) > trunc_limit else log_content

        target_str = f"\nTarget accuracy: {target}" if target else ""

        try:
            verdict = call_llm(
                AnalysisVerdict,
                messages=[
                    {"role": "system", "content": ANALYSIS_SYSTEM_PROMPT},
                    {
                        "role": "user",
                        "content": f"Training log{target_str}:\n{truncated}",
                    },
                ],
            )
            return verdict
        except Exception as e:
            return AnalysisVerdict(
                met_target=False,
                recommended_action="continue_iteration",
                feedback=f"Analysis LLM call failed: {e}",
                analysis_summary=f"Analysis failed: {e}",
            )

    def _is_pass(self, verdict: AnalysisVerdict) -> bool:
        return verdict.met_target or verdict.recommended_action == "accept"

    def post(self, shared: dict, prep_res, verdict) -> str:
        """Override to support `retry_coding` action and to fall through on
        retry exhaustion instead of raising.

        Routing:
        - BASELINE phase + training produced any epochs → "complete"
          (hill-climb will improve; do NOT loop on "low score" because
          that triggers code-edit retries which corrupt the baseline)
        - met_target / accept → "complete" (eval node decides keep/revert)
        - recommended_action == "retry_coding" → "retry_coding" (route back
          to the actor — flow wires this to baseline or implement)
        - otherwise → "retry" until max_retries, then "complete" anyway so
          the eval node sees the bad log and reverts/abandons. Raising here
          would crash the whole pipeline on a single bad training run.
        """
        run_id = _get_run_id(shared)
        stage = self._stage_name

        def _complete(outcome: str = "pass") -> str:
            # Always emit StageCompleted before returning "complete" so
            # the next stage's StageStarted handler doesn't deactivate
            # us back to "pending" and leave a stale display state.
            shared["verdict"] = verdict
            shared["feedback_history"] = []
            shared[self._attempt_key] = 0
            _emit(shared, StageCompleted(
                run_id=run_id, stage=stage, outcome=outcome,
                verdict=str(verdict),
            ))
            return "complete"

        # Baseline-phase short-circuit: if training produced even one epoch
        # of output, that's a successful baseline. Don't let an LLM verdict
        # of "score is low, retry" trigger a code-edit feedback loop —
        # baseline is supposed to measure starting state, not climb.
        is_baseline = shared.get("step_count", 0) == 0
        if is_baseline:
            log = prep_res.get("log_content", "") or ""
            had_training = "Epoch" in log or "epoch " in log
            if had_training:
                print(
                    "  [AnalysisCritic] Baseline phase: training produced "
                    "epoch output; accepting regardless of verdict score."
                )
                return _complete()

        if self._is_pass(verdict):
            return _complete()

        if getattr(verdict, "recommended_action", "") == "retry_coding":
            shared.setdefault("feedback_history", []).append(
                getattr(verdict, "feedback", "")
            )
            _emit(shared, RetryOccurred(
                run_id=run_id, stage=stage, attempt=1,
                max_attempts=self.critic_max_retries,
                feedback=getattr(verdict, "feedback", ""),
            ))
            return "retry_coding"

        attempt = shared.get(self._attempt_key, 0) + 1
        shared[self._attempt_key] = attempt

        if attempt >= self.critic_max_retries:
            print(
                f"  [AnalysisCritic] Max retries ({self.critic_max_retries}) "
                "reached — completing so eval can revert."
            )
            return _complete(outcome="fail")

        shared.setdefault("feedback_history", []).append(
            getattr(verdict, "feedback", "")
        )
        _emit(shared, RetryOccurred(
            run_id=run_id, stage=stage, attempt=attempt + 1,
            max_attempts=self.critic_max_retries,
            feedback=getattr(verdict, "feedback", ""),
        ))
        return "retry"
