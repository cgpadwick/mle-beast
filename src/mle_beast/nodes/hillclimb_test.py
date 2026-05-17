# Copyright 2026 Chris Padwick
# SPDX-License-Identifier: Apache-2.0

"""HillClimbTestingCriticNode — TestingCritic with abandon-on-retry-exhaust.

Inside the hill-climb loop, when smoke tests fail repeatedly the right move is
to abandon the experiment (revert the bad code via git + clean untracked
debris) and route back to the proposer, NOT raise a RuntimeError that kills
the whole run. This subclass of TestingCriticNode does exactly that.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

from mle_beast.nodes.testing import TestingCriticNode


class HillClimbTestingCriticNode(TestingCriticNode):
    """TestingCritic for use inside the hill-climb loop.

    On retry exhaustion: git checkout + git clean to revert the experiment,
    append an ABANDONED entry to research_log.md (preserving prior failure
    entries via save/restore), bump consecutive_failures, and route back to
    the proposer.
    """

    _stage_name = "hillclimb_test"
    _attempt_key = "hillclimb_test_attempt"

    def post(self, shared: dict, prep_res, verdict) -> str:
        if self._is_pass(verdict):
            shared["verdict"] = verdict
            return "complete"

        attempt = shared.get(self._attempt_key, 0) + 1
        shared[self._attempt_key] = attempt

        if attempt < self.critic_max_retries:
            feedback = getattr(verdict, "feedback", str(verdict))
            shared.setdefault("feedback_history", []).append(feedback)
            return "retry"

        # Retries exhausted — abandon this experiment.
        workspace = Path(shared.get("workspace", ""))
        log_path = workspace / "research_log.md"

        # Save research_log.md before checkout so prior uncommitted failure
        # entries persist.
        saved_log = (
            log_path.read_text(encoding="utf-8") if log_path.exists() else ""
        )

        # Revert tracked changes and remove untracked debris.
        try:
            subprocess.run(
                ["git", "checkout", "--", "."],
                cwd=str(workspace), capture_output=True, timeout=30,
            )
            subprocess.run(
                ["git", "clean", "-fd"],
                cwd=str(workspace), capture_output=True, timeout=30,
            )
        except Exception:
            pass

        if saved_log:
            try:
                log_path.write_text(saved_log, encoding="utf-8")
            except Exception:
                pass

        step = shared.get("step_count", 0) + 1
        proposal = shared.get("current_proposal", "") or f"step {step}"
        hypothesis = proposal[:120].replace("\n", " ")

        try:
            with open(log_path, "a", encoding="utf-8") as f:
                f.write(
                    f"## Experiment {step}\n"
                    f"- **Hypothesis**: {hypothesis}\n"
                    f"- **Result**: ABANDONED — smoke tests failed after "
                    f"{self.critic_max_retries} attempts (reverted)\n\n"
                )
        except Exception:
            pass

        shared.setdefault("experiments", []).append({
            "step": step,
            "hypothesis": hypothesis,
            "score": float("inf"),
            "improved": False,
        })
        shared["step_count"] = step
        shared["consecutive_failures"] = (
            shared.get("consecutive_failures", 0) + 1
        )
        shared["feedback_history"] = []
        for k in list(shared.keys()):
            if k.endswith("_attempt"):
                shared[k] = 0

        max_steps = shared.get("max_steps", 30)
        max_failures = shared.get("max_consecutive_failures", 10)
        print(
            f"  [HillClimbTest] Step {step}: ABANDONED after "
            f"{self.critic_max_retries} smoke-test retries (reverted)."
        )

        if step >= max_steps:
            print(f"  [HillClimbTest] Budget exhausted ({max_steps} steps).")
            from mle_beast.hillclimb import _commit_research_log_if_dirty
            _commit_research_log_if_dirty(workspace, reason="end of hill-climb")
            return "done"
        if shared["consecutive_failures"] >= max_failures:
            print(
                f"  [HillClimbTest] Converged "
                f"({max_failures} consecutive failures)."
            )
            from mle_beast.hillclimb import _commit_research_log_if_dirty
            _commit_research_log_if_dirty(workspace, reason="end of hill-climb")
            return "done"
        return "abandon"
