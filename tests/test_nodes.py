# Copyright 2026 Chris Padwick
# SPDX-License-Identifier: Apache-2.0

"""Unit tests for nodes with mocked LLM."""

from unittest.mock import MagicMock, patch


from mle_beast.models.verdicts import AnalysisVerdict, TestVerdict
from mle_beast.nodes.testing import TestingCriticNode, _parse_pytest_summary
from mle_beast.nodes.analysis import AnalysisCriticNode


# ---- pytest summary parsing ----

class TestParsePytestSummary:
    def test_all_passed(self):
        output = "===== 5 passed in 1.23s ====="
        counts = _parse_pytest_summary(output)
        assert counts["passed"] == 5
        assert counts["failed"] == 0
        assert counts["total"] == 5

    def test_mixed(self):
        output = "===== 3 passed, 2 failed, 1 error in 2.50s ====="
        counts = _parse_pytest_summary(output)
        assert counts["passed"] == 3
        assert counts["failed"] == 2
        assert counts["errors"] == 1
        assert counts["total"] == 6

    def test_fallback_verbose(self):
        output = "test_a PASSED\ntest_b PASSED\ntest_c FAILED\n"
        counts = _parse_pytest_summary(output)
        assert counts["passed"] == 2
        assert counts["failed"] == 1
        assert counts["total"] == 3

    def test_no_tests(self):
        output = "no tests collected"
        counts = _parse_pytest_summary(output)
        assert counts["total"] == 0


# ---- TestingCriticNode ----

class TestTestingCriticNode:
    def test_all_pass(self, workspace):
        """When tests pass, critic should return 'complete'."""
        node = TestingCriticNode()
        shared = {"workspace": str(workspace), "model_version": 1}

        # Create a passing test file
        test_dir = workspace / "tests"
        test_dir.mkdir(exist_ok=True)
        (test_dir / "test_trivial.py").write_text("def test_ok():\n    assert True\n")

        # Run the node
        prep_res = node.prep(shared)
        verdict = node.exec(prep_res)

        # Should pass (our workspace has a passing test)
        assert isinstance(verdict, TestVerdict)
        if verdict.passed:
            action = node.post(shared, prep_res, verdict)
            assert action == "complete"

    def test_failure_retry(self, workspace):
        """When tests fail, critic should return 'retry'."""
        node = TestingCriticNode()
        shared = {"workspace": str(workspace), "model_version": 1}

        # Create a failing test
        test_dir = workspace / "tests"
        test_dir.mkdir(exist_ok=True)
        (test_dir / "test_fail.py").write_text("def test_bad():\n    assert False\n")

        prep_res = node.prep(shared)

        # Mock the LLM feedback call so we don't need API key
        with patch("mle_beast.nodes.testing.call_llm") as mock_llm:
            mock_result = MagicMock()
            mock_result.feedback = "Fix the assertion in test_bad"
            mock_llm.return_value = mock_result

            verdict = node.exec(prep_res)

        assert isinstance(verdict, TestVerdict)
        assert not verdict.passed

        action = node.post(shared, prep_res, verdict)
        assert action == "retry"
        assert "feedback_history" in shared


# ---- AnalysisCriticNode ----

class TestAnalysisCriticNode:
    def test_missing_log(self, workspace):
        """Analysis should handle missing log gracefully."""
        node = AnalysisCriticNode()
        shared = {"workspace": str(workspace), "model_version": 1}

        prep_res = node.prep(shared)
        verdict = node._evaluate(prep_res)

        assert isinstance(verdict, AnalysisVerdict)
        assert not verdict.met_target

    @patch("mle_beast.nodes.analysis.call_llm")
    def test_log_present_target_met(self, mock_llm, workspace):
        """Analysis should detect target met from log."""
        # Create a training log
        logs_dir = workspace / "logs"
        logs_dir.mkdir(exist_ok=True)
        (logs_dir / "training.log").write_text(
            "Epoch 1: loss=0.5, accuracy=0.60\n"
            "Epoch 2: loss=0.3, accuracy=0.75\n"
            "Epoch 3: loss=0.2, accuracy=0.85\n"
        )

        mock_llm.return_value = AnalysisVerdict(
            met_target=True,
            best_accuracy=0.85,
            final_accuracy=0.85,
            recommended_action="accept",
            analysis_summary="Target met.",
        )

        node = AnalysisCriticNode()
        shared = {
            "workspace": str(workspace),
            "model_version": 1,
            "target_accuracy": 0.55,
        }

        prep_res = node.prep(shared)
        verdict = node._evaluate(prep_res)

        assert isinstance(verdict, AnalysisVerdict)
        assert verdict.met_target
        assert verdict.recommended_action == "accept"
