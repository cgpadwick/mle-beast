# Copyright 2026 Chris Padwick
# SPDX-License-Identifier: Apache-2.0

"""Unit tests for flow wiring.

These tests verify that flows are correctly wired (node connections)
without running the actual LLM. They check structure, not behavior.
"""

import pytest

from pocketflow import Flow

from mle_beast.flows.full_pipeline import build_full_pipeline


class TestFullPipeline:
    def test_builds(self):
        flow = build_full_pipeline()
        assert isinstance(flow, Flow)

    def test_structure(self):
        """Hill-climb pipeline:
          GitSetup → DataAnalysis → DataAnalysisCritic → BaselineGate
            → ... → loop → done

        Per-phase shape (both baseline and iter):
          Train → TrainFinder → TrainFinderCritic → AnalysisCritic →
            Evaluate → EvalFinder → EvalFinderCritic → RecordEval
        """
        from mle_beast.flows.full_pipeline import (
            BaselineGateNode,
            TerminalNode,
        )
        from mle_beast.hillclimb import (
            BaselineEvalNode,
            GitSetupNode,
            HillClimbEvalNode,
        )
        from mle_beast.nodes.analysis import AnalysisCriticNode
        from mle_beast.nodes.baseline import BaselineActorNode
        from mle_beast.nodes.data_analysis import (
            DataAnalysisActorNode,
            DataAnalysisCriticNode,
        )
        from mle_beast.nodes.evaluate import EvaluateActorNode
        from mle_beast.nodes.finder import (
            EvalFinderActorNode,
            EvalFinderCriticNode,
            TrainFinderActorNode,
            TrainFinderCriticNode,
        )
        from mle_beast.nodes.hillclimb_test import HillClimbTestingCriticNode
        from mle_beast.nodes.implement import ImplementActorNode
        from mle_beast.nodes.proposal import (
            ProposalActorNode,
            ProposalCriticNode,
        )

        flow = build_full_pipeline()
        # Start is GitSetup
        assert isinstance(flow.start_node, GitSetupNode)

        # GitSetup -> "complete" -> DataAnalysisActor
        data_analysis = flow.start_node.successors["complete"]
        assert isinstance(data_analysis, DataAnalysisActorNode)

        # DataAnalysisActor -> "evaluate" -> DataAnalysisCritic
        data_analysis_critic = data_analysis.successors["evaluate"]
        assert isinstance(data_analysis_critic, DataAnalysisCriticNode)
        # Critic retry loops back to actor
        assert data_analysis_critic.successors["retry"] is data_analysis

        # Critic complete -> BaselineGate
        gate = data_analysis_critic.successors["complete"]
        assert isinstance(gate, BaselineGateNode)

        # BaselineGate has both "build" (greenfield) and "skip" (brownfield)
        assert "build" in gate.successors
        assert "skip" in gate.successors
        assert isinstance(gate.successors["build"], BaselineActorNode)

        # Both paths converge into baseline_train (TrainingActorNode)
        baseline_train_skip = gate.successors["skip"]
        baseline_actor = gate.successors["build"]
        baseline_test = baseline_actor.successors["evaluate"]
        baseline_train_build = baseline_test.successors["complete"]
        assert baseline_train_skip is baseline_train_build

        # Baseline train → train_finder → train_finder_critic → analysis →
        # baseline_evaluate → eval_finder → eval_finder_critic → BaselineEval
        train_finder = baseline_train_build.successors["evaluate"]
        assert isinstance(train_finder, TrainFinderActorNode)

        train_finder_critic = train_finder.successors["evaluate"]
        assert isinstance(train_finder_critic, TrainFinderCriticNode)

        baseline_critic = train_finder_critic.successors["complete"]
        assert isinstance(baseline_critic, AnalysisCriticNode)

        baseline_evaluate = baseline_critic.successors["complete"]
        assert isinstance(baseline_evaluate, EvaluateActorNode)

        eval_finder = baseline_evaluate.successors["evaluate"]
        assert isinstance(eval_finder, EvalFinderActorNode)

        eval_finder_critic = eval_finder.successors["evaluate"]
        assert isinstance(eval_finder_critic, EvalFinderCriticNode)

        baseline_eval = eval_finder_critic.successors["complete"]
        assert isinstance(baseline_eval, BaselineEvalNode)

        propose = baseline_eval.successors["complete"]
        assert isinstance(propose, ProposalActorNode)

        # Hill-climb loop edges
        propose_critic = propose.successors["evaluate"]
        assert isinstance(propose_critic, ProposalCriticNode)
        implement = propose_critic.successors["complete"]
        assert isinstance(implement, ImplementActorNode)

        iter_test = implement.successors["evaluate"]
        assert isinstance(iter_test, HillClimbTestingCriticNode)
        for action in ("retry", "complete", "abandon", "done"):
            assert action in iter_test.successors, f"missing edge: {action}"
        assert iter_test.successors["abandon"] is propose

        # Iter: train → finder → critic → analysis → evaluate → finder → critic → eval
        iter_train = iter_test.successors["complete"]
        iter_train_finder = iter_train.successors["evaluate"]
        assert isinstance(iter_train_finder, TrainFinderActorNode)
        iter_train_finder_critic = iter_train_finder.successors["evaluate"]
        assert isinstance(iter_train_finder_critic, TrainFinderCriticNode)
        iter_critic = iter_train_finder_critic.successors["complete"]
        assert isinstance(iter_critic, AnalysisCriticNode)
        iter_evaluate = iter_critic.successors["complete"]
        assert isinstance(iter_evaluate, EvaluateActorNode)
        iter_eval_finder = iter_evaluate.successors["evaluate"]
        assert isinstance(iter_eval_finder, EvalFinderActorNode)
        iter_eval_finder_critic = iter_eval_finder.successors["evaluate"]
        assert isinstance(iter_eval_finder_critic, EvalFinderCriticNode)
        iter_eval = iter_eval_finder_critic.successors["complete"]
        assert isinstance(iter_eval, HillClimbEvalNode)
        # iterate routes back to propose; done routes to terminal
        assert iter_eval.successors["iterate"] is propose
        assert isinstance(iter_eval.successors["done"], TerminalNode)
        assert iter_test.successors["done"] is iter_eval.successors["done"]
