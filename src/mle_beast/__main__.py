# Copyright 2026 Chris Padwick
# SPDX-License-Identifier: Apache-2.0

"""Entry point for `python -m mle_beast` / `mle-beast`.

Default: starts the web dashboard and opens a browser tab.

Flags:
  --no-web        Skip the web dashboard and drop into the legacy CLI REPL.
  --no-browser    Start the dashboard but don't open a browser tab.
  --host HOST     Bind address (default 127.0.0.1).
  --port PORT     Port (default 8000).
  --ssl-cert PATH, --ssl-key PATH    Enable HTTPS.

Backwards compat: --web is accepted (and ignored — it's now the default).
"""

from __future__ import annotations

import argparse
import sys
import threading
import time
import webbrowser


def _open_browser_when_ready(url: str, *, wait_seconds: float = 1.0) -> None:
    """Open a browser tab after a short delay so uvicorn is listening.

    Run in a background daemon thread so we don't block the server. The
    delay isn't a guarantee (uvicorn could be slower on a cold start),
    but it's good enough for the common case — a missed open just means
    the user's browser shows a connection-refused once and the second
    auto-retry succeeds. Better than blocking startup on a health check.
    """
    def _open():
        time.sleep(wait_seconds)
        try:
            webbrowser.open(url)
        except Exception:
            # Headless boxes, no DISPLAY, etc. — server still works,
            # user just doesn't get an auto-tab.
            pass

    threading.Thread(target=_open, daemon=True).start()


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="mle-beast",
        description="MLE-Beast — LLM-driven ML engineering agent",
    )
    parser.add_argument(
        "--no-web", action="store_true",
        help="Skip the web dashboard; drop into the CLI REPL instead",
    )
    parser.add_argument(
        "--no-browser", action="store_true",
        help="Start the web server but don't open a browser tab",
    )
    parser.add_argument(
        "--web", action="store_true",
        help="(deprecated, no-op) The web dashboard is now the default",
    )
    parser.add_argument(
        "--host", default="127.0.0.1",
        help="Web server host (default: 127.0.0.1)",
    )
    parser.add_argument(
        "--port", type=int, default=8000,
        help="Web server port (default: 8000)",
    )
    parser.add_argument(
        "--ssl-cert", default=None,
        help="Path to SSL certificate file (enables HTTPS)",
    )
    parser.add_argument(
        "--ssl-key", default=None,
        help="Path to SSL private key file",
    )
    args = parser.parse_args()

    if args.no_web:
        from mle_beast.repl import run_repl
        run_repl()
        return

    try:
        from mle_beast.web.server import start_web
    except ImportError:
        print(
            "Error: web dependencies not installed.\n"
            "Install with: pip install 'mle-beast[web]'\n"
            "Or run without the dashboard: mle-beast --no-web",
            file=sys.stderr,
        )
        sys.exit(1)

    scheme = "https" if args.ssl_cert else "http"
    url = f"{scheme}://{args.host}:{args.port}"

    if not args.no_browser:
        _open_browser_when_ready(url)

    try:
        start_web(
            host=args.host,
            port=args.port,
            ssl_certfile=args.ssl_cert,
            ssl_keyfile=args.ssl_key,
        )
    except (ModuleNotFoundError, ImportError):
        print(
            "Error: web dependencies not installed.\n"
            "Install with: pip install 'mle-beast[web]'\n"
            "Or run without the dashboard: mle-beast --no-web",
            file=sys.stderr,
        )
        sys.exit(1)


if __name__ == "__main__":
    main()
