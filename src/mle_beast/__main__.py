# Copyright 2026 Chris Padwick
# SPDX-License-Identifier: Apache-2.0

"""Entry point for `python -m mle_beast`.

`mle-beast`      — starts the interactive CLI REPL
`mle-beast --web` — starts the web dashboard
"""

from __future__ import annotations

import argparse
import sys


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="mle-beast",
        description="MLE-Beast — ML Engineering Pipeline",
    )
    parser.add_argument(
        "--web", action="store_true",
        help="Start the web dashboard instead of the CLI REPL",
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

    if args.web:
        try:
            from mle_beast.web.server import start_web
        except ImportError:
            print(
                "Error: web dependencies not installed.\n"
                "Install with: pip install 'mle-beast[web]'",
                file=sys.stderr,
            )
            sys.exit(1)
        start_web(
            host=args.host,
            port=args.port,
            ssl_certfile=args.ssl_cert,
            ssl_keyfile=args.ssl_key,
        )
    else:
        from mle_beast.repl import run_repl
        run_repl()


if __name__ == "__main__":
    main()
