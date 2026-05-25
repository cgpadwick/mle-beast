# Copyright 2026 Chris Padwick
# SPDX-License-Identifier: Apache-2.0

"""MLE-Beast: PocketFlow-based ML pipeline with actor/critic loops."""

from importlib.metadata import PackageNotFoundError
from importlib.metadata import version as _pkg_version

try:
    # Single source of truth: the installed package's version, which comes
    # from pyproject.toml (bumped by release-please on each release).
    __version__ = _pkg_version("mle-beast")
except PackageNotFoundError:  # not installed (e.g. running from a raw checkout)
    __version__ = "0.0.0+unknown"

__all__ = ["__version__"]
