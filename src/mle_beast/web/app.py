# Copyright 2026 Chris Padwick
# SPDX-License-Identifier: Apache-2.0

"""FastAPI application factory for MLE-Beast.

Serves:
- /api/*  — JSON endpoints consumed by the React dashboard
- /       — built React SPA assets (when bundled)

When running from a fresh source checkout that hasn't been built
(`npm run build` in prototypes/dashboard/), the static mount is
skipped and the dev workflow stays: developer runs `npm run dev` on
:5173 with Vite proxying /api/* to this server on :8000.
"""

from __future__ import annotations

import logging
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

_STATIC_DIR = Path(__file__).parent / "static"

logger = logging.getLogger(__name__)


def create_app() -> FastAPI:
    """Create and configure the FastAPI application."""
    app = FastAPI(title="MLE-Beast", version="0.1.0")

    # CORS — purely a dev-mode convenience for the Vite dev server hitting
    # this app cross-origin. In bundled mode the SPA is served from the
    # same origin so CORS doesn't apply. Permissive because the server
    # binds to localhost by default.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    from mle_beast.web.routes import register_routes
    register_routes(app)

    # Mount the React SPA at /. FastAPI route matching prefers the more
    # specific /api/* routes over this catchall, and StaticFiles(html=True)
    # falls back to index.html for any unmatched path — that's SPA routing.
    #
    # Skipped when the static dir doesn't exist (developer ran without
    # `npm run build`). In that case the dev workflow is: Vite on :5173,
    # this server on :8000, browse http://localhost:5173 .
    if _STATIC_DIR.exists() and (_STATIC_DIR / "index.html").exists():
        app.mount(
            "/",
            StaticFiles(directory=str(_STATIC_DIR), html=True),
            name="spa",
        )
    else:
        logger.info(
            "SPA static assets not found at %s — running in dev mode. "
            "To bundle the dashboard: cd prototypes/dashboard && npm run build",
            _STATIC_DIR,
        )

    return app
