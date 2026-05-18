# Copyright 2026 Chris Padwick
# SPDX-License-Identifier: Apache-2.0

"""Unit tests for DataAnalysisCriticNode procedural validation.

The critic checks that data_analysis.md exists, has reasonable length, and
mentions every ALWAYS section by either heading or inline keyword. It does
not call the LLM — it's procedural by design.
"""

from __future__ import annotations

from pathlib import Path

from mle_beast.nodes.data_analysis import (
    DataAnalysisCriticNode,
    _check_artifact,
)

COMPLETE_ARTIFACT = """\
# Data Analysis — Test

## Inventory
- data/train.csv (4471 bytes)
- data/test.csv (1688 bytes)

## Modality
Tabular CSV with 4 columns.

## Sample size
400 train rows, 150 test rows.

## Target
`churned`, binary 0/1, 40% positive.

## Splits
train.csv vs test.csv, user-provided.

## Leakage risks
The `churned` column is present in test.csv. Drop it from features.

## Preprocessing recommendations
One-hot encode `plan`, standardize numerics.

## Modeling implications
Tree ensembles are the right starting point for this 400-row tabular task.
"""


def _make_workspace(tmp_path: Path, content: str | None) -> Path:
    if content is not None:
        (tmp_path / "data_analysis.md").write_text(content)
    return tmp_path


def test_complete_artifact_passes(tmp_path: Path):
    ws = _make_workspace(tmp_path, COMPLETE_ARTIFACT)
    verdict = _check_artifact(ws)
    assert verdict.passed, verdict.feedback
    assert verdict.missing_sections == []


def test_missing_file_fails(tmp_path: Path):
    ws = _make_workspace(tmp_path, None)
    verdict = _check_artifact(ws)
    assert not verdict.passed
    assert "(file)" in verdict.missing_sections
    assert "not written" in verdict.feedback.lower()


def test_too_short_fails(tmp_path: Path):
    ws = _make_workspace(tmp_path, "# tiny\nnothing here")
    verdict = _check_artifact(ws)
    assert not verdict.passed
    assert "too short" in verdict.feedback.lower()


def test_missing_leakage_section_fails(tmp_path: Path):
    # Remove the leakage block; everything else stays
    content = COMPLETE_ARTIFACT.replace(
        "## Leakage risks\nThe `churned` column is present in test.csv. Drop it from features.\n\n",
        "",
    )
    # Pad to satisfy the length check so we're testing the section check
    content += "x" * 500
    ws = _make_workspace(tmp_path, content)
    verdict = _check_artifact(ws)
    assert not verdict.passed
    assert "Leakage" in verdict.missing_sections


def test_missing_modality_section_fails(tmp_path: Path):
    content = COMPLETE_ARTIFACT.replace(
        "## Modality\nTabular CSV with 4 columns.\n\n", ""
    )
    content += "x" * 500
    ws = _make_workspace(tmp_path, content)
    verdict = _check_artifact(ws)
    assert not verdict.passed
    assert "Modality" in verdict.missing_sections


def test_inline_mentions_satisfy_sections(tmp_path: Path):
    """The critic accepts inline mentions, not just headings."""
    inline = (
        "An exploration of the dataset inventory. The modality is image. "
        "Sample size is 1000 with explicit train/test split via filename. "
        "The target label is class index. No leakage detected. "
        "Preprocessing: standard normalization and tokenization. "
        "Modeling implications: ResNet variants are appropriate. "
        + "x" * 300
    )
    ws = _make_workspace(tmp_path, inline)
    verdict = _check_artifact(ws)
    assert verdict.passed, f"expected pass, got {verdict}"


def test_critic_post_retries_on_first_fail(tmp_path: Path):
    """First failure should produce a retry signal + populate feedback_history."""
    critic = DataAnalysisCriticNode()
    shared = {"workspace": str(tmp_path)}
    (tmp_path / "data_analysis.md").write_text("# tiny\n")
    prep = critic.prep(shared)
    verdict = critic._evaluate(prep)
    decision = critic.post(shared, prep, verdict)
    assert decision == "retry"
    assert shared.get("data_analysis_critic_attempt") == 1
    assert len(shared.get("feedback_history", [])) == 1


def test_critic_completes_on_pass(tmp_path: Path):
    critic = DataAnalysisCriticNode()
    shared = {"workspace": str(tmp_path)}
    (tmp_path / "data_analysis.md").write_text(COMPLETE_ARTIFACT)
    prep = critic.prep(shared)
    verdict = critic._evaluate(prep)
    decision = critic.post(shared, prep, verdict)
    assert decision == "complete"
    # Passing run should clear feedback history
    assert shared.get("feedback_history", []) == []


def test_critic_completes_on_retry_exhaustion(tmp_path: Path):
    """After max_retries, the critic should complete (not crash) with
    a failing verdict so downstream stages can proceed."""
    critic = DataAnalysisCriticNode()
    critic.critic_max_retries = 2
    shared = {"workspace": str(tmp_path)}
    (tmp_path / "data_analysis.md").write_text("# tiny\n")
    prep = critic.prep(shared)
    # First attempt → retry
    v1 = critic._evaluate(prep)
    d1 = critic.post(shared, prep, v1)
    assert d1 == "retry"
    # Second attempt → still bad → complete (max_retries hit)
    v2 = critic._evaluate(prep)
    d2 = critic.post(shared, prep, v2)
    assert d2 == "complete"
    assert not shared["verdict"].passed
