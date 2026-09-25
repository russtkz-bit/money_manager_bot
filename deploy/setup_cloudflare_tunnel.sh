#!/usr/bin/env bash
#
# setup_cloudflare_tunnel.sh — installs cloudflared so the web dashboard
# can be reached from the internet without opening any port on your router
# or owning a domain.
#
# NOTE ON TESTING: unlike the other scripts in deploy/, the actual tunnel
# creation step is an interactive Cloudflare login (a browser flow) that
# cannot be scripted or verified from an automated session — only the
# package install below was written to Cloudflare's own documented method,
# not exercised end-to-end. Read deploy/WEBAPP_SETUP.md for what to expect
# at each step and verify the tunnel yourself before relying on it.
#
# This script only installs the `cloudflared` package (standard apt-repo
# method, the same shape as setup_postgres.sh's own package install). It
# does NOT create a tunnel for you — that's an interactive step, see
# deploy/WEBAPP_SETUP.md for both the zero-config "quick tunnel" (no
# Cloudflare account needed, URL changes on restart) and the "named
# tunnel" (stable URL, needs a free Cloudflare account + a domain you
# control) paths.
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

echo "==> Installing cloudflared from Cloudflare's official apt repo…"
mkdir -p --mode=0755 /usr/share/keyrings
curl -fsSL https://pkg.cloudflare.com/cloudflare-main.gpg -o /usr/share/keyrings/cloudflare-main.gpg

CODENAME="$(lsb_release -cs 2>/dev/null || echo noble)"
echo "deb [signed-by=/usr/share/keyrings/cloudflare-main.gpg] https://pkg.cloudflare.com/cloudflared ${CODENAME} main" \
  > /etc/apt/sources.list.d/cloudflared.list

apt-get update -y
apt-get install -y cloudflared

echo
echo "============================================================"
echo " cloudflared installed: $(cloudflared --version)"
echo
echo " Next: create a tunnel — this is an interactive step, see"
echo " deploy/WEBAPP_SETUP.md for the quick-tunnel (no account needed)"
echo " and named-tunnel (stable URL, needs a domain) instructions."
echo "============================================================"
