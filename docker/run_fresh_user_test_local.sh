#!/bin/bash
# Host-side driver: build a fresh-user Docker image, run it with GPU
# access + API key, capture per-step logs to /tmp/fresh-user-logs/<distro>/.
#
# Distro selection via DISTRO env var (defaults to ubuntu2204):
#   ./docker/run_fresh_user_test_local.sh                 # 22.04
#   DISTRO=ubuntu2404 ./docker/run_fresh_user_test_local.sh  # 24.04
#
# Run from the repo root so the build context picks up the whole
# source tree (the .dockerignore at the root filters out the heavy
# stuff like node_modules / .git).

set -euo pipefail

DISTRO=${DISTRO:-ubuntu2204}
DOCKERFILE=docker/Dockerfile.fresh-user-${DISTRO}
IMAGE=mle-beast-freshtest:${DISTRO}
LOGS_DIR=${LOGS_DIR:-/tmp/fresh-user-logs/${DISTRO}}

: "${OPENROUTER_API_KEY:?must export OPENROUTER_API_KEY before running}"

mkdir -p "$LOGS_DIR"
rm -f "$LOGS_DIR"/*.log "$LOGS_DIR/SUMMARY.txt" 2>/dev/null || true

echo "=== Building image $IMAGE from $DOCKERFILE ==="
docker build -f "$DOCKERFILE" -t "$IMAGE" .

echo
echo "=== Running container (GPU mode) ==="
echo "  logs → $LOGS_DIR"
echo "  model → ${MLE_BEAST_MODEL:-deepseek/deepseek-v4-flash}"
echo

# --gpus all       → expose all GPUs to the container (matches a real user)
# --rm             → clean up the container after exit (logs are on the bind mount)
# -e KEYS          → pass the LLM provider key + model selection
# -v LOGS:...      → bind-mount the host log dir so we can grep after exit
# --network=host   → simplifies any docker-internal network weirdness; the test
#                    only reaches out to openrouter.ai, github, and pypi
docker run --rm \
    --gpus all \
    --network=host \
    -e "OPENROUTER_API_KEY=$OPENROUTER_API_KEY" \
    -e "MLE_BEAST_MODEL=${MLE_BEAST_MODEL:-deepseek/deepseek-v4-flash}" \
    -v "$LOGS_DIR:/home/mlebeast/logs" \
    "$IMAGE"
RC=$?

echo
echo "=== Container exited with code $RC ==="
echo "=== Logs in $LOGS_DIR ==="
ls -la "$LOGS_DIR"
echo
if [ -f "$LOGS_DIR/SUMMARY.txt" ]; then
  echo "=== SUMMARY.txt ==="
  cat "$LOGS_DIR/SUMMARY.txt"
fi

exit $RC
