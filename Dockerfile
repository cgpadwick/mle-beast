# User-facing mle-beast image. Built and published to
# ghcr.io/cgpadwick/mle-beast by the .github/workflows/docker-publish.yml
# workflow on each tagged release + every merge to main.
#
# User runs: `docker compose up` (see docker-compose.yml at repo root)
# → dashboard at http://localhost:8000, no host-side install needed.
#
# Design notes:
#  - Multi-stage. A `cachebuilder` stage runs the real `poetry install`
#    once to populate poetry's artifact cache (~/.cache/pypoetry/artifacts),
#    then the final stage COPYs that cache in — split across 16 layers so
#    `docker pull` streams them in parallel instead of as one ~3.5 GB blob.
#  - Pre-clones ml-frameworks AND ships poetry's primed artifact cache so
#    the first workspace setup is fast and OFFLINE: WorkspaceCreator runs
#    `poetry install`, which resolves from the workspace's poetry.lock and
#    pulls every wheel from the bundled artifact cache (verified: full
#    cu126 stack installs with ~1 MB of network, vs ~3.5 GB cold).
#  - Two env vars wire the bundled caches in:
#      MLE_BEAST_ML_FRAMEWORKS_CACHE — WorkspaceCreator reads this and
#        cp -r's the repo instead of git clone'ing.
#      MLE_PYTORCH_STACK — cuda_detection.py's override hook; pins the
#        cu126 stack so it matches the artifact cache we primed (without
#        it, select_pytorch_stack picks off the HOST driver's CUDA version
#        — possibly 13.x — and misses our 12.6 wheels).
#
#  Why not PIP_FIND_LINKS + pip download (the previous approach)? Poetry
#  does NOT honor PIP_FIND_LINKS — it uses its own resolver and artifact
#  cache — so a flat pip-download wheel dir was bundled but never used,
#  and every first run re-downloaded the whole stack. Priming poetry's
#  own cache is what actually makes the runtime install offline.

# ====================================================================
# base — shared by the cache builder and the final image: system deps,
# the non-root user, pipx + poetry, and the ml-frameworks clone.
# ====================================================================
FROM nvidia/cuda:12.6.0-base-ubuntu22.04 AS base

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
#    MLE_BEAST_ML_FRAMEWORKS_CACHE env var (see final stage) and `cp -r`'s
#    instead of git-cloning. Saves ~30s + network on every workspace.
# --------------------------------------------------------------------
RUN git clone --depth 1 --branch master \
        https://github.com/cgpadwick/ml-frameworks.git \
        /home/mlebeast/ml-frameworks-cache

# ====================================================================
# cachebuilder — prime poetry's artifact cache for the cu126 stack, then
# reorganize it into 16 first-hex buckets so the final stage can COPY
# each as its own (parallel-pullable) layer. This whole stage is
# discarded; only the staged artifact buckets are copied forward.
# ====================================================================
FROM base AS cachebuilder

# Run the same install the runtime workspace setup runs. This downloads
# every wheel in the cu126 lock into ~/.cache/pypoetry/artifacts. The
# throwaway .venv it also builds is irrelevant — we keep only the cache.
RUN cd /home/mlebeast/ml-frameworks-cache/stacks/pytorch-cu126 \
    && poetry install --no-root

# Poetry lays artifacts out as artifacts/<2hex>/<2hex>/.../<hash>/pkg.whl.
# Bucket the top-level 2-hex dirs by their first hex char into staging/0..f
# (all 16 created up front so an empty bucket still COPYs cleanly). We
# move rather than copy to keep the builder lean. Poetry's separate HTTP
# cache (~/.cache/pypoetry/cache, a redundant ~3.5 GB copy of the same
# downloads) is deliberately NOT staged — the artifact cache alone makes
# the runtime install offline.
# POSIX sh (dash) here — no bash substring syntax. `printf %.1s` gives the
# first char of each 2-hex dir name to pick its bucket.
RUN cd /home/mlebeast/.cache/pypoetry/artifacts \
    && for h in 0 1 2 3 4 5 6 7 8 9 a b c d e f; do mkdir -p /home/mlebeast/staging/$h; done \
    && for d in */; do d=${d%/}; first=$(printf '%.1s' "$d"); mv "$d" "/home/mlebeast/staging/$first/"; done

# ====================================================================
# final — the published image.
# ====================================================================
FROM base

# --------------------------------------------------------------------
# 5. Bring in the primed poetry artifact cache, one bucket per layer.
#    16 COPY layers ≈ 16 shards pullable in parallel (bounded by
#    Docker's max-concurrent-downloads), vs one ~3.5 GB single-stream
#    layer. Each COPY pulls the CONTENTS of a staging bucket into the
#    real artifacts dir, preserving poetry's hash-path layout.
# --------------------------------------------------------------------
COPY --from=cachebuilder --chown=mlebeast:mlebeast /home/mlebeast/staging/0/ /home/mlebeast/.cache/pypoetry/artifacts/
COPY --from=cachebuilder --chown=mlebeast:mlebeast /home/mlebeast/staging/1/ /home/mlebeast/.cache/pypoetry/artifacts/
COPY --from=cachebuilder --chown=mlebeast:mlebeast /home/mlebeast/staging/2/ /home/mlebeast/.cache/pypoetry/artifacts/
COPY --from=cachebuilder --chown=mlebeast:mlebeast /home/mlebeast/staging/3/ /home/mlebeast/.cache/pypoetry/artifacts/
COPY --from=cachebuilder --chown=mlebeast:mlebeast /home/mlebeast/staging/4/ /home/mlebeast/.cache/pypoetry/artifacts/
COPY --from=cachebuilder --chown=mlebeast:mlebeast /home/mlebeast/staging/5/ /home/mlebeast/.cache/pypoetry/artifacts/
COPY --from=cachebuilder --chown=mlebeast:mlebeast /home/mlebeast/staging/6/ /home/mlebeast/.cache/pypoetry/artifacts/
COPY --from=cachebuilder --chown=mlebeast:mlebeast /home/mlebeast/staging/7/ /home/mlebeast/.cache/pypoetry/artifacts/
COPY --from=cachebuilder --chown=mlebeast:mlebeast /home/mlebeast/staging/8/ /home/mlebeast/.cache/pypoetry/artifacts/
COPY --from=cachebuilder --chown=mlebeast:mlebeast /home/mlebeast/staging/9/ /home/mlebeast/.cache/pypoetry/artifacts/
COPY --from=cachebuilder --chown=mlebeast:mlebeast /home/mlebeast/staging/a/ /home/mlebeast/.cache/pypoetry/artifacts/
COPY --from=cachebuilder --chown=mlebeast:mlebeast /home/mlebeast/staging/b/ /home/mlebeast/.cache/pypoetry/artifacts/
COPY --from=cachebuilder --chown=mlebeast:mlebeast /home/mlebeast/staging/c/ /home/mlebeast/.cache/pypoetry/artifacts/
COPY --from=cachebuilder --chown=mlebeast:mlebeast /home/mlebeast/staging/d/ /home/mlebeast/.cache/pypoetry/artifacts/
COPY --from=cachebuilder --chown=mlebeast:mlebeast /home/mlebeast/staging/e/ /home/mlebeast/.cache/pypoetry/artifacts/
COPY --from=cachebuilder --chown=mlebeast:mlebeast /home/mlebeast/staging/f/ /home/mlebeast/.cache/pypoetry/artifacts/

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
#    - MLE_PYTORCH_STACK: pins the cu126 stack so it matches the primed
#      poetry artifact cache. Without it, select_pytorch_stack picks off
#      the HOST driver's CUDA version (could be 13.x) and would miss the
#      cached 12.6 wheels, forcing a full re-download.
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
