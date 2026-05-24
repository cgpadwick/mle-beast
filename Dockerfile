# User-facing mle-beast image. Built and published to
# ghcr.io/cgpadwick/mle-beast by the .github/workflows/docker-publish.yml
# workflow on each tagged release + every merge to main.
#
# User runs: `docker compose up` (see docker-compose.yml at repo root)
# → dashboard at http://localhost:8000, no host-side install needed.
#
# Design notes:
#  - Single-stage build. Multi-stage with a separate builder doesn't buy
#    much here because the final image still needs Python, poetry, the
#    ml-frameworks cache, and the wheel cache — those are the bulk.
#  - Pre-clones ml-frameworks AND pre-primes the poetry cache so the
#    first workspace setup is fast (cp instead of git clone; install
#    resolves locally instead of pulling 5+ GB from PyPI).
#  - Two env vars (MLE_BEAST_ML_FRAMEWORKS_CACHE, MLE_BEAST_STACK_OVERRIDE)
#    tell mle-beast's workspace setup to USE the bundled cache instead
#    of going to the network. Without these, the image would still work
#    but each new workspace would re-download the world.

FROM nvidia/cuda:12.6.0-base-ubuntu22.04

ENV DEBIAN_FRONTEND=noninteractive \
    LANG=C.UTF-8 \
    LC_ALL=C.UTF-8 \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

# --------------------------------------------------------------------
# 1. System deps. Same prereq set the README describes for native
#    installs, plus build-essential / python3-dev so any sdist-only
#    transitive dep can compile if poetry's wheel cache misses.
# --------------------------------------------------------------------
RUN apt-get update && apt-get install -y --no-install-recommends \
        ca-certificates \
        curl \
        git \
        python3 \
        python3-pip \
        python3-venv \
        python3-dev \
        build-essential \
    && rm -rf /var/lib/apt/lists/*

# --------------------------------------------------------------------
# 2. Non-root user (uid 1000 matches the typical desktop user, which
#    avoids bind-mount permission surprises on Linux/WSL2).
# --------------------------------------------------------------------
RUN useradd -m -s /bin/bash -u 1000 mlebeast
USER mlebeast
WORKDIR /home/mlebeast
ENV PATH=/home/mlebeast/.local/bin:/home/mlebeast/.venv/bin:$PATH

# --------------------------------------------------------------------
# 3. pipx + poetry — installed at image build time so first workspace
#    setup doesn't have to fetch them. Poetry config persists per-user.
# --------------------------------------------------------------------
RUN python3 -m pip install --user --no-cache-dir pipx \
    && python3 -m pipx ensurepath \
    && pipx install poetry \
    && poetry config virtualenvs.in-project true \
    && poetry config virtualenvs.create true

# --------------------------------------------------------------------
# 4. Pre-clone ml-frameworks. WorkspaceCreator detects this dir via the
#    MLE_BEAST_ML_FRAMEWORKS_CACHE env var (see step 7) and `cp -r`'s
#    instead of git-cloning. Saves ~30s + network on every workspace.
# --------------------------------------------------------------------
RUN git clone --depth 1 --branch master \
        https://github.com/cgpadwick/ml-frameworks.git \
        /home/mlebeast/ml-frameworks-cache

# --------------------------------------------------------------------
# 5. Pre-prime the poetry wheel cache against the cu126 stack. After
#    this, a fresh `poetry install --no-root` against the same
#    pyproject + lock resolves from cache (~30s) instead of fetching
#    the world (~10 min). The .venv made by priming is throwaway; we
#    keep the cache (~/.cache/pypoetry/) and discard the build dir.
# --------------------------------------------------------------------
RUN mkdir -p /tmp/cache-priming && \
    cp /home/mlebeast/ml-frameworks-cache/stacks/pytorch-cu126/pyproject.toml /tmp/cache-priming/ && \
    cp /home/mlebeast/ml-frameworks-cache/stacks/pytorch-cu126/poetry.lock /tmp/cache-priming/ && \
    cd /tmp/cache-priming && \
    poetry install --no-root && \
    rm -rf /tmp/cache-priming

# --------------------------------------------------------------------
# 6. Copy the mle-beast source and install into a dedicated venv.
#    Editable install so users with a local source bind-mount can
#    iterate without rebuilding (though the typical user just pulls
#    the published image).
#
#    .dockerignore at repo root keeps the COPY lean (~10 MB instead of
#    pulling in node_modules / .git / pytest caches / etc.).
# --------------------------------------------------------------------
COPY --chown=mlebeast:mlebeast . /home/mlebeast/mle-beast
RUN python3 -m venv /home/mlebeast/.venv \
    && /home/mlebeast/.venv/bin/pip install --no-cache-dir -e "/home/mlebeast/mle-beast[web]"

# --------------------------------------------------------------------
# 7. Wire the bundled cache + stack override.
#    - MLE_BEAST_ML_FRAMEWORKS_CACHE: WorkspaceCreator reads this and
#      uses cp -r from this dir instead of cloning ml-frameworks again.
#    - MLE_PYTORCH_STACK: forces the cu126 stack to match the poetry
#      cache we primed. Without it, select_pytorch_stack would pick
#      based on the HOST driver's CUDA version (could be 13.x) and
#      miss our cached 12.6 wheels. (This env var is the existing
#      override hook in cuda_detection.py.)
# --------------------------------------------------------------------
ENV MLE_BEAST_ML_FRAMEWORKS_CACHE=/home/mlebeast/ml-frameworks-cache \
    MLE_PYTORCH_STACK=pytorch-cu126

# --------------------------------------------------------------------
# 8. Persistence mount points. The compose file binds host paths here
#    so the SQLite DB + workspaces survive `docker compose down`.
# --------------------------------------------------------------------
VOLUME ["/home/mlebeast/.mle-beast", "/workspaces"]

# --------------------------------------------------------------------
# 9. Dashboard listens on the container's port 8000 on all interfaces
#    (so the docker port forward to the host actually works). User
#    points their browser at http://localhost:8000.
# --------------------------------------------------------------------
EXPOSE 8000
ENTRYPOINT ["mle-beast", "--no-browser", "--host", "0.0.0.0", "--port", "8000"]
