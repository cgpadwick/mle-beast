# Changelog

All notable changes to this project will be documented in this file.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [1.1.0](https://github.com/cgpadwick/mle-beast/compare/v1.0.0...v1.1.0) (2026-05-26)


### Bug Fixes

* dataset_path allowlist should not be gated on metric_name ([7cc1eca](https://github.com/cgpadwick/mle-beast/commit/7cc1eca8978fe345c1bf11c1f6a61768e0aa8704))
* validator must check for pip, not just pytest ([8918c6e](https://github.com/cgpadwick/mle-beast/commit/8918c6ee937ef241aecd9b1dad408e5d0aa6cd54))


### Performance Improvements

* fix run-detail freeze on long runs (console windowing + coalesced refetch) ([3626d76](https://github.com/cgpadwick/mle-beast/commit/3626d7637c2f5bf804076fd188beee4d7fe539d4))
* window the console + coalesce summary refetch (run-detail freeze) ([1e7b803](https://github.com/cgpadwick/mle-beast/commit/1e7b8033a245b43d8257b968fc50061e138fefd4))


### Documentation

* add dashboard hero screenshot to README ([9531f4a](https://github.com/cgpadwick/mle-beast/commit/9531f4a2a3ffd43d904434ad4bd359b8c6c72737))
* add dashboard hero screenshot to README ([f741e53](https://github.com/cgpadwick/mle-beast/commit/f741e5365a3440d07284d5365c53aab8fed8c9af))
* add demo videos to README ([283c12a](https://github.com/cgpadwick/mle-beast/commit/283c12a3ad177e86dc508db897b39810aa5c04ac))
* add demo videos to README ([5c8dc39](https://github.com/cgpadwick/mle-beast/commit/5c8dc3978503d6792ac0e4777f83401ff98a6a3e))

## [1.0.0](https://github.com/cgpadwick/mle-beast/compare/v0.1.0...v1.0.0) (2026-05-26)

🎉 **First stable release.** Everything merged after the 0.1.0 initial public release, hand-curated into the buckets below.

### Features

* runs list: per-run delete, pagination, and a readability pass ([#32](https://github.com/cgpadwick/mle-beast/pull/32))
* in-app bug reports — pre-filled GitHub issues + structured issue form ([#29](https://github.com/cgpadwick/mle-beast/pull/29))
* show the version in the UI + automate releases with release-please ([#28](https://github.com/cgpadwick/mle-beast/pull/28))
* dashboard: theme-aware runs-list hero (no black banner in light mode) ([#27](https://github.com/cgpadwick/mle-beast/pull/27))
* dashboard: surface critic feedback + distinguish retry from failure ([#26](https://github.com/cgpadwick/mle-beast/pull/26))
* new run: validate the workspace path + surface the mounted root ([#25](https://github.com/cgpadwick/mle-beast/pull/25))
* setup wizard + Docker wheel-layer split + dashboard error surfacing ([#23](https://github.com/cgpadwick/mle-beast/pull/23))
* Docker bundle — `docker compose up` as the primary install path ([#22](https://github.com/cgpadwick/mle-beast/pull/22))
* dashboard: light-mode contrast pass + new logo ([#18](https://github.com/cgpadwick/mle-beast/pull/18))
* safety guardrails — block sudo + path escapes from agent tool calls ([#17](https://github.com/cgpadwick/mle-beast/pull/17))
* `mle-beast init` for prereq diagnostics + project scaffolding ([#16](https://github.com/cgpadwick/mle-beast/pull/16))

### Bug Fixes

* prime poetry's artifact cache in the multi-stage Docker build (#23 regression) ([#24](https://github.com/cgpadwick/mle-beast/pull/24))
* `init --check` poetry prompt + pipeline git-identity ([#20](https://github.com/cgpadwick/mle-beast/pull/20))
* dataset_path allowlist should not be gated on metric_name ([7cc1eca](https://github.com/cgpadwick/mle-beast/commit/7cc1eca8978fe345c1bf11c1f6a61768e0aa8704))
* validator must check for pip, not just pytest ([8918c6e](https://github.com/cgpadwick/mle-beast/commit/8918c6ee937ef241aecd9b1dad408e5d0aa6cd54))

### Performance Improvements

* fix run-detail freeze on long runs — console windowing + coalesced refetch ([#31](https://github.com/cgpadwick/mle-beast/pull/31))

### Documentation

* add dashboard hero screenshot to README ([#35](https://github.com/cgpadwick/mle-beast/pull/35))
* add demo videos to README ([#34](https://github.com/cgpadwick/mle-beast/pull/34))

### Continuous Integration

* lint PR titles against Conventional Commits ([#33](https://github.com/cgpadwick/mle-beast/pull/33))

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

[Unreleased]: https://github.com/cgpadwick/mle-beast/compare/v1.0.0...HEAD
[1.0.0]: https://github.com/cgpadwick/mle-beast/releases/tag/v1.0.0
[0.1.0]: https://github.com/cgpadwick/mle-beast/releases/tag/v0.1.0
