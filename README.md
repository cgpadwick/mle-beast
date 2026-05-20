# mle-beast

[![Tests](https://github.com/cgpadwick/mle-beast/actions/workflows/tests.yml/badge.svg)](https://github.com/cgpadwick/mle-beast/actions/workflows/tests.yml)
[![License: Apache 2.0](https://img.shields.io/badge/License-Apache_2.0-blue.svg)](LICENSE)
[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)

**An LLM-driven ML engineering agent.** Point it at a dataset and a goal — it writes the model, tests it, trains it, evaluates it, and iteratively improves the result via an actor/critic hill-climbing loop.

Give it as little as one sentence:

```yaml
task_description: Build an image classifier for this dataset.
target_metric: { name: accuracy, target_value: 0.85 }
```

…and it'll explore architectures (CNN → ViT → classical CV + sklearn), augmentations, and hyperparameters until it clears your bar.

## Two modes

| Mode | Use when |
|---|---|
| **Greenfield** (default) | You have data but no code. Agent writes `model.py`, `train.py`, `predict.py` from scratch, then hill-climbs. |
| **Brownfield** (`mode = "existing"`) | You have working code that needs improvement. Agent reads your existing baseline, then proposes/tests/keeps changes. |

Both modes share the same hill-climbing engine: propose → implement → test → train → evaluate, keep improvements via git, revert failures.

## Install

Prerequisites for greenfield runs (mle-beast builds the workspace venv for you):

- **git** — clones the [ml-frameworks](https://github.com/cgpadwick/ml-frameworks) stack into each new workspace
- **poetry** — installs the pinned ml-frameworks dependency lock into the workspace venv. Install with `pipx install poetry` or `curl -sSL https://install.python-poetry.org | python3 -`

(Brownfield / BYO-environment runs skip both — you bring your own venv.)

```bash
pip install -e .

# With the optional web dashboard
pip install -e ".[web]"
```

## Quickstart

mle-beast needs an LLM provider. Pick one:

```bash
# OpenAI
export OPENAI_API_KEY=sk-...

# Or OpenRouter (recommended — access to many models via one key)
export OPENROUTER_API_KEY=sk-or-...

# Or a local OpenAI-compatible server (vLLM, Ollama, llama.cpp, etc.)
export LOCAL_LLM_BASE_URL=http://localhost:8000/v1
```

Then run a sample project:

```bash
pytest tests/integration/test_shapes.py -m integration -v -s
```

You should see the agent discover the dataset, write a baseline classifier, train it, and iteratively improve it until accuracy clears 0.85.

## How it works

```
GitSetup → Baseline → [Propose → Implement → Test → Train → Evaluate] × N → Done
                       ↑__________________________________________________|
                                    hill-climb loop
```

- **Actors** run an inner tool loop — the LLM picks tools (read/write file, run shell command, launch training, etc.) via a [discriminated-union Pydantic model](src/mle_beast/models/tool_calls.py), eliminating tool hallucination.
- **Critics** are procedural: they run pytest, parse logs, check git state — and call the LLM once for feedback text. Critics don't use tools.
- **Convergence**: `max_steps` (default 30) or `max_consecutive_failures` (default 10), whichever fires first. `target_metric` lets the run exit early when the bar is cleared.

## Choosing a model

```bash
# Override the default model for any provider
export MLE_BEAST_MODEL=anthropic/claude-sonnet-4

# Provider priority: LOCAL_LLM_BASE_URL > OPENROUTER_API_KEY > OPENAI_API_KEY
```

Recommended models (good cost/quality for hill-climbing):

| Provider | Model | Notes |
|---|---|---|
| OpenRouter | `deepseek/deepseek-v4-flash` | Cheap, surprisingly capable on ML tasks |
| OpenAI | `gpt-5-mini` | Solid, more expensive |
| Local | `Qwen/Qwen3-Coder-30B-A3B-Instruct` | Strong open-weight code model |

## Configuration via project.yaml

Sample projects in `tests/integration/*/project.yaml` show the full schema. The minimum:

```yaml
goals:
  task_description: Build an image classifier for this dataset.
  target_metric:
    name: accuracy
    target_value: 0.85
    comparison: ">="
```

**Tip from running the suite:** terse task descriptions outperform prescriptive ones. `"Build an image classifier for this dataset"` lets the agent explore architecture freely; `"Build a CNN with Conv2d layers and data augmentation"` anchors the search inside CNN-land and often fails to escape on small datasets. Be specific only when domain constraints actually matter.

## Web dashboard

```bash
pip install -e ".[web]"
mle-beast --web
```

Then open `http://localhost:8000`. The React frontend shows live run state, hill-climb experiments, token usage, and a DAG view of the pipeline.

## Running unit tests

```bash
# Unit tests (no API key needed)
pytest tests/ -k "not integration"

# A single integration test
pytest tests/integration/test_churn_quick.py -m integration -v -s
```

CI runs unit tests on Python 3.10 / 3.11 / 3.12 against every PR.

## Contributing

PRs welcome. See [CONTRIBUTING.md](CONTRIBUTING.md) — contributions use the [Developer Certificate of Origin](https://developercertificate.org/) (just add `-s` to your commits).

## License

[Apache License 2.0](LICENSE). Third-party dependency attributions in [THIRD_PARTY_LICENSES.md](THIRD_PARTY_LICENSES.md).
