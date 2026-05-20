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

```bash
# Recommended — installs in an isolated venv, command goes on your PATH
pipx install mle-beast

# Or with the optional web dashboard
pipx install 'mle-beast[web]'

# Plain pip also works
pip install mle-beast
```

Don't have `pipx`? `python3 -m pip install --user pipx && python3 -m pipx ensurepath` then open a new shell.

**Working from a clone (e.g. contributing):**

```bash
git clone https://github.com/cgpadwick/mle-beast.git
cd mle-beast
pip install -e '.[web]'    # editable install — your changes are picked up live
```

### Prerequisites

mle-beast itself just needs Python 3.10+. For **greenfield** runs (where mle-beast builds a workspace venv for you) it also needs:

- **git** — clones the [ml-frameworks](https://github.com/cgpadwick/ml-frameworks) stack into each workspace
- **poetry** — installs ml-frameworks's pinned dependency lock into that workspace venv

The `mle-beast init` step below diagnoses these for you and offers to install poetry via pipx if it's missing. **Brownfield / BYO-environment runs skip both** — you bring your own venv.

## Quickstart

After installing mle-beast (above), run `mle-beast init` in your project directory:

```bash
mkdir ~/my-mle-experiment && cd ~/my-mle-experiment
git init -q
mle-beast init
```

The init flow walks you through:

1. **Prereq check** — verifies Python / poetry / git, offers to install poetry via pipx if it's missing.
2. **LLM provider** — detects API keys already in your shell environment; if multiple are present, asks which to use. If none, prompts you to paste one in.
3. **Model picker** — fetches the live catalog from your provider, prunes stale defaults, fuzzy-matches typos (`gpt-4o-mini` against OpenRouter → corrected to `openai/gpt-4o-mini`).
4. **Scaffolding** — writes `.env`, ensures `.env` is gitignored, and drops an `AGENTS.md` so coding agents (Claude Code, Cursor, Aider) can drive mle-beast on your behalf.

Then start the dashboard:

```bash
mle-beast    # opens http://127.0.0.1:8000 in your browser
```

Or jump straight into the CLI REPL:

```bash
mle-beast --no-web
```

Or run a sample integration test end-to-end:

```bash
pytest tests/integration/test_shapes.py -m integration -v -s
```

You should see the agent discover the dataset, write a baseline classifier, train it, and iteratively improve it until accuracy clears 0.85.

### Init flags

```bash
mle-beast init --check          # diagnose only; don't write any files
mle-beast init --yes            # accept all defaults; no prompts (CI-friendly)
mle-beast init --no-validate-key   # skip the live /models verification
mle-beast init --cwd PATH       # scaffold into PATH instead of cwd
```

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

`mle-beast init` walks you through this interactively, but the underlying knobs (which init writes to `.env` for you) are:

```bash
# Pick a model. init writes this based on the live provider catalog.
export MLE_BEAST_MODEL=deepseek/deepseek-v4-flash

# Pin the provider explicitly when multiple keys are present.
# Without this pin, the resolution order is:
#   LOCAL_LLM_BASE_URL > OPENROUTER_API_KEY > OPENAI_API_KEY
export MLE_BEAST_PROVIDER=openrouter
```

**Shell environment variables always win over `.env`** — `.env` only fills in gaps. So if you're testing a one-off model swap, just `MLE_BEAST_MODEL=other/model mle-beast` overrides what's in `.env` for that invocation.

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

The dashboard is the default when you run `mle-beast` — it'll open in your browser automatically.

```bash
mle-beast                              # starts dashboard + opens browser
mle-beast --no-browser                 # starts dashboard, you open the URL yourself
mle-beast --no-browser --port 9000     # custom port
mle-beast --no-web                     # drop into the CLI REPL instead
```

The React frontend shows live run state, hill-climb experiments, per-experiment scores + commit SHAs, token usage, a DAG view of the pipeline, and a **"Show Report"** button that pops a self-contained HTML report (saved to `<workspace>/reports/` for offline sharing or PDF export).

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
