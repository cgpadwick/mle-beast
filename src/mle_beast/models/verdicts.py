# Copyright 2026 Chris Padwick
# SPDX-License-Identifier: Apache-2.0

"""Verdict models for critic nodes.

Each critic returns a structured verdict that drives the retry/complete transition.
"""

from __future__ import annotations

from typing import List, Optional

from pydantic import BaseModel, Field


class TestVerdict(BaseModel):
    """Returned by TestingCriticNode after running pytest and LLM analysis."""

    passed: bool = Field(description="True if all tests passed")
    total: int = Field(default=0, description="Total tests discovered")
    num_passed: int = Field(default=0, description="Tests that passed")
    num_failed: int = Field(default=0, description="Tests that failed")
    failed_tests: List[str] = Field(default_factory=list)
    feedback: str = Field(
        default="",
        description="Actionable feedback for the coding actor if tests failed",
    )


class AnalysisVerdict(BaseModel):
    """Returned by AnalysisCriticNode after reading logs and LLM analysis."""

    met_target: bool = Field(description="True if target accuracy was met")
    best_accuracy: Optional[float] = Field(default=None)
    final_accuracy: Optional[float] = Field(default=None)
    recommended_action: str = Field(
        default="continue_iteration",
        description="accept | continue_iteration | abort",
    )
    feedback: str = Field(
        default="",
        description="Actionable feedback for the training actor if target not met",
    )
    analysis_summary: str = Field(default="")
