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
#  - Three env vars tell mle-beast's workspace setup to USE the
#    pre-staged caches instead of going to the network:
#      MLE_BEAST_ML_FRAMEWORKS_CACHE — WorkspaceCreator reads this and
#        cp -r's instead of git clone'ing.
#      MLE_PYTORCH_STACK — cuda_detection.py's existing override hook;
#        forces the cu126 stack to match the wheels we pre-downloaded.
#      PIP_FIND_LINKS — points pip at /opt/wheels so the workspace's
#        poetry install (which shells out to pip) finds wheels
#        locally instead of going to PyPI.
#  - The wheel cache is split across many small Docker layers (~16)
#    so `docker pull` can stream them in parallel. The naive
#    "single big poetry install" approach produced one ~7 GB layer
#    that pulled as a single TCP stream and took ~30 min on a fast
#    connection. Splitting into N layers reduces pull time roughly
#    by N (modulo Docker's max-concurrent-downloads).

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
# Pre-create the wheel cache dir while still root (/opt is root-owned) and
# hand it to mlebeast, so the non-root build steps below can populate it.
RUN mkdir -p /opt/wheels && chown mlebeast:mlebeast /opt/wheels
USER mlebeast
WORKDIR /home/mlebeast
ENV PATH=/home/mlebeast/.local/bin:/home/mlebeast/.venv/bin:$PATH

# --------------------------------------------------------------------
# 3. pipx + poetry — installed at image build time so first workspace
#    setup doesn't have to fetch them. Poetry config persists per-user.
#    poetry-plugin-export is injected because Poetry 2.x dropped the
#    built-in `poetry export` command (it lives in this plugin now) and
#    step 5 below uses `poetry export` to generate the wheel-bucket
#    requirements files.
# --------------------------------------------------------------------
RUN python3 -m pip install --user --no-cache-dir pipx \
    && python3 -m pipx ensurepath \
    && pipx install poetry \
    && pipx inject poetry poetry-plugin-export \
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
# 5. Pre-download wheels for the cu126 stack into /opt/wheels, split
#    across many small RUN layers. Each RUN = one Docker layer = one
#    parallelizable stream during `docker pull`. The old approach (a
#    single `poetry install` priming step) produced one ~7 GB layer
#    that pulled as a single TCP stream — ~30 min to pull on a fast
#    connection because Docker can't parallelize within one layer.
#    Splitting into ~16 buckets lets Docker pull multiple shards
#    concurrently (`max-concurrent-downloads`, default 3-5), cutting
#    end-to-end pull time roughly to 1/N.
#
#    Pip writes wheels to /opt/wheels (a flat dir). At runtime the
#    workspace's `poetry install` shells out to pip, which honors
#    PIP_FIND_LINKS=/opt/wheels (set later in step 7) and skips
#    network for any wheel already on disk.
#
#    `--no-deps` keeps each bucket installable independently — the
#    poetry-exported requirements file lists every transitive
#    dependency explicitly, so we don't need pip's resolver to add
#    anything per-bucket. That also avoids per-bucket dependency
#    resolution overlap.
# --------------------------------------------------------------------
RUN cd /home/mlebeast/ml-frameworks-cache/stacks/pytorch-cu126 \
    && poetry export -f requirements.txt --output /tmp/all-reqs.txt --without-hashes \
    && python3 -c "\
raw = [l for l in open('/tmp/all-reqs.txt') if l.strip() and not l.startswith('#')]; \
opts = [l for l in raw if l.lstrip().startswith('-')]; \
pkgs = [l for l in raw if not l.lstrip().startswith('-')]; \
[open(f'/tmp/reqs-{i:02d}.txt', 'w').writelines(opts + pkgs[i::16]) for i in range(16)]; \
print(f'Split {len(pkgs)} packages into 16 buckets (+{len(opts)} index opt(s) per bucket)')" \
    && mkdir -p /opt/wheels

# Each pip-download is its own Docker layer. 16 layers ≈ 16 shards
# pullable in parallel. Round-robin partitioning (lines[i::16]) keeps
# bucket sizes roughly balanced since the requirements list is
# alphabetic + sorted-ish.
RUN pip download -r /tmp/reqs-00.txt -d /opt/wheels --no-deps
RUN pip download -r /tmp/reqs-01.txt -d /opt/wheels --no-deps
RUN pip download -r /tmp/reqs-02.txt -d /opt/wheels --no-deps
RUN pip download -r /tmp/reqs-03.txt -d /opt/wheels --no-deps
RUN pip download -r /tmp/reqs-04.txt -d /opt/wheels --no-deps
RUN pip download -r /tmp/reqs-05.txt -d /opt/wheels --no-deps
RUN pip download -r /tmp/reqs-06.txt -d /opt/wheels --no-deps
RUN pip download -r /tmp/reqs-07.txt -d /opt/wheels --no-deps
RUN pip download -r /tmp/reqs-08.txt -d /opt/wheels --no-deps
RUN pip download -r /tmp/reqs-09.txt -d /opt/wheels --no-deps
RUN pip download -r /tmp/reqs-10.txt -d /opt/wheels --no-deps
RUN pip download -r /tmp/reqs-11.txt -d /opt/wheels --no-deps
RUN pip download -r /tmp/reqs-12.txt -d /opt/wheels --no-deps
RUN pip download -r /tmp/reqs-13.txt -d /opt/wheels --no-deps
RUN pip download -r /tmp/reqs-14.txt -d /opt/wheels --no-deps
RUN pip download -r /tmp/reqs-15.txt -d /opt/wheels --no-deps
# Throw away the requirements file scratch space; /opt/wheels persists.
RUN rm -f /tmp/all-reqs.txt /tmp/reqs-*.txt

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
#    - MLE_PYTORCH_STACK: forces the cu126 stack to match the wheels
#      we pre-downloaded into /opt/wheels. Without it,
#      select_pytorch_stack would pick based on the HOST driver's
#      CUDA version (could be 13.x) and miss our pre-staged 12.6
#      wheels. (This env var is the existing override hook in
#      cuda_detection.py.)
#    - PIP_FIND_LINKS: pip looks here BEFORE going to PyPI. When the
#      workspace's poetry install shells out to pip, pip finds our
#      pre-staged wheels in /opt/wheels and skips the download. This
#      is what lets the multi-layer pull from step 5 actually pay
#      off at workspace-setup time.
# --------------------------------------------------------------------
ENV MLE_BEAST_ML_FRAMEWORKS_CACHE=/home/mlebeast/ml-frameworks-cache \
    MLE_PYTORCH_STACK=pytorch-cu126 \
    PIP_FIND_LINKS=/opt/wheels

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
