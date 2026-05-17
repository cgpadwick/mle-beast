# Copyright 2026 Chris Padwick
# SPDX-License-Identifier: Apache-2.0

"""Training script for shapes classification model."""

import argparse
import os

import torch
import torch.nn as nn
from torch.utils.data import DataLoader
from torchvision import datasets, transforms

from model import create_model


def get_transforms():
    """Return training transforms."""
    return transforms.Compose([
        transforms.Resize((64, 64)),
        transforms.ToTensor(),
        transforms.Normalize(mean=[0.5, 0.5, 0.5], std=[0.5, 0.5, 0.5]),
    ])


def train(args):
    device = torch.device(args.device)
    transform = get_transforms()

    train_dir = os.path.join(args.data_path, "train")
    train_dataset = datasets.ImageFolder(train_dir, transform=transform)
    loader = DataLoader(train_dataset, batch_size=16, shuffle=True)

    model = create_model(num_classes=3).to(device)
    optimizer = torch.optim.Adam(model.parameters(), lr=0.001)
    criterion = nn.CrossEntropyLoss()

    best_loss = float("inf")
    patience_counter = 0

    for epoch in range(1, args.epochs + 1):
        model.train()
        total_loss = 0.0
        correct = 0
        total = 0

        for images, labels in loader:
            images, labels = images.to(device), labels.to(device)
            optimizer.zero_grad()
            outputs = model(images)
            loss = criterion(outputs, labels)
            loss.backward()
            optimizer.step()

            total_loss += loss.item() * len(images)
            correct += (outputs.argmax(1) == labels).sum().item()
            total += len(labels)

        avg_loss = total_loss / total
        accuracy = correct / total
        print(f"Epoch {epoch}/{args.epochs} — loss: {avg_loss:.4f}, accuracy: {accuracy:.4f}")

        if avg_loss < best_loss:
            best_loss = avg_loss
            patience_counter = 0
            os.makedirs("checkpoints", exist_ok=True)
            torch.save(model.state_dict(), "checkpoints/best_model.pt")
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
