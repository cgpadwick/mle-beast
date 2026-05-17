# Copyright 2026 Chris Padwick
# SPDX-License-Identifier: Apache-2.0

"""Basic tests for the shapes classification model."""

import torch
from model import create_model


def test_model_forward():
    """Test that the model produces output of the correct shape."""
    model = create_model(num_classes=3)
    x = torch.randn(4, 3, 64, 64)
    out = model(x)
    assert out.shape == (4, 3), f"Expected shape (4, 3), got {out.shape}"


def test_model_single_sample():
    """Test model with a single sample."""
    model = create_model(num_classes=3)
    x = torch.randn(1, 3, 64, 64)
    out = model(x)
    assert out.shape == (1, 3)
