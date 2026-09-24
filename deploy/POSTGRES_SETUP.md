# PostgreSQL on your own Ubuntu Server — setup & security notes

This sets up PostgreSQL for the bot **on the same machine** the bot runs on,
locked down to localhost-only access. That's the right default for a
personal bot: nothing about PostgreSQL is reachable from the network at all,
so there's no port to attack, brute-force, or leave misconfigured.

If you need the bot and the database on *different* machines, read
[When you actually need remote access](#when-you-actually-need-remote-access)
before changing anything — don't just widen `listen_addresses`.

## What `setup_postgres.sh` does

Run it once, as root, on the Ubuntu Server that will host the database:

```bash
sudo ./deploy/setup_postgres.sh
# or, to pick your own password instead of a generated one:
sudo DB_PASSWORD='your-strong-password' ./deploy/setup_postgres.sh
```

It:

1. Installs PostgreSQL from the Ubuntu repos if it isn't already present.
2. Creates a **dedicated, non-superuser role** (`money_manager_bot` by
   default) that owns exactly one database (`money_manager`). The bot never
   connects as the `postgres` superuser — if its credentials ever leak, the
   blast radius is "can read/write its own tables," not "can do anything to
   the whole cluster."
3. Forces `password_encryption = scram-sha-256` — SCRAM is the modern,
   salted-challenge auth method; avoid `md5` (weak hashing) and never use
   `trust` (no password at all) for anything but a throwaway local dev box.
4. Sets `listen_addresses = 'localhost'` — PostgreSQL binds only to the
   loopback interface. There is nothing listening on your LAN or the
   internet, so there's no firewall rule you could forget to add.
5. Adds one `pg_hba.conf` rule scoped to exactly `money_manager_bot` +
   `money_manager` over `127.0.0.1`/`::1`, ahead of the generic rules — it
   doesn't touch the default `peer` auth used by `sudo -u postgres psql`,
   so your own admin access keeps working.
6. Verifies the new role can actually log in over TCP before finishing; if
   not, it rolls the config files back automatically.
7. Prints (and saves to a `chmod 600` file) the resulting connection string.

At the end, run `./deploy/configure_env.sh` — it picks up the printed
`DATABASE_URL` straight from the credentials file this script wrote
(`/root/money_manager_db_credentials.txt` by default), asks only for the
Telegram token, and writes a `chmod 600` `.env`. It also tells you when it's
safe to delete the standalone credentials file — once the value is in
`.env`, there's no reason for a second copy to exist on disk.

Re-running the script is safe: it won't create duplicate roles/databases,
and re-running with a new `DB_PASSWORD` rotates the password (see below).

## Why these specific choices

| Choice | Why |
|---|---|
| Dedicated role, not `postgres` superuser | Limits what a leaked credential can do to just this one database |
| `scram-sha-256`, not `md5`/`trust` | SCRAM resists offline cracking of a captured hash far better than md5; `trust` skips authentication entirely |
| `listen_addresses = 'localhost'` | The strongest possible network control: there's no listener to reach from outside this machine, full stop |
| Narrow `pg_hba.conf` rule, not `0.0.0.0/0` | Even on localhost, scoping the rule to the exact db/user/address is defense in depth and makes the intent explicit for the next person reading the file |
| Config backed up before editing | `sed`/`awk` mistakes are common; the script keeps a `*.bak.<timestamp>` copy of every file it touches |

## Rotating the password

```bash
sudo DB_PASSWORD='new-strong-password' ./deploy/setup_postgres.sh
```

This resets the existing role's password without touching your data, then
update `.env` on the bot with the new `DATABASE_URL`.

## Backups

```bash
sudo ./deploy/backup_postgres.sh
```

Writes a gzip'd `pg_dump` to `/var/backups/money_manager_bot/`
(`chmod 700` directory, `chmod 600` files) and deletes anything older than
14 days (`KEEP_DAYS` env var to change that).

To back up automatically, add a cron job as root:

```bash
sudo crontab -e
# daily at 03:15
15 3 * * * /path/to/money_manager_bot/deploy/backup_postgres.sh >> /var/log/money_manager_backup.log 2>&1
```

Restore:

```bash
gunzip -c /var/backups/money_manager_bot/money_manager_<timestamp>.sql.gz \
  | sudo -u postgres psql -d money_manager
```

Consider also copying backups off the machine periodically (another disk,
another host, or object storage) — a local-only backup doesn't help if the
disk itself fails.

## Keeping PostgreSQL patched

Ubuntu ships PostgreSQL security fixes through the normal `apt` channel:

```bash
sudo apt update && sudo apt upgrade postgresql postgresql-client
```

Consider enabling `unattended-upgrades` for security updates in general if
this server isn't otherwise centrally managed.

## When you actually need remote access

If the bot ever runs on a **different** machine than PostgreSQL, do **not**
just set `listen_addresses = '*'` and open port 5432 to the world. In order
of preference:

1. **SSH tunnel** — simplest for a single bot host: `ssh -L 5432:localhost:5432 user@db-host`
   and point the bot at `localhost:5432` locally. No PostgreSQL config
   changes needed at all.
2. **WireGuard/VPN between the two hosts**, then allow the database to
   listen on the VPN interface's IP only (not `0.0.0.0`), with a `pg_hba.conf`
   rule scoped to the VPN's subnet and `scram-sha-256` — never `trust`.
3. **Direct TCP exposure** — only if 1 and 2 are truly not options. Then,
   at minimum: `sslmode=require` (or `verify-full` with a real cert) in the
   connection string, a `pg_hba.conf` rule scoped to the specific source
   IP/CIDR (never `0.0.0.0/0`), and a firewall (`ufw allow from <ip> to any
   port 5432`) that denies everyone else by default.

In every case, keep the dedicated non-superuser role and `scram-sha-256` —
those don't change just because the network path does.
