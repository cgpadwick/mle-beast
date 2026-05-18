# Copyright 2026 Chris Padwick
# SPDX-License-Identifier: Apache-2.0

"""Shared fixtures for mle_beast tests."""


import pytest

from mle_beast.workspace import WorkspaceRegistry


@pytest.fixture(autouse=True)
def _clear_workspace_registry():
    """Reset the workspace registry before/after each test."""
    WorkspaceRegistry.clear_workspace()
    yield
    WorkspaceRegistry.clear_workspace()


@pytest.fixture
def workspace(tmp_path):
    """Create a temporary workspace and register it."""
    ws = tmp_path / "workspace"
    ws.mkdir()
    (ws / "models").mkdir()
    (ws / "scripts").mkdir()
    (ws / "tests").mkdir()
    (ws / "logs").mkdir()
    (ws / "data").mkdir()
    WorkspaceRegistry.set_workspace(ws)
    return ws
