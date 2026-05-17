# Copyright 2026 Chris Padwick
# SPDX-License-Identifier: Apache-2.0

"""ImplementActorNode — implements the proposal produced by ProposalActorNode."""

from __future__ import annotations

from mle_beast.models.tool_calls import ExistingCodeToolCall
from mle_beast.nodes.base import BaseActorNode
from mle_beast.prompts.implement import IMPLEMENT_SYSTEM_PROMPT


class ImplementActorNode(BaseActorNode):
    """Implement the proposed experiment by modifying workspace code in place."""

    _stage_name = "implement"
    system_prompt = IMPLEMENT_SYSTEM_PROMPT
    tool_call_model = ExistingCodeToolCall
    max_iterations = 40

    def _build_user_prompt(self, prep_res: dict) -> str:
        task = prep_res["task"]
        workspace = prep_res["workspace"]
        shared = prep_res.get("shared", {})

        proposal = shared.get("current_proposal", "")

        prompt = f"User task:\n{task}\n\nWorkspace root: {workspace}"
        prompt += f"\n\nIMPLEMENT THE FOLLOWING EXPERIMENT:\n{proposal}"
        prompt += (
            "\n\nFor data facts (schema, target column, distributions, leakage "
            "risks, preprocessing recommendations), read `data_analysis.md` "
            "at the workspace root. It was produced by the EDA stage and "
            "contains the authoritative description of THIS dataset.\n\n"
            "All code lives at the workspace root (model.py, train.py, "
            "predict.py). Modify these files to implement the proposed change. "
            "Checkpoints go to checkpoints/."
        )

        device = shared.get("device", "cpu")
        prompt += f"\nIMPORTANT: Pass --device {device} for all training and evaluation."

        feedback = prep_res.get("feedback_history", [])
        if feedback:
            prompt += "\n\nPrevious feedback (address these issues):\n"
            for i, fb in enumerate(feedback, 1):
                prompt += f"  {i}. {fb}\n"

        return prompt
