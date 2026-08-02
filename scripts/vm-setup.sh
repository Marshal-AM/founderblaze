#!/usr/bin/env bash
# Prepare an Ubuntu/Debian VPS for FounderForge Reddit Chrome (social-listening).
# Installs: Node (if missing), Google Chrome, xvfb, Playwright deps.
set -euo pipefail

if [[ "$(id -u)" -eq 0 ]]; then
  SUDO=""
else
  SUDO="sudo"
fi

echo "==> Updating apt"
$SUDO apt-get update -y

echo "==> Installing Chrome runtime deps + xvfb"
$SUDO apt-get install -y \
  ca-certificates \
  curl \
  gnupg \
  xvfb \
  fonts-liberation \
  libasound2t64 || true
$SUDO apt-get install -y \
  fonts-liberation \
  libatk-bridge2.0-0 \
  libatk1.0-0 \
  libcups2 \
  libdbus-1-3 \
  libdrm2 \
  libgbm1 \
  libgtk-3-0 \
  libnspr4 \
  libnss3 \
  libx11-xcb1 \
  libxcomposite1 \
  libxdamage1 \
  libxrandr2 \
  xdg-utils \
  xvfb

if ! command -v google-chrome >/dev/null 2>&1 && ! command -v google-chrome-stable >/dev/null 2>&1; then
  echo "==> Installing Google Chrome"
  tmp="$(mktemp)"
  curl -fsSL https://dl.google.com/linux/direct/google-chrome-stable_current_amd64.deb -o "$tmp"
  $SUDO apt-get install -y "$tmp" || $SUDO dpkg -i "$tmp" || true
  $SUDO apt-get install -f -y
  rm -f "$tmp"
fi

if ! command -v node >/dev/null 2>&1; then
  echo "==> Installing Node.js 22"
  curl -fsSL https://deb.nodesource.com/setup_22.x | $SUDO -E bash -
  $SUDO apt-get install -y nodejs
fi

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

echo "==> pnpm install (workspace)"
if command -v pnpm >/dev/null 2>&1; then
  pnpm install
else
  corepack enable && pnpm install
fi

echo "==> Playwright Chromium (fallback browser)"
cd "$ROOT/services/social-listening-service"
pnpm exec playwright install chromium
pnpm exec playwright install-deps chromium || true

mkdir -p "$ROOT/.reddit-profile" "$ROOT/scripts"

cat <<EOF

VM setup complete for FounderForge social-listening.

Next:
  1) Fill FounderForge/.env (REDDAPI_PROXY, GROQ keys, REDDIT_BROWSER_HEADED=true)
  2) One-time login (desktop/VNC) or copy .reddit-profile/ + cookies onto this host
  3) Smoke headed+proxy:
       bash scripts/run-xvfb.sh pnpm --filter @founderforge/social-listening-service reddit:vm-smoke
  4) Comment smoke (no ReddAPI):
       bash scripts/run-xvfb.sh pnpm --filter @founderforge/social-listening-service reddit:comment-smoke

Persist .reddit-profile/ on a volume across reboots. Keep the same REDDAPI_PROXY.

EOF
