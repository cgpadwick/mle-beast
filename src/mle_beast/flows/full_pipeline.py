# Copyright 2026 Chris Padwick
# SPDX-License-Identifier: Apache-2.0

"""Full pipeline — hill-climbing for greenfield and brownfield modes.

Pipeline shape (per phase):

  Train → TrainFinder → TrainFinderCritic → AnalysisCritic →
    Evaluate → EvalFinder → EvalFinderCritic →
      RecordEval (BaselineEval / HillClimbEval)

The Train/Evaluate split lets us score on a separate test pass instead
of parsing whatever the training script chose to print. The Finder pair
discovers the produced artifacts (checkpoint paths, eval metric) so we
don't hardcode filenames or formats.

GitSetup → DataAnalysisActor → DataAnalysisCritic → BaselineGate
                                                    ↓                  ↓
                                                    build (greenfield) skip (brownfield)
                                                    BaselineActor → TestingCritic → BaselineTrain
                                                                                    └── BaselineTrain ──┘
BaselineTrain → TrainFinder → TrainFinderCritic → AnalysisCritic →
  BaselineEvaluate → EvalFinder → EvalFinderCritic → BaselineEval → Propose
  ↓
[Propose → ProposalCritic → Implement → HillClimbTest → Train →
  TrainFinder → TrainFinderCritic → AnalysisCritic →
  Evaluate → EvalFinder → EvalFinderCritic → HillClimbEval] × N
  ↓ done
TerminalNode

Convergence: max_steps OR max_consecutive_failures (HillClimbEval / HillClimbTest
return "done" when either fires).

Brownfield runs SKIP the BaselineActor stage — the user's existing code IS
the baseline; we just train it once to measure the starting score.
"""

from __future__ import annotations

from pocketflow import Flow, Node

from mle_beast.hillclimb import (
    BaselineEvalNode,
    GitSetupNode,
    HillClimbEvalNode,
)
from mle_beast.nodes.analysis import AnalysisCriticNode
from mle_beast.nodes.baseline import BaselineActorNode
from mle_beast.nodes.data_analysis import DataAnalysisActorNode, DataAnalysisCriticNode
from mle_beast.nodes.evaluate import EvaluateActorNode
from mle_beast.nodes.finder import (
    EvalFinderActorNode,
    EvalFinderCriticNode,
    TrainFinderActorNode,
    TrainFinderCriticNode,
)
from mle_beast.nodes.hillclimb_test import HillClimbTestingCriticNode
from mle_beast.nodes.implement import ImplementActorNode
from mle_beast.nodes.proposal import ProposalActorNode, ProposalCriticNode
from mle_beast.nodes.testing import TestingCriticNode
from mle_beast.nodes.training import TrainingActorNode


class BaselineGateNode(Node):
    """Procedural gate: route greenfield to BaselineActor, brownfield past it."""

    _stage_name = "baseline_gate"

    def prep(self, shared: dict) -> dict:
        return {"mode": shared.get("mode", "greenfield")}

    def exec(self, prep_res: dict) -> str:
        return prep_res["mode"]

    def post(self, shared: dict, prep_res, mode: str) -> str:
        if mode == "existing":
            print("  [BaselineGate] brownfield mode — skipping baseline actor.")
            return "skip"
        print("  [BaselineGate] greenfield mode — running baseline actor.")
        return "build"


class TerminalNode(Node):
    """No-op sink so PocketFlow has a well-defined end node for 'done' edges."""

    _stage_name = "done"

    def prep(self, shared: dict) -> None:
        return None

    def exec(self, prep_res) -> None:
        return None

    def post(self, shared: dict, prep_res, exec_res) -> str:
        print("  [Pipeline] hill-climb complete.")
        return "complete"


def build_full_pipeline() -> Flow:
    """Wire the hill-climb pipeline: setup → eda → baseline → loop → done."""
    git_setup = GitSetupNode()
    data_analysis = DataAnalysisActorNode()
    data_analysis_critic = DataAnalysisCriticNode()
    baseline_gate = BaselineGateNode()

    # Baseline path
    baseline_actor = BaselineActorNode()
    baseline_test = TestingCriticNode()
    baseline_train = TrainingActorNode()
    baseline_train_finder = TrainFinderActorNode()
    baseline_train_finder_critic = TrainFinderCriticNode()
    baseline_train_critic = AnalysisCriticNode()
    baseline_evaluate = EvaluateActorNode()
    baseline_eval_finder = EvalFinderActorNode()
    baseline_eval_finder_critic = EvalFinderCriticNode()
    baseline_eval = BaselineEvalNode()

    # Hill-climb iteration
    propose = ProposalActorNode()
    propose_critic = ProposalCriticNode()
    implement = ImplementActorNode()
    iter_test = HillClimbTestingCriticNode()
    iter_train = TrainingActorNode()
    iter_train_finder = TrainFinderActorNode()
    iter_train_finder_critic = TrainFinderCriticNode()
    iter_train_critic = AnalysisCriticNode()
    iter_evaluate = EvaluateActorNode()
    iter_eval_finder = EvalFinderActorNode()
    iter_eval_finder_critic = EvalFinderCriticNode()
    iter_eval = HillClimbEvalNode()

    terminal = TerminalNode()

    # Setup → EDA → BaselineGate
    git_setup - "complete" >> data_analysis
    data_analysis - "evaluate" >> data_analysis_critic
    data_analysis_critic - "retry" >> data_analysis
    data_analysis_critic - "complete" >> baseline_gate

    # ---- Baseline path ----
    baseline_gate - "build" >> baseline_actor
    baseline_gate - "skip" >> baseline_train

    baseline_actor - "evaluate" >> baseline_test
    baseline_test - "retry" >> baseline_actor
    baseline_test - "complete" >> baseline_train

    # Train → TrainFinder → TrainFinderCritic → AnalysisCritic
    baseline_train - "evaluate" >> baseline_train_finder
    baseline_train_finder - "evaluate" >> baseline_train_finder_critic
    baseline_train_finder_critic - "retry" >> baseline_train_finder
    baseline_train_finder_critic - "complete" >> baseline_train_critic
    # AnalysisCritic feedback paths unchanged — retry training, or kick
    # back to the BaselineActor on a "code-level" failure.
    baseline_train_critic - "retry" >> baseline_train
    baseline_train_critic - "retry_coding" >> baseline_actor
    baseline_train_critic - "complete" >> baseline_evaluate

    # Evaluate → EvalFinder → EvalFinderCritic → BaselineEval
    baseline_evaluate - "evaluate" >> baseline_eval_finder
    baseline_eval_finder - "evaluate" >> baseline_eval_finder_critic
    baseline_eval_finder_critic - "retry" >> baseline_eval_finder
    baseline_eval_finder_critic - "complete" >> baseline_eval

    baseline_eval - "complete" >> propose
    baseline_eval - "done" >> terminal

    # ---- Hill-climb iteration ----
    propose - "evaluate" >> propose_critic
    propose_critic - "retry" >> propose
    propose_critic - "complete" >> implement

    implement - "evaluate" >> iter_test
    iter_test - "retry" >> implement
    iter_test - "complete" >> iter_train
    iter_test - "abandon" >> propose
    iter_test - "done" >> terminal

    # Train → TrainFinder → TrainFinderCritic → AnalysisCritic
    iter_train - "evaluate" >> iter_train_finder
    iter_train_finder - "evaluate" >> iter_train_finder_critic
    iter_train_finder_critic - "retry" >> iter_train_finder
    iter_train_finder_critic - "complete" >> iter_train_critic
    iter_train_critic - "retry" >> iter_train
    iter_train_critic - "retry_coding" >> implement
    iter_train_critic - "complete" >> iter_evaluate

    # Evaluate → EvalFinder → EvalFinderCritic → HillClimbEval
    iter_evaluate - "evaluate" >> iter_eval_finder
    iter_eval_finder - "evaluate" >> iter_eval_finder_critic
    iter_eval_finder_critic - "retry" >> iter_eval_finder
    iter_eval_finder_critic - "complete" >> iter_eval

    iter_eval - "iterate" >> propose
    iter_eval - "done" >> terminal

    return Flow(start=git_setup)
