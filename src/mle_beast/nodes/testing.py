# Copyright 2026 Chris Padwick
# SPDX-License-Identifier: Apache-2.0

"""TestingCriticNode — runs pytest procedurally, LLM for feedback only.

This is a CRITIC node: it doesn't use the tool loop pattern.
- prep(): identifies test files
- exec(): runs pytest directly, parses results, asks LLM for feedback if failed
- post(): returns "retry" or "complete"
"""

from __future__ import annotations

import re

from mle_beast.llm import call_llm
from mle_beast.models.verdicts import TestVerdict
from mle_beast.nodes.base import BaseCriticNode
from mle_beast.prompts.testing import TESTING_FEEDBACK_PROMPT
from mle_beast.tools.execution import run_tests


class TestingCriticNode(BaseCriticNode):
    """Run pytest and produce a TestVerdict."""

    _stage_name = "testing"
    _attempt_key = "testing_attempt"

    def prep(self, shared: dict) -> dict:
        from mle_beast.settings import Settings
        settings: Settings = shared.get("settings") or Settings()
        self.critic_max_retries = settings.max_code_review_retries
        return {
            "workspace": str(shared.get("workspace", "")),
            "shared": shared,
        }

    def _evaluate(self, prep_res: dict) -> TestVerdict:
        from mle_beast.settings import Settings
        shared = prep_res.get("shared", {})
        settings: Settings = shared.get("settings") or Settings()

        # Run all tests in the workspace
        output = run_tests(verbose=True, timeout=settings.test_timeout)

        # Parse pytest summary
        counts = _parse_pytest_summary(output)
        all_passed = counts["failed"] == 0 and counts["errors"] == 0 and counts["total"] > 0

        if all_passed:
            return TestVerdict(
                passed=True,
                total=counts["total"],
                num_passed=counts["passed"],
                num_failed=0,
                feedback="All tests passed.",
            )

        # Extract failed test names
        failed_tests = re.findall(r"FAILED\s+([\w/:.]+)", output)

        # Ask LLM for actionable feedback
        feedback = _get_llm_feedback(output, settings.testing_llm_context_truncation)

        return TestVerdict(
            passed=False,
            total=counts["total"],
            num_passed=counts["passed"],
            num_failed=counts["failed"],
            failed_tests=failed_tests,
            feedback=feedback,
        )

    def _is_pass(self, verdict: TestVerdict) -> bool:
        return verdict.passed

    def post(self, shared: dict, prep_res, verdict) -> str:
        """On retry exhaustion: complete with the failing verdict instead of
        raising. Downstream stages see a workspace that doesn't pass smoke
        tests and either fail to train (BaselineEval gets inf) or, in the
        hill-climb path, the subclass routes to abandon. Either way, a
        single bad iteration shouldn't crash the whole pipeline.
        """
        if self._is_pass(verdict):
            shared["verdict"] = verdict
            return "complete"

        attempt = shared.get(self._attempt_key, 0) + 1
        shared[self._attempt_key] = attempt

        if attempt >= self.critic_max_retries:
            print(
                f"  [TestingCritic] Max retries ({self.critic_max_retries}) "
                "reached — completing with failing verdict (downstream will "
                "detect missing/broken workspace)."
            )
            shared["verdict"] = verdict
            return "complete"

        feedback = getattr(verdict, "feedback", str(verdict))
        shared.setdefault("feedback_history", []).append(feedback)
        return "retry"


def _parse_pytest_summary(output: str) -> dict:
    """Parse pytest summary line to extract counts."""
    counts = {"total": 0, "passed": 0, "failed": 0, "errors": 0, "skipped": 0}

    summary_match = re.search(r"=+\s*([\d\w\s,]+?)\s*in\s+[\d.]+s?\s*=+", output)
    if summary_match:
        summary_text = summary_match.group(1)
        for part in summary_text.split(","):
            part = part.strip()
            num_match = re.match(r"(\d+)\s+(\w+)", part)
            if num_match:
                count = int(num_match.group(1))
                label = num_match.group(2).lower()
                if label in ("passed",):
                    counts["passed"] = count
                elif label in ("failed",):
                    counts["failed"] = count
                elif label in ("error", "errors"):
                    counts["errors"] = count
                elif label in ("skipped", "deselected"):
                    counts["skipped"] = count
        counts["total"] = counts["passed"] + counts["failed"] + counts["errors"] + counts["skipped"]

    if counts["total"] == 0:
        counts["passed"] = len(re.findall(r" PASSED", output))
        counts["failed"] = len(re.findall(r" FAILED", output))
        counts["errors"] = len(re.findall(r" ERROR", output))
        counts["total"] = counts["passed"] + counts["failed"] + counts["errors"]

    return counts


def _get_llm_feedback(test_output: str, max_chars: int = 3000) -> str:
    """Ask LLM for actionable feedback on test failures."""
    truncated = test_output[-max_chars:] if len(test_output) > max_chars else test_output
    try:
        from pydantic import BaseModel, Field

        class FeedbackResponse(BaseModel):
            feedback: str = Field(description="Actionable feedback for fixing test failures")

        result = call_llm(
            FeedbackResponse,
            messages=[
                {"role": "system", "content": TESTING_FEEDBACK_PROMPT},
                {"role": "user", "content": f"Pytest output:\n{truncated}"},
            ],
        )
        return result.feedback
    except Exception:
        # Fallback: return raw tail of output
        tail = "\n".join(test_output.splitlines()[-20:])
        return f"Tests failed. Output tail:\n{tail}"
