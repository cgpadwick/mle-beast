# Contributing to mle-beast

Thanks for your interest! Contributions of all sizes are welcome — bug reports, fixes, features, docs, tests, ideas.

## Quick start

```bash
git clone https://github.com/cgpadwick/mle-beast.git
cd mle-beast
python -m venv .venv && source .venv/bin/activate
pip install -e ".[web]"
pytest tests/ -k "not integration"   # unit tests, no API key required
```

## Developer Certificate of Origin (DCO)

We use the [DCO](https://developercertificate.org/) instead of a CLA. It's a one-line attestation that you wrote the code and have the right to contribute it under this project's license.

To comply: **add `-s` to every `git commit`.**

```bash
git commit -s -m "Add feature X"
```

That appends a `Signed-off-by:` line to your commit message using your `git config user.name` and `user.email`. The DCO check on PRs verifies every commit has this line.

If you forget, you can amend or rebase:
```bash
git commit --amend -s --no-edit              # last commit
git rebase HEAD~3 --signoff                  # last 3 commits
```

## Pull request guidelines

- **One logical change per PR.** Easier to review, easier to revert.
- **Write a clear description.** What does it do, why, how did you verify?
- **Add or update tests.** Bug fixes should include a regression test.
- **Run the unit suite locally** before opening the PR: `pytest tests/ -k "not integration"`.
- **Integration tests** require an LLM provider env var and cost real money — they run in CI on merge, not on every PR.
- **Be conservative about new dependencies.** If you add one, justify it in the PR description.

## Code style

- Python 3.10+. Type hints encouraged but not enforced.
- Prefer clarity over cleverness. Critics-don't-use-tools, structured-output-is-non-negotiable, and similar invariants are documented in the codebase — preserve them.
- Run `ruff check src/ tests/` if you've installed dev deps (CI doesn't fail on style yet but we'd like it to).

## Reporting bugs

Use [GitHub Issues](https://github.com/cgpadwick/mle-beast/issues) with the **Bug report** template. Helpful information:

- mle-beast version (`pip show mle-beast`)
- Python version
- LLM provider + model
- Full command + error output
- Workspace directory contents (especially `train.log`, `research_log.md`, `eval_results.json` if they exist)

## Proposing features

Open an issue with the **Feature request** template *before* implementing — this avoids us redesigning your work in review. For larger changes, a brief design sketch in the issue saves everyone time.

## Code of Conduct

This project follows the [Contributor Covenant](CODE_OF_CONDUCT.md). Be kind, be patient, assume good faith.

## License

By contributing, you agree your contributions are licensed under the [Apache License 2.0](LICENSE), and you certify the [DCO](https://developercertificate.org/) by signing off on your commits.
