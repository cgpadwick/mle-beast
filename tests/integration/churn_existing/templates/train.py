# Copyright 2026 Chris Padwick
# SPDX-License-Identifier: Apache-2.0

"""Training script for churn prediction model.

Splits train.csv 80/20 (deterministic seed 42) into train and validation
sets for internal early-stopping. The true held-out evaluation is done
by evaluate.py against data/test.csv. Saves best-by-val checkpoint to
checkpoints/best_model.pt.
"""

import argparse
import os

import pandas as pd
import torch
import torch.nn as nn
from torch.utils.data import DataLoader, TensorDataset

from model import create_model


def load_split(data_path: str, seed: int = 42):
    """Load train.csv and split 80/20 into (train, val). Deterministic."""
    train_csv = os.path.join(data_path, "train.csv")
    df = pd.read_csv(train_csv)
    features = df.drop(columns=["churned"]).select_dtypes(include=["number"])
    X = torch.tensor(features.values, dtype=torch.float32)
    y = torch.tensor(df["churned"].values, dtype=torch.float32)

    n = len(X)
    n_val = max(1, n // 5)
    rng = torch.Generator().manual_seed(seed)
    perm = torch.randperm(n, generator=rng)
    val_idx = perm[:n_val]
    train_idx = perm[n_val:]

    return (X[train_idx], y[train_idx]), (X[val_idx], y[val_idx])


def _accuracy(model, X, y):
    model.eval()
    with torch.no_grad():
        preds = model(X)
        return ((preds > 0.5).float() == y).float().mean().item()


def train(args):
    device = torch.device(args.device)
    (X_tr, y_tr), (X_val, y_val) = load_split(args.data_path)
    X_tr, y_tr = X_tr.to(device), y_tr.to(device)
    X_val, y_val = X_val.to(device), y_val.to(device)

    model = create_model(input_dim=X_tr.shape[1]).to(device)
    optimizer = torch.optim.Adam(model.parameters(), lr=0.01)
    criterion = nn.BCELoss()

    dataset = TensorDataset(X_tr, y_tr)
    loader = DataLoader(dataset, batch_size=32, shuffle=True)

    best_val_acc = -1.0
    patience_counter = 0
    os.makedirs("checkpoints", exist_ok=True)

    for epoch in range(1, args.epochs + 1):
        model.train()
        total_loss = 0.0
        seen = 0
        for batch_x, batch_y in loader:
            optimizer.zero_grad()
            preds = model(batch_x)
            loss = criterion(preds, batch_y)
            loss.backward()
            optimizer.step()
            total_loss += loss.item() * len(batch_x)
            seen += len(batch_x)
        avg_loss = total_loss / max(1, seen)
        val_acc = _accuracy(model, X_val, y_val)
        train_acc = _accuracy(model, X_tr, y_tr)
        print(
            f"Epoch {epoch}/{args.epochs} — loss: {avg_loss:.4f}, "
            f"train_acc: {train_acc:.4f}, val_acc: {val_acc:.4f}"
        )

        if val_acc > best_val_acc:
            best_val_acc = val_acc
            patience_counter = 0
            torch.save(model.state_dict(), "checkpoints/best_model.pt")
        else:
            patience_counter += 1
            if patience_counter >= 5:
                print("Early stopping.")
                break

        if args.smoke:
            break

    print(
        f"Training complete. Best val_acc: {best_val_acc:.4f}, "
        f"checkpoint: checkpoints/best_model.pt"
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(allow_abbrev=False)
    parser.add_argument("--device", default="cuda" if torch.cuda.is_available() else "cpu")
    parser.add_argument("--epochs", type=int, default=50)
    parser.add_argument("--data-path", default="data")
    parser.add_argument("--smoke", action="store_true")
    train(parser.parse_args())
