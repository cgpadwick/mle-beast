# Changelog

All notable changes to this project will be documented in this file.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.1.0] — Initial public release

### Added
- LLM-driven hill-climbing ML pipeline (PocketFlow actor/critic loops)
- Greenfield mode: write `model.py` / `train.py` / `predict.py` from a task description
- Brownfield mode: improve an existing codebase via the same hill-climb loop
- React web dashboard with live run state, hill-climb experiment view, and pipeline DAG visualization
- SQLite-backed run persistence and event log
- Auto-detection of LLM provider (Local / OpenRouter / OpenAI)
- Integration test suite covering tabular, NLP, and image classification tasks

[Unreleased]: https://github.com/cgpadwick/mle-beast/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/cgpadwick/mle-beast/releases/tag/v0.1.0
