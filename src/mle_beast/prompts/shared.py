# Copyright 2026 Chris Padwick
# SPDX-License-Identifier: Apache-2.0

"""Prompt fragments shared across multiple actor prompts.

Centralized here so wording stays consistent and one edit propagates
everywhere. Import the constant and interpolate it into the host prompt
with an f-string — keeping it a plain str (not a callable / template)
keeps the host prompt readable at a glance.
"""

INSTALLING_ADDITIONAL_PACKAGES = """\
INSTALLING ADDITIONAL PACKAGES:
The workspace's venv has the ml-frameworks BASE stack: torch + torchvision
+ torchaudio + numpy + scipy + pandas + scikit-learn + matplotlib + seaborn
+ pytest. If you need a package NOT in base (e.g. transformers, ultralytics,
pytorch-lightning), prefer (via run_shell_command, which already cd's to
the workspace root):
    poetry install --no-root -E <group>
over a raw `pip install <pkg>`. The available groups are defined in
pyproject.toml at the workspace root under [tool.poetry.extras] —
common ones: nlp (transformers, datasets, peft, accelerate), training
(pytorch-lightning, torchmetrics, tensorboard, optuna), vision
(opencv-contrib-python, scikit-image, albumentations), vision-extra
(ultralytics, timm), viz (plotly), data (dask, polars, pyarrow), gnn
(torch-geometric). Poetry uses the pinned lock file ml-frameworks has
already validated, so groups install cleanly and don't conflict. Fall
back to `pip install` ONLY for packages not covered by any group.\
"""
