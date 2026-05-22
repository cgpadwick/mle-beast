#!/bin/bash
# Fresh-user smoke test driver. Runs inside the Dockerfile.fresh-user-*
# images. Simulates the actions of a brand-new user who has just
# installed Python/git/pipx on their box and is trying mle-beast for
# the first time.
#
# Required env vars (passed via `docker run -e`):
#   OPENROUTER_API_KEY    The LLM provider key for the integration test
#   MLE_BEAST_MODEL       (optional) Model slug; defaults to deepseek/deepseek-v4-flash
#
# Bind a host dir at /home/mlebeast/logs to capture per-step logs.

set -u
set -o pipefail

REPO=/home/mlebeast/mle-beast
LOGS=/home/mlebeast/logs
mkdir -p "$LOGS"

: "${OPENROUTER_API_KEY:?must pass OPENROUTER_API_KEY via docker run -e}"
: "${MLE_BEAST_MODEL:=deepseek/deepseek-v4-flash}"
export MLE_BEAST_MODEL

# Step counters — match log filenames to step names for easy grepping.
step() {
  echo
  echo "============================================================"
  echo "STEP $1: $2"
  echo "============================================================"
}

fail() {
  echo "FAIL: $1" | tee -a "$LOGS/SUMMARY.txt"
  exit 1
}

ok() {
  echo "OK:   $1" | tee -a "$LOGS/SUMMARY.txt"
}

: > "$LOGS/SUMMARY.txt"
echo "Fresh-user test started at $(date)" >> "$LOGS/SUMMARY.txt"

# ----------------------------------------------------------------
step 1 "pipx ensurepath (PATH bootstrap)"
# pipx ensurepath modifies shell init files; our PATH is already set
# in the Dockerfile so this should be a no-op, but the user's first
# action after installing pipx via apt would be to run this. Document
# that it ran.
pipx ensurepath > "$LOGS/01_pipx_ensurepath.log" 2>&1 || true
which pipx && pipx --version
ok "pipx on PATH"

# ----------------------------------------------------------------
step 2 "pipx install -e mle-beast (the user install)"
# This is the official user install path per README. Editable from a
# clone — in production users would `pipx install mle-beast` from PyPI
# once we publish.
pipx install -e "$REPO" 2>&1 | tee "$LOGS/02_pipx_install.log"
if ! which mle-beast >/dev/null 2>&1; then
  fail "mle-beast command not on PATH after pipx install"
fi
mle-beast --help 2>&1 | head -3
ok "mle-beast command installed"

# ----------------------------------------------------------------
step 3 "mle-beast init --check (diagnose only)"
mle-beast init --check 2>&1 | tee "$LOGS/03_init_check.log"
ok "init --check completed (poetry may be missing — init --yes installs it)"

# ----------------------------------------------------------------
step 4 "mle-beast init --yes (scaffolds project; installs poetry if missing)"
PROJ=/home/mlebeast/myproject
mkdir -p "$PROJ"
cd "$PROJ"
git init -q
mle-beast init --yes --no-validate-key 2>&1 | tee "$LOGS/04_init.log"
[ -f .env ] || fail ".env not written"
[ -f AGENTS.md ] || fail "AGENTS.md not written"
echo "--- .env contents ---"
cat .env
echo "--- (end .env) ---"
ok "init completed; .env + AGENTS.md scaffolded"

# Verify poetry is now on PATH (init should have installed it via pipx)
if ! which poetry >/dev/null 2>&1; then
  echo "WARN: poetry not on PATH after mle-beast init. Greenfield run will fail at workspace setup." \
      | tee -a "$LOGS/SUMMARY.txt"
else
  poetry --version
  ok "poetry on PATH ($(which poetry))"
fi

# ----------------------------------------------------------------
step 5 "Integration test: tests/integration/test_churn_quick.py"
# Run pytest from inside the pipx-managed venv so mle_beast is importable.
# This is the "real run" — exercises the full first-run path: ml-frameworks
# clone + ~5.5 GB poetry install + hill-climb pipeline.
#
# Discover the venv path dynamically — older pipx (Ubuntu 22.04) uses
# ~/.local/pipx/venvs/, newer pipx (Ubuntu 24.04) uses
# ~/.local/share/pipx/venvs/ per XDG. `pipx environment` is the
# pipx-native API for this and works across versions.
PIPX_VENVS=$(pipx environment --value PIPX_LOCAL_VENVS 2>/dev/null || true)
if [ -z "$PIPX_VENVS" ]; then
  # Last-ditch fallback: scan both known locations.
  for candidate in "$HOME/.local/pipx/venvs" "$HOME/.local/share/pipx/venvs"; do
    [ -d "$candidate" ] && PIPX_VENVS="$candidate" && break
  done
fi
VENV_PY="$PIPX_VENVS/mle-beast/bin/python3"
if [ ! -x "$VENV_PY" ]; then
  echo "DEBUG: pipx environment listing follows" >&2
  pipx environment 2>&1 | head -20 >&2 || true
  pipx list 2>&1 | head -20 >&2 || true
  fail "pipx venv python not found at $VENV_PY (PIPX_VENVS='$PIPX_VENVS')"
fi
echo "Using venv python: $VENV_PY"

# Need PyYAML in the venv for the integration test conftest. mle-beast
# already ships PyYAML as a runtime dep so pipx should have included it,
# but install defensively in case the test harness needs anything extra.
"$VENV_PY" -m pip install --quiet pyyaml 2>&1 | tee -a "$LOGS/05_pytest_install_extras.log" || true

cd "$REPO"
START=$(date +%s)
"$VENV_PY" -m pytest tests/integration/test_churn_quick.py -m integration -v -s \
    > "$LOGS/05_pytest_run.log" 2>&1
RC=$?
END=$(date +%s)
DUR=$((END - START))

if [ $RC -eq 0 ]; then
  ok "integration test PASSED in ${DUR}s"
else
  echo "FAIL: integration test exit $RC after ${DUR}s" | tee -a "$LOGS/SUMMARY.txt"
  echo "--- last 60 lines of pytest log ---"
  tail -60 "$LOGS/05_pytest_run.log"
  exit $RC
fi

# ----------------------------------------------------------------
echo
echo "============================================================"
echo "ALL DONE"
echo "============================================================"
cat "$LOGS/SUMMARY.txt"
