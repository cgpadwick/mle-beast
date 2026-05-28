#!/usr/bin/env bash
# mle-beast quickstart wizard.
#
# Curl-able first-run setup. Usage:
#
#   curl -fsSL https://raw.githubusercontent.com/cgpadwick/mle-beast/main/setup-mle-beast.sh | bash
#
# Or, if you'd rather review before running (recommended for any
# pipe-to-shell script):
#
#   curl -fsSL https://raw.githubusercontent.com/cgpadwick/mle-beast/main/setup-mle-beast.sh -o setup-mle-beast.sh
#   less setup-mle-beast.sh
#   bash setup-mle-beast.sh
#
# Two installation paths, picked interactively or via flags:
#
#   --docker   Generate a docker-compose.yml + .env in CWD, run
#              `docker compose up -d`. Zero host-side Python install.
#   --native   pipx install mle-beast, then hand off to `mle-beast init`
#              for the per-project setup.
#
# Non-interactive automation flags (Docker path):
#   --yes / -y              Accept all defaults; no prompts.
#   --openrouter-key=K      Set OPENROUTER_API_KEY in .env (skips prompt).
#   --openai-key=K          Set OPENAI_API_KEY.
#   --local-llm-url=URL     Set LOCAL_LLM_BASE_URL.
#   --gpu / --no-gpu        Force GPU on/off (default: auto-detect).
#   --port=N                Dashboard port (default: 8000).
#   --tag=T                 Image tag (default: edge).
#   --model=SLUG            Model slug (default: deepseek/deepseek-v4-flash).
#   --data-dir=PATH         Where the host stores SQLite + settings
#                           (default: ~/.mle-beast). ~/ is expanded.
#   --workspaces-dir=PATH   Where the host stores per-run workspace dirs
#                           (default: ~/mle-beast-runs).

set -euo pipefail

# --------------------------------------------------------------------
# Configuration constants
# --------------------------------------------------------------------

readonly IMAGE_REPO="ghcr.io/cgpadwick/mle-beast"
readonly DEFAULT_TAG="edge"
readonly DEFAULT_PORT="8000"

# --------------------------------------------------------------------
# Output helpers — ANSI colors only when stdout is a TTY (so
# `| tee log` produces clean output).
# --------------------------------------------------------------------

if [ -t 1 ] && [ "${NO_COLOR:-}" = "" ]; then
  C_RESET=$'\033[0m'
  C_BOLD=$'\033[1m'
  C_DIM=$'\033[2m'
  C_GREEN=$'\033[32m'
  C_RED=$'\033[31m'
  C_YELLOW=$'\033[33m'
  C_CYAN=$'\033[36m'
else
  C_RESET=''
  C_BOLD=''
  C_DIM=''
  C_GREEN=''
  C_RED=''
  C_YELLOW=''
  C_CYAN=''
fi

header() { printf '\n%s⏵ %s%s\n' "${C_BOLD}" "$1" "${C_RESET}"; }
ok()     { printf '  %s✓%s %s\n' "${C_GREEN}" "${C_RESET}" "$1"; }
fail()   { printf '  %s✗%s %s\n' "${C_RED}" "${C_RESET}" "$1" >&2; exit 1; }
warn()   { printf '  %s⚠%s %s\n' "${C_YELLOW}" "${C_RESET}" "$1"; }
info()   { printf '  %s→%s %s\n' "${C_CYAN}" "${C_RESET}" "$1"; }
dim()    { printf '  %s%s%s\n' "${C_DIM}" "$1" "${C_RESET}"; }

# --------------------------------------------------------------------
# Argument parsing
# --------------------------------------------------------------------

PATH_CHOICE=""           # "docker" | "native" | "" (= ask)
YES=false
OPENROUTER_KEY=""
OPENAI_KEY=""
LOCAL_LLM_URL=""
GPU_PREF=""              # "yes" | "no" | "" (= auto-detect)
PORT="$DEFAULT_PORT"
TAG="$DEFAULT_TAG"
MODEL=""                 # explicit slug; empty = ask (Docker) or defer (Native)
DATA_DIR=""              # SQLite + settings location on host; "" = ask
WORKSPACES_DIR=""        # per-run workspace dirs on host; "" = ask

while [ $# -gt 0 ]; do
  case "$1" in
    --docker)              PATH_CHOICE="docker" ;;
    --native)              PATH_CHOICE="native" ;;
    --yes|-y)              YES=true ;;
    --openrouter-key=*)    OPENROUTER_KEY="${1#*=}" ;;
    --openai-key=*)        OPENAI_KEY="${1#*=}" ;;
    --local-llm-url=*)     LOCAL_LLM_URL="${1#*=}" ;;
    --gpu)                 GPU_PREF="yes" ;;
    --no-gpu)              GPU_PREF="no" ;;
    --port=*)              PORT="${1#*=}" ;;
    --tag=*)               TAG="${1#*=}" ;;
    --model=*)             MODEL="${1#*=}" ;;
    --data-dir=*)          DATA_DIR="${1#*=}" ;;
    --workspaces-dir=*)    WORKSPACES_DIR="${1#*=}" ;;
    -h|--help)
      # When run as a file, print the header docstring straight from source.
      # When piped (curl ... | bash), $0 is "bash" — not our script — so the
      # sed-from-$0 trick reads the wrong file. Fall back to a static block.
      if [ -r "$0" ] && head -n1 "$0" 2>/dev/null | grep -q '^#!'; then
        sed -n '/^# mle-beast quickstart wizard\./,/^set -euo/p' "$0" | sed 's/^# \{0,1\}//; /^set -euo/d'
      else
        cat <<'EOF'
mle-beast quickstart wizard

Usage:
  curl -fsSL https://raw.githubusercontent.com/cgpadwick/mle-beast/main/setup-mle-beast.sh | bash
  bash setup-mle-beast.sh [--docker | --native] [flags]

Flags:
  --docker / --native        Pick install path (default: ask).
  --yes, -y                  Accept all defaults; no prompts.
  --openrouter-key=K         Set OPENROUTER_API_KEY.
  --openai-key=K             Set OPENAI_API_KEY.
  --local-llm-url=URL        Set LOCAL_LLM_BASE_URL.
  --gpu / --no-gpu           Force GPU on/off (default: auto-detect).
  --port=N                   Dashboard port (default: 8000).
  --tag=T                    Image tag (default: edge).
  --model=SLUG               Model slug.
  --data-dir=PATH            SQLite + settings dir (default: ~/.mle-beast).
  --workspaces-dir=PATH      Per-run workspace dir (default: ~/mle-beast-runs).

Docs: https://github.com/cgpadwick/mle-beast
EOF
      fi
      exit 0 ;;
    *)
      fail "Unknown flag: $1 (try --help)" ;;
  esac
  shift
done

# Expand ~ in user-supplied paths. Compose YAML doesn't expand $HOME,
# so we resolve at script time and write absolute paths into the
# generated compose. Run early in case --yes uses the defaults below
# (which also use ~).
expand_tilde() { printf '%s' "${1/#\~/$HOME}"; }
[ -n "$DATA_DIR" ]       && DATA_DIR=$(expand_tilde "$DATA_DIR")
[ -n "$WORKSPACES_DIR" ] && WORKSPACES_DIR=$(expand_tilde "$WORKSPACES_DIR")

# --------------------------------------------------------------------
# Banner
# --------------------------------------------------------------------

printf '%smle-beast quickstart%s\n' "${C_BOLD}" "${C_RESET}"
dim "https://github.com/cgpadwick/mle-beast"

# --------------------------------------------------------------------
# Prompt helpers
# --------------------------------------------------------------------

# Plain prompt. Returns default value when --yes is on.
ask() {
  local prompt="$1"
  local default="${2:-}"
  local suffix=""
  [ -n "$default" ] && suffix=" [${default}]"
  if [ "$YES" = "true" ]; then
    printf '%s' "$default"
    return
  fi
  local raw
  read -r -p "  ${prompt}${suffix}: " raw </dev/tty
  printf '%s' "${raw:-$default}"
}

# Hidden prompt for secrets. Returns empty when --yes (no way to
# default a secret).
ask_hidden() {
  local prompt="$1"
  if [ "$YES" = "true" ]; then
    printf ''
    return
  fi
  local raw
  read -r -s -p "  ${prompt}: " raw </dev/tty
  printf '\n' >&2
  printf '%s' "$raw"
}

# Yes/no prompt. Default Y unless explicit "n" passed.
ask_bool() {
  local prompt="$1"
  local default="${2:-y}"
  if [ "$YES" = "true" ]; then
    [ "$default" = "y" ] && return 0 || return 1
  fi
  local suffix
  if [ "$default" = "y" ]; then suffix="[Y/n]"; else suffix="[y/N]"; fi
  local raw
  read -r -p "  ${prompt} ${suffix} " raw </dev/tty || raw=""
  case "$(printf '%s' "$raw" | tr '[:upper:]' '[:lower:]')" in
    y|yes|1|true) return 0 ;;
    n|no|0|false) return 1 ;;
    "") [ "$default" = "y" ] && return 0 || return 1 ;;
    *) [ "$default" = "y" ] && return 0 || return 1 ;;
  esac
}

# --------------------------------------------------------------------
# Path chooser
# --------------------------------------------------------------------

if [ -z "$PATH_CHOICE" ]; then
  header "How do you want to use mle-beast?"
  printf '    1) %sDocker%s    zero host install, full isolation\n' "${C_BOLD}" "${C_RESET}"
  printf '    2) %sNative%s    pipx install on host (BYO env / hack on the source)\n' "${C_BOLD}" "${C_RESET}"
  raw=$(ask "Choice" "1")
  case "$raw" in
    2|native|Native|NATIVE)  PATH_CHOICE="native" ;;
    *)                       PATH_CHOICE="docker" ;;
  esac
fi

# --------------------------------------------------------------------
# Native path: defer almost everything to `mle-beast init`
# --------------------------------------------------------------------

run_native() {
  header "Checking native-install prerequisites"

  # Python 3.10+
  if ! command -v python3 >/dev/null 2>&1; then
    fail "python3 not found. Install Python 3.10+ via your system package manager and re-run."
  fi
  local py_version
  py_version=$(python3 -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')
  ok "python3 ${py_version}"
  if ! python3 -c 'import sys; sys.exit(0 if sys.version_info >= (3,10) else 1)'; then
    fail "Python ${py_version} is too old. mle-beast requires 3.10+."
  fi

  # pipx
  if command -v pipx >/dev/null 2>&1; then
    ok "pipx $(pipx --version)"
  else
    warn "pipx not found."
    info "Install with one of:"
    dim "    sudo apt install pipx                 # Debian / Ubuntu"
    dim "    brew install pipx                     # macOS"
    dim "    python3 -m pip install --user pipx    # universal fallback"
    dim "    python3 -m pipx ensurepath            # add to PATH"
    info "Then open a new shell and re-run this script."
    exit 1
  fi

  header "Installing mle-beast via pipx"
  # Try PyPI first (the standard install path post-v0.1.0). If that
  # fails — e.g. pre-release window where mle-beast isn't on PyPI
  # yet — fall back to installing directly from the GitHub repo so
  # the script remains useful TODAY without waiting for a publish.
  #
  # Capture full output to a temp log rather than discarding it (2>/dev/null)
  # or truncating it (| tail -3). The pipe also masked failure: `pipx ... |
  # tail` returns tail's exit code, so a failed install looked like success.
  # On total failure we point the user at the log instead of telling them to
  # re-run by hand.
  local pipx_log
  pipx_log=$(mktemp)
  if pipx install mle-beast >"$pipx_log" 2>&1; then
    ok "mle-beast installed (from PyPI)"
    rm -f "$pipx_log"
  else
    info "PyPI install didn't work (likely pre-launch); trying GitHub instead…"
    if pipx install git+https://github.com/cgpadwick/mle-beast.git >"$pipx_log" 2>&1; then
      ok "mle-beast installed (from GitHub main)"
      rm -f "$pipx_log"
    else
      warn "pipx install failed from both PyPI and GitHub."
      info "Last lines of the install log ($pipx_log):"
      tail -n 15 "$pipx_log" >&2
      fail "See the full log at $pipx_log"
    fi
  fi

  # pipx may have installed the app into a bin dir (usually ~/.local/bin)
  # that isn't on PATH yet — common when pipx itself came from apt. Catch
  # that here so the exec below doesn't die with a bare "command not found".
  if ! command -v mle-beast >/dev/null 2>&1; then
    warn "mle-beast installed but not found on PATH."
    info "pipx's app directory likely isn't on your PATH. Fix with:"
    dim "    python3 -m pipx ensurepath"
    info "Then open a new shell and run: mle-beast init"
    exit 1
  fi

  header "Handing off to mle-beast init"
  dim "  The next step is interactive. mle-beast init walks you through"
  dim "  prereqs, LLM provider selection, model picking, and scaffolds"
  dim "  .env + AGENTS.md in your current directory."
  printf '\n'

  # Exec so the user's shell takes over the init wizard cleanly —
  # this script exits, mle-beast init owns the tty.
  exec mle-beast init
}

# --------------------------------------------------------------------
# Docker path
# --------------------------------------------------------------------

# --------------------------------------------------------------------
# Port helpers
# --------------------------------------------------------------------

# Return 0 (true) if the given TCP port is free on the host.
# Tries ss (Linux), then lsof (macOS), then netstat as a last resort.
# Note: on WSL2 with mirrored networking, ports held by Windows
# processes won't appear here — the check will report them as free
# even though Docker can't bind them.
port_is_free() {
  local port="$1"
  if command -v ss >/dev/null 2>&1; then
    ! ss -tln 2>/dev/null | grep -qE ":${port}([[:space:]]|$)"
  elif command -v lsof >/dev/null 2>&1; then
    ! lsof -nP -iTCP:"$port" -sTCP:LISTEN >/dev/null 2>&1
  elif command -v netstat >/dev/null 2>&1; then
    # BSD-flavored netstat output: "*.8000  ... LISTEN"
    ! netstat -an 2>/dev/null | grep -qE "\.${port}[[:space:]]+.*LISTEN"
  else
    return 0  # can't check — assume free
  fi
}

# Find the lowest free port >= the given starting port. Returns 1 (and
# emits nothing on stdout) if every port up to 65535 is in use.
find_free_port() {
  local port="$1"
  while [ "$port" -le 65535 ] && ! port_is_free "$port"; do
    port=$((port + 1))
  done
  [ "$port" -gt 65535 ] && return 1
  printf '%s' "$port"
}

# Compose v2 vs v1 detection — they're different binaries.
# v2 = `docker compose` subcommand of the docker CLI (current).
# v1 = `docker-compose` standalone (deprecated, was never going to
# support the `deploy.resources.reservations.devices` GPU block we
# emit). We require v2.
compose_v2_present() {
  docker compose version >/dev/null 2>&1
}

detect_nvidia_runtime() {
  # `docker info` reports registered runtimes. If "nvidia" is among
  # them, the NVIDIA Container Toolkit is installed and `--gpus all`
  # will work.
  docker info 2>/dev/null | grep -qiE '^\s*Runtimes:.*\bnvidia\b'
}

run_docker() {
  header "Checking Docker prerequisites"

  if ! command -v docker >/dev/null 2>&1; then
    warn "docker not found on PATH."
    info "Install Docker via the official path for your platform:"
    dim "    https://docs.docker.com/engine/install/"
    info "After install, ensure your user is in the docker group:"
    dim "    sudo usermod -aG docker \$USER     # then log out / back in"
    exit 1
  fi
  ok "docker $(docker --version | awk '{print $3}' | tr -d ',')"

  if ! compose_v2_present; then
    warn "docker compose v2 not detected."
    info "On most modern Docker installs, compose ships as a plugin."
    info "Install via:"
    dim "    sudo apt install docker-compose-plugin    # Debian / Ubuntu (Docker repo)"
    dim "    brew install docker-compose               # macOS"
    info "Or follow https://docs.docker.com/compose/install/."
    exit 1
  fi
  ok "docker compose $(docker compose version --short)"

  # Daemon reachability. The CLI being present doesn't mean the daemon is
  # running or that we can talk to it (stopped service, or user not in the
  # docker group). Probe explicitly — otherwise detect_nvidia_runtime's
  # `docker info` silently fails, we misreport "no GPU", and the run only
  # blows up later at `docker compose up`.
  if ! docker info >/dev/null 2>&1; then
    warn "Docker is installed but the daemon isn't reachable."
    info "Check that Docker is running and you have permission:"
    dim "    sudo systemctl start docker          # if the service is stopped"
    dim "    sudo usermod -aG docker \$USER        # then log out / back in"
    info "Then re-run this script."
    exit 1
  fi
  ok "docker daemon reachable"

  # GPU detection. If user explicitly said --no-gpu, skip. Otherwise
  # probe for the nvidia runtime; if absent and they didn't insist
  # on GPU via --gpu, ask interactively.
  local want_gpu="$GPU_PREF"
  if [ "$want_gpu" = "" ]; then
    if detect_nvidia_runtime; then
      ok "nvidia-container-toolkit detected (GPU passthrough available)"
      want_gpu="yes"
    else
      warn "nvidia-container-toolkit not detected."
      dim "    Install: https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/install-guide.html"
      dim "    Without it, the container can still run — just CPU-only."
      if ask_bool "Continue without GPU?" "y"; then
        want_gpu="no"
      else
        info "Install the toolkit, then re-run this script."
        exit 1
      fi
    fi
  elif [ "$want_gpu" = "yes" ] && ! detect_nvidia_runtime; then
    warn "--gpu passed but nvidia-container-toolkit not detected. Trying anyway."
  fi

  # ---- Provider selection ----
  header "LLM provider"

  # If any provider keys / urls were passed on the CLI, skip the picker.
  local provider_via_flags=false
  if [ -n "$OPENROUTER_KEY" ] || [ -n "$OPENAI_KEY" ] || [ -n "$LOCAL_LLM_URL" ]; then
    provider_via_flags=true
  fi

  local provider
  if [ "$provider_via_flags" = "true" ]; then
    # Pick the first non-empty key as the provider.
    if [ -n "$OPENROUTER_KEY" ]; then provider="openrouter"
    elif [ -n "$OPENAI_KEY" ];     then provider="openai"
    else                                 provider="local"
    fi
    ok "Provider via flag: $provider"
  else
    printf '    1) %sOpenRouter%s   (one key, many models — recommended)\n' "${C_BOLD}" "${C_RESET}"
    printf '    2) %sOpenAI%s\n' "${C_BOLD}" "${C_RESET}"
    printf '    3) %sLocal LLM%s    (vLLM / Ollama / llama.cpp, OpenAI-compatible /v1/* API)\n' "${C_BOLD}" "${C_RESET}"
    raw=$(ask "Choice" "1")
    case "$raw" in
      2) provider="openai" ;;
      3) provider="local" ;;
      *) provider="openrouter" ;;
    esac
  fi

  # ---- Key / URL ----
  case "$provider" in
    openrouter)
      if [ -z "$OPENROUTER_KEY" ]; then
        OPENROUTER_KEY=$(ask_hidden "Paste OPENROUTER_API_KEY (hidden, won't echo)")
      fi
      [ -z "$OPENROUTER_KEY" ] && warn "No key provided. mle-beast will fail at first run; you can edit .env later."
      ;;
    openai)
      if [ -z "$OPENAI_KEY" ]; then
        OPENAI_KEY=$(ask_hidden "Paste OPENAI_API_KEY (hidden, won't echo)")
      fi
      [ -z "$OPENAI_KEY" ] && warn "No key provided. mle-beast will fail at first run; you can edit .env later."
      ;;
    local)
      if [ -z "$LOCAL_LLM_URL" ]; then
        # Default to host.docker.internal which the compose extra_hosts
        # block makes work on Linux too.
        LOCAL_LLM_URL=$(ask "Local LLM base URL (use host.docker.internal to reach a host-running server)" "http://host.docker.internal:8001/v1")
      fi
      ;;
  esac

  # ---- Model ----
  # Skip if --model passed explicitly. Otherwise offer a provider-
  # appropriate curated list — OpenRouter slugs are `provider/model`,
  # OpenAI uses bare names, Local LLM defers to whatever the server
  # serves up. Mirrors the picker pattern from `mle-beast init`.
  if [ -z "$MODEL" ]; then
    header "Model"
    case "$provider" in
      openrouter)
        printf '    1) %sdeepseek/deepseek-v4-flash%s    cheap, fast (recommended)\n' "${C_BOLD}" "${C_RESET}"
        printf '    2) %sopenai/gpt-4o-mini%s             cheap\n' "${C_BOLD}" "${C_RESET}"
        printf '    3) %santhropic/claude-haiku-4-5%s    balanced\n' "${C_BOLD}" "${C_RESET}"
        printf '    4) %santhropic/claude-sonnet-4-6%s   premium\n' "${C_BOLD}" "${C_RESET}"
        printf '    5) %santhropic/claude-opus-4-7%s     premium-plus\n' "${C_BOLD}" "${C_RESET}"
        printf '    6) [type your own slug]\n'
        raw=$(ask "Choice" "1")
        case "$raw" in
          2) MODEL="openai/gpt-4o-mini" ;;
          3) MODEL="anthropic/claude-haiku-4-5" ;;
          4) MODEL="anthropic/claude-sonnet-4-6" ;;
          5) MODEL="anthropic/claude-opus-4-7" ;;
          6) MODEL=$(ask "Type model slug" "deepseek/deepseek-v4-flash") ;;
          *) MODEL="deepseek/deepseek-v4-flash" ;;
        esac
        ;;
      openai)
        printf '    1) %sgpt-4o-mini%s    cheap (recommended)\n' "${C_BOLD}" "${C_RESET}"
        printf '    2) %sgpt-4o%s          balanced\n' "${C_BOLD}" "${C_RESET}"
        printf '    3) %sgpt-5-mini%s      premium\n' "${C_BOLD}" "${C_RESET}"
        printf '    4) [type your own slug]\n'
        raw=$(ask "Choice" "1")
        case "$raw" in
          2) MODEL="gpt-4o" ;;
          3) MODEL="gpt-5-mini" ;;
          4) MODEL=$(ask "Type model slug" "gpt-4o-mini") ;;
          *) MODEL="gpt-4o-mini" ;;
        esac
        ;;
      local)
        # No curated list — local servers can be running anything.
        MODEL=$(ask "Model slug (whatever your local server serves)" "local-model")
        ;;
    esac
  fi
  ok "Model: $MODEL"

  # ---- Port / tag ----
  header "Dashboard host port"
  PORT=$(ask "Port" "$PORT")
  if ! port_is_free "$PORT"; then
    local suggested
    suggested=$(find_free_port "$((PORT + 1))")
    if [ "$YES" = "true" ]; then
      warn "Port ${PORT} is already in use. Auto-selecting ${suggested}."
      PORT="$suggested"
    else
      warn "Port ${PORT} is already in use."
      info "Tip: on WSL2 with mirrored networking a Windows process can hold"
      info "a port that's invisible to ss/lsof inside Linux."
      PORT=$(ask "Choose a different port" "$suggested")
      while ! port_is_free "$PORT"; do
        warn "Still in use."
        suggested=$(find_free_port "$((PORT + 1))")
        PORT=$(ask "Choose a different port" "$suggested")
      done
    fi
    ok "Dashboard will be served on port ${PORT}"
  fi
  header "Image tag"
  dim "  :edge tracks every main merge. :latest tracks tagged releases."
  TAG=$(ask "Tag" "$TAG")

  # ---- Data + workspaces directories ----
  # Host paths for the two bind mounts. Defaults put everything under
  # the user's home dir so the cwd (often the repo or a temp project
  # dir) stays uncluttered. Both prompts accept ~/ — expand_tilde
  # resolves it before the compose file is generated since YAML
  # doesn't expand $HOME.
  header "Where to store data on the host"
  dim "  The dashboard's SQLite DB + run history goes in the data dir."
  dim "  Per-run workspace dirs (model.py, checkpoints, reports) go in"
  dim "  the workspaces dir. Both default to your home for cleanliness;"
  dim "  use ./.mle-beast and ./workspaces if you want them next to the"
  dim "  compose file instead."
  if [ -z "$DATA_DIR" ]; then
    DATA_DIR=$(ask "Data dir (SQLite + settings)" "$HOME/.mle-beast")
    DATA_DIR=$(expand_tilde "$DATA_DIR")
  fi
  if [ -z "$WORKSPACES_DIR" ]; then
    WORKSPACES_DIR=$(ask "Workspaces dir (per-run artifacts)" "$HOME/mle-beast-runs")
    WORKSPACES_DIR=$(expand_tilde "$WORKSPACES_DIR")
  fi

  # ---- Write files ----
  header "Writing files to $(pwd)"
  write_env_file "$provider" "$OPENROUTER_KEY" "$OPENAI_KEY" "$LOCAL_LLM_URL" "$MODEL"
  ok ".env"
  write_compose_file "$provider" "$want_gpu" "$PORT" "$TAG" "$DATA_DIR" "$WORKSPACES_DIR"
  ok "docker-compose.yml"

  # Pre-create the bind-mount directories so the running user owns
  # them. Without this, `docker compose up` would create them at
  # mount time as root, which means the container's mlebeast user
  # (uid 1000) can't write to them — every SQLite write fails with
  # EACCES and /api/runs returns HTTP 500. Caught during local
  # smoke testing of this script.
  mkdir -p "$DATA_DIR" "$WORKSPACES_DIR"
  ok "bind-mount directories created"
  dim "    Data:        $DATA_DIR"
  dim "    Workspaces:  $WORKSPACES_DIR"

  # Ensure .gitignore covers .env if the cwd is a git repo
  if [ -d .git ] && [ ! -f .gitignore ]; then
    printf '.env\n' > .gitignore
    ok ".gitignore (created)"
  elif [ -f .gitignore ] && ! grep -qx '\.env' .gitignore 2>/dev/null; then
    printf '\n# Added by setup-mle-beast.sh\n.env\n' >> .gitignore
    ok ".gitignore (.env appended)"
  fi

  # ---- Start ----
  header "Starting container"
  if ! docker compose up -d; then
    fail "docker compose up failed. Check 'docker compose logs' for details."
  fi

  printf '\n'
  printf '%s%s✓ mle-beast is running%s\n' "${C_BOLD}" "${C_GREEN}" "${C_RESET}"
  printf '\n'
  printf '    Dashboard:  %shttp://localhost:%s%s\n' "${C_CYAN}" "${PORT}" "${C_RESET}"
  printf '    Logs:       docker compose logs -f\n'
  printf '    Stop:       docker compose down\n'
  printf '    Update:     docker compose pull && docker compose up -d\n'
  printf '\n'
}

# --------------------------------------------------------------------
# File writers — generators for the .env and docker-compose.yml
# tailored to the user's answers. Two sources of truth (this and the
# canonical compose at repo root), but the compose surface is small
# and changes are rare.
# --------------------------------------------------------------------

write_env_file() {
  local provider="$1" or_key="$2" oa_key="$3" local_url="$4" model="$5"
  {
    printf '# Generated by setup-mle-beast.sh on %s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)"
    printf '# Used by docker-compose.yml — Compose substitutes ${VAR} from this file.\n'
    printf '\n'
    printf 'MLE_BEAST_PROVIDER=%s\n' "$provider"
    printf '\n'
    # All three provider creds appear so switching later is just an edit
    # here: uncomment one and change MLE_BEAST_PROVIDER above. The active
    # provider's value is filled in; the others are commented stubs.
    if [ "$provider" = "openrouter" ]; then
      printf 'OPENROUTER_API_KEY=%s\n' "$or_key"
    else
      printf '# OPENROUTER_API_KEY=\n'
    fi
    if [ "$provider" = "openai" ]; then
      printf 'OPENAI_API_KEY=%s\n' "$oa_key"
    else
      printf '# OPENAI_API_KEY=\n'
    fi
    if [ "$provider" = "local" ]; then
      printf 'LOCAL_LLM_BASE_URL=%s\n' "$local_url"
    else
      printf '# LOCAL_LLM_BASE_URL=http://host.docker.internal:8001/v1\n'
    fi
    printf '\n'
    # Pin the model the user picked in the wizard. The compose file
    # falls back to the same default if this line is removed, so the
    # user can also blank it later without breaking anything.
    printf 'MLE_BEAST_MODEL=%s\n' "$model"
  } > .env
  chmod 600 .env 2>/dev/null || true
}

write_compose_file() {
  local provider="$1" want_gpu="$2" port="$3" tag="$4"
  local data_dir="$5" workspaces_dir="$6"
  {
    printf '# Generated by setup-mle-beast.sh on %s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)"
    printf '# Edit .env to change provider keys / model. Edit this file\n'
    printf '# directly for structural changes (ports, volumes, etc.).\n'
    printf '\n'
    printf 'services:\n'
    printf '  mle-beast:\n'
    printf '    image: %s:%s\n' "$IMAGE_REPO" "$tag"
    printf '    container_name: mle-beast\n'
    printf '    ports:\n'
    printf '      - "%s:8000"\n' "$port"
    # Read every provider var from .env (each with a :- default) so the
    # user can switch provider / keys / model later by editing .env alone —
    # Compose substitutes ${VAR}, and mle-beast ignores empty keys. Mirrors
    # the repo's canonical docker-compose.yml. MLE_BEAST_PROVIDER falls back
    # to the wizard's pick if the user deletes the line from .env.
    printf '    environment:\n'
    printf '      MLE_BEAST_PROVIDER: ${MLE_BEAST_PROVIDER:-%s}\n' "$provider"
    printf '      OPENROUTER_API_KEY: ${OPENROUTER_API_KEY:-}\n'
    printf '      OPENAI_API_KEY: ${OPENAI_API_KEY:-}\n'
    printf '      LOCAL_LLM_BASE_URL: ${LOCAL_LLM_BASE_URL:-}\n'
    printf '      MLE_BEAST_MODEL: ${MLE_BEAST_MODEL:-deepseek/deepseek-v4-flash}\n'
    # Always emit the host.docker.internal shim (a no-op unless the user
    # points LOCAL_LLM_BASE_URL at it) so switching to a local LLM via .env
    # later just works on Linux without editing this file.
    printf '    extra_hosts:\n'
    printf '      - "host.docker.internal:host-gateway"\n'
    # Use absolute paths so the bind mounts work regardless of where
    # `docker compose up/down` is invoked from. (Compose's relative
    # paths resolve against the compose file's dir, which is fine —
    # but writing absolute here lets the user `mv` the compose file
    # without breaking the mounts.)
    # Quote the whole bind spec so host paths with spaces / : / # don't
    # produce invalid or misparsed YAML.
    printf '    volumes:\n'
    printf '      - "%s:/home/mlebeast/.mle-beast"\n' "$data_dir"
    printf '      - "%s:/workspaces"\n' "$workspaces_dir"
    if [ "$want_gpu" = "yes" ]; then
      printf '    deploy:\n'
      printf '      resources:\n'
      printf '        reservations:\n'
      printf '          devices:\n'
      printf '            - driver: nvidia\n'
      printf '              count: all\n'
      printf '              capabilities: [gpu]\n'
    fi
  } > docker-compose.yml
}

# --------------------------------------------------------------------
# Dispatch
# --------------------------------------------------------------------

case "$PATH_CHOICE" in
  docker) run_docker ;;
  native) run_native ;;
  *)      fail "Unknown path: $PATH_CHOICE" ;;
esac
