# Copyright 2026 Chris Padwick
# SPDX-License-Identifier: Apache-2.0

"""Basic tests for the churn prediction model."""

import torch
from model import create_model


def test_model_forward():
    """Test that the model produces output of the correct shape."""
    model = create_model(input_dim=3)
    x = torch.randn(4, 3)
    out = model(x)
    assert out.shape == (4,), f"Expected shape (4,), got {out.shape}"
    assert (out >= 0).all() and (out <= 1).all(), "Output should be in [0, 1]"


def test_model_single_sample():
    """Test model with a single sample."""
    model = create_model(input_dim=3)
    x = torch.randn(1, 3)
    out = model(x)
    assert out.shape == (1,)
