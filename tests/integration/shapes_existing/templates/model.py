# Copyright 2026 Chris Padwick
# SPDX-License-Identifier: Apache-2.0

"""Shapes classification model — baseline CNN."""

import torch
import torch.nn as nn


class ShapesModel(nn.Module):
    """Simple CNN for 64x64 RGB image classification (3 classes)."""

    def __init__(self, num_classes: int = 3):
        super().__init__()
        self.features = nn.Sequential(
            nn.Conv2d(3, 16, kernel_size=3, padding=1),
            nn.ReLU(),
            nn.MaxPool2d(2),
            nn.Conv2d(16, 32, kernel_size=3, padding=1),
            nn.ReLU(),
            nn.MaxPool2d(2),
        )
        # After two 2x poolings: 64 -> 32 -> 16, so 32 * 16 * 16
        self.classifier = nn.Sequential(
            nn.Linear(32 * 16 * 16, 64),
            nn.ReLU(),
            nn.Linear(64, num_classes),
        )

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        x = self.features(x)
        x = x.view(x.size(0), -1)
        return self.classifier(x)


def create_model(num_classes: int = 3) -> ShapesModel:
    """Factory function returning a ShapesModel instance."""
    return ShapesModel(num_classes=num_classes)
