# Copyright 2026 Chris Padwick
# SPDX-License-Identifier: Apache-2.0

"""BaselineActorNode — builds the initial working model from scratch (greenfield).

Brownfield runs SKIP this stage; the user's existing code IS the baseline.
"""

from __future__ import annotations

from mle_beast.models.tool_calls import ExistingCodeToolCall
from mle_beast.nodes.base import BaseActorNode
from mle_beast.prompts.baseline import BASELINE_SYSTEM_PROMPT


class BaselineActorNode(BaseActorNode):
    """Build the initial baseline solution: model.py, train.py, predict.py."""

    _stage_name = "baseline"
    system_prompt = BASELINE_SYSTEM_PROMPT
    tool_call_model = ExistingCodeToolCall
    max_iterations = 40

    def _build_user_prompt(self, prep_res: dict) -> str:
        task = prep_res["task"]
        workspace = prep_res["workspace"]
        shared = prep_res.get("shared", {})

        prompt = f"Task:\n{task}\n\nWorkspace root: {workspace}"

        dataset_path = shared.get("dataset_path")
        if dataset_path:
            prompt += f"\nDataset path: {dataset_path}"

        target_accuracy = shared.get("target_accuracy")
        if target_accuracy is not None:
            prompt += f"\nTarget accuracy: {target_accuracy}"

        prompt += (
            "\n\nRead `data_analysis.md` at the workspace root FIRST — the EDA "
            "stage already characterized this dataset (modality, target, "
            "leakage risks, preprocessing recommendations). Build your baseline "
            "grounded in those facts.\n\n"
            "Build a SIMPLE BASELINE. Write model.py, train.py, predict.py "
            "to the workspace root, plus tests/test_smoke.py. The goal is a "
            "working pipeline — you will improve the score iteratively in "
            "later steps."
        )

        device = shared.get("device", "cpu")
        prompt += f"\nIMPORTANT: Pass --device {device} for all training and evaluation."

        feedback = prep_res.get("feedback_history", [])
        if feedback:
            prompt += "\n\nPrevious feedback (address these issues):\n"
            for i, fb in enumerate(feedback, 1):
                prompt += f"  {i}. {fb}\n"

        return prompt
