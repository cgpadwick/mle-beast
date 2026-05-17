# Copyright 2026 Chris Padwick
# SPDX-License-Identifier: Apache-2.0

"""Training script for sentiment classification model."""

import argparse
import json
import os
from collections import Counter

import torch
import torch.nn as nn
from torch.utils.data import DataLoader, TensorDataset

from model import create_model


def load_jsonl(path: str):
    """Load JSONL file returning list of dicts."""
    items = []
    with open(path) as f:
        for line in f:
            items.append(json.loads(line))
    return items


def build_vocab(texts, max_vocab: int = 5000):
    """Build vocabulary from texts."""
    counter = Counter()
    for text in texts:
        counter.update(text.lower().split())
    vocab = {word: idx for idx, (word, _) in enumerate(counter.most_common(max_vocab))}
    return vocab


def texts_to_bow(texts, vocab):
    """Convert texts to bag-of-words tensor."""
    bow = torch.zeros(len(texts), len(vocab))
    for i, text in enumerate(texts):
        for word in text.lower().split():
            if word in vocab:
                bow[i, vocab[word]] += 1
    return bow


def load_data(data_path: str, max_vocab: int = 5000):
    """Load training data and build features."""
    pos = load_jsonl(os.path.join(data_path, "train", "positive.jsonl"))
    neg = load_jsonl(os.path.join(data_path, "train", "negative.jsonl"))

    texts = [item["text"] for item in pos + neg]
    labels = [1.0] * len(pos) + [0.0] * len(neg)

    vocab = build_vocab(texts, max_vocab)
    X = texts_to_bow(texts, vocab)
    y = torch.tensor(labels, dtype=torch.float32)
    return X, y, vocab


def train(args):
    device = torch.device(args.device)
    X, y, vocab = load_data(args.data_path)
    X, y = X.to(device), y.to(device)

    model = create_model(vocab_size=len(vocab)).to(device)
    optimizer = torch.optim.Adam(model.parameters(), lr=0.001)
    criterion = nn.BCELoss()

    dataset = TensorDataset(X, y)
    loader = DataLoader(dataset, batch_size=32, shuffle=True)

    best_loss = float("inf")
    patience_counter = 0

    for epoch in range(1, args.epochs + 1):
        model.train()
        total_loss = 0.0
        correct = 0
        total = 0

        for batch_x, batch_y in loader:
            optimizer.zero_grad()
            preds = model(batch_x)
            loss = criterion(preds, batch_y)
            loss.backward()
            optimizer.step()

            total_loss += loss.item() * len(batch_x)
            correct += ((preds > 0.5).float() == batch_y).sum().item()
            total += len(batch_y)

        avg_loss = total_loss / total
        accuracy = correct / total
        print(f"Epoch {epoch}/{args.epochs} — loss: {avg_loss:.4f}, accuracy: {accuracy:.4f}")

        if avg_loss < best_loss:
            best_loss = avg_loss
            patience_counter = 0
            os.makedirs("checkpoints", exist_ok=True)
            torch.save({"model": model.state_dict(), "vocab": vocab},
                       "checkpoints/best_model.pt")
        else:
            patience_counter += 1
            if patience_counter >= 5:
                print("Early stopping.")
                break

        if args.smoke:
            break


if __name__ == "__main__":
    parser = argparse.ArgumentParser(allow_abbrev=False)
    parser.add_argument("--device", default="cpu")
    parser.add_argument("--epochs", type=int, default=50)
    parser.add_argument("--data-path", default="data")
    parser.add_argument("--smoke", action="store_true")
    train(parser.parse_args())
