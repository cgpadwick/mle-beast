# Copyright 2026 Chris Padwick
# SPDX-License-Identifier: Apache-2.0

"""Churn prediction model — baseline MLP."""

import torch
import torch.nn as nn


class ChurnModel(nn.Module):
    """Simple MLP for churn prediction."""

    def __init__(self, input_dim: int = 3, hidden_dim: int = 16):
        super().__init__()
        self.net = nn.Sequential(
            nn.Linear(input_dim, hidden_dim),
            nn.ReLU(),
            nn.Linear(hidden_dim, 1),
            nn.Sigmoid(),
        )

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        return self.net(x).squeeze(-1)


def create_model(input_dim: int = 3) -> ChurnModel:
    """Factory function returning a ChurnModel instance."""
    return ChurnModel(input_dim=input_dim)
