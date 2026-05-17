# Copyright 2026 Chris Padwick
# SPDX-License-Identifier: Apache-2.0

"""EvaluateActorNode — runs the inner tool loop for evaluation.

Mirror of TrainingActorNode. Discovers evaluate.py's CLI, launches it
against the trained checkpoint, reports completion. The Finder node
that runs after this one extracts the actual metric value.
"""

from __future__ import annotations

from mle_beast.models.tool_calls import EvaluateToolCall
from mle_beast.nodes.base import BaseActorNode
from mle_beast.prompts.evaluate import EVALUATE_SYSTEM_PROMPT


class EvaluateActorNode(BaseActorNode):
    """Evaluation actor: launches evaluate.py against the trained model."""

    _stage_name = "evaluate"
    system_prompt = EVALUATE_SYSTEM_PROMPT
    tool_call_model = EvaluateToolCall
    # max_iterations gets overridden in exec() from settings.
    max_iterations = 8

    def exec(self, prep_res: dict) -> list[str]:
        from mle_beast.settings import Settings
        settings: Settings = prep_res.get("shared", {}).get("settings") or Settings()
        # Reuse training's iteration cap — eval has fewer steps but the
        # retry-feedback loop can still need a few rounds.
        self.max_iterations = max(8, settings.max_tool_iterations_training // 2)
        return super().exec(prep_res)

    def _build_user_prompt(self, prep_res: dict) -> str:
        shared = prep_res.get("shared", {})
        workspace = prep_res["workspace"]
        feedback = prep_res.get("feedback_history", [])
        is_baseline = shared.get("step_count", 0) == 0

        # Surface what the TrainFinder discovered, when available — gives
        # the actor a known checkpoint path without having to rediscover.
        train_findings = shared.get("train_findings") or {}
        ckpt = train_findings.get("checkpoint_path")
        train_log = train_findings.get("training_log_path")

        if feedback:
            prompt = (
                "PHASE: RETRY (previous evaluation failed)\n"
                "CRITICAL: read evaluate.py, fix the issue, then re-launch.\n\n"
                "Failure feedback from analysis:\n"
            )
            for i, fb in enumerate(feedback, 1):
                prompt += f"  {i}. {fb}\n"
            prompt += f"\nWorkspace: {workspace}"
        else:
            phase = "BASELINE" if is_baseline else "HILL-CLIMB"
            prompt = (
                f"PHASE: {phase} — run evaluate.py against the trained model.\n"
                "Do NOT call edit_file or write_file. Discover the CLI, "
                "launch evaluate.py, report.\n"
                f"\nWorkspace: {workspace}"
            )

        if ckpt:
            prompt += f"\nTrained checkpoint (from TrainFinder): {ckpt}"
        if train_log:
            prompt += f"\nTraining log (from TrainFinder): {train_log}"

        dataset_path = shared.get("dataset_path")
        if dataset_path:
            prompt += f"\nDataset path: {dataset_path}"

        device = shared.get("device", "cpu")
        prompt += f"\nIMPORTANT: pass --device {device} to evaluate.py."

        metric_name = shared.get("metric_name")
        if metric_name:
            prompt += (
                f"\nThe configured evaluation metric is `{metric_name}`. "
                f"If evaluate.py supports a --metric flag, pass it."
            )

        return prompt
