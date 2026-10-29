#!/bin/sh
# jobslop – installation for macOS and Linux
#   curl -fsSL https://raw.githubusercontent.com/1xxn/jobslop/main/install.sh | sh
# Installs uv if needed, offers Claude Code, installs the `jobslop` command and its browser, then starts jobslop.
set -eu

REPO="${JOBSLOP_REPO:-git+https://github.com/1xxn/jobslop}"
# uv as a fixed release whose installer is checked against its SHA-256 before it runs (from the GitHub release page
# of astral-sh/uv) – not whatever a mutable URL serves at that moment. Bump both together.
UV_VERSION="0.13.6"
UV_INSTALLER_SHA256="f7a56e7afaec49a3bcbc3ac3cdbe917e7c6ce30e0d815308a12e531aa5ef23b7"
step() { printf '\n\033[36m==> %s\033[0m\n' "$1"; }
export PATH="$HOME/.local/bin:$PATH"

printf '\033[35mjobslop – local job application autopilot\033[0m\n'

step "uv (Python package manager)"
if command -v uv >/dev/null 2>&1; then
  echo "uv is already installed."
else
  tmp="$(mktemp -d)"
  curl -LsSf -o "$tmp/uv-installer.sh" "https://github.com/astral-sh/uv/releases/download/$UV_VERSION/uv-installer.sh"
  if command -v sha256sum >/dev/null 2>&1; then
    echo "$UV_INSTALLER_SHA256  $tmp/uv-installer.sh" | sha256sum -c - >/dev/null
  else
    echo "$UV_INSTALLER_SHA256  $tmp/uv-installer.sh" | shasum -a 256 -c - >/dev/null
  fi
  sh "$tmp/uv-installer.sh"
  rm -rf "$tmp"
fi

step "Claude Code (your Claude subscription)"
if command -v claude >/dev/null 2>&1; then
  echo "Claude Code is already installed."
else
  printf 'Install Claude Code now? Without it only a simple rule mode works. [Y/n] '
  answer=""
  if [ -r /dev/tty ]; then read -r answer < /dev/tty || answer=""; fi
  case "$answer" in
    n|N) echo "Skipped – you can install it later from the setup wizard." ;;
    # Anthropic's official installer (no versioned URL; it verifies the Claude Code binary itself)
    *) curl -fsSL https://claude.ai/install.sh | bash ;;
  esac
fi

step "Installing jobslop"
uv tool install --force "$REPO"
uv tool update-shell >/dev/null 2>&1 || true

step "Browser (Chromium) for the forms"
jobslop install-browser
if [ "$(uname -s)" = "Linux" ]; then
  echo "On a minimal Linux you may also need system libraries: sudo \"\$(uv tool dir)/jobslop/bin/python\" -m playwright install-deps chromium"
fi

step "Done – starting jobslop"
echo "Next time just run: jobslop"
exec jobslop
