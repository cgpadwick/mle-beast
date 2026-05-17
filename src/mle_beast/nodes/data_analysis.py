# Copyright 2026 Chris Padwick
# SPDX-License-Identifier: Apache-2.0

"""DataAnalysisActorNode + DataAnalysisCriticNode.

First stage of the pipeline after GitSetup. The actor inspects the user's
dataset using read/write/list/run_python tools and produces a single
artifact — `data_analysis.md` at the workspace root — that downstream
stages anchor on. The critic is procedural: it checks the artifact exists,
has reasonable length, and contains the required ALWAYS sections. No
LLM-judgment loop for the critic; if the schema's there, the artifact's
good enough.
"""

from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel, Field

from mle_beast.events import LogMessage, RetryOccurred, StageCompleted
from mle_beast.models.tool_calls import DataAnalysisToolCall
from mle_beast.nodes.base import BaseActorNode, BaseCriticNode, _emit, _get_run_id
from mle_beast.prompts.data_analysis import DATA_ANALYSIS_SYSTEM_PROMPT


class DataAnalysisActorNode(BaseActorNode):
    """Inspect the dataset and produce data_analysis.md at workspace root."""

    _stage_name = "data_analysis"
    system_prompt = DATA_ANALYSIS_SYSTEM_PROMPT
    tool_call_model = DataAnalysisToolCall
    max_iterations = 25

    def _build_user_prompt(self, prep_res: dict) -> str:
        task = prep_res["task"]
        workspace = prep_res["workspace"]
        shared = prep_res.get("shared", {})

        prompt = f"Task:\n{task}\n\nWorkspace root: {workspace}"

        dataset_path = shared.get("dataset_path")
        if dataset_path:
            prompt += f"\nDataset path: {dataset_path}"

        prompt += (
            "\n\nInspect the dataset and produce data_analysis.md at the "
            "workspace root. Follow the WORKFLOW in your system prompt. "
            "When the artifact is ready, call mark_complete."
        )

        feedback = prep_res.get("feedback_history", [])
        if feedback:
            prompt += "\n\nPrevious feedback (address these issues):\n"
            for i, fb in enumerate(feedback, 1):
                prompt += f"  {i}. {fb}\n"

        return prompt


class DataAnalysisVerdict(BaseModel):
    """Procedural verdict on data_analysis.md."""

    passed: bool = Field(description="True if the artifact is complete enough")
    missing_sections: list[str] = Field(
        default_factory=list,
        description="ALWAYS sections that the artifact appears to skip",
    )
    feedback: str = Field(
        default="",
        description="Actionable feedback for the agent on a retry round",
    )


# The ALWAYS sections from DATA_ANALYSIS_SYSTEM_PROMPT. Each entry is a
# tuple of (canonical_label, list_of_substrings_any_of_which_would_satisfy).
# We accept either a heading-style match ("Modality:") or an inline mention
# ("data modality") so we don't over-constrain the agent's formatting.
_REQUIRED_SECTIONS: list[tuple[str, list[str]]] = [
    ("Inventory",    ["inventory"]),
    ("Modality",     ["modality"]),
    ("Sample size",  ["sample size", "samples", "n =", "rows", "examples"]),
    ("Target",       ["target", "label"]),
    ("Splits",       ["split"]),
    ("Leakage",      ["leakage"]),
    ("Preprocessing", ["preprocessing", "normaliz", "encode", "tokeniz"]),
    ("Modeling implications", ["modeling implication", "modeling recommend",
                               "modeling guidance", "models to try",
                               "model choice", "modeling"]),
]


def _check_artifact(workspace: Path) -> DataAnalysisVerdict:
    """Procedural validation of data_analysis.md.

    Passes if the file exists, is at least 400 characters of substantive
    content, and mentions every ALWAYS section by either heading or inline
    keyword. Returns actionable feedback listing the missing sections on
    failure.
    """
    path = workspace / "data_analysis.md"
    if not path.exists():
        return DataAnalysisVerdict(
            passed=False,
            missing_sections=["(file)"],
            feedback=(
                "data_analysis.md was not written to the workspace root. "
                "Write the artifact and call mark_complete."
            ),
        )

    content = path.read_text(encoding="utf-8", errors="ignore")
    if len(content) < 400:
        return DataAnalysisVerdict(
            passed=False,
            feedback=(
                f"data_analysis.md is too short ({len(content)} chars). "
                "Expand it with the required sections (Inventory, Modality, "
                "Sample size, Target, Splits, Leakage risks, Preprocessing, "
                "Modeling implications)."
            ),
        )

    lowered = content.lower()
    missing: list[str] = []
    for label, keywords in _REQUIRED_SECTIONS:
        if not any(kw in lowered for kw in keywords):
            missing.append(label)

    if missing:
        return DataAnalysisVerdict(
            passed=False,
            missing_sections=missing,
            feedback=(
                f"data_analysis.md is missing required sections: "
                f"{', '.join(missing)}. Add them per the ALWAYS list in "
                f"your system prompt, then call mark_complete."
            ),
        )

    return DataAnalysisVerdict(passed=True)


class DataAnalysisCriticNode(BaseCriticNode):
    """Procedural critic: verify data_analysis.md exists and has required sections."""

    _stage_name = "data_analysis_critic"
    _attempt_key = "data_analysis_critic_attempt"
    critic_max_retries = 3

    def prep(self, shared: dict) -> dict:
        return {
            "workspace": str(shared.get("workspace", "")),
            "shared": shared,
        }

    def _evaluate(self, prep_res: dict) -> DataAnalysisVerdict:
        workspace = Path(prep_res["workspace"])
        return _check_artifact(workspace)

    def _is_pass(self, verdict: DataAnalysisVerdict) -> bool:
        return bool(verdict.passed)

    def post(self, shared: dict, prep_res, verdict: DataAnalysisVerdict) -> str:
        run_id = _get_run_id(shared)
        stage = self._stage_name

        if verdict.passed:
            shared["verdict"] = verdict
            shared["feedback_history"] = []
            shared[self._attempt_key] = 0
            _emit(shared, StageCompleted(
                run_id=run_id, stage=stage, outcome="pass",
                verdict=str(verdict),
            ))
            return "complete"

        attempt = shared.get(self._attempt_key, 0) + 1
        shared[self._attempt_key] = attempt

        if attempt >= self.critic_max_retries:
            # Don't crash the run — let downstream stages proceed with
            # whatever artifact (if any) was produced. Modeling will be
            # weaker without good EDA but the pipeline keeps moving.
            _emit(shared, LogMessage(
                run_id=run_id, stage=stage, level="warning",
                message=(
                    f"[DataAnalysisCritic] Max retries ({self.critic_max_retries}) "
                    f"reached — proceeding without a complete data_analysis.md. "
                    f"Missing: {verdict.missing_sections}"
                ),
            ))
            _emit(shared, StageCompleted(
                run_id=run_id, stage=stage, outcome="fail",
                verdict=str(verdict),
            ))
            shared["verdict"] = verdict
            return "complete"

        shared.setdefault("feedback_history", []).append(verdict.feedback)
        _emit(shared, RetryOccurred(
            run_id=run_id, stage=stage, attempt=attempt + 1,
            max_attempts=self.critic_max_retries, feedback=verdict.feedback,
        ))
        return "retry"
