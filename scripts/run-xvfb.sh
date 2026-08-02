#!/usr/bin/env bash
# Wrap any command so Chrome runs headed against a virtual display.
# Reddit often blocks true headless on datacenter proxies; xvfb looks headed.
set -euo pipefail

if [[ "$(uname -s)" != "Linux" ]]; then
  echo "run-xvfb.sh is for Linux VMs; running command directly on $(uname -s)" >&2
  exec "$@"
fi

if [[ -n "${DISPLAY:-}" && "${FORCE_XVFB:-}" != "1" ]]; then
  # Already have a display (desktop / existing Xvfb)
  exec "$@"
fi

if ! command -v xvfb-run >/dev/null 2>&1; then
  echo "xvfb-run not found. Install: sudo apt-get install -y xvfb" >&2
  echo "Or run: bash scripts/vm-setup.sh" >&2
  exit 1
fi

export REDDIT_BROWSER_HEADED="${REDDIT_BROWSER_HEADED:-true}"
export REDDIT_CONTENT_HEADED="${REDDIT_CONTENT_HEADED:-true}"
export REDDIT_POST_HEADED="${REDDIT_POST_HEADED:-true}"
export REDDIT_REFRESH_HEADED="${REDDIT_REFRESH_HEADED:-true}"
export REDDIT_DISCOVER_HEADED="${REDDIT_DISCOVER_HEADED:-true}"

exec xvfb-run -a --server-args="-screen 0 1280x900x24 -ac +extension GLX +render -noreset" "$@"
