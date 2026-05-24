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

## Quick start with Docker (recommended)

Zero Python install needed on your host. Three commands:

```bash
# 1. Grab the compose file + env template
curl -O https://raw.githubusercontent.com/cgpadwick/mle-beast/main/docker-compose.yml
curl -O https://raw.githubusercontent.com/cgpadwick/mle-beast/main/.env.example

# 2. Drop in your LLM provider key
cp .env.example .env
# edit .env, set OPENROUTER_API_KEY=sk-or-...  (or OPENAI_API_KEY, etc.)

# 3. Up and away
docker compose up
# → dashboard at http://localhost:8000
```

The published image at `ghcr.io/cgpadwick/mle-beast` ships with ml-frameworks pre-cloned and the poetry wheel cache pre-primed, so the first greenfield run is fast (~30s of workspace setup instead of ~10 min of PyPI fetching). The default compose pulls `:edge` (continuous-delivery, follows every merge to main); switch to `:0.1.0` / `:latest` once stable releases are tagged.

### Requirements

- **Docker** (or Docker Desktop on Mac/Windows). Linux: also install `nvidia-container-toolkit` if you want GPU access; the image falls back to CPU automatically if the GPU isn't visible.
- **An LLM provider key** — get one at [openrouter.ai](https://openrouter.ai/) (recommended, one key for many models), or use OpenAI / a local OpenAI-compatible endpoint.

### Persistence

`docker compose up` creates two host directories next to your `docker-compose.yml`:

| Path | Holds |
|---|---|
| `./.mle-beast/` | SQLite DB + global settings. Run history survives `docker compose down`. |
| `./workspaces/` | Per-run workspace dirs (`model.py`, checkpoints, reports). `cd` in from your host to grab a model. |

### Without compose

The same image works with raw `docker run` if you prefer:

```bash
docker run --rm --gpus all -p 8000:8000 \
  -e OPENROUTER_API_KEY=sk-or-... \
  -v $(pwd)/.mle-beast:/home/mlebeast/.mle-beast \
  -v $(pwd)/workspaces:/workspaces \
  ghcr.io/cgpadwick/mle-beast:edge
```

---

## Developer install (native Python)

Use this if you want to **bring your own venv** ([brownfield mode](#two-modes)) or **iterate on the mle-beast source**. The Docker bundle above is the easy "just try it" path; this is for when you want more control.

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

### Prerequisites for native install

mle-beast itself just needs Python 3.10+. For **greenfield** runs (where mle-beast builds a workspace venv for you) it also needs:

- **git** — clones the [ml-frameworks](https://github.com/cgpadwick/ml-frameworks) stack into each workspace
- **poetry** — installs ml-frameworks's pinned dependency lock into that workspace venv

The `mle-beast init` step below diagnoses these for you and offers to install poetry via pipx if it's missing. **Brownfield / BYO-environment runs skip both** — you bring your own venv.

### First-run setup (native)

After installing mle-beast, run `mle-beast init` in your project directory:

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

## Safety guardrails

Every shell command and Python file the agent runs is pre-screened against a small policy at `src/mle_beast/safety/policy.json`. Blocked commands return a recoverable error string (`ERROR: blocked by safety policy: <reason>`) that the agent sees in its tool-result loop and self-corrects from — the run continues, the dangerous command never executes.

**Blocked by default:**

- **Privilege escalation tokens**: `sudo`, `su`, `doas`, `pkexec`. Word-boundary matched, so `pseudo-random` is fine.
- **Catastrophic patterns**: `rm -rf /`, `rm -rf ~`, `mkfs`, `dd if=...of=/dev/`, `curl ... | bash`, fork bombs, `shutdown` / `reboot`.
- **Workspace escapes**: any destructive verb (`rm`, `mv`, `chmod`, `chown`, `tee`, shell redirects) with an absolute or `..`-relative path that resolves outside the workspace.
- **Remote git mutations**: `git push` (any form). Local git operations — `commit`, `status`, `log`, `checkout`, `diff`, `add` — are always allowed because the hill-climb pipeline relies on them.

**Deliberately NOT blocked:**

- Read-only commands outside the workspace (`cat /etc/os-release`, `ls /usr/lib`) — the agent legitimately needs to inspect system files sometimes.
- Workspace-internal writes (`rm -rf checkpoints/old`, `mv train.py train.py.bak`) — workspace cleanup is normal hill-climb behavior.
- Writes to allow-listed paths outside the workspace: `/tmp`, `/var/tmp`, `~/.cache`, `~/.config/pypoetry`, `~/.mle-beast` (these hold poetry caches, dataset downloads, mle-beast's own DB).

### Editing the policy

Open `src/mle_beast/safety/policy.json` and:

- Add a whole-word token (e.g. another privilege-escalation tool) to `blocked_tokens`.
- Add a Python regex (case-insensitive, matched against the full command line) to `blocked_patterns`.
- Add a path you DO want writable outside the workspace to `allow_paths_outside_workspace`.

Restart any running mle-beast process to pick up the change — the policy is loaded once per process and cached.

### Audit log

Every block is appended to `<workspace>/logs/safety.log` as a tab-separated line:

```
2026-05-21T11:24:33	shell	token:sudo	sudo apt install foo
```

Useful when a run takes a recovery path you didn't expect — grep the file to see exactly what was blocked and why.

### Threat model

These guardrails catch the **confused-LLM failure mode** — an agent that hallucinates `sudo apt install ...` or accidentally points `rm -rf` at the wrong directory. They are NOT a sandbox: a deliberately adversarial model could bypass string-based checks (e.g. `$(echo s)udo`, `base64 -d | sh`). For threat models that include hostile prompts, container-based isolation is the correct answer; mle-beast doesn't ship that today.

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
