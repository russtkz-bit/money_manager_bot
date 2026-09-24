#!/usr/bin/env bash
#
# configure_env.sh — writes the bot's .env without hand-editing a file or
# leaving secrets in your shell history.
#
# - Telegram token: prompted with input hidden (like a password prompt);
#   never pass it as a bare command-line argument — that lands in shell
#   history and is visible to anyone on the box via `ps aux`.
# - DATABASE_URL: auto-picked up from the credentials file
#   deploy/setup_postgres.sh writes, if present — no copy/paste needed.
#   Falls back to a hidden prompt otherwise.
# - Writes .env with chmod 600 (only the owner can read it) and refuses to
#   silently clobber an existing one.
#
# Usage:
#   ./deploy/configure_env.sh
#
# Non-interactive (e.g. from another script): set TELEGRAM_BOT_TOKEN and/or
# DATABASE_URL as environment variables before calling — whichever one(s)
# are already set won't be prompted for.

set -euo pipefail

cd "$(dirname "${BASH_SOURCE[0]}")/.."   # repo root, regardless of caller's cwd

ENV_FILE=".env"
CREDS_FILE="${CREDS_FILE:-/root/money_manager_db_credentials.txt}"

if [[ -f "$ENV_FILE" ]]; then
  read -rp "${ENV_FILE} already exists — overwrite? [y/N] " ans
  [[ "$ans" =~ ^[Yy]$ ]] || { echo "Aborted — left ${ENV_FILE} untouched."; exit 1; }
fi

if [[ -n "${TELEGRAM_BOT_TOKEN:-}" ]]; then
  TOKEN="$TELEGRAM_BOT_TOKEN"
else
  read -rsp "Telegram bot token (from @BotFather, input hidden): " TOKEN
  echo
fi
[[ -n "$TOKEN" ]] || { echo "No token given, aborting." >&2; exit 1; }

CREDS_FOUND=0
if [[ -n "${DATABASE_URL:-}" ]]; then
  DB_URL="$DATABASE_URL"
else
  # setup_postgres.sh writes this chmod 600 as root, and this script is
  # normally run as the bot's own (non-root) user — a plain `[[ -f ]]` can't
  # even see into /root in that case (silently reads as "not found", not an
  # error), so try a direct read first and fall back to sudo before giving
  # up and asking interactively. sudo's own password prompt goes straight
  # to the terminal, so this stays interactive-safe.
  CREDS_CONTENT="$( { cat "$CREDS_FILE" 2>/dev/null || sudo cat "$CREDS_FILE" 2>/dev/null; } || true )"
  DB_URL="$(grep -m1 '^DATABASE_URL=' <<<"$CREDS_CONTENT" | cut -d= -f2-)" || true
  if [[ -n "$DB_URL" ]]; then
    CREDS_FOUND=1
    echo "==> Using DATABASE_URL from ${CREDS_FILE} (written by setup_postgres.sh)."
  else
    read -rsp "DATABASE_URL (postgresql://user:pass@host:5432/db, input hidden): " DB_URL
    echo
  fi
fi
[[ -n "$DB_URL" ]] || { echo "No DATABASE_URL given, aborting." >&2; exit 1; }

umask 077
{
  echo "TELEGRAM_BOT_TOKEN=${TOKEN}"
  echo "DATABASE_URL=${DB_URL}"
} > "$ENV_FILE"
chmod 600 "$ENV_FILE"

echo "==> Wrote ${ENV_FILE} (chmod 600 — only $(whoami) can read it)."
if [[ "$CREDS_FOUND" == "1" ]]; then
  echo "==> The token/password are now in ${ENV_FILE}. You can remove the"
  echo "    standalone credentials file: sudo rm ${CREDS_FILE}"
fi
