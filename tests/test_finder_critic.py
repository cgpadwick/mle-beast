# Copyright 2026 Chris Padwick
# SPDX-License-Identifier: Apache-2.0

"""Unit tests for FinderCriticNode value-verification.

The critic must open the cited ground-truth file and reject any
EvalFindings whose claimed metric_value disagrees with what's on disk.
This is the procedural critic that catches LLM hallucination of scores.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from mle_beast.models.findings import EvalFindings
from mle_beast.nodes.finder import (
    EvalFinderCriticNode,
    _ground_truth_metric,
    _parse_test_accuracy,
    _values_match,
)


def _make_node():
    return EvalFinderCriticNode()


def _make_prep(workspace: Path, summary: str, shared: dict | None = None) -> dict:
    return {
        "workspace": str(workspace),
        "kind": "eval",
        "summary": summary,
        "shared": shared or {},
    }


def test_eval_results_json_match_passes(tmp_path: Path):
    (tmp_path / "eval_results.json").write_text(
        json.dumps({"value": 0.7, "metric_name": "accuracy", "split": "test"})
    )
    node = _make_node()
    prep = _make_prep(
        tmp_path,
        json.dumps({"metric_value": 0.7, "metric_name": "accuracy", "split": "test"}),
    )
    verdict = node._evaluate(prep)
    assert verdict.ok, verdict.feedback


def test_eval_results_json_mismatch_rejected(tmp_path: Path):
    (tmp_path / "eval_results.json").write_text(
        json.dumps({"value": 0.7, "metric_name": "accuracy", "split": "test"})
    )
    node = _make_node()
    prep = _make_prep(
        tmp_path,
        json.dumps({"metric_value": 0.793, "metric_name": "accuracy", "split": "test"}),
    )
    verdict = node._evaluate(prep)
    assert not verdict.ok
    assert "mismatch" in verdict.feedback.lower()
    assert "0.793" in verdict.feedback
    assert "0.7" in verdict.feedback


def test_eval_log_match_when_no_results_json(tmp_path: Path):
    logs = tmp_path / "logs"
    logs.mkdir()
    (logs / "eval.log").write_text(
        "Some preamble\nTest accuracy: 0.8500\nWrote results.\n"
    )
    node = _make_node()
    prep = _make_prep(
        tmp_path,
        json.dumps({"metric_value": 0.85, "metric_name": "accuracy", "split": "test"}),
    )
    verdict = node._evaluate(prep)
    assert verdict.ok, verdict.feedback


def test_eval_log_mismatch_rejected(tmp_path: Path):
    logs = tmp_path / "logs"
    logs.mkdir()
    (logs / "eval.log").write_text("Test accuracy: 0.6000\n")
    node = _make_node()
    prep = _make_prep(
        tmp_path,
        json.dumps({"metric_value": 0.91, "metric_name": "accuracy", "split": "test"}),
    )
    verdict = node._evaluate(prep)
    assert not verdict.ok
    assert "mismatch" in verdict.feedback.lower()


def test_no_ground_truth_passes_through(tmp_path: Path):
    # No eval_results.json, no logs/eval.log → critic can't verify, must
    # fall through (don't make the LLM stuck if no ground-truth source
    # is available).
    node = _make_node()
    prep = _make_prep(
        tmp_path,
        json.dumps({"metric_value": 0.5, "metric_name": "accuracy", "split": "test"}),
    )
    verdict = node._evaluate(prep)
    assert verdict.ok


def test_results_json_takes_precedence_over_eval_log(tmp_path: Path):
    # Both files exist with different values — eval_results.json wins.
    (tmp_path / "eval_results.json").write_text(
        json.dumps({"value": 0.8, "metric_name": "accuracy", "split": "test"})
    )
    logs = tmp_path / "logs"
    logs.mkdir()
    (logs / "eval.log").write_text("Test accuracy: 0.5000\n")
    node = _make_node()
    prep = _make_prep(
        tmp_path,
        json.dumps({"metric_value": 0.8, "metric_name": "accuracy", "split": "test"}),
    )
    verdict = node._evaluate(prep)
    assert verdict.ok, verdict.feedback


def test_metric_value_field_alt_key(tmp_path: Path):
    # eval_results.json with "metric_value" key (instead of "value")
    # should still be parsed.
    (tmp_path / "eval_results.json").write_text(
        json.dumps({"metric_value": 0.91, "metric_name": "accuracy"})
    )
    node = _make_node()
    prep = _make_prep(
        tmp_path,
        json.dumps({"metric_value": 0.91, "metric_name": "accuracy", "split": "test"}),
    )
    verdict = node._evaluate(prep)
    assert verdict.ok, verdict.feedback


def test_invalid_results_json_falls_through_to_log(tmp_path: Path):
    (tmp_path / "eval_results.json").write_text("not valid json")
    logs = tmp_path / "logs"
    logs.mkdir()
    (logs / "eval.log").write_text("Test accuracy: 0.42\n")
    node = _make_node()
    prep = _make_prep(
        tmp_path,
        json.dumps({"metric_value": 0.42, "metric_name": "accuracy", "split": "test"}),
    )
    verdict = node._evaluate(prep)
    assert verdict.ok, verdict.feedback


def test_values_match_tolerance():
    # Floating-point near-equality: 0.79999... ~ 0.8.
    assert _values_match(0.7999999, 0.8)
    assert _values_match(0.8000001, 0.8)
    assert not _values_match(0.79, 0.8, tol=1e-4)


def test_parse_test_accuracy_picks_last_match():
    text = "Test accuracy: 0.5000\nLater run\nTest accuracy: 0.8000\n"
    assert _parse_test_accuracy(text) == pytest.approx(0.8)


def test_parse_test_accuracy_handles_validation_phrasing():
    text = "Validation accuracy: 0.65\n"
    assert _parse_test_accuracy(text) == pytest.approx(0.65)


def test_ground_truth_uses_cited_path_when_root_missing(tmp_path: Path):
    # If there's no workspace-root eval_results.json and no logs/eval.log,
    # fall back to whatever the LLM cited (eval_log_path).
    custom = tmp_path / "outputs" / "scores.json"
    custom.parent.mkdir()
    custom.write_text(json.dumps({"value": 0.77, "metric_name": "accuracy"}))
    findings = EvalFindings(
        metric_value=0.77,
        metric_name="accuracy",
        split="test",
        eval_log_path="outputs/scores.json",
    )
    val, src = _ground_truth_metric(tmp_path, findings)
    assert val == pytest.approx(0.77)
    assert "scores.json" in src
