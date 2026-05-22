# Copyright 2026 Chris Padwick
# SPDX-License-Identifier: Apache-2.0

"""`mle-beast init` — diagnose prereqs + scaffold a project.

Run `mle-beast init` in any directory. The command:

  1. Checks Python, poetry, git, LLM-provider env vars.
  2. Offers to install poetry via pipx if missing.
  3. Detects existing API keys in the shell environment; if multiple
     are present, asks the user to pin one via `MLE_BEAST_PROVIDER`.
     If none are present, prompts for one to paste into .env.
  4. Verifies the chosen key against the provider's /models endpoint
     (best-effort — network failures don't block scaffolding).
  5. Picks a model from a curated per-provider list and validates the
     slug against the live model catalog (including fuzzy-match for
     typos / cross-provider prefix mistakes like `gpt-4o-mini` on
     OpenRouter, which actually wants `openai/gpt-4o-mini`).
  6. Writes `.env`, `AGENTS.md`, and ensures `.env` is in `.gitignore`.

Non-interactive use: `--yes` accepts all defaults. `--check` runs only
the diagnose phase. `--no-validate-key` skips the network round-trip
for offline / air-gapped boxes.

Design constraint: no new heavy deps. Uses stdlib only (urllib for HTTP,
getpass for hidden input, difflib for fuzzy match, shutil.which for
PATH checks). python-dotenv is the one new dep, and it's a tiny pure-
Python package already on most boxes.
"""

from __future__ import annotations

import argparse
import difflib
import getpass
import json
import os
import shutil
import subprocess
import sys
import urllib.error
import urllib.request
from dataclasses import dataclass
from importlib import resources
from pathlib import Path
from typing import Optional

# --------------------------------------------------------------------
# Provider configuration. Add new providers here — the rest of the
# module is driven by this dict, so adding e.g. an "anthropic" entry
# is a one-stop change (assuming llm.py grows native support to match).
# --------------------------------------------------------------------

@dataclass(frozen=True)
class ProviderSpec:
    name: str                # canonical id (matches MLE_BEAST_PROVIDER)
    label: str               # human label for prompts
    key_env: Optional[str]   # env var the API key lives in (None for local)
    base_url_env: Optional[str]  # env var the base URL lives in (None for hosted)
    models_url: str          # full URL to GET for the live catalog
    auth_header: str         # "Bearer ${key}" / "${key}" / ""
    # Curated picker list. Items are model slugs as the provider accepts
    # them. Ordered cheap-ish → premium-ish but no cost annotations
    # because prices go stale.
    suggested_models: tuple[str, ...]
    # Plain-name suffix used when a user types a bare model name
    # without the provider prefix on a prefix-requiring provider
    # (OpenRouter). Maps "gpt-4o-mini" → ["openai/gpt-4o-mini"].
    requires_prefix: bool = False


_PROVIDERS: dict[str, ProviderSpec] = {
    "openrouter": ProviderSpec(
        name="openrouter",
        label="OpenRouter (one key, many models — recommended)",
        key_env="OPENROUTER_API_KEY",
        base_url_env=None,
        models_url="https://openrouter.ai/api/v1/models",
        auth_header="Bearer",
        suggested_models=(
            "deepseek/deepseek-v4-flash",
            "openai/gpt-4o-mini",
            "anthropic/claude-haiku-4-5",
            "anthropic/claude-sonnet-4-6",
            "anthropic/claude-opus-4-7",
        ),
        requires_prefix=True,
    ),
    "openai": ProviderSpec(
        name="openai",
        label="OpenAI",
        key_env="OPENAI_API_KEY",
        base_url_env=None,
        models_url="https://api.openai.com/v1/models",
        auth_header="Bearer",
        suggested_models=(
            "gpt-4o-mini",
            "gpt-4o",
            "gpt-5-mini",
        ),
        requires_prefix=False,
    ),
    "local": ProviderSpec(
        name="local",
        label="Local LLM (vLLM / Ollama / llamacpp — OpenAI-compatible API)",
        key_env=None,
        base_url_env="LOCAL_LLM_BASE_URL",
        models_url="",  # filled in dynamically from base_url
        auth_header="",
        suggested_models=(),  # populated from /v1/models at runtime
        requires_prefix=False,
    ),
}


# --------------------------------------------------------------------
# Tiny ANSI color helpers — keep `rich` out of the dep list. We're
# writing to a TTY in 99% of cases; if stdout isn't a TTY we strip
# the codes so `mle-beast init 2>&1 | tee log` produces clean output.
# --------------------------------------------------------------------

_USE_COLOR = sys.stdout.isatty() and os.environ.get("NO_COLOR") is None


def _c(text: str, code: str) -> str:
    return f"\033[{code}m{text}\033[0m" if _USE_COLOR else text


def _ok(t: str) -> str:    return _c(t, "32")  # green
def _bad(t: str) -> str:   return _c(t, "31")  # red
def _warn(t: str) -> str:  return _c(t, "33")  # yellow
def _info(t: str) -> str:  return _c(t, "36")  # cyan
def _dim(t: str) -> str:   return _c(t, "2")   # faint
def _bold(t: str) -> str:  return _c(t, "1")


# --------------------------------------------------------------------
# I/O helpers
# --------------------------------------------------------------------

def _header(label: str) -> None:
    print()
    print(_bold(f"⏵ {label}"))


def _line(symbol: str, text: str) -> None:
    print(f"  {symbol} {text}")


def _ask(prompt: str, *, default: Optional[str] = None, yes: bool = False) -> str:
    """Plain-text prompt. With yes=True returns the default unattended."""
    suffix = f" [{default}]" if default is not None else ""
    if yes:
        return default if default is not None else ""
    raw = input(f"  {prompt}{suffix}: ").strip()
    return raw or (default or "")


def _ask_bool(prompt: str, *, default: bool = True, yes: bool = False) -> bool:
    if yes:
        return default
    suffix = "[Y/n]" if default else "[y/N]"
    raw = input(f"  {prompt} {suffix} ").strip().lower()
    if not raw:
        return default
    return raw in ("y", "yes", "1", "true")


def _ask_hidden(prompt: str, *, yes: bool = False) -> str:
    """getpass-style hidden input. With yes=True returns empty string
    (callers should skip if hidden input isn't safe to default)."""
    if yes:
        return ""
    return getpass.getpass(f"  {prompt}: ").strip()


# --------------------------------------------------------------------
# Phase: prereq check
# --------------------------------------------------------------------

@dataclass
class PrereqResult:
    python_ok: bool
    python_version: str
    poetry_ok: bool
    git_ok: bool
    pipx_ok: bool


def _check_prereqs() -> PrereqResult:
    """Probe the environment for hard dependencies."""
    py = sys.version_info
    python_ok = (py.major, py.minor) >= (3, 10)
    python_version = f"{py.major}.{py.minor}.{py.micro}"
    return PrereqResult(
        python_ok=python_ok,
        python_version=python_version,
        poetry_ok=shutil.which("poetry") is not None,
        git_ok=shutil.which("git") is not None,
        pipx_ok=shutil.which("pipx") is not None,
    )


def _print_prereq_status(p: PrereqResult) -> None:
    if p.python_ok:
        _line(_ok("✓"), f"Python {p.python_version}")
    else:
        _line(_bad("✗"), f"Python {p.python_version} — mle-beast needs 3.10+")
    _line(_ok("✓") if p.poetry_ok else _bad("✗"),
          "poetry " + ("found" if p.poetry_ok else "not found"))
    _line(_ok("✓") if p.git_ok else _bad("✗"),
          "git " + ("found" if p.git_ok else "not found"))


def _try_install_poetry(p: PrereqResult, *, yes: bool) -> bool:
    """Offer to `pipx install poetry`. Returns True if poetry is on PATH
    after this function returns (either pre-existing or freshly installed)."""
    if p.poetry_ok:
        return True
    if not p.pipx_ok:
        print()
        _line(_warn("→"), "Can't auto-install poetry: pipx isn't on PATH.")
        _line(" ", "Install pipx first:")
        _line(" ", _dim("python3 -m pip install --user pipx && python3 -m pipx ensurepath"))
        _line(" ", "then open a new shell and re-run `mle-beast init`.")
        return False

    if not _ask_bool("Install poetry now with `pipx install poetry`?", default=True, yes=yes):
        return False

    print(_dim("  ⏳ Running `pipx install poetry` …"))
    try:
        subprocess.run(["pipx", "install", "poetry"], check=True)
    except subprocess.CalledProcessError as e:
        _line(_bad("✗"), f"pipx install poetry failed (exit {e.returncode})")
        return False
    # Re-probe.
    return shutil.which("poetry") is not None


# --------------------------------------------------------------------
# Phase: LLM provider detection + selection
# --------------------------------------------------------------------

def _detect_keys_in_env() -> list[str]:
    """Return provider ids whose key/base-url env var is currently set."""
    present: list[str] = []
    for pid, spec in _PROVIDERS.items():
        env_var = spec.key_env or spec.base_url_env
        if env_var and os.environ.get(env_var):
            present.append(pid)
    return present


def _mask(secret: str) -> str:
    if not secret:
        return ""
    if len(secret) <= 8:
        return "*" * len(secret)
    return f"{secret[:6]}…{secret[-4:]}"


def _pick_provider(detected: list[str], *, yes: bool) -> ProviderSpec:
    """Walk the user through provider selection."""
    if detected:
        _line(_info("Found in your shell environment:"), "")
        for i, pid in enumerate(detected, start=1):
            spec = _PROVIDERS[pid]
            value = os.environ.get(spec.key_env or spec.base_url_env or "", "")
            print(f"    {i}) {spec.label}  {_dim(_mask(value))}")
        if len(detected) == 1:
            choice = _ask("Use this one?", default="Y", yes=yes).lower()
            if choice not in ("", "y", "yes"):
                # User said no — fall through to manual selection.
                detected = []
            else:
                return _PROVIDERS[detected[0]]
        else:
            raw = _ask("Which would you like mle-beast to use?", default="1", yes=yes)
            try:
                idx = int(raw) - 1
                if 0 <= idx < len(detected):
                    return _PROVIDERS[detected[idx]]
            except ValueError:
                pass
            # Fall through to manual on bad input.

    # Manual provider selection.
    _line(_info("No API keys detected. Pick a provider:"), "")
    ordered = list(_PROVIDERS.values())
    for i, spec in enumerate(ordered, start=1):
        print(f"    {i}) {spec.label}")
    raw = _ask("Choice", default="1", yes=yes)
    try:
        idx = int(raw) - 1
        if 0 <= idx < len(ordered):
            return ordered[idx]
    except ValueError:
        pass
    return ordered[0]


def _prompt_for_key(spec: ProviderSpec, *, yes: bool) -> Optional[str]:
    """If the user picked a hosted provider but has no key set, prompt
    for one (hidden input). Returns the typed key or None to skip."""
    if spec.key_env is None:
        # local — no key needed, but we do need a base URL.
        existing = os.environ.get(spec.base_url_env or "", "")
        if existing:
            return existing
        if yes:
            return None
        # /v1 included by convention — llm.py treats LOCAL_LLM_BASE_URL
        # as an OpenAI-compatible base URL, and the OpenAI SDK appends
        # endpoints onto it directly. Without /v1 the runtime requests
        # would 404 against vLLM / Ollama / llama.cpp servers.
        return _ask(
            f"{spec.label} base URL",
            default="http://localhost:8000/v1",
        )

    existing = os.environ.get(spec.key_env, "")
    if existing:
        return existing
    if yes:
        return None
    return _ask_hidden(f"Paste your {spec.key_env} (won't echo)") or None


# --------------------------------------------------------------------
# Phase: live API verification (key + model catalog in one trip)
# --------------------------------------------------------------------

def _fetch_models(spec: ProviderSpec, secret: str) -> Optional[list[str]]:
    """Hit the provider's /models endpoint with a 10s timeout. Returns
    a list of slugs on success, None on any failure (network, auth,
    timeout). Callers decide whether to soft-warn or hard-fail."""
    if spec.name == "local":
        # `LOCAL_LLM_BASE_URL` is treated by the rest of the codebase
        # (llm.py) as an OpenAI-compatible base URL, which by
        # convention ALREADY includes `/v1`. Be lenient here: accept
        # `http://host:8000` OR `http://host:8000/v1` and produce a
        # well-formed `/v1/models` either way.
        base = secret.rstrip("/")
        if base.endswith("/v1"):
            url = f"{base}/models"
        else:
            url = f"{base}/v1/models"
        headers: dict[str, str] = {}
    else:
        url = spec.models_url
        headers = {"Authorization": f"{spec.auth_header} {secret}"} if spec.auth_header else {}

    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=10.0) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError,
            json.JSONDecodeError, ConnectionError):
        return None
    data = payload.get("data") or payload.get("models") or []
    slugs: list[str] = []
    for item in data:
        if isinstance(item, dict) and "id" in item:
            slugs.append(item["id"])
        elif isinstance(item, str):
            slugs.append(item)
    return slugs


def _pick_model(
    spec: ProviderSpec,
    available_slugs: Optional[list[str]],
    *,
    yes: bool,
    validate: bool,
) -> Optional[str]:
    """Walk the user through model selection + validation."""
    # Build the picker list:
    #   - For hosted providers, intersect curated suggestions with the
    #     live catalog so stale defaults are auto-pruned.
    #   - For local, just take whatever /v1/models returned.
    suggestions: list[str]
    if spec.name == "local":
        suggestions = list(available_slugs or [])
    else:
        if available_slugs is None:
            suggestions = list(spec.suggested_models)
        else:
            avail = set(available_slugs)
            suggestions = [m for m in spec.suggested_models if m in avail]
            # If curated list got fully filtered out, fall back to the
            # raw curated list so the user can still see something to
            # type. They'll get a validation warning if they pick one
            # that's actually missing.
            if not suggestions:
                suggestions = list(spec.suggested_models)

    if not suggestions and spec.name == "local":
        # Local server didn't report any models — fall back to free-form.
        if yes:
            return None
        return _ask("Type model slug for your local server", default="") or None

    _line(_info(f"Suggested for {spec.name}"
                + (" (verified live)" if available_slugs else " (offline — not verified)")
                + ":"), "")
    for i, slug in enumerate(suggestions, start=1):
        marker = " ← default" if i == 1 else ""
        print(f"    {i}) {slug}{marker}")
    print(f"    {len(suggestions) + 1}) [type your own model slug]")

    default_index = "1"
    raw = _ask("Choice", default=default_index, yes=yes)
    try:
        idx = int(raw) - 1
    except ValueError:
        idx = 0
    if idx == len(suggestions):
        if yes:
            return suggestions[0] if suggestions else None
        slug = _ask("Type model slug", default="") or (suggestions[0] if suggestions else None)
    elif 0 <= idx < len(suggestions):
        slug = suggestions[idx]
    else:
        slug = suggestions[0] if suggestions else None

    if slug is None:
        return None

    # Validate (and maybe auto-correct format mismatches). If the
    # validator returns None, the user explicitly declined both the
    # correction AND saving the original — respect that decision and
    # return None up the chain instead of silently keeping the bad
    # slug (which would otherwise land in .env and confuse the next run).
    if validate and available_slugs is not None:
        corrected = _validate_or_correct(slug, spec, available_slugs, yes=yes)
        return corrected

    return slug


def _validate_or_correct(
    slug: str,
    spec: ProviderSpec,
    available_slugs: list[str],
    *,
    yes: bool,
) -> Optional[str]:
    """If `slug` is in available_slugs, return it as-is. Otherwise look
    for cross-provider prefix mistakes and fuzzy matches, and offer a
    correction. Returns the corrected slug, the original slug if the
    user wants to save it anyway, or None to abort."""
    if slug in available_slugs:
        _line(_ok("✓"), f"verified {slug} in {spec.name}'s catalog")
        return slug

    # Prefix-mismatch heuristic for OpenRouter (requires `provider/model`).
    candidates: list[str] = []
    if spec.requires_prefix and "/" not in slug:
        # User typed e.g. "gpt-4o-mini" against OpenRouter. Look for any
        # available slug whose suffix matches.
        candidates = [m for m in available_slugs if m.endswith("/" + slug)]
    elif (not spec.requires_prefix) and "/" in slug:
        # User typed e.g. "openai/gpt-4o-mini" against OpenAI. Strip
        # the prefix and see if the bare name is available.
        bare = slug.split("/", 1)[1]
        if bare in available_slugs:
            candidates = [bare]

    if not candidates:
        # Fall back to general fuzzy match.
        candidates = difflib.get_close_matches(slug, available_slugs, n=3, cutoff=0.55)

    if not candidates:
        _line(_warn("⚠"), f"{slug} not found in {spec.name}'s catalog and no close matches.")
        if _ask_bool("Save this slug anyway?", default=False, yes=yes):
            return slug
        return None

    _line(_warn("⚠"), f"{slug} not found in {spec.name}'s catalog. Did you mean:")
    for i, c in enumerate(candidates, start=1):
        marker = " (closest match)" if i == 1 else ""
        print(f"      → {c}{marker}")

    if _ask_bool(f"Use {candidates[0]}?", default=True, yes=yes):
        return candidates[0]
    if _ask_bool("Save your original slug anyway?", default=False, yes=yes):
        return slug
    return None


# --------------------------------------------------------------------
# Phase: scaffold the project
# --------------------------------------------------------------------

@dataclass
class ProjectChoices:
    provider: ProviderSpec
    secret: Optional[str]            # API key or base URL
    secret_was_in_shell: bool        # if True, don't copy into .env
    model: Optional[str]


def _write_env_file(cwd: Path, choices: ProjectChoices) -> Path:
    """Write `.env` based on the user's choices. Returns the path written.

    Idempotent in spirit — we overwrite our managed keys
    (`MLE_BEAST_PROVIDER`, `MLE_BEAST_MODEL`, and the chosen provider's
    `*_API_KEY` / `*_BASE_URL`) and preserve every other line the user
    may have added. No special marker is appended to lines — the key
    names themselves are how we identify what's ours on re-runs.
    """
    env_path = cwd / ".env"
    existing_lines: list[str] = []
    managed_keys = {"MLE_BEAST_PROVIDER", "MLE_BEAST_MODEL"}
    if choices.provider.key_env:
        managed_keys.add(choices.provider.key_env)
    if choices.provider.base_url_env:
        managed_keys.add(choices.provider.base_url_env)

    if env_path.exists():
        for line in env_path.read_text().splitlines():
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                existing_lines.append(line)
                continue
            key = stripped.split("=", 1)[0].strip()
            if key in managed_keys:
                continue  # we'll re-emit
            existing_lines.append(line)

    new_lines: list[str] = []
    if not env_path.exists():
        new_lines.append("# Managed by `mle-beast init`. Shell environment")
        new_lines.append("# variables override anything in this file.")
        new_lines.append("")

    new_lines.append(f"MLE_BEAST_PROVIDER={choices.provider.name}")
    if choices.model:
        new_lines.append(f"MLE_BEAST_MODEL={choices.model}")

    # Only write the secret into .env if the user typed it interactively
    # (i.e., it wasn't already exported in their shell). For shell-sourced
    # keys we trust the shell to keep providing them.
    if choices.secret and not choices.secret_was_in_shell:
        if choices.provider.key_env:
            new_lines.append(f"{choices.provider.key_env}={choices.secret}")
        elif choices.provider.base_url_env:
            new_lines.append(f"{choices.provider.base_url_env}={choices.secret}")

    content = "\n".join(existing_lines + ([""] if existing_lines else []) + new_lines) + "\n"
    env_path.write_text(content)
    return env_path


def _ensure_gitignore(cwd: Path) -> Optional[Path]:
    """Append `.env` to `.gitignore` if not already present. Creates
    `.gitignore` if it doesn't exist. Returns the path on change,
    None if no change was needed (or if cwd isn't a git repo and there's
    no .gitignore to update)."""
    gi_path = cwd / ".gitignore"
    if gi_path.exists():
        existing = gi_path.read_text()
        if any(line.strip() == ".env" for line in existing.splitlines()):
            return None
        new = existing.rstrip("\n") + "\n.env\n"
        gi_path.write_text(new)
        return gi_path
    # No .gitignore yet — only create one if we're in a git repo, to
    # avoid littering non-git directories.
    if not (cwd / ".git").exists():
        return None
    gi_path.write_text(".env\n")
    return gi_path


def _write_agents_md(cwd: Path) -> Optional[Path]:
    """Copy the packaged AGENTS.md into cwd if not already present."""
    dest = cwd / "AGENTS.md"
    if dest.exists():
        return None
    try:
        files = resources.files("mle_beast.templates")
        src = files / "AGENTS.md"
        # `as_file` handles wheel-extraction transparently. .read_text
        # also works on path-like resources for plain files.
        dest.write_text(src.read_text(encoding="utf-8"), encoding="utf-8")
    except Exception as e:
        _line(_warn("⚠"), f"Couldn't write AGENTS.md from packaged template: {e}")
        return None
    return dest


# --------------------------------------------------------------------
# Entry point
# --------------------------------------------------------------------

def run_init(argv: list[str]) -> int:
    """Run the init flow. Returns a shell exit code."""
    parser = argparse.ArgumentParser(
        prog="mle-beast init",
        description="Diagnose prerequisites and scaffold a project for mle-beast.",
    )
    parser.add_argument("--yes", "-y", action="store_true",
                        help="Accept all defaults; no prompts (CI-friendly).")
    parser.add_argument("--check", action="store_true",
                        help="Run only the diagnose phase; don't write any files.")
    parser.add_argument("--no-validate-key", action="store_true",
                        help="Skip the API-call verification step.")
    parser.add_argument("--cwd", default=None,
                        help="Target directory (default: current working dir).")
    args = parser.parse_args(argv)

    cwd = Path(args.cwd).expanduser().resolve() if args.cwd else Path.cwd()
    # Create the target if --cwd points at a not-yet-existing path so
    # subsequent .env / AGENTS.md writes don't FileNotFoundError mid-run.
    # When cwd defaults to Path.cwd() the dir obviously exists; mkdir
    # is idempotent (exist_ok=True) either way.
    cwd.mkdir(parents=True, exist_ok=True)

    print(_bold("mle-beast init"))
    print(_dim(f"  target dir: {cwd}"))

    # ---- 1. prereqs ---------------------------------------------------
    _header("Checking prerequisites")
    pre = _check_prereqs()
    _print_prereq_status(pre)
    if not pre.python_ok:
        print()
        print(_bad("Python 3.10+ is required. Upgrade Python and re-run."))
        return 2

    # --check is diagnose-only by contract. Return BEFORE any action
    # (install offer, file scaffold, etc.). Previously the install
    # prompt for missing poetry ran first, which broke `--check` in
    # non-interactive contexts (CI, Docker, headless servers) — the
    # `Install poetry? [Y/n]` prompt EOF'd on missing stdin.
    if args.check:
        if not pre.poetry_ok:
            _line(_dim("→"), "poetry missing; rerun without --check for an interactive install offer.")
        if not pre.git_ok:
            _line(_dim("→"), "git missing; install via your system package manager.")
        return 0 if (pre.python_ok and pre.poetry_ok and pre.git_ok) else 1

    if not pre.poetry_ok:
        installed = _try_install_poetry(pre, yes=args.yes)
        if installed:
            _line(_ok("✓"), "poetry now on PATH")
        # We don't hard-fail if poetry's still missing — they can run
        # brownfield/BYO without poetry. The greenfield path will fail
        # fast with the clear message we already wrote into workspace.py.
    if not pre.git_ok:
        _line(" ", _dim("Install git via your system package manager and re-run."))

    # ---- 2. provider selection ---------------------------------------
    _header("LLM provider")
    detected = _detect_keys_in_env()
    spec = _pick_provider(detected, yes=args.yes)
    secret = _prompt_for_key(spec, yes=args.yes)
    secret_in_shell = bool(spec.key_env and os.environ.get(spec.key_env)) or \
        bool(spec.base_url_env and os.environ.get(spec.base_url_env))

    if not secret:
        _line(_warn("⚠"), "No key/URL provided — skipping verification + model picker.")
        choices = ProjectChoices(
            provider=spec, secret=None, secret_was_in_shell=False, model=None
        )
        env_path = _write_env_file(cwd, choices)
        _line(_ok("✓"), f"Wrote {env_path.name} (provider only — add the key later)")
        return 0

    # ---- 3. live verification + model picker -------------------------
    available_slugs: Optional[list[str]] = None
    if args.no_validate_key:
        _line(_dim("→"), "skipping verification (--no-validate-key)")
    else:
        _line(_dim("→"), f"verifying against {spec.name}'s /models endpoint …")
        available_slugs = _fetch_models(spec, secret)
        if available_slugs is None:
            _line(_warn("⚠"), "verification failed (network down, key invalid, or endpoint changed).")
            if not _ask_bool("Continue without verification?", default=False, yes=args.yes):
                return 1
        else:
            _line(_ok("✓"), f"reached {spec.name} — {len(available_slugs)} models in catalog")

    _header("Pick a model")
    model = _pick_model(spec, available_slugs, yes=args.yes,
                        validate=not args.no_validate_key)
    if model:
        _line(_ok("✓"), f"will use model: {_bold(model)}")
    else:
        _line(_warn("⚠"), "no model selected — falling back to provider default at runtime")

    # ---- 4. scaffold -------------------------------------------------
    _header("Scaffolding project")
    choices = ProjectChoices(
        provider=spec,
        secret=secret,
        secret_was_in_shell=secret_in_shell,
        model=model,
    )
    env_path = _write_env_file(cwd, choices)
    _line(_ok("✓"), f"wrote {env_path.name}")

    gi_path = _ensure_gitignore(cwd)
    if gi_path:
        _line(_ok("✓"), f"updated {gi_path.name} (.env is gitignored)")

    agents_path = _write_agents_md(cwd)
    if agents_path:
        _line(_ok("✓"), f"wrote {agents_path.name}")
    else:
        _line(_dim("·"), "AGENTS.md already exists — left untouched")

    # ---- 5. next steps -----------------------------------------------
    _header("Next steps")
    _line("•", "First greenfield run downloads ~5.5 GB of ml-frameworks deps (cached after).")
    _line("•", f"`{_bold('mle-beast')}` to start the dashboard at http://127.0.0.1:8000")
    _line("•", f"`{_bold('mle-beast --no-web')}` for the CLI REPL")
    _line("•", f"See {_bold('AGENTS.md')} to drive mle-beast from Claude Code / Cursor / etc.")
    print()
    return 0
