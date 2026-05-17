# Copyright 2026 Chris Padwick
# SPDX-License-Identifier: Apache-2.0

"""CodingActorNode — runs the inner tool loop for code generation.

The LLM selects tools via CodingToolCall discriminated union until it emits
mark_complete (or hits the iteration cap).

After the move to a hill-climbing pipeline this node is no longer used by the
default flow (BaselineActorNode + ImplementActorNode replaced it). It's kept
for any external callers that still want a "regenerate-style" coding actor.
"""

from __future__ import annotations

from mle_beast.models.tool_calls import CodingToolCall
from mle_beast.nodes.base import BaseActorNode
from mle_beast.prompts.coding import CODING_SYSTEM_PROMPT


class CodingActorNode(BaseActorNode):
    """Coding actor: creates models, training scripts, tests."""

    _stage_name = "coding"
    system_prompt = CODING_SYSTEM_PROMPT
    tool_call_model = CodingToolCall

    def _build_user_prompt(self, prep_res: dict) -> str:
        task = prep_res["task"]
        workspace = prep_res["workspace"]
        shared = prep_res.get("shared", {})

        prompt = f"Task: {task}\nWorkspace root: {workspace}"

        dataset_path = shared.get("dataset_path")
        if dataset_path:
            prompt += f"\nDataset path: {dataset_path}"

        target_accuracy = shared.get("target_accuracy")
        if target_accuracy is not None:
            prompt += f"\nTarget accuracy: {target_accuracy}"

        device = shared.get("device", "cpu")
        prompt += f"\nIMPORTANT: Pass --device {device} for all training and evaluation."

        feedback = prep_res.get("feedback_history", [])
        if feedback:
            prompt += "\n\nPrevious feedback (address these issues):\n"
            for i, fb in enumerate(feedback, 1):
                prompt += f"  {i}. {fb}\n"

        return prompt
