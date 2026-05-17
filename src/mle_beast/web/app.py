# Copyright 2026 Chris Padwick
# SPDX-License-Identifier: Apache-2.0

"""FastAPI application factory for MLE-Beast web dashboard."""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

_WEB_DIR = Path(__file__).parent
_TEMPLATES_DIR = _WEB_DIR / "templates"
_STATIC_DIR = _WEB_DIR / "static"


def create_app() -> FastAPI:
    """Create and configure the FastAPI application."""
    app = FastAPI(title="MLE-Beast Dashboard", version="0.1.0")

    # CORS — the React prototype dashboard runs on Vite's dev server
    # (default port 5173) and hits this FastAPI app cross-origin during
    # development. Production builds will be served from the same origin
    # so this is purely a dev-mode convenience; we keep it permissive
    # because the dashboard is bound to localhost anyway.
    from fastapi.middleware.cors import CORSMiddleware
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Mount static files
    app.mount("/static", StaticFiles(directory=str(_STATIC_DIR)), name="static")

    # Register templates
    templates = Jinja2Templates(directory=str(_TEMPLATES_DIR))
    app.state.templates = templates

    # Register routes
    from mle_beast.web.routes import register_routes
    register_routes(app, templates)

    return app
