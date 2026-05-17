# Copyright 2026 Chris Padwick
# SPDX-License-Identifier: Apache-2.0

"""Sentiment classification model — baseline bag-of-words MLP."""

import torch
import torch.nn as nn


class SentimentModel(nn.Module):
    """Bag-of-words MLP for sentiment classification."""

    def __init__(self, vocab_size: int = 5000, hidden_dim: int = 64):
        super().__init__()
        self.net = nn.Sequential(
            nn.Linear(vocab_size, hidden_dim),
            nn.ReLU(),
            nn.Linear(hidden_dim, 1),
            nn.Sigmoid(),
        )

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        return self.net(x).squeeze(-1)


def create_model(vocab_size: int = 5000) -> SentimentModel:
    """Factory function returning a SentimentModel instance."""
    return SentimentModel(vocab_size=vocab_size)
