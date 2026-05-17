# Copyright 2026 Chris Padwick
# SPDX-License-Identifier: Apache-2.0

"""TrainingActorNode — runs the inner tool loop for training.

The LLM discovers the workspace's train.py, launches training, and reports
results. Uses TrainingToolCall discriminated union.
"""

from __future__ import annotations

from mle_beast.models.tool_calls import TrainingToolCall
from mle_beast.nodes.base import BaseActorNode
from mle_beast.prompts.training import TRAINING_SYSTEM_PROMPT


class TrainingActorNode(BaseActorNode):
    """Training actor: discovers CLI, launches training, reports results."""

    _stage_name = "training"
    system_prompt = TRAINING_SYSTEM_PROMPT
    tool_call_model = TrainingToolCall
    # Sentinel: max_iterations is overridden from settings in exec()
    max_iterations = 15

    def exec(self, prep_res: dict) -> list[str]:
        from mle_beast.settings import Settings
        settings: Settings = prep_res.get("shared", {}).get("settings") or Settings()
        self.max_iterations = settings.max_tool_iterations_training
        return super().exec(prep_res)

    def _build_user_prompt(self, prep_res: dict) -> str:
        shared = prep_res.get("shared", {})
        workspace = prep_res["workspace"]
        feedback = prep_res.get("feedback_history", [])
        # Baseline phase = step_count == 0. After BaselineEval increments
        # past zero (or the hill-climb starts), this is False.
        is_baseline = shared.get("step_count", 0) == 0

        if feedback:
            prompt = (
                "PHASE: RETRY (previous training failed)\n"
                "CRITICAL: You MUST fix the code before launching again.\n"
                "READ the files, EDIT the code, THEN launch training.\n\n"
                "Failure details from analysis:\n"
            )
            for i, fb in enumerate(feedback, 1):
                prompt += f"  {i}. {fb}\n"
            prompt += f"\nWorkspace: {workspace}"
        elif is_baseline:
            # Strict no-edit policy: the pipeline needs the *starting* score
            # from the existing code, not a covertly-improved version. Any
            # improvements belong in the hill-climb loop's proposals.
            prompt = (
                "PHASE: BASELINE — run the existing train.py AS-IS.\n"
                "Do NOT call edit_file or write_file. Do NOT 'improve' "
                "feature engineering, hyperparameters, model architecture,\n"
                "or anything else. The hill-climb's Propose/Implement stages "
                "are where improvements happen — not here.\n"
                "Allowed: read_file (to discover CLI/usage), list_files,\n"
                "run_python_file (only for --help), check_cuda, "
                "launch_training, mark_complete.\n"
                f"\nWorkspace: {workspace}"
            )
        else:
            # Hill-climb training: an ImplementActor has already written the
            # proposed change. Just run it and report the score.
            prompt = (
                "PHASE: HILL-CLIMB — an ImplementActor has applied a proposal.\n"
                "Launch training on the modified code and report the score.\n"
                "STRICT NO-EDIT POLICY: Do NOT call edit_file or write_file. "
                "The Implementer's code is final for this iteration; if you "
                "edit it you will mask whether the proposal worked. The "
                "MANDATORY PRE-FLIGHT CHECK in the system prompt does NOT "
                "apply here — it is RETRY-only. If training has problems, "
                "let it fail; AnalysisCritic will route to a retry round "
                "where edits ARE allowed.\n"
                "Allowed: read_file (to discover CLI/usage), list_files,\n"
                "run_python_file (only for --help), check_cuda, "
                "launch_training, mark_complete.\n"
                f"\nWorkspace: {workspace}"
            )

        training_script = shared.get("training_script", "train.py")
        prompt += f"\nTraining script: {training_script}"

        dataset_path = shared.get("dataset_path")
        if dataset_path:
            prompt += f"\nDataset path: {dataset_path}"

        target_accuracy = shared.get("target_accuracy")
        if target_accuracy is not None:
            prompt += f"\nTarget accuracy: {target_accuracy}"

        device = shared.get("device", "cpu")
        prompt += f"\nIMPORTANT: Pass --device {device} to the training script."

        return prompt
