# Copyright 2026 Chris Padwick
# SPDX-License-Identifier: Apache-2.0

"""Hill-climbing evaluation, git management, and report nodes.

Scaffolding for the greenfield/brownfield hill-climb pipeline.

Pipeline shape:
  GitSetup → BaselineEval → [HillClimbEval] × N → (post-loop steps).

Each experiment is evaluated by comparing the new validation score to the current
best. Improvements are committed via git; regressions are reverted.

Score extraction is LLM-based (handles arbitrary metric names + lower-vs-higher
direction) with a regex parser as fallback.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path
from typing import Optional

from pocketflow import Node
from pydantic import BaseModel, Field

# ---------------------------------------------------------------------------
# Validation score extraction
# ---------------------------------------------------------------------------


class ValScoreVerdict(BaseModel):
    """Best validation score extracted from a training log."""

    score_found: bool = Field(
        description="True if a usable validation score was found in the log"
    )
    score: float = Field(
        default=0.0,
        description="Best validation score on the held-out validation set",
    )
    is_lower_better: bool = Field(
        default=True,
        description=(
            "True if lower scores are better (loss/error metrics like RMSE, "
            "RMSLE, log-loss). False for accuracy-style metrics (AUC, F1, "
            "accuracy, MAP). Default to True for unknown metrics."
        ),
    )
    metric_name: str = Field(
        default="",
        description="Human-readable name of the metric extracted",
    )


_VAL_SCORE_EXTRACTOR_PROMPT = """\
You extract the BEST validation score from a training log so a hill-climbing
loop can compare experiments.

Inputs:
- A training log tail (most recent ~5000 chars).
- Optional context describing the task's evaluation metric.

Rules:
1. Find the BEST score on the HELD-OUT validation set.
   - "Best validation X: 0.05" or "best val_X = 0.05" — use that.
   - Otherwise, scan all validation lines per epoch and return the best one
     (lowest if lower-is-better, highest if higher-is-better).
2. Determine whether lower or higher is better for this metric:
   - lower-is-better: loss, RMSE, RMSLE, MAE, MSE, log-loss, NLL, error rate.
   - higher-is-better: accuracy, AUC, ROC-AUC, F1, precision, recall, MAP,
     mAP, NDCG, BLEU, ROUGE, R^2, Pearson correlation.
3. Use the metric context if provided; otherwise infer from the metric name
   in the log.
4. If no validation score is reported (training failed, only training-set
   metrics, etc.), set score_found=False and leave score=0.

Return only fields defined in the verdict schema."""


def parse_val_score(log_content: str) -> float:
    """Extract the best validation score from a training log.

    Searches for common patterns like:
      val_loss=0.777, validation_loss: 0.777, val_score=0.777,
      Best validation loss: 0.777, val_log_loss=0.777,
      Best validation RMSLE: 0.0632, val_rmsle=0.0632, val_logloss=0.5

    Returns the lowest matching value (assumes lower is better).
    """
    if not log_content:
        return float("inf")

    # Metric keywords that all conventionally have lower==better.
    metric_kw = (
        r"(?:loss|score|rmse|rmsle|mae|mse|nll|log[_\s]?loss|log[_\s]?error|"
        r"cross[_\s]?entropy|error)"
    )
    patterns = [
        # "Best/final validation X: 0.777" or "val X: 0.777"
        rf"(?:best|final)?\s*val(?:idation)?[_\s]{metric_kw}[=:\s]+([0-9]+\.?[0-9]*)",
        # "val_<X>=0.777"
        rf"val(?:idation)?_{metric_kw}[=:\s]+([0-9]+\.?[0-9]*)",
    ]

    scores: list[float] = []
    for pattern in patterns:
        for match in re.finditer(pattern, log_content, re.IGNORECASE):
            try:
                scores.append(float(match.group(1)))
            except ValueError:
                continue

    return min(scores) if scores else float("inf")


# Keywords that signal a higher-is-better metric. Used as a fallback when the
# LLM extractor fails entirely (exception) and we'd otherwise default to
# lower-is-better — which inverts the comparison for accuracy-style metrics.
_HIGHER_IS_BETTER_KEYWORDS = (
    "accuracy", "acc", "auc", "roc-auc", "roc_auc", "f1", "precision",
    "recall", "map", "mAP", "ndcg", "bleu", "rouge", "pearson", "r^2",
    "r2", "spearman", "iou",
)


def _infer_direction_from_hint(metric_hint: str) -> bool:
    """Return True if the metric described in `metric_hint` is lower-is-better.

    Used as a last-resort heuristic when the LLM extractor crashes. Default
    to True (lower-is-better) only when there's no strong signal of a
    higher-is-better metric in the text.
    """
    if not metric_hint:
        return True
    lowered = metric_hint.lower()
    for kw in _HIGHER_IS_BETTER_KEYWORDS:
        if kw in lowered:
            return False
    return True


def llm_parse_val_score(
    log_content: str,
    metric_hint: str = "",
    direction_override: Optional[bool] = None,
    metric_name: Optional[str] = None,
) -> tuple[float, bool]:
    """Use an LLM to extract (best_val_score, lower_is_better) from a log.

    Falls back to the regex parser (assuming lower-is-better) if the LLM call
    fails or returns score_found=False.

    Args:
        log_content: Full training log text.
        metric_hint: Optional context describing the competition metric, e.g.
            an excerpt from the task description like "Mean column-wise RMSLE".
        direction_override: When set (True/False), bypasses the LLM/heuristic
            direction inference entirely and trusts the caller. Used when the
            user explicitly configures the metric direction at run-creation
            time, since that's authoritative information the inference
            heuristics can flip on ambiguous logs.

    Returns:
        (score, lower_is_better). Score is float("inf") (lower-better case) or
        float("-inf") (higher-better case) when no score could be extracted.
    """
    from mle_beast.llm import call_llm

    # Pick the no-score sentinel by direction so it loses every comparison.
    # When the caller provided an explicit direction we use that to
    # parameterize the sentinel, otherwise default to lower-is-better.
    direction_for_sentinel = direction_override if direction_override is not None else True
    no_score_sentinel = float("inf") if direction_for_sentinel else float("-inf")

    if not log_content:
        return no_score_sentinel, direction_for_sentinel

    tail = log_content[-5000:]
    user_msg = f"Training log tail:\n{tail}"
    if metric_hint:
        user_msg = (
            f"Competition metric context:\n{metric_hint.strip()}\n\n" + user_msg
        )
    # Authoritative metric-name override beats any hint inferred from the
    # task description. The user has named the metric explicitly so the
    # extractor must pick a value labeled with that name (or a recognized
    # alias) — never a different metric just because the training log
    # emphasized it.
    if metric_name:
        user_msg = (
            f"Metric name (AUTHORITATIVE — set by user): {metric_name}\n"
            f"Find the BEST value of this exact metric in the validation log.\n"
            f"Common aliases for this metric should match (e.g. accuracy ≈ acc ≈ val_acc).\n"
            f"Do NOT return a different metric even if the log emphasizes it.\n\n"
            + user_msg
        )
    # When the user explicitly configured a direction, instruct the LLM
    # to pick a value matching that direction. Without this nudge the
    # extractor can latch onto whatever metric the agent's train.py
    # emphasizes (e.g. "Best val_loss=0.4512") even when the task
    # evaluates accuracy — flipping the entire hill-climb's interpretation.
    if direction_override is not None:
        if direction_override:
            user_msg = (
                "Direction (AUTHORITATIVE — set by user): LOWER-IS-BETTER.\n"
                "Extract a value from a LOSS/ERROR-style metric only "
                "(loss, RMSE, RMSLE, MAE, MSE, log-loss, NLL, error rate).\n"
                "Do NOT return accuracy, F1, AUC, or other higher-is-better metrics.\n\n"
                + user_msg
            )
        else:
            user_msg = (
                "Direction (AUTHORITATIVE — set by user): HIGHER-IS-BETTER.\n"
                "Extract a value from an ACCURACY-style metric only "
                "(accuracy, F1, AUC, ROC-AUC, precision, recall, mAP, NDCG, BLEU, R^2, IoU).\n"
                "Do NOT return loss, RMSE, MAE, or other lower-is-better metrics —\n"
                "even if the training log emphasizes them with phrases like "
                "'best val_loss=...' or 'best model saved'. The user has\n"
                "specified the metric direction; honor it.\n\n"
                + user_msg
            )

    # Default direction from the metric_hint via keyword heuristic. Only
    # applies if the LLM call completely fails — if the LLM succeeds we
    # trust its judgement instead.
    is_lower_better = _infer_direction_from_hint(metric_hint)
    try:
        verdict = call_llm(
            ValScoreVerdict,
            messages=[
                {"role": "system", "content": _VAL_SCORE_EXTRACTOR_PROMPT},
                {"role": "user", "content": user_msg},
            ],
        )
        if verdict.score_found:
            # Direction precedence: explicit override > LLM verdict.
            direction = direction_override if direction_override is not None else verdict.is_lower_better
            return verdict.score, direction
        # LLM gave a verdict but couldn't pull a score out. Keep its direction
        # judgement — it inferred that from the metric name, which we still
        # trust — and fall through to the regex parser for the score itself.
        is_lower_better = verdict.is_lower_better
    except Exception as e:
        print(f"  [llm_parse_val_score] LLM call failed: {e!r}; falling back to regex")

    # Fallback: regex parser. Direction comes from override → LLM verdict →
    # metric_hint keyword heuristic, in that priority order.
    direction = direction_override if direction_override is not None else is_lower_better
    return parse_val_score(log_content), direction


# Synthetic identity used for all git commits the pipeline makes inside
# the workspace. Without this, a fresh-user box that hasn't run
# `git config --global user.email/user.name` would have every pipeline
# commit fail with `fatal: empty ident name not allowed`. The `-c`
# flags scope the override to the single invocation — the user's
# global config is untouched.
_GIT_IDENTITY_FLAGS = (
    "-c", "user.email=mle-beast@noreply.local",
    "-c", "user.name=mle-beast",
)


def _git(workspace: str | Path, *args: str) -> str:
    """Run a git command in the workspace directory. Returns stdout."""
    result = subprocess.run(
        ["git", *_GIT_IDENTITY_FLAGS, *args],
        cwd=str(workspace),
        capture_output=True,
        text=True,
        timeout=30,
    )
    if result.returncode != 0 and result.stderr:
        print(f"  [git] warning: git {' '.join(args)} stderr: {result.stderr.strip()}")
    return result.stdout.strip()


def _git_run(workspace: str | Path, *args: str) -> tuple[int, str, str]:
    """Run a git command and return (returncode, stdout, stderr) — use when
    the caller needs to distinguish success from failure.
    """
    result = subprocess.run(
        ["git", *_GIT_IDENTITY_FLAGS, *args],
        cwd=str(workspace),
        capture_output=True,
        text=True,
        timeout=30,
    )
    return result.returncode, result.stdout.strip(), result.stderr.strip()


def _generate_branch_name() -> str:
    """Make a unique branch name `mle-beast-YYYYMMDD-HHMMSS` (UTC)."""
    from datetime import datetime, timezone
    return f"mle-beast-{datetime.now(timezone.utc):%Y%m%d-%H%M%S}"


_TAG_KEYWORDS = (
    # ENSEMBLE first — phrases like "stack GBM" should beat the MODEL match.
    ("ENSEMBLE", ("stack", "blend", "ensemble", "voting", "bagging", "boost")),
    ("HYPERPARAM", ("lr ", "learning rate", "epoch", "n_estimators", "max_depth",
                    "tune", "tuning", "weight_decay", "dropout", "schedule",
                    "hyperparam", "regulariz", "optuna", "bayesian opt")),
    ("FEATURE", ("feature", "encoding", "polynomial", "embedding", "shap",
                 "pca", "tfidf", "select", "engineering", "drop")),
    ("DATA", ("augment", "sampling", "smote", "oversample", "undersample",
              "split", "imbalance")),
    ("MODEL", ("model", "rf ", "random forest", "xgboost", "lightgbm",
               "catboost", "gbm", "neural", "transformer", "cnn", "lstm",
               "logistic", "svm", "kernel", "tree")),
)


def _infer_tag(proposal: str | None) -> str | None:
    """Heuristic categorization of a proposal for the dashboard tag chip.

    Returns None when nothing matches; callers persist None which the UI
    renders as no tag rather than a misleading default.
    """
    if not proposal:
        return None
    text = proposal.lower()
    for tag, kws in _TAG_KEYWORDS:
        if any(kw in text for kw in kws):
            return tag
    return None


def _record_experiment(
    shared: dict,
    *,
    step: int,
    parent_step: int | None,
    proposal: str | None,
    score: float | None,
    lower_is_better: bool,
    kept: bool,
    commit_sha: str | None,
) -> None:
    """Persist an experiment row + emit an ExperimentRecorded event.

    Wraps everything in try/except so a DB or event-bus hiccup never
    breaks the pipeline — observability must not fail the run.
    """
    run_id = shared.get("run_id")
    if not run_id:
        # Standalone test or non-RunManager invocation — just skip persistence.
        return

    tag = _infer_tag(proposal)

    # Persist
    try:
        from mle_beast.db import get_database
        get_database().record_experiment(
            run_id=run_id,
            step=step,
            parent_step=parent_step,
            proposal=proposal,
            score=score,
            lower_is_better=lower_is_better,
            kept=kept,
            tag=tag,
            commit_sha=commit_sha,
        )
    except Exception as exc:
        print(f"  [Experiment] DB record failed: {exc}")

    # Emit
    bus = shared.get("event_bus")
    if bus is None:
        return
    try:
        from mle_beast.events import ExperimentRecorded
        bus.emit(ExperimentRecorded(
            run_id=run_id,
            step=step,
            parent_step=parent_step,
            proposal=proposal,
            score=score,
            lower_is_better=lower_is_better,
            kept=kept,
            tag=tag,
            commit_sha=commit_sha,
        ))
    except Exception as exc:
        print(f"  [Experiment] event emit failed: {exc}")


def _head_sha_or_none(workspace: Path) -> str | None:
    """Read the current HEAD SHA, or None if git is in a weird state."""
    rc, sha, _ = _git_run(workspace, "rev-parse", "HEAD")
    if rc != 0 or not sha:
        return None
    return sha


def _target_met(score: float, target: float | None, lower_is_better: bool) -> bool:
    """Has the current score met the user-specified target?

    Returns False when target is unset or score is a no-score sentinel.
    Direction is honored: lower-is-better metrics (loss, RMSLE) need the
    score to be at-or-below target; higher-is-better metrics (accuracy,
    AUC) need at-or-above.
    """
    if target is None:
        return False
    if score in (float("inf"), float("-inf")):
        return False
    return score <= target if lower_is_better else score >= target


# ---------------------------------------------------------------------------
# GitSetupNode
# ---------------------------------------------------------------------------

GITIGNORE_CONTENT = """\
# Workspace artifacts
data/
venv/
.venv/
__pycache__/
*.pyc
*.pyo
*.log
logs/
checkpoints/
*.pt
*.pth
*.pkl
*.joblib
*.h5
*.onnx
# EDA artifacts
*.png
*.jpg
*.jpeg
"""


class GitSetupNode(Node):
    """Initialize git tracking for the pipeline.

    Two paths depending on whether the workspace is already a git repo:

    Existing repo (.git/ present): smart mode. Capture the user's current
    branch, stash any uncommitted work to keep their tree clean, then create
    a new dated branch off their HEAD. Don't touch their .gitignore. Don't
    create a synthetic "initial workspace setup" commit on top of their
    history.

    Fresh workspace (no .git/): init mode. git init, write our .gitignore,
    commit everything as the initial state, then branch.

    Branch names are unique by timestamp (mle-beast-YYYYMMDD-HHMMSS UTC) so
    we never collide with a user's existing branch.

    State written to shared (read by ReportNode and the run summary):
      - experiment_branch: name of the dated branch we work on
      - original_branch: name of the user's branch before we switched
        (only set in existing-repo mode; None for fresh init)
      - is_existing_repo: True/False, for downstream messaging
      - mle_beast_stashed: True if we stashed uncommitted work
    """

    def prep(self, shared: dict) -> dict:
        return {"workspace": str(shared.get("workspace", ""))}

    def exec(self, prep_res: dict) -> dict:
        ws = prep_res["workspace"]
        branch_name = _generate_branch_name()
        is_existing_repo = (Path(ws) / ".git").is_dir()

        original_branch: str | None = None
        stashed = False

        if is_existing_repo:
            # Smart mode — don't trash the user's history or working tree.
            rc, out, _ = _git_run(ws, "branch", "--show-current")
            if rc == 0 and out:
                original_branch = out

            # If the working tree is dirty, stash it so we start from a
            # clean state. We do NOT auto-pop at the end — the user gets
            # restore instructions in the run summary.
            rc, out, _ = _git_run(ws, "status", "--porcelain")
            if rc == 0 and out:
                _git(ws, "stash", "push", "-u", "-m", "mle-beast: pre-pipeline stash")
                stashed = True

            _git(ws, "checkout", "-b", branch_name)
        else:
            # Fresh init mode — empty / non-git workspace.
            _git(ws, "init")
            gitignore_path = Path(ws) / ".gitignore"
            gitignore_path.write_text(GITIGNORE_CONTENT, encoding="utf-8")
            _git(ws, "add", "-A")
            _git(ws, "commit", "-m", "initial workspace setup")
            _git(ws, "checkout", "-b", branch_name)

        return {
            "branch_name": branch_name,
            "original_branch": original_branch,
            "is_existing_repo": is_existing_repo,
            "stashed": stashed,
        }

    def post(self, shared: dict, prep_res, exec_res) -> str:
        shared["experiment_branch"] = exec_res["branch_name"]
        shared["original_branch"] = exec_res["original_branch"]
        shared["is_existing_repo"] = exec_res["is_existing_repo"]
        shared["mle_beast_stashed"] = exec_res["stashed"]

        if exec_res["is_existing_repo"]:
            origin = exec_res["original_branch"] or "(detached HEAD)"
            stash_note = " (stashed your uncommitted work)" if exec_res["stashed"] else ""
            print(
                f"  [GitSetup] Existing repo detected (was on '{origin}')"
                f"{stash_note}. Working on '{exec_res['branch_name']}'."
            )
        else:
            print(
                f"  [GitSetup] Initialized git repo. Working on "
                f"'{exec_res['branch_name']}'."
            )
        return "complete"


# ---------------------------------------------------------------------------
# BaselineEvalNode
# ---------------------------------------------------------------------------

class BaselineEvalNode(Node):
    """Record the baseline score and commit it.

    Score now comes from `shared["eval_findings"]` produced by the
    EvalFinder upstream (run on a separate evaluate.py call). Falls back
    to LLM-parsing training.log only when the finder couldn't produce a
    valid finding — this keeps the run alive instead of crashing on a
    bad eval, but is no longer the primary path.
    """

    def prep(self, shared: dict) -> dict:
        return {
            "workspace": shared.get("workspace", ""),
            "task": shared.get("task", ""),
            "lower_is_better_override": shared.get("lower_is_better_override"),
            "metric_name": shared.get("metric_name"),
            "eval_findings": shared.get("eval_findings"),
        }

    def exec(self, prep_res: dict) -> dict:
        findings = prep_res.get("eval_findings") or {}
        score = findings.get("metric_value")
        # Direction: explicit run config wins; otherwise default to
        # higher-is-better (most ML metrics) since we no longer have a
        # log-content heuristic at this point.
        override = prep_res.get("lower_is_better_override")
        if isinstance(score, (int, float)) and score == score:  # finite
            lower_is_better = bool(override) if override is not None else False
            return {"score": float(score), "lower_is_better": lower_is_better,
                    "source": "eval_findings"}

        # Fallback path — finder couldn't produce a metric. Use the old
        # LLM training-log parser so the run can keep moving instead of
        # immediately failing. Logged so the user sees we're degraded.
        workspace = Path(prep_res["workspace"])
        log_path = workspace / "training.log"
        if not log_path.exists():
            log_path = workspace / "logs" / "training.log"
        log_content = log_path.read_text(encoding="utf-8", errors="replace") if log_path.exists() else ""
        score, lower_is_better = llm_parse_val_score(
            log_content, metric_hint=prep_res.get("task", "")[:4000],
            direction_override=prep_res.get("lower_is_better_override"),
            metric_name=prep_res.get("metric_name"),
        )
        print(
            "  [BaselineEval] No finder score; falling back to LLM training-log parser."
        )
        return {"score": score, "lower_is_better": lower_is_better,
                "source": "llm_log_fallback"}

    def post(self, shared: dict, prep_res, exec_res) -> str:
        workspace = Path(prep_res["workspace"])
        score = exec_res["score"]
        lower_is_better = exec_res["lower_is_better"]

        # If parsing failed, set the sentinel to the appropriate worst value
        # for the metric direction. parse_val_score / llm_parse_val_score
        # return +inf for "no score found"; that's correct as a worst-case
        # for lower-is-better, but for higher-is-better the worst case is
        # -inf so any later finite score still registers as an improvement.
        if score == float("inf") and not lower_is_better:
            score = float("-inf")

        shared["best_score"] = score
        shared["lower_is_better"] = lower_is_better
        shared["step_count"] = 0
        shared["consecutive_failures"] = 0
        shared["experiments"] = []

        direction = "lower-is-better" if lower_is_better else "higher-is-better"

        # Commit baseline
        _git(workspace, "add", "-A")
        _git(workspace, "commit", "-m", f"baseline: val_score={score}")

        # Initialize research log
        log_path = workspace / "research_log.md"
        log_path.write_text(
            "# Research Log\n\n"
            "## Baseline\n"
            f"- **Score**: {score} ({direction})\n"
            f"- **Approach**: Initial baseline model\n"
            f"- **Git**: baseline commit\n\n",
            encoding="utf-8",
        )

        # Commit research log
        _git(workspace, "add", "research_log.md")
        _git(workspace, "commit", "-m", "add research log")

        print(f"  [BaselineEval] Baseline score: {score} ({direction})")

        # Persist baseline as experiment step=0. Subsequent hill-climb
        # iterations get parent_step=0 (or the latest kept step) so the
        # dashboard can render the experiment tree.
        shared["last_kept_step"] = 0
        _record_experiment(
            shared,
            step=0,
            parent_step=None,
            proposal="Baseline",
            score=score,
            lower_is_better=lower_is_better,
            kept=True,
            commit_sha=_head_sha_or_none(workspace),
        )

        # Early-exit if the baseline already meets the user's target.
        # No point running hill-climb experiments — we're already done.
        target = shared.get("target_accuracy")
        if _target_met(score, target, lower_is_better):
            print(
                f"  [BaselineEval] Target already met "
                f"({score} vs target {target}, {direction}) — skipping hill-climb."
            )
            return "done"
        return "complete"


# ---------------------------------------------------------------------------
# HillClimbEvalNode
# ---------------------------------------------------------------------------

class HillClimbEvalNode(Node):
    """Evaluate an experiment: keep (commit) or revert, update research log.

    Returns "iterate" to continue hill climbing, or "done" when budget is
    exhausted or convergence is detected.
    """

    def prep(self, shared: dict) -> dict:
        return {
            "workspace": str(shared.get("workspace", "")),
            "step_count": shared.get("step_count", 0),
            "max_steps": shared.get("max_steps", 30),
            "best_score": shared.get("best_score", float("inf")),
            "lower_is_better": shared.get("lower_is_better", True),
            "lower_is_better_override": shared.get("lower_is_better_override"),
            "metric_name": shared.get("metric_name"),
            "consecutive_failures": shared.get("consecutive_failures", 0),
            "max_consecutive_failures": shared.get("max_consecutive_failures", 5),
            "current_proposal": shared.get("current_proposal", ""),
            "task": shared.get("task", ""),
            "eval_findings": shared.get("eval_findings"),
            "shared": shared,
        }

    def exec(self, prep_res: dict) -> dict:
        # Primary: read score from EvalFinder findings.
        findings = prep_res.get("eval_findings") or {}
        score = findings.get("metric_value")
        source = "eval_findings"

        if not (isinstance(score, (int, float)) and score == score):
            # Fallback: same LLM training-log parser as before. Only fires
            # when the EvalFinder couldn't produce a finite metric — this
            # iteration will likely revert anyway.
            workspace = Path(prep_res["workspace"])
            log_path = workspace / "training.log"
            if not log_path.exists():
                log_path = workspace / "logs" / "training.log"
            log_content = log_path.read_text(encoding="utf-8", errors="replace") if log_path.exists() else ""
            score, _ = llm_parse_val_score(
                log_content, metric_hint=prep_res.get("task", "")[:4000],
                direction_override=prep_res.get("lower_is_better_override"),
                metric_name=prep_res.get("metric_name"),
            )
            source = "llm_log_fallback"

        best = prep_res["best_score"]
        lower_is_better = prep_res["lower_is_better"]

        # "No score" sentinel depends on direction
        no_score = score == float("inf") or score == float("-inf")
        if no_score or best is None:
            improved = False
        elif lower_is_better:
            improved = score < best
        else:
            improved = score > best

        return {"score": score, "improved": improved, "source": source}

    def post(self, shared: dict, prep_res, exec_res) -> str:
        workspace = Path(prep_res["workspace"])
        step = prep_res["step_count"] + 1
        score = exec_res["score"]
        improved = exec_res["improved"]
        best = prep_res["best_score"]
        proposal = prep_res["current_proposal"]
        max_steps = prep_res["max_steps"]
        max_failures = prep_res["max_consecutive_failures"]

        # Extract a short hypothesis from the proposal
        hypothesis = proposal[:120].replace("\n", " ") if proposal else f"step {step}"

        if improved:
            # Commit the improvement
            _git(workspace, "add", "-A")
            _git(workspace, "commit", "-m",
                 f"step {step}: {hypothesis[:60]} (score {score:.4f}, was {best:.4f})")
            shared["best_score"] = score
            shared["consecutive_failures"] = 0

            # Append success to research log
            _append_research_log(workspace, step, hypothesis, score, best, True)

            # Commit updated research log
            _git(workspace, "add", "research_log.md")
            _git(workspace, "commit", "-m", f"research log: step {step} (improved)")

            print(f"  [HillClimbEval] Step {step}: IMPROVED {best:.4f} → {score:.4f} (kept)")
        else:
            # Save research_log.md before checkout — it carries uncommitted
            # entries from prior failed experiments that checkout would wipe.
            log_path = workspace / "research_log.md"
            saved_log = (
                log_path.read_text(encoding="utf-8") if log_path.exists() else ""
            )

            # Revert tracked changes AND remove untracked files. Without
            # `git clean`, debris from failed experiments (fix_*.py,
            # model_new.py, etc.) accumulates and can pollute the next
            # experiment's behavior.
            _git(workspace, "checkout", "--", ".")
            _git(workspace, "clean", "-fd")

            # Restore research_log so prior failure entries persist
            if saved_log:
                log_path.write_text(saved_log, encoding="utf-8")

            shared["consecutive_failures"] = prep_res["consecutive_failures"] + 1

            # Append this experiment's failure to the research log
            _append_research_log(workspace, step, hypothesis, score, best, False)

            # Don't commit the failure — research log update is local only
            # (it will be included in the next successful commit)

            best_disp = f"{best:.4f}" if best not in (float("inf"), float("-inf"), None) else str(best)
            print(f"  [HillClimbEval] Step {step}: NO IMPROVEMENT "
                  f"(score={score}, best={best_disp}) (reverted)")

        # Record experiment in shared (legacy in-memory list).
        # Tag is the heuristic category (HYPERPARAM/FEATURE/MODEL/...) that
        # the proposer's plateau-detection prompt aggregates over to nudge
        # toward unexplored families.
        shared.setdefault("experiments", []).append({
            "step": step,
            "hypothesis": hypothesis,
            "score": score,
            "improved": improved,
            "tag": _infer_tag(proposal),
        })

        # Persist experiment row + emit event for the dashboard.
        # parent_step is the latest *kept* step at the time this attempt
        # branched off — that's what the experiment-tree visualization wants.
        parent_step = shared.get("last_kept_step", 0)
        _record_experiment(
            shared,
            step=step,
            parent_step=parent_step,
            proposal=proposal or hypothesis,
            score=score,
            lower_is_better=prep_res["lower_is_better"],
            kept=improved,
            commit_sha=_head_sha_or_none(workspace) if improved else None,
        )
        if improved:
            shared["last_kept_step"] = step

        shared["step_count"] = step
        shared["feedback_history"] = []  # Reset for next experiment

        # Reset critic attempt counters
        for key in list(shared.keys()):
            if key.endswith("_attempt"):
                shared[key] = 0

        # Decide whether to continue
        target = shared.get("target_accuracy")
        lower_is_better = shared.get("lower_is_better", True)
        if improved and _target_met(score, target, lower_is_better):
            direction = "lower-is-better" if lower_is_better else "higher-is-better"
            print(
                f"  [HillClimbEval] Target met "
                f"({score} vs target {target}, {direction}) — stopping hill-climb."
            )
            _commit_research_log_if_dirty(workspace, reason="target met")
            return "done"

        if step >= max_steps:
            print(f"  [HillClimbEval] Budget exhausted ({max_steps} steps).")
            _commit_research_log_if_dirty(workspace, reason="end of hill-climb")
            return "done"

        if shared["consecutive_failures"] >= max_failures:
            print(f"  [HillClimbEval] Converged ({max_failures} consecutive failures).")
            _commit_research_log_if_dirty(workspace, reason="end of hill-climb")
            return "done"

        return "iterate"


def _commit_research_log_if_dirty(workspace: Path, reason: str = "") -> None:
    """Commit research_log.md if it has uncommitted changes.

    Failure-path entries are appended without committing (the design lets the
    next successful keep bundle them in). When the loop ends without another
    keep, that bundle never happens — so we commit explicitly here.
    """
    status = _git(workspace, "status", "--porcelain", "--", "research_log.md")
    if not status.strip():
        return
    _git(workspace, "add", "research_log.md")
    msg = f"research log: {reason}" if reason else "research log: final state"
    _git(workspace, "commit", "-m", msg)


def _append_research_log(
    workspace: Path,
    step: int,
    hypothesis: str,
    score: float,
    best_score: float,
    improved: bool,
) -> None:
    """Append an experiment entry to research_log.md."""
    log_path = workspace / "research_log.md"

    no_score = score == float("inf") or score == float("-inf")
    if improved:
        delta = abs(score - best_score)
        result_text = f"val_score {best_score:.4f} → {score:.4f} (IMPROVED, delta={delta:.4f}, kept)"
    elif no_score:
        result_text = "Training failed or no score produced (REVERTED)"
    else:
        result_text = f"val_score={score:.4f}, best={best_score:.4f} (NO IMPROVEMENT, reverted)"

    entry = (
        f"## Experiment {step}\n"
        f"- **Hypothesis**: {hypothesis}\n"
        f"- **Result**: {result_text}\n\n"
    )

    with open(log_path, "a", encoding="utf-8") as f:
        f.write(entry)


# ---------------------------------------------------------------------------
# ReportNode
# ---------------------------------------------------------------------------

class ReportNode(Node):
    """Generate REPORT.md from the research log and git history."""

    def prep(self, shared: dict) -> dict:
        return {
            "workspace": str(shared.get("workspace", "")),
            "experiments": shared.get("experiments", []),
            "best_score": shared.get("best_score"),
            "step_count": shared.get("step_count", 0),
            "shared": shared,
        }

    def exec(self, prep_res: dict) -> dict:
        workspace = Path(prep_res["workspace"])

        # Read research log
        research_log = ""
        log_path = workspace / "research_log.md"
        if log_path.exists():
            research_log = log_path.read_text(encoding="utf-8", errors="replace")

        # Read EDA writeup
        data_analysis = ""
        da_path = workspace / "data_analysis.md"
        if da_path.exists():
            data_analysis = da_path.read_text(encoding="utf-8", errors="replace")

        # Locate EDA plot images at workspace root
        plot_paths: list[str] = []
        for ext in ("png", "jpg", "jpeg"):
            plot_paths.extend(
                sorted(p.name for p in workspace.glob(f"*.{ext}"))
            )

        # Read git log on the experiment branch (whatever name GitSetupNode
        # picked — `mle-beast-<ts>`). The `--` disambiguator is only needed
        # if the branch name happens to collide with a workspace path; we
        # include it defensively.
        branch = (
            (prep_res.get("shared", {}) or {}).get("experiment_branch")
            or "HEAD"
        )
        git_log = _git(workspace, "log", "--oneline", branch, "--")

        # Read current model.py
        model_code = ""
        model_path = workspace / "model.py"
        if model_path.exists():
            model_code = model_path.read_text(encoding="utf-8", errors="replace")

        return {
            "research_log": research_log,
            "data_analysis": data_analysis,
            "plot_paths": plot_paths,
            "git_log": git_log,
            "model_code": model_code,
        }

    def post(self, shared: dict, prep_res, exec_res) -> str:
        workspace = Path(prep_res["workspace"])
        experiments = prep_res["experiments"]
        best_score = prep_res["best_score"]

        lines: list[str] = ["# Benchmark Report", ""]

        # Experiment results table
        lines.append("## Experiment Results")
        lines.append("")
        lines.append("| Step | Score | Improved | Hypothesis |")
        lines.append("|------|-------|----------|------------|")
        for exp in experiments:
            score = exp.get("score", "N/A")
            if isinstance(score, float) and score != float("inf"):
                score_str = f"{score:.4f}"
            else:
                score_str = str(score)
            improved_str = "YES" if exp.get("improved") else "no"
            hypothesis = exp.get("hypothesis", "N/A")
            if len(hypothesis) > 80:
                hypothesis = hypothesis[:77] + "..."
            lines.append(f"| {exp['step']} | {score_str} | {improved_str} | {hypothesis} |")

        if best_score is not None:
            lines.append("")
            lines.append(f"**Best score: {best_score}** after {prep_res['step_count']} experiments")
        lines.append("")

        # EDA / Data Analysis writeup
        data_analysis = exec_res.get("data_analysis", "")
        plot_paths = exec_res.get("plot_paths", [])
        if data_analysis or plot_paths:
            lines.append("## Exploratory Data Analysis")
            lines.append("")
            if data_analysis:
                lines.append(data_analysis.rstrip())
                lines.append("")
            if plot_paths:
                lines.append("### Plots")
                lines.append("")
                for name in plot_paths:
                    lines.append(f"![{name}]({name})")
                lines.append("")

        # Git history
        lines.append("## Git History")
        lines.append("")
        lines.append("```")
        lines.append(exec_res["git_log"] or "(no git history)")
        lines.append("```")
        lines.append("")

        # Final model architecture
        lines.append("## Final Model Architecture")
        lines.append("")
        model_code = exec_res["model_code"]
        if model_code:
            if len(model_code) > 3000:
                model_code = model_code[:3000] + "\n# ... (truncated)"
            lines.append("```python")
            lines.append(model_code.rstrip())
            lines.append("```")
        else:
            lines.append("_model.py not found_")
        lines.append("")

        # Full research log
        lines.append("## Full Research Log")
        lines.append("")
        research_log = exec_res["research_log"]
        if research_log:
            lines.append(research_log)
        else:
            lines.append("_research_log.md not found_")

        report_text = "\n".join(lines)
        report_path = workspace / "REPORT.md"
        report_path.write_text(report_text, encoding="utf-8")
        print(f"  [Report] Wrote {report_path.name} ({len(report_text):,} chars)")

        # Commit final artifacts so the workspace ends in a clean state.
        # `git add -A` picks up REPORT.md, submission.csv (if predict already
        # ran), the final-train checkpoint dir contents, etc.
        _git(workspace, "add", "-A")
        _git(workspace, "commit", "-m", "final artifacts: REPORT.md + final train state")

        return "complete"


# ---------------------------------------------------------------------------
# Run summary helper
# ---------------------------------------------------------------------------

def print_pipeline_summary(shared: dict) -> None:
    """Print a final summary of where the pipeline ended up.

    Called by run_manager.py after the flow exits, so the user sees how
    to inspect, switch back, merge, or restore stashed work.
    """
    workspace = shared.get("workspace") or "."
    branch = shared.get("experiment_branch")
    original = shared.get("original_branch")
    is_existing = shared.get("is_existing_repo", False)
    stashed = shared.get("mle_beast_stashed", False)

    if not branch:
        return  # GitSetupNode never ran (or was bypassed) — nothing to say

    print()
    print("=" * 60)
    print("Pipeline run complete.")
    print("=" * 60)
    print(f"  Workspace:     {workspace}")
    print(f"  Branch:        {branch}")
    if is_existing and original:
        print(f"  Was on:        {original}")
        print()
        print("To go back to your branch:")
        print(f"  cd {workspace} && git switch {original}")
        print()
        print(f"To merge experiment commits into '{original}':")
        print(f"  cd {workspace} && git switch {original} && git merge {branch}")
        print()
        print("To inspect what changed:")
        print(f"  cd {workspace} && git log {original}..{branch} --oneline")
        if stashed:
            print()
            print("Your pre-pipeline uncommitted work is in stash. To restore:")
            print(f"  cd {workspace} && git switch {original} && git stash pop")
    else:
        print()
        print(f"To inspect: cd {workspace} && git log --oneline")
    print("=" * 60)
