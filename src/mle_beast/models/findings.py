# Copyright 2026 Chris Padwick
# SPDX-License-Identifier: Apache-2.0

"""Structured outputs of the Finder actor.

Two schemas — one for "what came out of training", one for "what came out
of evaluation". The Finder claims paths and values; FinderCritic verifies.

Designed to be permissive about what the user's train.py / evaluate.py
actually produces — most fields are optional. The critic checks that the
required ones are present and that paths exist.
"""

from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field


class TrainingFindings(BaseModel):
    """What the Finder discovered after a training run.

    Bare minimum: training_log_path. Everything else is best-effort.
    """

    training_log_path: str = Field(
        description=(
            "Path (relative to workspace) to the training log file the "
            "training script produced. Common conventions: "
            "logs/training.log, training.log, runs/last/log.txt."
        )
    )
    checkpoint_path: Optional[str] = Field(
        default=None,
        description=(
            "Path to the saved model checkpoint the training run produced. "
            "Prefer the 'best' checkpoint when multiple exist (e.g. by "
            "validation metric), otherwise the final one. Examples: "
            "checkpoints/best.pt, models/model.pt, runs/exp1/best.ckpt. "
            "Set to null only if no checkpoint was saved."
        ),
    )
    best_metric_value: Optional[float] = Field(
        default=None,
        description=(
            "If the training log explicitly reports a 'best' metric on the "
            "validation set (e.g. 'best val_acc: 0.83'), capture it here. "
            "Optional — leave null if not clearly stated."
        ),
    )
    best_metric_name: Optional[str] = Field(
        default=None,
        description="Name of the metric in best_metric_value, if known.",
    )
    notes: str = Field(
        default="",
        description=(
            "Free-form: anything notable about the artifacts (e.g. multiple "
            "checkpoints saved, training appears to have crashed, etc.)."
        ),
    )


class EvalFindings(BaseModel):
    """What the Finder discovered after an evaluation run.

    The whole point is metric_value + metric_name. The critic verifies
    both are sensible numbers/strings, not the no-score sentinel.
    """

    metric_value: float = Field(
        description=(
            "The numeric metric value produced by the evaluation script. "
            "Must be a finite number; do not use inf/-inf/NaN as sentinels."
        )
    )
    metric_name: str = Field(
        description=(
            "Name of the metric (e.g. 'accuracy', 'f1_macro', 'rmse'). "
            "Should match the run's configured metric_name when one is set."
        )
    )
    split: str = Field(
        default="test",
        description="Which data split was evaluated (e.g. 'test', 'val').",
    )
    eval_log_path: Optional[str] = Field(
        default=None,
        description=(
            "Path to the eval log/output file (relative to workspace). "
            "Examples: logs/eval.log, eval_results.json, results.txt."
        ),
    )
    source: str = Field(
        default="",
        description=(
            "Brief: where the value came from (e.g. 'eval_results.json', "
            "'stdout: \"Test accuracy: 0.83\"', 'parsed from results.csv'). "
            "Helps the critic's verification."
        ),
    )
    extra: dict = Field(
        default_factory=dict,
        description=(
            "Optional additional metrics found alongside (precision, recall, "
            "n_samples, etc.). Display-only; not used by hill-climb."
        ),
    )
