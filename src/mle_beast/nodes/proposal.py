# Copyright 2026 Chris Padwick
# SPDX-License-Identifier: Apache-2.0

"""ProposalActorNode + ProposalCriticNode — hill-climb experiment proposer.

Each iteration of the loop the proposer reads the research log + current code
and produces ONE proposal. The critic checks for duplicates / vagueness.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from mle_beast.llm import call_llm
from mle_beast.models.tool_calls import ProposalToolCall
from mle_beast.nodes.base import BaseActorNode, BaseCriticNode
from mle_beast.prompts.proposal import (
    PROPOSAL_CRITIC_PROMPT,
    PROPOSAL_SYSTEM_PROMPT,
)
from mle_beast.tools.file_ops import read_file


class ProposalVerdict(BaseModel):
    """Verdict from the proposal critic."""

    approved: bool = Field(description="True if proposal should be implemented")
    is_duplicate: bool = Field(
        default=False,
        description="Proposal duplicates a previously failed experiment",
    )
    is_specific: bool = Field(
        default=True,
        description="Proposal is specific enough to implement",
    )
    feedback: str = Field(default="", description="Actionable feedback")


class ProposalActorNode(BaseActorNode):
    """Propose ONE experiment based on the research log and current code."""

    _stage_name = "proposal"
    system_prompt = PROPOSAL_SYSTEM_PROMPT
    tool_call_model = ProposalToolCall
    max_iterations = 15

    def _build_user_prompt(self, prep_res: dict) -> str:
        workspace = prep_res["workspace"]
        shared = prep_res.get("shared", {})

        step = shared.get("step_count", 0) + 1
        max_steps = shared.get("max_steps", 30)
        best_score = shared.get("best_score", "N/A")
        consecutive_failures = shared.get("consecutive_failures", 0)
        experiments = shared.get("experiments", [])
        task = shared.get("task", "")

        prompt = f"User task:\n{task}\n\nWorkspace: {workspace}"
        prompt += f"\n\nThis is experiment step {step} of {max_steps}."
        prompt += f"\nCurrent best validation score: {best_score}"

        # Plateau detection: when failures are stacking up, surface a
        # tag-tally of recent attempts so the proposer's "be bold"
        # instruction in the system prompt has something concrete to
        # escalate from. Without this, the model just keeps suggesting
        # variants on the most-recent theme.
        if consecutive_failures >= 3 and experiments:
            from collections import Counter
            recent = experiments[-min(8, consecutive_failures + 2):]
            tag_counts = Counter(
                (exp.get("tag") or "UNTAGGED") for exp in recent
            )
            tally = ", ".join(
                f"{tag.lower()} ({n}×)"
                for tag, n in tag_counts.most_common()
            )
            prompt += (
                f"\n\nPLATEAU DETECTED: {consecutive_failures} consecutive "
                f"experiments failed to improve. Recent proposal families: "
                f"{tally}.\n"
                f"ESCALATE: Pick a category you have NOT tried recently, "
                f"or that you have only tried once. Different model family "
                f"(if you've been doing feature engineering), different "
                f"loss / output parameterization (if you've been tuning "
                f"hyperparameters), or a structurally different "
                f"architecture. Don't propose another minor tweak."
            )
        elif consecutive_failures > 0:
            prompt += (
                f"\n\nWARNING: {consecutive_failures} consecutive experiments have "
                f"failed to improve the score. Consider trying something "
                f"structurally different."
            )

        if experiments:
            prompt += "\n\nRecent experiments:"
            for exp in experiments[-10:]:
                status = "IMPROVED" if exp["improved"] else "no improvement"
                score = exp.get("score", "N/A")
                if isinstance(score, float) and score not in (
                    float("inf"), float("-inf"),
                ):
                    score = f"{score:.4f}"
                tag = exp.get("tag") or "UNTAGGED"
                prompt += (
                    f"\n  Step {exp['step']} [{tag}]: {exp['hypothesis'][:70]} "
                    f"→ {status} (score={score})"
                )

        prompt += (
            "\n\nRead `data_analysis.md` FIRST for facts about THIS specific "
            "dataset — modality, target distribution, leakage risks, "
            "per-feature stats, modeling implications. Ground your proposal "
            "in those facts rather than generic priors about similar problems. "
            "Then read research_log.md for the experiment history and the "
            "current model.py, train.py, predict.py to understand the code. "
            "Finally propose ONE experiment via mark_complete."
        )

        return prompt

    def post(self, shared: dict, prep_res, exec_res) -> str:
        """Capture the proposal from mark_complete summary."""
        shared["tool_log"] = exec_res
        shared["current_proposal"] = shared.get("last_mark_complete_summary", "")
        return "evaluate"


class ProposalCriticNode(BaseCriticNode):
    """LLM critic for proposals: dedup + specificity check."""

    _stage_name = "proposal_critic"
    _attempt_key = "proposal_critic_attempt"
    critic_max_retries = 3

    def prep(self, shared: dict) -> dict:
        proposal = shared.get("current_proposal", "")
        research_log = read_file("research_log.md")
        return {
            "proposal": proposal,
            "research_log": research_log,
            "shared": shared,
        }

    def _evaluate(self, prep_res: dict) -> ProposalVerdict:
        proposal = prep_res["proposal"]
        research_log = prep_res["research_log"]

        if not proposal:
            return ProposalVerdict(
                approved=False,
                is_specific=False,
                feedback="No proposal text was captured. Re-run the proposer.",
            )

        if research_log.startswith("ERROR"):
            research_log = "(research log not yet present)"

        try:
            return call_llm(
                ProposalVerdict,
                messages=[
                    {"role": "system", "content": PROPOSAL_CRITIC_PROMPT},
                    {
                        "role": "user",
                        "content": (
                            f"Research log:\n{research_log[-30000:]}\n\n"
                            f"Proposal:\n{proposal}"
                        ),
                    },
                ],
            )
        except Exception as e:
            return ProposalVerdict(
                approved=False,
                feedback=f"Proposal critic LLM call failed: {e}",
            )

    def _is_pass(self, verdict: ProposalVerdict) -> bool:
        return verdict.approved

    def post(self, shared: dict, prep_res, verdict) -> str:
        """Override the default critic post() so retry exhaustion doesn't
        kill the pipeline. If the LLM is rate-limited or briefly broken we'd
        rather let the proposal through (and let the implementation /
        smoke-test stage catch real problems) than abort the whole run.
        """
        if self._is_pass(verdict):
            shared["verdict"] = verdict
            return "complete"

        attempt = shared.get(self._attempt_key, 0) + 1
        shared[self._attempt_key] = attempt

        if attempt >= self.critic_max_retries:
            print(
                f"  [ProposalCritic] Max retries ({self.critic_max_retries}) "
                "reached — letting the proposal through to implement."
            )
            shared["verdict"] = verdict
            return "complete"

        feedback = getattr(verdict, "feedback", str(verdict))
        shared.setdefault("feedback_history", []).append(feedback)
        return "retry"
