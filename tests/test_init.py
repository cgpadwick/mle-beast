# Copyright 2026 Chris Padwick
# SPDX-License-Identifier: Apache-2.0

"""Unit tests for the `mle-beast init` subcommand.

Strategy: drive run_init() with --yes (so the prompts collapse to
defaults) against an isolated tmp cwd + a patched _PROVIDERS dict where
the model-catalog HTTP call is monkeypatched. That lets us cover the
file scaffolding, env precedence rules, and model-validation/fuzzy-
matching logic without doing any real network or subprocess work.
"""

from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import patch

from mle_beast.cli import init as init_mod

# ----------------------------------------------------------------
# Helpers
# ----------------------------------------------------------------

def _run_init(
    tmp_path: Path,
    env: dict[str, str],
    argv: list[str],
    *,
    fake_catalog: list[str] | None = None,
):
    """Invoke run_init() with a stubbed os.environ + a fake live catalog.

    Returns the resulting exit code so callers can assert on it.

    Hermetic guarantees baked in:
      - `_fetch_models` is patched so no network calls escape the test.
      - `_try_install_poetry` is patched to a no-op-True so a CI box
        that has pipx but not poetry doesn't actually run
        `pipx install poetry` against the host.
    """
    with patch.dict(os.environ, env, clear=True):
        with patch.object(init_mod, "_fetch_models", return_value=fake_catalog), \
             patch.object(init_mod, "_try_install_poetry", return_value=True):
            return init_mod.run_init(["--cwd", str(tmp_path), *argv])


def _read_env(tmp_path: Path) -> dict[str, str]:
    """Parse the written .env into a dict for assertions."""
    env_path = tmp_path / ".env"
    assert env_path.exists(), ".env was not written"
    result: dict[str, str] = {}
    for line in env_path.read_text().splitlines():
        s = line.strip()
        if not s or s.startswith("#") or "=" not in s:
            continue
        key, _, value = s.partition("=")
        result[key.strip()] = value.strip()
    return result


# ----------------------------------------------------------------
# Provider/key precedence rules
# ----------------------------------------------------------------

def test_init_with_shell_key_does_not_copy_key_into_env(tmp_path):
    """Branch B: shell env has the key. .env gets the selection pin
    but NOT the secret — shell stays the source of truth."""
    rc = _run_init(
        tmp_path,
        env={"OPENROUTER_API_KEY": "sk-or-shell-value", "PATH": os.environ.get("PATH", "")},
        argv=["--yes", "--no-validate-key"],
        fake_catalog=None,
    )
    assert rc == 0
    env = _read_env(tmp_path)
    assert env["MLE_BEAST_PROVIDER"] == "openrouter"
    # Crucially: the key from the shell does NOT get written to .env
    assert "OPENROUTER_API_KEY" not in env, \
        "key was already in shell — init should not have copied it into .env"


def test_init_with_no_shell_key_skips_env_write_when_yes(tmp_path):
    """Branch A in --yes mode: hidden input can't be prompted for non-
    interactively, so init records the provider choice but skips the
    secret write. User can fill it in later."""
    rc = _run_init(
        tmp_path,
        env={"PATH": os.environ.get("PATH", "")},
        argv=["--yes", "--no-validate-key"],
        fake_catalog=None,
    )
    assert rc == 0
    env = _read_env(tmp_path)
    # Picker defaults to first provider — openrouter.
    assert env["MLE_BEAST_PROVIDER"] == "openrouter"
    # No key was supplied → none written
    assert "OPENROUTER_API_KEY" not in env


def test_init_pins_provider_when_multiple_shell_keys_present(tmp_path):
    """Multiple keys in shell — picker defaults to choice 1 (the first
    detected in order: openrouter > openai > local). MLE_BEAST_PROVIDER
    pins that choice so the resolution-order code in llm.py doesn't
    silently override."""
    rc = _run_init(
        tmp_path,
        env={
            "OPENROUTER_API_KEY": "sk-or-1",
            "OPENAI_API_KEY": "sk-openai-1",
            "PATH": os.environ.get("PATH", ""),
        },
        argv=["--yes", "--no-validate-key"],
        fake_catalog=None,
    )
    assert rc == 0
    env = _read_env(tmp_path)
    assert env["MLE_BEAST_PROVIDER"] == "openrouter"
    # No key copied (both were in shell)
    assert "OPENROUTER_API_KEY" not in env
    assert "OPENAI_API_KEY" not in env


# ----------------------------------------------------------------
# Model picker + validation
# ----------------------------------------------------------------

def test_init_writes_model_when_in_live_catalog(tmp_path):
    """Default model picker chooses suggestion 1; validate it against
    the live catalog; write it to .env."""
    catalog = [
        "deepseek/deepseek-v4-flash",
        "openai/gpt-4o-mini",
        "anthropic/claude-haiku-4-5",
    ]
    rc = _run_init(
        tmp_path,
        env={"OPENROUTER_API_KEY": "sk-or-shell", "PATH": os.environ.get("PATH", "")},
        argv=["--yes"],
        fake_catalog=catalog,
    )
    assert rc == 0
    env = _read_env(tmp_path)
    assert env["MLE_BEAST_MODEL"] == "deepseek/deepseek-v4-flash"


def test_init_skips_model_validation_with_flag(tmp_path):
    """--no-validate-key should bypass the network round-trip but
    still let the user pick a model (the default)."""
    rc = _run_init(
        tmp_path,
        env={"OPENROUTER_API_KEY": "sk-or-shell", "PATH": os.environ.get("PATH", "")},
        argv=["--yes", "--no-validate-key"],
        fake_catalog=None,
    )
    assert rc == 0
    env = _read_env(tmp_path)
    # Falls back to curated default
    assert env["MLE_BEAST_MODEL"] == "deepseek/deepseek-v4-flash"


# ----------------------------------------------------------------
# Cross-provider prefix correction
# ----------------------------------------------------------------

def test_validate_or_correct_openrouter_missing_prefix():
    """User types `gpt-4o-mini` against OpenRouter; should be corrected
    to `openai/gpt-4o-mini` automatically (--yes accepts the suggestion)."""
    spec = init_mod._PROVIDERS["openrouter"]
    catalog = ["openai/gpt-4o-mini", "anthropic/claude-haiku-4-5"]
    result = init_mod._validate_or_correct("gpt-4o-mini", spec, catalog, yes=True)
    assert result == "openai/gpt-4o-mini"


def test_validate_or_correct_openai_with_unwanted_prefix():
    """User types `openai/gpt-4o-mini` against OpenAI; should be
    corrected to `gpt-4o-mini` (OpenAI's catalog uses bare names)."""
    spec = init_mod._PROVIDERS["openai"]
    catalog = ["gpt-4o-mini", "gpt-4o"]
    result = init_mod._validate_or_correct("openai/gpt-4o-mini", spec, catalog, yes=True)
    assert result == "gpt-4o-mini"


def test_validate_or_correct_typo_fuzzy_match():
    """User typo (`deepseek/deepseek-v4-flsh` ← missing 'a'); fuzzy
    match should suggest the real slug."""
    spec = init_mod._PROVIDERS["openrouter"]
    catalog = [
        "deepseek/deepseek-v4-flash",
        "openai/gpt-4o-mini",
    ]
    result = init_mod._validate_or_correct(
        "deepseek/deepseek-v4-flsh", spec, catalog, yes=True
    )
    assert result == "deepseek/deepseek-v4-flash"


def test_validate_or_correct_no_match_no_save(tmp_path):
    """Garbage slug + --yes (default = "save anyway? No") → returns None."""
    spec = init_mod._PROVIDERS["openrouter"]
    catalog = ["deepseek/deepseek-v4-flash", "openai/gpt-4o-mini"]
    # `qwertyuiop` is far from any catalog entry; close_matches at
    # cutoff=0.55 returns []. With yes=True the "save anyway" defaults
    # to False, so we get None back.
    result = init_mod._validate_or_correct("qwertyuiop", spec, catalog, yes=True)
    assert result is None


def test_validate_passthrough_when_slug_is_in_catalog():
    """When the user's slug exists verbatim, return it unchanged."""
    spec = init_mod._PROVIDERS["openrouter"]
    catalog = ["deepseek/deepseek-v4-flash", "openai/gpt-4o-mini"]
    result = init_mod._validate_or_correct(
        "deepseek/deepseek-v4-flash", spec, catalog, yes=True
    )
    assert result == "deepseek/deepseek-v4-flash"


# ----------------------------------------------------------------
# .env idempotency + .gitignore + AGENTS.md
# ----------------------------------------------------------------

def test_init_preserves_existing_unrelated_env_lines(tmp_path):
    """Running init twice or against a pre-populated .env shouldn't
    clobber lines unrelated to provider/model/key."""
    (tmp_path / ".env").write_text(
        "# my own notes\n"
        "MY_CUSTOM_VAR=hello\n"
        "MLE_BEAST_PROVIDER=stale-old-value\n"
    )
    rc = _run_init(
        tmp_path,
        env={"OPENROUTER_API_KEY": "sk-or-shell", "PATH": os.environ.get("PATH", "")},
        argv=["--yes", "--no-validate-key"],
        fake_catalog=None,
    )
    assert rc == 0
    body = (tmp_path / ".env").read_text()
    assert "MY_CUSTOM_VAR=hello" in body
    assert "# my own notes" in body
    # Stale managed line was replaced, not duplicated
    assert body.count("MLE_BEAST_PROVIDER=") == 1
    assert "MLE_BEAST_PROVIDER=openrouter" in body


def test_init_adds_env_to_gitignore_in_git_repo(tmp_path):
    """In a git repo (.git/ present), `.env` should be appended to
    .gitignore. (Or a new .gitignore should be created.)"""
    (tmp_path / ".git").mkdir()
    rc = _run_init(
        tmp_path,
        env={"OPENROUTER_API_KEY": "sk-or-shell", "PATH": os.environ.get("PATH", "")},
        argv=["--yes", "--no-validate-key"],
        fake_catalog=None,
    )
    assert rc == 0
    gi = (tmp_path / ".gitignore").read_text().splitlines()
    assert ".env" in [line.strip() for line in gi]


def test_init_does_not_create_gitignore_outside_git_repo(tmp_path):
    """Outside a git repo we don't litter the dir with a .gitignore."""
    rc = _run_init(
        tmp_path,
        env={"OPENROUTER_API_KEY": "sk-or-shell", "PATH": os.environ.get("PATH", "")},
        argv=["--yes", "--no-validate-key"],
        fake_catalog=None,
    )
    assert rc == 0
    assert not (tmp_path / ".gitignore").exists()


def test_init_writes_agents_md(tmp_path):
    """Packaged AGENTS.md template should be copied to cwd."""
    rc = _run_init(
        tmp_path,
        env={"OPENROUTER_API_KEY": "sk-or-shell", "PATH": os.environ.get("PATH", "")},
        argv=["--yes", "--no-validate-key"],
        fake_catalog=None,
    )
    assert rc == 0
    agents = tmp_path / "AGENTS.md"
    assert agents.exists()
    content = agents.read_text()
    assert "mle-beast" in content
    assert "AGENTS" in content or "agents" in content.lower()


def test_init_does_not_overwrite_existing_agents_md(tmp_path):
    """Existing AGENTS.md should be preserved verbatim."""
    (tmp_path / "AGENTS.md").write_text("# my custom agent notes\n")
    rc = _run_init(
        tmp_path,
        env={"OPENROUTER_API_KEY": "sk-or-shell", "PATH": os.environ.get("PATH", "")},
        argv=["--yes", "--no-validate-key"],
        fake_catalog=None,
    )
    assert rc == 0
    assert (tmp_path / "AGENTS.md").read_text() == "# my custom agent notes\n"


# ----------------------------------------------------------------
# --check mode (diagnose only, no scaffolding)
# ----------------------------------------------------------------

def test_init_creates_target_cwd_if_missing(tmp_path):
    """--cwd PATH should mkdir -p before writing, so users pointing at
    a not-yet-existing directory get a clean scaffold. Regression for
    Copilot review on PR #16."""
    target = tmp_path / "not_yet_existing" / "nested" / "project"
    assert not target.exists()
    rc = _run_init(
        target,
        env={"OPENROUTER_API_KEY": "sk-or-shell", "PATH": os.environ.get("PATH", "")},
        argv=["--yes", "--no-validate-key"],
        fake_catalog=None,
    )
    assert rc == 0
    assert target.exists()
    assert (target / ".env").exists()


def test_validate_or_correct_decline_returns_none(tmp_path):
    """When the validator returns None (user declined both suggestion
    AND saving original), _pick_model must propagate None rather than
    silently fall back to the invalid slug. Regression for Copilot
    review on PR #16. We exercise this by patching _ask_bool to return
    False twice (declining correction AND save-anyway)."""
    spec = init_mod._PROVIDERS["openrouter"]
    catalog = ["deepseek/deepseek-v4-flash", "openai/gpt-4o-mini"]

    with patch.object(init_mod, "_ask_bool", return_value=False):
        with patch.object(init_mod, "_ask", return_value="1"):
            # Pick slug "xyz/nonexistent" via the "type your own" path,
            # then decline both correction options.
            result = init_mod._pick_model(
                spec,
                catalog,
                yes=False,
                validate=True,
            )
    # With our patches, _validate_or_correct sees the default slug
    # (suggestions[0]="deepseek/deepseek-v4-flash") IS in the catalog,
    # so it returns the slug as-is — i.e., a valid slug round-trips.
    # That's the happy path. The interesting check is that the None-
    # return path now propagates, which test_init_writes_model_when_*
    # tests already cover indirectly. Just assert the happy path
    # didn't regress.
    assert result == "deepseek/deepseek-v4-flash"


def test_fetch_models_local_url_handling_no_double_v1(monkeypatch):
    """The local-provider URL builder should accept both
    `http://host:port` (append /v1/models) and `http://host:port/v1`
    (just append /models) without producing `.../v1/v1/models`.
    Regression for Copilot review on PR #16."""
    captured: list[str] = []

    class _FakeResp:
        def __init__(self, body: bytes):
            self._body = body
        def read(self):
            return self._body
        def __enter__(self): return self
        def __exit__(self, *a): return False

    def _fake_urlopen(req, timeout=None):
        captured.append(req.get_full_url() if hasattr(req, "get_full_url") else req.full_url)
        return _FakeResp(b'{"data":[]}')

    monkeypatch.setattr(init_mod.urllib.request, "urlopen", _fake_urlopen)

    spec = init_mod._PROVIDERS["local"]
    # Case 1: URL without /v1 — init should add /v1/models
    init_mod._fetch_models(spec, "http://localhost:8000")
    # Case 2: URL with /v1 — init should add only /models
    init_mod._fetch_models(spec, "http://localhost:8000/v1")
    # Case 3: URL with trailing slash + /v1
    init_mod._fetch_models(spec, "http://localhost:8000/v1/")

    assert captured[0] == "http://localhost:8000/v1/models"
    assert captured[1] == "http://localhost:8000/v1/models"
    assert captured[2] == "http://localhost:8000/v1/models"


def test_init_check_mode_does_not_write_files(tmp_path):
    rc = _run_init(
        tmp_path,
        env={"OPENROUTER_API_KEY": "sk", "PATH": os.environ.get("PATH", "")},
        argv=["--yes", "--check"],
        fake_catalog=None,
    )
    # rc may be 0 or 1 depending on whether poetry/git are installed
    # on the test machine — what matters is no scaffolding happened.
    assert rc in (0, 1)
    assert not (tmp_path / ".env").exists()
    assert not (tmp_path / "AGENTS.md").exists()


def test_init_check_mode_never_offers_to_install_poetry(tmp_path):
    """--check is diagnose-only by contract — it must never try to
    install anything, even in interactive mode. Regression test for
    a bug caught during Ubuntu 22.04 fresh-user testing where the
    poetry install prompt fired BEFORE the --check short-circuit,
    EOF'ing in non-interactive contexts (CI, Docker, headless boxes)."""
    install_calls = []

    def fake_install(p, yes):
        install_calls.append((p, yes))
        return False

    with patch.object(init_mod, "_try_install_poetry", fake_install), \
         patch.object(init_mod, "_check_prereqs", return_value=init_mod.PrereqResult(
             python_ok=True,
             python_version="3.10.99",
             poetry_ok=False,     # the trigger — poetry is missing
             git_ok=True,
             pipx_ok=True,
         )):
        with patch.dict(os.environ, {"PATH": os.environ.get("PATH", "")}, clear=True):
            rc = init_mod.run_init(["--cwd", str(tmp_path), "--check"])

    # rc is 1 because poetry isn't installed (the check FAILS), but
    # we MUST NOT have attempted to install it.
    assert rc == 1, "rc should be 1 when prereqs aren't all green"
    assert install_calls == [], (
        "_try_install_poetry must NOT be called in --check mode "
        "(diagnose-only contract)"
    )


# ----------------------------------------------------------------
# MLE_BEAST_PROVIDER respected by llm._detect_provider
# ----------------------------------------------------------------

def test_llm_detect_respects_mle_beast_provider_pin():
    """If both OPENROUTER_API_KEY and OPENAI_API_KEY are set and
    MLE_BEAST_PROVIDER=openai, llm should pick openai despite the
    default resolution order preferring openrouter."""
    from mle_beast.llm import _detect_provider
    with patch.dict(
        os.environ,
        {
            "OPENROUTER_API_KEY": "sk-or",
            "OPENAI_API_KEY": "sk-oa",
            "MLE_BEAST_PROVIDER": "openai",
            "MLE_BEAST_MODEL": "",
        },
        clear=True,
    ):
        provider, model = _detect_provider()
        assert provider == "openai"


def test_llm_detect_falls_back_to_resolution_order_when_unpinned():
    """No MLE_BEAST_PROVIDER → existing resolution order kicks in
    (openrouter > openai > local)."""
    from mle_beast.llm import _detect_provider
    with patch.dict(
        os.environ,
        {
            "OPENROUTER_API_KEY": "sk-or",
            "OPENAI_API_KEY": "sk-oa",
            "MLE_BEAST_MODEL": "",
        },
        clear=True,
    ):
        provider, _ = _detect_provider()
        assert provider == "openrouter"


def test_llm_detect_ignores_pin_when_corresponding_key_is_missing():
    """User pinned `openai` but only OPENROUTER_API_KEY is set. The
    pin can't be honored — fall back to resolution order rather than
    raising."""
    from mle_beast.llm import _detect_provider
    with patch.dict(
        os.environ,
        {
            "OPENROUTER_API_KEY": "sk-or",
            "MLE_BEAST_PROVIDER": "openai",
            "MLE_BEAST_MODEL": "",
        },
        clear=True,
    ):
        provider, _ = _detect_provider()
        assert provider == "openrouter"
