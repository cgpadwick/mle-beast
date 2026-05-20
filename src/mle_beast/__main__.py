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
import os
import sys
import threading
import time
import webbrowser
from pathlib import Path


def _load_dotenv_early() -> None:
    """Load `<cwd>/.env` BEFORE any mle-beast module that reads env vars
    (notably mle_beast.llm, which detects the provider at import time).

    Uses python-dotenv if installed; falls back to a tiny inline parser
    otherwise so this never becomes a hard dependency for users who set
    everything in their shell env. `override=False` semantics: shell-
    exported variables always win, .env only fills in the gaps.
    """
    env_path = Path.cwd() / ".env"
    if not env_path.exists():
        return
    try:
        from dotenv import load_dotenv  # type: ignore
        load_dotenv(env_path, override=False)
        return
    except ImportError:
        pass
    # Stdlib fallback. Bare KEY=VALUE only; strips outer quotes. Skips
    # comments and blank lines. Not as robust as python-dotenv (no
    # interpolation, no export prefix) but good enough that the user
    # gets `.env` support even on an install that didn't pick up the
    # python-dotenv dep yet.
    for line in env_path.read_text(encoding="utf-8", errors="replace").splitlines():
        s = line.strip()
        if not s or s.startswith("#") or "=" not in s:
            continue
        key, _, value = s.partition("=")
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


_load_dotenv_early()


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
    # Subcommand dispatch BEFORE the main argparse setup. Keeps backward
    # compatibility (no args → dashboard) while letting us grow new
    # subcommands without disturbing the existing flag set.
    if len(sys.argv) > 1 and sys.argv[1] == "init":
        from mle_beast.cli.init import run_init
        sys.exit(run_init(sys.argv[2:]))

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

    # SSL: both cert and key, or neither. uvicorn would fail with a less
    # obvious error if only one is given.
    if bool(args.ssl_cert) ^ bool(args.ssl_key):
        print(
            "Error: --ssl-cert and --ssl-key must be provided together "
            "(or neither, for HTTP).",
            file=sys.stderr,
        )
        sys.exit(2)

    # Build the URL the browser should open. When the user binds to all
    # interfaces (0.0.0.0 / ::) we can't actually open a local browser
    # at that "host" — substitute the loopback equivalent. The server
    # still binds to whatever the user asked for.
    browser_host = args.host
    if args.host in ("0.0.0.0", ""):
        browser_host = "127.0.0.1"
    elif args.host in ("::", "::0"):
        browser_host = "[::1]"
    scheme = "https" if args.ssl_cert else "http"
    url = f"{scheme}://{browser_host}:{args.port}"

    if not args.no_browser:
        _open_browser_when_ready(url)

    try:
        from mle_beast.web.server import start_web
        start_web(
            host=args.host,
            port=args.port,
            ssl_certfile=args.ssl_cert,
            ssl_keyfile=args.ssl_key,
        )
    except (ModuleNotFoundError, ImportError) as e:
        # FastAPI/uvicorn are deferred imports inside server.py, so any
        # missing extras don't surface until start_web() actually runs.
        # Catch here so the [web]-extras install message is what users
        # see instead of a bare traceback.
        print(
            "Error: web dependencies not installed.\n"
            "Install with: pip install 'mle-beast[web]'\n"
            "Or run without the dashboard: mle-beast --no-web\n"
            f"(import failed: {e})",
            file=sys.stderr,
        )
        sys.exit(1)


if __name__ == "__main__":
    main()
