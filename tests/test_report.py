# Copyright 2026 Chris Padwick
# SPDX-License-Identifier: Apache-2.0

"""Unit tests for the HTML report renderer.

These verify the renderer is robust against the shapes of data we
actually see in SQLite (including the unhappy paths: missing scores,
no experiments, missing timestamps, etc.) and that the output has the
structural pieces we promise the user. They do NOT visually inspect
the HTML — that's by-hand against a real workspace.
"""

from __future__ import annotations

from mle_beast.web.report import render_report


def _base_run(**overrides) -> dict:
    base = {
        "id": "abcd1234-5678-90ab-cdef-1234567890ab",
        "status": "completed",
        "workspace": "/tmp/test_ws",
        "task": "Build a baseline classifier on the toy dataset.",
        "target_accuracy": 0.85,
        "dataset_path": "/tmp/test_ws/data",
        "mode": "greenfield",
        "force_cpu": False,
        "created_at": 1779000000.0,
        "started_at": 1779000010.0,
        "completed_at": 1779000610.0,
        "verdict_json": None,
        "error_message": None,
        "experiment_branch": "mle-beast-test",
        "lower_is_better": False,
        "metric_name": "accuracy",
        "environment": None,
        "total_cost_usd": 0.42,
        "total_prompt_tokens": 100000,
        "total_completion_tokens": 5000,
        "total_reasoning_tokens": 0,
        "total_llm_calls": 25,
    }
    base.update(overrides)
    return base


def _exp(step: int, score: float | None, kept: bool, proposal: str = "test") -> dict:
    return {
        "id": step + 1,
        "run_id": "abcd1234-5678-90ab-cdef-1234567890ab",
        "step": step,
        "parent_step": step - 1 if step > 0 else None,
        "proposal": proposal,
        "score": score,
        "lower_is_better": 0,
        "kept": int(kept),
        "tag": None,
        "commit_sha": f"{step:08x}" * 5,
        "created_at": 1779000000.0 + step * 60,
    }


def test_render_completed_run_with_hill_climb():
    run = _base_run()
    experiments = [
        _exp(0, 0.72, True, "Baseline"),
        _exp(1, 0.68, False, "Try deeper model — too slow, reverted"),
        _exp(2, 0.78, True, "Increase L2 regularization"),
        _exp(3, 0.84, True, "Add cosine LR schedule"),
    ]
    html = render_report(run, experiments, peak={"step": 3, "score": 0.84})

    # Structural pieces every report needs
    assert "<!doctype html>" in html.lower()
    assert "mle-beast report" in html.lower()
    # Hero
    assert run["task"] in html
    assert "completed" in html.lower()
    # Stats: best, target, experiments, runtime, cost
    assert "0.8400" in html  # best score
    assert "0.8500" in html  # target
    assert "$0.4200" in html  # llm cost
    # SVG hill-climb chart
    assert "<svg" in html
    assert 'viewBox="0 0 760 320"' in html
    # Experiments table
    assert "Increase L2 regularization" in html
    assert "Add cosine LR schedule" in html
    # The reverted one should still appear in the table
    assert "Try deeper model — too slow, reverted" in html
    # Best-row marker + delta should be present
    assert "★ best" in html or "best" in html.lower()
    # Print stylesheet is present so PDFs come out light
    assert "@media print" in html


def test_render_failed_run_without_experiments():
    run = _base_run(
        status="failed",
        completed_at=None,
        verdict_json=None,
        error_message="BaselineActor raised: ModuleNotFoundError: No module named 'xyz'",
    )
    html = render_report(run, experiments=[], peak=None)

    assert "failed" in html.lower()
    assert "BaselineActor raised" in html
    assert "ModuleNotFoundError" in html
    # Empty-state messaging for sections that have no data
    assert "No scored experiments" in html or "No experiments recorded" in html
    # Should still have all the framing
    assert "<!doctype html>" in html.lower()


def test_render_lower_is_better_run():
    """RMSE-style metric — best is min, delta sign convention flips."""
    run = _base_run(lower_is_better=True, metric_name="rmse", target_accuracy=0.20)
    experiments = [
        _exp(0, 0.45, True, "Baseline RMSE"),
        _exp(1, 0.38, True, "Feature engineering"),
        _exp(2, 0.42, False, "Try L1 — got worse, reverted"),
        _exp(3, 0.31, True, "Stacked ensemble"),
    ]
    html = render_report(run, experiments, peak={"step": 3, "score": 0.31})

    assert "rmse" in html
    assert "lower better" in html  # axis label hint
    # 0.31 is the best for lower-is-better
    assert "0.3100" in html
    # Target was 0.20 — best 0.31 > target, so "not reached"
    assert "not reached" in html


def test_render_with_research_log_markdown():
    run = _base_run()
    experiments = [_exp(0, 0.7, True, "Baseline")]
    md = """# Run notes

Tried the obvious baseline first.

## Iteration 1

- Tried `LogisticRegression` with default params
- Got 0.70 accuracy

```python
clf = LogisticRegression(C=1.0)
clf.fit(X_train, y_train)
```
"""
    html = render_report(run, experiments, peak=None, research_log_md=md)

    assert "Run notes" in html
    assert "Iteration 1" in html
    assert "LogisticRegression" in html
    # Code fence should land in a styled <pre>
    assert "code-fence" in html
    # No raw markdown escapes leaking through
    assert "**" not in html.split("research-body")[1].split("</details>")[0]
