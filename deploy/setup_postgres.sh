#!/usr/bin/env bash
#
# setup_postgres.sh — installs and hardens a local PostgreSQL instance for
# the Money Manager Bot on Ubuntu Server.
#
# What it does:
#   1. Installs PostgreSQL from the Ubuntu repos (if not already present).
#   2. Creates a dedicated, non-superuser role + database for the bot
#      (never uses the `postgres` superuser role for the app).
#   3. Forces password auth to scram-sha-256 (not md5/trust).
#   4. Binds PostgreSQL to localhost only — it is never reachable from the
#      network, only from processes on this same machine.
#   5. Adds a pg_hba.conf rule scoped to exactly this role + database over
#      the loopback interface.
#   6. Verifies the new role can actually connect before finishing.
#
# What it deliberately does NOT do:
#   - It does not open any firewall port. Since PostgreSQL only listens on
#     localhost, there is nothing to open. If you later need the bot to
#     connect from a *different* machine, see deploy/POSTGRES_SETUP.md —
#     do not just widen listen_addresses/pg_hba without reading that first.
#   - It does not touch unrelated pg_hba.conf entries (e.g. the default
#     `peer` auth for the `postgres` OS role), so local admin access via
#     `sudo -u postgres psql` keeps working.
#
# Usage:
#   sudo DB_PASSWORD='...' ./setup_postgres.sh     # use your own password
#   sudo ./setup_postgres.sh                       # auto-generate one
#
# Re-running is safe: role/database creation and the pg_hba rule are
# idempotent (existing role just gets its password reset to $DB_PASSWORD).

set -euo pipefail

DB_NAME="${DB_NAME:-money_manager}"
DB_USER="${DB_USER:-money_manager_bot}"
DB_PASSWORD="${DB_PASSWORD:-}"
CREDS_FILE="${CREDS_FILE:-/root/money_manager_db_credentials.txt}"

if [[ $EUID -ne 0 ]]; then
  echo "Please run as root: sudo $0" >&2
  exit 1
fi

if [[ -z "$DB_PASSWORD" ]]; then
  if command -v openssl >/dev/null 2>&1; then
    DB_PASSWORD="$(openssl rand -base64 32 | tr -d '\n')"
  else
    DB_PASSWORD="$(tr -dc 'A-Za-z0-9' </dev/urandom | head -c 40)"
  fi
  echo "==> Generated a random password for role '${DB_USER}'."
fi

echo "==> Installing PostgreSQL (skipped if already installed)…"
if ! command -v psql >/dev/null 2>&1; then
  apt-get update -y
  apt-get install -y postgresql postgresql-contrib
fi

systemctl enable --now postgresql

PG_CONF="$(find /etc/postgresql -maxdepth 3 -name postgresql.conf | sort -V | tail -n1)"
PG_HBA="$(find /etc/postgresql -maxdepth 3 -name pg_hba.conf   | sort -V | tail -n1)"

if [[ -z "$PG_CONF" || -z "$PG_HBA" ]]; then
  echo "Could not locate postgresql.conf / pg_hba.conf under /etc/postgresql." >&2
  exit 1
fi
echo "==> Using config: $PG_CONF"
echo "==> Using config: $PG_HBA"

TIMESTAMP="$(date +%Y%m%d%H%M%S)"
cp "$PG_CONF" "${PG_CONF}.bak.${TIMESTAMP}"
cp "$PG_HBA"  "${PG_HBA}.bak.${TIMESTAMP}"
echo "==> Backed up existing configs (*.bak.${TIMESTAMP})"

echo "==> Creating role and database (idempotent)…"
# Deliberately avoids DO $$ ... $$ blocks: psql's :'var'/:"var" interpolation
# is only reliable in plain top-level statements, not inside dollar-quoted
# PL/pgSQL bodies — so role creation uses the same \gexec idiom as the
# database creation below, and the password is (re-)set with a plain,
# unconditional ALTER ROLE.
sudo -u postgres psql -v ON_ERROR_STOP=1 -v db_user="$DB_USER" -v db_pass="$DB_PASSWORD" -v db_name="$DB_NAME" <<'SQL'
SELECT format('CREATE ROLE %I LOGIN PASSWORD %L', :'db_user', :'db_pass')
WHERE NOT EXISTS (SELECT FROM pg_roles WHERE rolname = :'db_user')
\gexec

ALTER ROLE :"db_user" WITH LOGIN PASSWORD :'db_pass';

SELECT format('CREATE DATABASE %I OWNER %I', :'db_name', :'db_user')
WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname = :'db_name')
\gexec

REVOKE ALL ON DATABASE :"db_name" FROM PUBLIC;
SQL

echo "==> Forcing scram-sha-256 password encryption…"
if grep -q '^password_encryption' "$PG_CONF"; then
  sed -i "s/^password_encryption.*/password_encryption = scram-sha-256/" "$PG_CONF"
else
  echo "password_encryption = scram-sha-256" >> "$PG_CONF"
fi

echo "==> Restricting listen_addresses to localhost…"
if grep -qE '^#?listen_addresses' "$PG_CONF"; then
  sed -i "s/^#\?listen_addresses.*/listen_addresses = 'localhost'/" "$PG_CONF"
else
  echo "listen_addresses = 'localhost'" >> "$PG_CONF"
fi

RULE_V4="host    ${DB_NAME}    ${DB_USER}    127.0.0.1/32    scram-sha-256"
RULE_V6="host    ${DB_NAME}    ${DB_USER}    ::1/128         scram-sha-256"

if grep -qF "$DB_USER" "$PG_HBA" && grep -qF "$DB_NAME" "$PG_HBA"; then
  echo "==> pg_hba.conf already has a rule mentioning this role/database — leaving it as-is."
  echo "    (delete the old rule manually if you changed DB_USER/DB_NAME and re-ran this script)"
else
  echo "==> Adding a scoped pg_hba.conf rule for ${DB_USER}/${DB_NAME} over loopback only…"
  awk -v r1="$RULE_V4" -v r2="$RULE_V6" '
    !done && ($0 ~ /^(local|host)/) { print r1; print r2; done=1 }
    { print }
    END { if (!done) { print r1; print r2 } }
  ' "$PG_HBA" > "${PG_HBA}.new"
  mv "${PG_HBA}.new" "$PG_HBA"
fi

echo "==> Restarting PostgreSQL…"
systemctl restart postgresql
sleep 2

echo "==> Verifying the new role can connect over TCP (127.0.0.1)…"
if PGPASSWORD="$DB_PASSWORD" psql -h 127.0.0.1 -U "$DB_USER" -d "$DB_NAME" -c 'SELECT 1;' >/dev/null; then
  echo "==> Connection OK."
else
  echo "!! Could not connect with the new role. Restoring backed-up configs and exiting." >&2
  cp "${PG_CONF}.bak.${TIMESTAMP}" "$PG_CONF"
  cp "${PG_HBA}.bak.${TIMESTAMP}"  "$PG_HBA"
  systemctl restart postgresql
  exit 1
fi

DATABASE_URL="postgresql://${DB_USER}:${DB_PASSWORD}@localhost:5432/${DB_NAME}"

umask 077
{
  echo "# Generated by setup_postgres.sh on $(date -Is)"
  echo "# Copy DATABASE_URL into the bot's .env, then delete this file."
  echo "DATABASE_URL=${DATABASE_URL}"
} > "$CREDS_FILE"
chmod 600 "$CREDS_FILE"

cat <<EOF

============================================================
 PostgreSQL is set up and listening on localhost only.

 Role:      ${DB_USER}   (not a superuser, owns only its own DB)
 Database:  ${DB_NAME}
 Password:  saved to ${CREDS_FILE} (chmod 600)

 Next steps:
   1. cat ${CREDS_FILE}
   2. Paste the DATABASE_URL line into money_manager_bot/.env
   3. rm ${CREDS_FILE}
   4. python bot.py   (it will create/migrate its schema automatically)

 See deploy/POSTGRES_SETUP.md for backups, password rotation, and what
 to change if the bot ever needs to connect from a different machine.
============================================================
EOF
