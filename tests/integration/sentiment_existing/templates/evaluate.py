# Copyright 2026 Chris Padwick
# SPDX-License-Identifier: Apache-2.0

"""Evaluation script: load checkpoint, score on the held-out test set.

Reads data/test/{positive,negative}.jsonl, runs inference, computes
accuracy. Writes eval_results.json AND prints a clean
"Test accuracy: X.XXXX" line.
"""

import argparse
import json
import os

import torch

from model import create_model
from train import texts_to_bow


def load_jsonl(path: str):
    items = []
    with open(path) as f:
        for line in f:
            items.append(json.loads(line))
    return items


def evaluate(args):
    device = torch.device(args.device)

    pos = load_jsonl(os.path.join(args.data_path, "test", "positive.jsonl"))
    neg = load_jsonl(os.path.join(args.data_path, "test", "negative.jsonl"))

    texts = [item["text"] for item in pos + neg]
    labels = [1.0] * len(pos) + [0.0] * len(neg)
    y = torch.tensor(labels, dtype=torch.float32).to(device)

    checkpoint = torch.load(args.checkpoint, map_location=device)
    vocab = checkpoint["vocab"]
    X = texts_to_bow(texts, vocab).to(device)

    model = create_model(vocab_size=len(vocab)).to(device)
    model.load_state_dict(checkpoint["model"])
    model.eval()

    with torch.no_grad():
        preds = model(X)
        predicted = (preds > 0.5).float()
        accuracy = (predicted == y).float().mean().item()

    print(f"Test accuracy: {accuracy:.4f}")
    print(f"Evaluated on {len(y)} held-out test samples.")

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
