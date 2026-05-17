# Copyright 2026 Chris Padwick
# SPDX-License-Identifier: Apache-2.0

"""Entry point for starting the MLE-Beast web server."""

from __future__ import annotations

import asyncio


def start_web(
    host: str = "127.0.0.1",
    port: int = 8000,
    ssl_certfile: str | None = None,
    ssl_keyfile: str | None = None,
) -> None:
    """Start the web dashboard with uvicorn."""
    import uvicorn

    from mle_beast.events import get_event_bus
    from mle_beast.web.app import create_app

    app = create_app()

    config = uvicorn.Config(
        app,
        host=host,
        port=port,
        log_level="info",
        ssl_certfile=ssl_certfile,
        ssl_keyfile=ssl_keyfile,
    )
    server = uvicorn.Server(config)

    async def _serve() -> None:
        # Register the running loop with the event bus for async bridging
        loop = asyncio.get_running_loop()
        get_event_bus().set_loop(loop)
        await server.serve()

    scheme = "https" if ssl_certfile else "http"
    print(f"Starting MLE-Beast web dashboard at {scheme}://{host}:{port}")
    asyncio.run(_serve())
