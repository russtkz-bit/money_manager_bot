#!/usr/bin/env bash
#
# setup_cloudflare_tunnel.sh — installs cloudflared so the web dashboard
# can be reached from the internet without opening any port on your router
# or owning a domain.
#
# NOTE ON TESTING: unlike the other scripts in deploy/, the actual tunnel
# creation step is an interactive Cloudflare login (a browser flow) that
# cannot be scripted or verified from an automated session. Read
# deploy/WEBAPP_SETUP.md for what to expect at each step and verify the
# tunnel yourself before relying on it.
#
# This script only installs the `cloudflared` package. It does NOT create
# a tunnel for you — that's an interactive step, see deploy/WEBAPP_SETUP.md
# for both the zero-config "quick tunnel" (no Cloudflare account needed,
# URL changes on restart) and the "named tunnel" (stable URL, needs a free
# Cloudflare account + a domain you control) paths.
#
# Installs the official .deb directly from Cloudflare's GitHub releases,
# rather than adding pkg.cloudflare.com as an apt source. Cloudflare's apt
# repo only publishes packages for a fixed list of Debian/Ubuntu codenames
# — a codename it hasn't added yet (common right after a new Ubuntu
# release) makes `apt-get update` fail with "repository ... does not have
# a Release file", even though cloudflared itself (a single static Go
# binary, no OS-version-specific dependencies) works identically on any
# reasonably recent Debian/Ubuntu. The direct .deb sidesteps that
# entirely, regardless of how new or old your release's codename is.
#
# Usage:
#   sudo ./deploy/setup_cloudflare_tunnel.sh

set -euo pipefail

if [[ $EUID -ne 0 ]]; then
  echo "Please run as root: sudo $0" >&2
  exit 1
fi

if command -v cloudflared >/dev/null 2>&1; then
  echo "==> cloudflared already installed ($(cloudflared --version))."
  exit 0
fi

ARCH="$(dpkg --print-architecture)"
case "$ARCH" in
  amd64|arm64) ;;
  *)
    echo "Unsupported architecture: ${ARCH}" >&2
    echo "cloudflared publishes .deb packages for amd64/arm64 only — see" >&2
    echo "https://github.com/cloudflare/cloudflared/releases for other options." >&2
    exit 1
    ;;
esac

echo "==> Downloading cloudflared (.deb, ${ARCH}) from Cloudflare's GitHub releases…"
TMP_DEB="$(mktemp --suffix=.deb)"
trap 'rm -f "$TMP_DEB"' EXIT
curl -fsSL -o "$TMP_DEB" \
  "https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-${ARCH}.deb"

echo "==> Installing…"
dpkg -i "$TMP_DEB" || apt-get install -f -y   # pulls in any missing deps, then retries the .deb

echo
echo "============================================================"
echo " cloudflared installed: $(cloudflared --version)"
echo
echo " Next: create a tunnel — this is an interactive step, see"
echo " deploy/WEBAPP_SETUP.md for the quick-tunnel (no account needed)"
echo " and named-tunnel (stable URL, needs a domain) instructions."
echo "============================================================"
