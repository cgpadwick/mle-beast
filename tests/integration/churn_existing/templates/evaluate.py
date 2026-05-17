# Copyright 2026 Chris Padwick
# SPDX-License-Identifier: Apache-2.0

"""Evaluation script: load checkpoint, score on the held-out test set.

Reads data/test.csv (a true holdout — never seen during training) and
applies the same featurization as train.py so the saved checkpoint can
score it. Writes structured results to eval_results.json AND prints a
clean "Test accuracy: X.XXXX" line.
"""

import argparse
import json
import os

import pandas as pd
import torch

from model import create_model


def load_test(data_path: str):
    """Load test.csv with the same feature shape train.py used."""
    test_csv = os.path.join(data_path, "test.csv")
    df = pd.read_csv(test_csv)
    features = df.drop(columns=["churned"]).select_dtypes(include=["number"])
    X = torch.tensor(features.values, dtype=torch.float32)
    y = torch.tensor(df["churned"].values, dtype=torch.float32)
    return X, y


def evaluate(args):
    device = torch.device(args.device)
    X, y = load_test(args.data_path)
    X, y = X.to(device), y.to(device)

    model = create_model(input_dim=X.shape[1]).to(device)
    state = torch.load(args.checkpoint, map_location=device)
    model.load_state_dict(state)
    model.eval()

    with torch.no_grad():
        preds = model(X)
        accuracy = ((preds > 0.5).float() == y).float().mean().item()

    print(f"Test accuracy: {accuracy:.4f}")
    print(f"Evaluated on {len(y)} held-out samples (split=test).")

    result = {
        "metric_name": "accuracy",
        "value": accuracy,
        "split": "test",
        "n_samples": int(len(y)),
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
