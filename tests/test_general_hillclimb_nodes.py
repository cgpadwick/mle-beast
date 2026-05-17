# Copyright 2026 Chris Padwick
# SPDX-License-Identifier: Apache-2.0

"""Unit tests for the general-mode hill-climb nodes.

Covers BaselineActorNode, ProposalActorNode/Critic, ImplementActorNode,
and HillClimbTestingCriticNode (abandon path).
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from unittest.mock import patch

import pytest

from mle_beast.models.tool_calls import CodingToolCall, ProposalToolCall
from mle_beast.nodes.baseline import BaselineActorNode
from mle_beast.nodes.hillclimb_test import HillClimbTestingCriticNode
from mle_beast.nodes.implement import ImplementActorNode
from mle_beast.nodes.proposal import (
    ProposalActorNode,
    ProposalCriticNode,
    ProposalVerdict,
)
from mle_beast.models.verdicts import TestVerdict


@pytest.fixture
def workspace(tmp_path: Path) -> Path:
    """Workspace with a git repo on the experiments branch and a baseline commit."""
    subprocess.run(["git", "init"], cwd=tmp_path, capture_output=True, check=True)
    subprocess.run(
        ["git", "config", "user.email", "test@example.com"],
        cwd=tmp_path, capture_output=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "Test"],
        cwd=tmp_path, capture_output=True,
    )
    (tmp_path / "research_log.md").write_text(
        "# Research Log\n\n## Baseline\n- **Score**: 0.5 (lower-is-better)\n",
        encoding="utf-8",
    )
    (tmp_path / "model.py").write_text("# baseline model\n", encoding="utf-8")
    subprocess.run(
        ["git", "add", "-A"], cwd=tmp_path, capture_output=True, check=True,
    )
    subprocess.run(
        ["git", "commit", "-m", "baseline"],
        cwd=tmp_path, capture_output=True, check=True,
    )
    subprocess.run(
        ["git", "checkout", "-b", "experiments"],
        cwd=tmp_path, capture_output=True, check=True,
    )
    return tmp_path


class TestBaselineActorNode:
    def test_uses_coding_tool_call_union(self):
        node = BaselineActorNode()
        assert node.tool_call_model is CodingToolCall

    def test_user_prompt_no_versioning(self):
        node = BaselineActorNode()
        prep = {
            "task": "predict X",
            "workspace": "/tmp/ws",
            "shared": {"dataset_path": "/tmp/data"},
            "feedback_history": [],
        }
        prompt = node._build_user_prompt(prep)
        assert "model_v" not in prompt
        assert "version" not in prompt.lower()
        assert "BASELINE" in prompt or "baseline" in prompt.lower()


class TestProposalActorNode:
    def test_uses_proposal_tool_call_union(self):
        node = ProposalActorNode()
        assert node.tool_call_model is ProposalToolCall

    def test_user_prompt_includes_history(self):
        node = ProposalActorNode()
        shared = {
            "step_count": 2,
            "max_steps": 30,
            "best_score": 0.05,
            "consecutive_failures": 1,
            "experiments": [
                {"step": 1, "hypothesis": "use XGBoost", "score": 0.06,
                 "improved": True},
                {"step": 2, "hypothesis": "deeper net", "score": 0.07,
                 "improved": False},
            ],
            "task": "predict X",
        }
        prep = {"workspace": "/tmp/ws", "shared": shared, "task": shared["task"]}
        prompt = node._build_user_prompt(prep)
        assert "experiment step 3 of 30" in prompt
        assert "best validation score: 0.05" in prompt.lower()
        assert "use XGBoost" in prompt
        assert "deeper net" in prompt

    def test_post_captures_proposal(self):
        node = ProposalActorNode()
        shared = {"last_mark_complete_summary": "HYPOTHESIS: try ABC"}
        action = node.post(shared, {}, "exec_log")
        assert action == "evaluate"
        assert shared["current_proposal"] == "HYPOTHESIS: try ABC"


class TestProposalCriticNode:
    def test_empty_proposal_rejected_without_llm(self, workspace, monkeypatch):
        monkeypatch.chdir(workspace)
        from mle_beast.workspace import WorkspaceRegistry
        WorkspaceRegistry.set_workspace(workspace)
        try:
            node = ProposalCriticNode()
            shared = {"current_proposal": "", "workspace": str(workspace)}
            prep = node.prep(shared)
            verdict = node._evaluate(prep)
            assert isinstance(verdict, ProposalVerdict)
            assert not verdict.approved
            assert "No proposal" in verdict.feedback
        finally:
            WorkspaceRegistry.clear_workspace()

    @patch("mle_beast.nodes.proposal.call_llm")
    def test_llm_returns_verdict(self, mock_llm, workspace, monkeypatch):
        monkeypatch.chdir(workspace)
        from mle_beast.workspace import WorkspaceRegistry
        WorkspaceRegistry.set_workspace(workspace)
        try:
            mock_llm.return_value = ProposalVerdict(
                approved=True, feedback="ok",
            )
            node = ProposalCriticNode()
            shared = {
                "current_proposal": "switch to XGBoost",
                "workspace": str(workspace),
            }
            prep = node.prep(shared)
            verdict = node._evaluate(prep)
            assert verdict.approved
            mock_llm.assert_called_once()
        finally:
            WorkspaceRegistry.clear_workspace()


class TestImplementActorNode:
    def test_user_prompt_uses_proposal(self):
        node = ImplementActorNode()
        prep = {
            "task": "predict X",
            "workspace": "/tmp/ws",
            "shared": {"current_proposal": "swap to XGBoost"},
            "feedback_history": [],
        }
        prompt = node._build_user_prompt(prep)
        assert "swap to XGBoost" in prompt
        assert "IMPLEMENT" in prompt


class TestHillClimbTestingCriticNode:
    def test_pass_returns_complete(self, workspace):
        node = HillClimbTestingCriticNode()
        shared = {"workspace": str(workspace)}
        verdict = TestVerdict(passed=True)
        action = node.post(shared, {}, verdict)
        assert action == "complete"

    def test_failure_below_max_returns_retry(self, workspace):
        node = HillClimbTestingCriticNode()
        node.critic_max_retries = 3
        shared = {"workspace": str(workspace)}
        verdict = TestVerdict(passed=False, feedback="boom")
        action = node.post(shared, {}, verdict)
        assert action == "retry"
        assert shared["hillclimb_test_attempt"] == 1
        assert "boom" in shared["feedback_history"]

    def test_max_retries_abandons_and_reverts(self, workspace):
        node = HillClimbTestingCriticNode()
        node.critic_max_retries = 2
        shared = {
            "workspace": str(workspace),
            "step_count": 5,
            "max_steps": 30,
            "max_consecutive_failures": 10,
            "hillclimb_test_attempt": 1,  # already on the last attempt
            "current_proposal": "do something",
            "experiments": [],
            "consecutive_failures": 0,
        }

        # Drop a debris file that should be cleaned up.
        (workspace / "fix_error.py").write_text("# debris", encoding="utf-8")

        verdict = TestVerdict(passed=False, feedback="boom")
        action = node.post(shared, {}, verdict)

        assert action == "abandon"
        assert shared["consecutive_failures"] == 1
        assert shared["step_count"] == 6
        # Debris cleaned
        assert not (workspace / "fix_error.py").exists()
        # Research log got an ABANDONED entry preserved
        log = (workspace / "research_log.md").read_text(encoding="utf-8")
        assert "ABANDONED" in log
        assert "Experiment 6" in log

    def test_done_when_consecutive_failures_threshold(self, workspace):
        node = HillClimbTestingCriticNode()
        node.critic_max_retries = 1
        shared = {
            "workspace": str(workspace),
            "step_count": 9,
            "max_steps": 30,
            "max_consecutive_failures": 10,
            "hillclimb_test_attempt": 0,
            "current_proposal": "x",
            "experiments": [],
            "consecutive_failures": 9,  # one more abandon → 10 → done
        }
        verdict = TestVerdict(passed=False, feedback="boom")
        action = node.post(shared, {}, verdict)
        assert action == "done"
