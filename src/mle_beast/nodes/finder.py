# Copyright 2026 Chris Padwick
# SPDX-License-Identifier: Apache-2.0

"""FinderActorNode + FinderCriticNode.

Generic actor/critic pair for *locating* artifacts on disk and reporting
them as structured output. Two pipeline uses today:

- After Training: locate the produced checkpoint + training log, report
  TrainingFindings → shared["train_findings"].
- After Evaluation: locate the metric value (whether in JSON, stdout,
  or a CSV), report EvalFindings → shared["eval_findings"].

The actor reads/scans/reports a JSON summary via mark_complete. The
critic procedurally verifies the JSON parses against the requested
schema, paths exist, and metric values are finite.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Optional, Type

from pydantic import BaseModel, ValidationError

from mle_beast.events import LogMessage, RetryOccurred, StageCompleted
from mle_beast.models.findings import EvalFindings, TrainingFindings
from mle_beast.models.tool_calls import FinderToolCall
from mle_beast.nodes.base import BaseActorNode, BaseCriticNode, _emit, _get_run_id
from mle_beast.prompts.finder import FINDER_SYSTEM_PROMPT


# ---------------------------------------------------------------------------
# Actor
# ---------------------------------------------------------------------------

class FinderActorNode(BaseActorNode):
    """Generic finder actor — parameterized by `findings_kind` in shared.

    Two values are recognized today:
      "training" → expects TrainingFindings JSON; writes shared["train_findings"]
      "eval"     → expects EvalFindings JSON;     writes shared["eval_findings"]

    Subclasses below set shared["finder_kind"] in prep() so each use site
    in the flow graph self-identifies. Don't instantiate this class
    directly — use TrainFinderActorNode / EvalFinderActorNode.
    """

    _stage_name = "finder"
    finder_kind: str = "training"  # default; subclasses override
    system_prompt = FINDER_SYSTEM_PROMPT
    tool_call_model = FinderToolCall
    max_iterations = 10

    def prep(self, shared: dict) -> dict:
        # Stamp the kind so the system+user prompts and the critic
        # downstream all agree on what we're looking for.
        shared["finder_kind"] = self.finder_kind
        # Each finder use is independent: clear feedback so a previous
        # stage's failure doesn't leak into the actor's first prompt.
        shared["feedback_history"] = []
        return super().prep(shared)

    def exec(self, prep_res: dict) -> list[str]:
        from mle_beast.settings import Settings
        settings: Settings = prep_res.get("shared", {}).get("settings") or Settings()
        # Smaller iteration cap than training — discovery should be quick.
        self.max_iterations = max(8, min(15, settings.max_tool_iterations // 2))
        return super().exec(prep_res)

    def _build_user_prompt(self, prep_res: dict) -> str:
        shared = prep_res.get("shared", {})
        workspace = prep_res["workspace"]
        kind = shared.get("finder_kind") or self.finder_kind or "training"
        feedback = prep_res.get("feedback_history", [])

        if kind == "training":
            schema_name = "TrainingFindings"
            directive = (
                "Find what the most recent TRAINING run produced.\n"
                "Required:\n"
                "  - training_log_path: where train.py wrote its log.\n"
                "Optional but desired:\n"
                "  - checkpoint_path: best/most-recent checkpoint file.\n"
                "  - best_metric_value + best_metric_name: if the log "
                "explicitly states a 'best val_X = Y' or similar.\n"
            )
        else:  # "eval"
            schema_name = "EvalFindings"
            directive = (
                "Find what the most recent EVALUATION run produced.\n"
                "Required:\n"
                "  - metric_value: numeric metric reported by evaluate.py.\n"
                "  - metric_name: e.g. 'accuracy', 'f1', 'rmse'.\n"
                "Optional but desired:\n"
                "  - split (default 'test'), eval_log_path, source, extra.\n"
                "\n"
                "Likely places to look (in order):\n"
                "  1. eval_results.json or similar JSON file at workspace "
                "root (preferred — structured).\n"
                "  2. logs/eval.log — final lines often print the metric.\n"
                "  3. stdout captured by launch_evaluate.\n"
                "  4. results.csv or other tabular output.\n"
            )

        prompt = f"Locate {schema_name}.\n\n{directive}\n\nWorkspace: {workspace}"

        # If the run config pinned a specific metric_name, pass it as a
        # hint so the eval Finder doesn't accidentally pick a side metric.
        configured_metric = shared.get("metric_name")
        if kind == "eval" and configured_metric:
            prompt += (
                f"\n\nThe run is configured to track `{configured_metric}`. "
                f"Pick that metric (or a close alias like val_{configured_metric}) "
                f"in your EvalFindings."
            )

        if feedback:
            prompt += "\n\nFeedback from previous attempt(s):\n"
            for i, fb in enumerate(feedback, 1):
                prompt += f"  {i}. {fb}\n"
            prompt += (
                "\nFix the specific issues called out and retry. The schema "
                "fields and JSON-only summary format have not changed."
            )

        prompt += (
            "\n\nReturn the result via mark_complete with the summary set to "
            f"a JSON object matching the {schema_name} schema. "
            "No markdown fences, no prose around the JSON."
        )
        return prompt


# ---------------------------------------------------------------------------
# Critic
# ---------------------------------------------------------------------------

def _parse_findings_json(raw: str) -> Optional[dict]:
    """Extract a JSON object from the actor's mark_complete summary.

    The system prompt forbids markdown fences but real-world LLM output
    sometimes still wraps the JSON in ```json ... ```. Strip those if
    present and try to parse.
    """
    if not raw:
        return None
    text = raw.strip()
    if text.startswith("```"):
        # Strip leading and trailing fences.
        lines = text.splitlines()
        if lines:
            lines = lines[1:]  # drop opening ```...
            if lines and lines[-1].strip().startswith("```"):
                lines = lines[:-1]
            text = "\n".join(lines)
    # As a last resort, try to find the first balanced { ... }.
    try:
        return json.loads(text)
    except Exception:
        pass
    start = text.find("{")
    end = text.rfind("}")
    if start >= 0 and end > start:
        try:
            return json.loads(text[start:end + 1])
        except Exception:
            return None
    return None


class FinderVerdict(BaseModel):
    """Internal verdict the FinderCritic returns to the flow."""

    ok: bool
    feedback: str = ""
    findings: Optional[dict] = None


class FinderCriticNode(BaseCriticNode):
    """Procedural critic that verifies the FinderActor's claims.

    Parses the actor's mark_complete summary as JSON, validates against
    the appropriate Pydantic schema (TrainingFindings or EvalFindings),
    checks claimed paths exist on disk and metric values are finite.
    On success: stamps the validated findings into shared["{kind}_findings"].
    On failure: returns "retry" with prescriptive feedback.
    """

    _stage_name = "finder_critic"
    _attempt_key = "finder_critic_attempt"

    def prep(self, shared: dict) -> dict:
        from mle_beast.settings import Settings
        settings: Settings = shared.get("settings") or Settings()
        # Reuse the analysis-retry budget — same retry-on-feedback shape.
        self.critic_max_retries = settings.max_training_analysis_retries
        return {
            "kind": shared.get("finder_kind") or "training",
            "summary": shared.get("last_mark_complete_summary", ""),
            "workspace": str(shared.get("workspace", "")),
            "shared": shared,
        }

    def _evaluate(self, prep_res: dict) -> FinderVerdict:
        kind = prep_res["kind"]
        raw = prep_res.get("summary") or ""
        workspace = Path(prep_res["workspace"])

        data = _parse_findings_json(raw)
        if data is None:
            return FinderVerdict(
                ok=False,
                feedback=(
                    "Your mark_complete summary did not parse as JSON. The "
                    "summary field MUST be a single JSON object that "
                    "validates against the requested schema. "
                    "Do not wrap it in markdown fences. Try again."
                ),
            )

        schema_cls: Type[BaseModel] = (
            TrainingFindings if kind == "training" else EvalFindings
        )
        try:
            validated = schema_cls(**data)
        except ValidationError as e:
            return FinderVerdict(
                ok=False,
                feedback=(
                    f"Your JSON did not validate against {schema_cls.__name__}. "
                    f"Errors: {e.errors()[:5]}"
                ),
            )

        # Validate disk-backed claims.
        problems: list[str] = []
        if kind == "training":
            f: TrainingFindings = validated  # type: ignore[assignment]
            if f.training_log_path:
                if not (workspace / f.training_log_path).exists():
                    problems.append(
                        f"Claimed training_log_path '{f.training_log_path}' "
                        f"does not exist."
                    )
            if f.checkpoint_path:
                if not (workspace / f.checkpoint_path).exists():
                    problems.append(
                        f"Claimed checkpoint_path '{f.checkpoint_path}' "
                        f"does not exist."
                    )
            if f.best_metric_value is not None:
                if not _is_finite(f.best_metric_value):
                    problems.append(
                        f"best_metric_value must be a finite float; got "
                        f"{f.best_metric_value!r}."
                    )
        else:  # eval
            f: EvalFindings = validated  # type: ignore[assignment]
            if not _is_finite(f.metric_value):
                problems.append(
                    f"metric_value must be a finite float; got {f.metric_value!r}."
                )
            if not f.metric_name or not f.metric_name.strip():
                problems.append("metric_name must be a non-empty string.")
            if f.eval_log_path:
                if not (workspace / f.eval_log_path).exists():
                    problems.append(
                        f"Claimed eval_log_path '{f.eval_log_path}' does "
                        f"not exist."
                    )

            # Cross-check the claimed metric_value against ground-truth
            # files on disk. This is the heart of "critics check
            # procedurally" — without it the LLM can hallucinate a number
            # and we'd accept it. Order of authority:
            #   1. eval_results.json at workspace root (structured, written
            #      by evaluate.py — most authoritative).
            #   2. logs/eval.log "Test accuracy: X.XXXX" line.
            #   3. f.eval_log_path (whatever the LLM cited).
            if _is_finite(f.metric_value):
                ground_truth, src = _ground_truth_metric(workspace, f)
                if ground_truth is not None and not _values_match(
                    f.metric_value, ground_truth
                ):
                    problems.append(
                        f"metric_value mismatch: you reported "
                        f"{f.metric_value!r} but {src} on disk shows "
                        f"{ground_truth!r}. Read {src} again and report "
                        f"the EXACT value from the file. Do not invent or "
                        f"round numbers."
                    )

        if problems:
            return FinderVerdict(
                ok=False,
                feedback=(
                    "Verification failed. Fix these and re-report:\n  - "
                    + "\n  - ".join(problems)
                ),
            )

        return FinderVerdict(
            ok=True,
            findings=validated.model_dump(),
        )

    def _is_pass(self, verdict: FinderVerdict) -> bool:
        return bool(verdict.ok)

    def post(self, shared: dict, prep_res, verdict: FinderVerdict) -> str:
        kind = prep_res["kind"]
        run_id = _get_run_id(shared)
        stage = self._stage_name

        if verdict.ok:
            key = "train_findings" if kind == "training" else "eval_findings"
            shared[key] = verdict.findings or {}
            shared["verdict"] = verdict
            # Reset feedback so the next pipeline stage gets a clean slate.
            shared["feedback_history"] = []
            shared[self._attempt_key] = 0
            _emit(shared, StageCompleted(
                run_id=run_id, stage=stage, outcome="pass",
                verdict=str(verdict),
            ))
            return "complete"

        attempt = shared.get(self._attempt_key, 0) + 1
        shared[self._attempt_key] = attempt
        if attempt >= self.critic_max_retries:
            _emit(shared, LogMessage(
                run_id=run_id, stage=stage, level="error",
                message=(
                    f"[FinderCritic] Max retries ({self.critic_max_retries}) "
                    f"reached for {kind} finder; completing without findings."
                ),
            ))
            _emit(shared, StageCompleted(
                run_id=run_id, stage=stage, outcome="fail",
                verdict=str(verdict),
            ))
            shared["verdict"] = verdict
            # Don't write findings on max-retry-failure. Downstream nodes
            # will see the absence and fall back to the sentinel path.
            return "complete"

        shared.setdefault("feedback_history", []).append(verdict.feedback)
        _emit(shared, RetryOccurred(
            run_id=run_id, stage=stage, attempt=attempt + 1,
            max_attempts=self.critic_max_retries, feedback=verdict.feedback,
        ))
        return "retry"


def _is_finite(value: float) -> bool:
    try:
        return value not in (float("inf"), float("-inf")) and value == value
    except Exception:
        return False


def _values_match(claimed: float, ground_truth: float, tol: float = 1e-4) -> bool:
    """Floating-point comparison with absolute tolerance."""
    try:
        return abs(float(claimed) - float(ground_truth)) <= tol
    except Exception:
        return False


def _ground_truth_metric(
    workspace: Path, findings: EvalFindings
) -> tuple[Optional[float], str]:
    """Try to extract the ground-truth metric value from disk.

    Returns (value, source_label) where source_label is a short
    human-readable string like "eval_results.json" used in feedback.
    Returns (None, "") if no source could be parsed.
    """
    # Source 1: structured eval_results.json at workspace root.
    er_path = workspace / "eval_results.json"
    if er_path.exists():
        try:
            data = json.loads(er_path.read_text(encoding="utf-8", errors="ignore"))
            if isinstance(data, dict):
                v = data.get("value")
                if v is None:
                    v = data.get("metric_value")
                if v is not None:
                    return float(v), "eval_results.json"
        except (json.JSONDecodeError, ValueError, OSError):
            pass

    # Source 2: logs/eval.log — match "Test accuracy: X.XXXX".
    el_path = workspace / "logs" / "eval.log"
    if el_path.exists():
        try:
            text = el_path.read_text(encoding="utf-8", errors="ignore")
            v = _parse_test_accuracy(text)
            if v is not None:
                return v, "logs/eval.log"
        except OSError:
            pass

    # Source 3: whatever the LLM itself cited.
    if findings.eval_log_path:
        cited = workspace / findings.eval_log_path
        if cited.exists() and cited != er_path and cited != el_path:
            try:
                text = cited.read_text(encoding="utf-8", errors="ignore")
                if cited.suffix == ".json":
                    try:
                        data = json.loads(text)
                        if isinstance(data, dict):
                            v = data.get("value") or data.get("metric_value")
                            if v is not None:
                                return float(v), findings.eval_log_path
                    except (json.JSONDecodeError, ValueError):
                        pass
                v = _parse_test_accuracy(text)
                if v is not None:
                    return v, findings.eval_log_path
            except OSError:
                pass

    return None, ""


def _parse_test_accuracy(text: str) -> Optional[float]:
    """Find 'Test accuracy: X.XXXX' (case-insensitive) in text."""
    import re
    matches = re.findall(
        r"(?i)(?:test|val(?:idation)?)\s+accuracy[:=\s]+([0-9]*\.?[0-9]+)",
        text,
    )
    if not matches:
        return None
    try:
        return float(matches[-1])
    except ValueError:
        return None


# ---------------------------------------------------------------------------
# Concrete subclasses for the two pipeline use sites.
# Each just stamps the right `finder_kind` so a single FinderActor
# implementation can serve both training and evaluation discovery
# without the flow graph having to write to shared.
# ---------------------------------------------------------------------------

class TrainFinderActorNode(FinderActorNode):
    finder_kind = "training"
    _stage_name = "train_finder"


class EvalFinderActorNode(FinderActorNode):
    finder_kind = "eval"
    _stage_name = "eval_finder"


class TrainFinderCriticNode(FinderCriticNode):
    _stage_name = "train_finder_critic"
    _attempt_key = "train_finder_critic_attempt"

    def prep(self, shared: dict) -> dict:
        # Mirror the kind from upstream actor so this critic critiques
        # the right schema even if shared["finder_kind"] is stale.
        shared["finder_kind"] = "training"
        return super().prep(shared)


class EvalFinderCriticNode(FinderCriticNode):
    _stage_name = "eval_finder_critic"
    _attempt_key = "eval_finder_critic_attempt"

    def prep(self, shared: dict) -> dict:
        shared["finder_kind"] = "eval"
        return super().prep(shared)
