# AGENTS.md — driving mle-beast from a coding agent

This file teaches an AI coding agent (Claude Code, Cursor, Aider, etc.)
how to drive mle-beast on your behalf. Drop it in your project root
alongside your `.env` and your agent will read it as context.

## What mle-beast is

mle-beast is a hill-climbing ML engineering agent. You give it a task
description and (optionally) a dataset; it generates `model.py` /
`train.py` / `evaluate.py`, runs them, evaluates results, proposes
improvements, and iterates — committing each kept change to git.

There are two modes:

- **Greenfield** (default): mle-beast generates code from scratch in a
  fresh workspace.
- **Brownfield** (`mode = "existing"`): mle-beast iterates on YOUR
  existing `model.py` / `train.py` / `evaluate.py`. Use this when the
  user already has working code and wants improvements.

## Launching a run

```bash
mle-beast
# starts the web dashboard at http://127.0.0.1:8000
# create a new run from the UI, or via the REPL:

mle-beast --no-web
# drops into the CLI REPL
```

In the REPL, the minimum a run needs:

- **task**: a one-paragraph description of what to build (e.g.
  "Build a baseline binary classifier for customer churn on the data
  at /path/to/train.csv. Use accuracy as the metric. Target 0.85.")
- **workspace**: a fresh empty directory where mle-beast can write
  `model.py`, `train.py`, etc.
- **dataset_path**: path to the data (optional but recommended).

## Writing a useful task description

Three things matter most:

1. **Be specific about the metric** — name it ("accuracy", "F1",
   "RMSE") and the direction ("higher is better"). mle-beast tries to
   auto-detect but explicit is faster and more reliable.
2. **Say "minimal" if you want speed** — phrases like "build a
   MINIMAL baseline" steer mle-beast toward simple models (logistic
   regression, small MLP) instead of pulling in transformers /
   ultralytics. This is usually what you want.
3. **Point at the data** — give a concrete path. If you don't,
   mle-beast wastes turns figuring out where the data lives.

Good:

> Build a MINIMAL model to predict customer churn on /tmp/churn/train.csv
> (binary classification, label column is "churned"). Use accuracy as
> the metric (higher is better). Target 0.85.

Bad:

> Make a model for the data.

## Where outputs live

After a run completes, the workspace contains:

- `model.py`, `train.py`, `evaluate.py`, `predict.py` — the final code
- `tests/test_smoke.py` — smoke tests mle-beast wrote and runs
- `checkpoints/` — saved model state
- `logs/training.log` — per-epoch metrics
- `eval_results.json` — the canonical score (this is what mle-beast
  reads back to decide "did this experiment improve?")
- `research_log.md` — the agent's own narrative across iterations
- `reports/report_<timestamp>.html` — pretty self-contained HTML
  reports (generated via the dashboard's "Show Report" button)
- `.git/` — every kept experiment is a commit on a dedicated branch

## Watching a run

While a run is in progress:

- **Web dashboard**: http://127.0.0.1:8000 — shows live stage
  progression, experiment-by-experiment scores, LLM cost, console
  output, and a clickable DAG view.
- **SQLite**: every event is persisted to `~/.mle-beast/mle_beast.db`.
  Useful for post-hoc queries:
  ```python
  from mle_beast.db import get_database
  db = get_database()
  for r in db.list_runs(limit=5):
      print(r["id"][:8], r["status"], r.get("task", "")[:60])
  ```

## Brownfield (existing repo) usage

When the user already has a working pipeline and wants improvements:

1. The workspace should contain their existing `model.py`,
   `train.py`, `evaluate.py`, `predict.py`.
2. The workspace's `.venv` is owned by the user — mle-beast won't
   touch it. They install dependencies themselves.
3. Pass `mode = "existing"` when creating the run.
4. mle-beast skips the baseline-generation step, trains the user's
   code once to record the starting score, then iterates.

## Common pitfalls

- **LLM provider not configured.** If you see "no provider configured,"
  the user needs `OPENROUTER_API_KEY` / `OPENAI_API_KEY` /
  `LOCAL_LLM_BASE_URL` in their environment or in `.env`. Run
  `mle-beast init` to set up.
- **First greenfield run is slow.** The first run downloads ~5.5 GB
  of ml-frameworks dependencies into the workspace's `.venv`. Later
  runs reuse poetry's cache and are much faster.
- **Base venv doesn't include transformers / ultralytics.** mle-beast
  ships a base ML stack (torch, sklearn, pandas, matplotlib, etc.).
  For NLP/heavy-vision tasks the agent will `poetry install -E nlp`
  / `-E vision-extra` on demand from inside the workspace.
- **Metric direction matters.** mle-beast will auto-detect, but
  explicit `lower_is_better=true` for loss/RMSE-style metrics avoids
  silent hill-climbing in the wrong direction.

## Cancelling a run

```python
from mle_beast.run_manager import get_run_manager
get_run_manager().cancel_run(run_id)
```

Or click the red "Cancel Run" button in the web UI while it's running.

## Getting help

- Code: <https://github.com/cgpadwick/mle-beast>
- Issues: <https://github.com/cgpadwick/mle-beast/issues>
- Architecture notes: see `CLAUDE.md` at the mle-beast repo root.
