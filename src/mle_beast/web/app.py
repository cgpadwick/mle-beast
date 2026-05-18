# Copyright 2026 Chris Padwick
# SPDX-License-Identifier: Apache-2.0

"""FastAPI application factory for MLE-Beast.

Serves only the `/api/*` JSON endpoints used by the React dashboard.
"""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware


def create_app() -> FastAPI:
    """Create and configure the FastAPI application."""
    app = FastAPI(title="MLE-Beast API", version="0.1.0")

    # CORS — the React dashboard runs on Vite's dev server (default port 5173)
    # and hits this FastAPI app cross-origin during development. In production
    # the built React assets are served from the same origin, so this is purely
    # a dev-mode convenience. We keep it permissive because the server binds
    # to localhost by default.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    from mle_beast.web.routes import register_routes
    register_routes(app)

    return app
