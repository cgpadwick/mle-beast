# Copyright 2026 Chris Padwick
# SPDX-License-Identifier: Apache-2.0

"""Evaluation script: load checkpoint, score on the held-out test set.

Reads data/test/{circle,square,triangle}/*.png, runs inference, computes
accuracy. Writes eval_results.json AND prints a clean
"Test accuracy: X.XXXX" line.
"""

import argparse
import json
import os

import torch
from torch.utils.data import DataLoader
from torchvision import datasets, transforms

from model import create_model


def evaluate(args):
    device = torch.device(args.device)

    transform = transforms.Compose([
        transforms.Resize((64, 64)),
        transforms.ToTensor(),
        transforms.Normalize(mean=[0.5, 0.5, 0.5], std=[0.5, 0.5, 0.5]),
    ])

    test_dir = os.path.join(args.data_path, "test")
    test_dataset = datasets.ImageFolder(test_dir, transform=transform)
    loader = DataLoader(test_dataset, batch_size=16, shuffle=False)

    model = create_model(num_classes=3).to(device)
    state = torch.load(args.checkpoint, map_location=device)
    model.load_state_dict(state)
    model.eval()

    correct = 0
    total = 0
    with torch.no_grad():
        for images, labels in loader:
            images, labels = images.to(device), labels.to(device)
            outputs = model(images)
            correct += (outputs.argmax(1) == labels).sum().item()
            total += len(labels)

    accuracy = correct / total if total > 0 else 0.0
    print(f"Test accuracy: {accuracy:.4f}")
    print(f"Evaluated on {total} held-out test images.")

    result = {
        "metric_name": "accuracy",
        "value": accuracy,
        "split": "test",
        "n_samples": int(total),
    }
    with open("eval_results.json", "w") as f:
        json.dump(result, f, indent=2)
    print(f"Wrote eval_results.json: {result}")
    return accuracy


if __name__ == "__main__":
    parser = argparse.ArgumentParser(allow_abbrev=False)
    parser.add_argument("--device", default="cuda" if torch.cuda.is_available() else "cpu")
    parser.add_argument("--data-path", default="data")
    parser.add_argument("--checkpoint", default="checkpoints/best_model.pt")
    evaluate(parser.parse_args())
