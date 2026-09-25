# Web dashboard setup

The web dashboard (`webapp.py`) is a separate process from the bot — same
database, same `finance.py`/`database.py` logic, but its own systemd
service and its own way of reaching the internet. This doc covers: running
it, exposing it publicly without a domain or port-forwarding (Cloudflare
Tunnel), and the systemd services for both.

Everything here was verified locally (FastAPI TestClient + a real uvicorn
server) **except cloudflared itself** — installing the package and
creating a tunnel both need outbound internet access this session
doesn't have, so neither step was exercised end-to-end. The install
script follows Cloudflare's own documented method and the doc below
matches their current instructions, but verify both steps yourself the
first time you run them.

## 1. Install dependencies

```bash
git pull
venv/bin/pip install -r requirements.txt   # adds fastapi, uvicorn, jinja2, itsdangerous, python-multipart
```

## 2. Configure secrets

```bash
./deploy/configure_env.sh
```

Re-running this is safe — it keeps your existing `TELEGRAM_BOT_TOKEN` and
`DATABASE_URL` untouched and just adds a freshly generated
`SESSION_SECRET` (signs the login cookie) if one isn't already in `.env`.

`WEB_BASE_URL` is optional and only needed for a **named tunnel**
(Option B in step 4) — a quick tunnel's URL is auto-detected by
`/webcode` every time, so nothing to set there:

```bash
WEB_BASE_URL='https://money.yourdomain.com' ./deploy/configure_env.sh
```

## 3. Run it locally first

```bash
venv/bin/uvicorn webapp:app --host 127.0.0.1 --port 8000
```

Visit `http://<server-ip>:8000/login` from a browser on the same network,
send `/webcode` to the bot in Telegram, and enter the code. Confirm the
dashboard loads before moving on to public access.

## 4. Public access: Cloudflare Tunnel

You asked for the dashboard to be reachable from your phone anywhere. A
home server almost never has a stable public IP you can port-forward to
(many ISPs use CGNAT, which makes that impossible regardless), so this
uses Cloudflare Tunnel instead: it makes an outbound-only connection from
your server to Cloudflare, no inbound port ever opens on your router.

```bash
sudo ./deploy/setup_cloudflare_tunnel.sh
```

installs the `cloudflared` package. From there, pick one:

### Option A — Quick tunnel (no Cloudflare account, no domain)

Fastest way to get a public URL right now:

```bash
cloudflared tunnel --url http://localhost:8000
```

This prints a `https://<random-words>.trycloudflare.com` URL in its
output — that's your dashboard, reachable from anywhere immediately. The
tradeoff: **the URL changes every time this restarts.** You don't need to
track it by hand though — `/webcode` asks cloudflared's local metrics API
for whatever the current URL is and includes a fresh link every time, so
this is fine to rely on long-term too, not just for trying things out.

To run it as a background service:

```ini
# /etc/systemd/system/money-tunnel.service
[Unit]
Description=Cloudflare Quick Tunnel for Money Manager dashboard
After=network.target money-webapp.service

[Service]
Type=simple
ExecStart=/usr/bin/cloudflared tunnel --url http://localhost:8000 --metrics 127.0.0.1:20241
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

`--metrics 127.0.0.1:20241` is what makes the auto-detected link in
`/webcode` work — it's how the bot (running as `money-webapp`/`money-bot`
on the same machine) asks cloudflared for the current URL. If you ever
change that port, set `CLOUDFLARED_METRICS_PORT` to match in `.env`.

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now money-tunnel
# sanity check — same thing /webcode does internally:
curl -s http://127.0.0.1:20241/quicktunnel
```

### Option B — Named tunnel (stable URL, needs a domain you control)

If you own a domain (any registrar) and add it to Cloudflare (free plan is
enough), you get a URL that never changes:

```bash
cloudflared tunnel login          # opens a browser, pick your domain's zone
cloudflared tunnel create money-manager
cloudflared tunnel route dns money-manager money.yourdomain.com
```

Then create `/etc/cloudflared/config.yml`:

```yaml
tunnel: money-manager
credentials-file: /root/.cloudflared/<tunnel-id>.json

ingress:
  - hostname: money.yourdomain.com
    service: http://localhost:8000
  - service: http_status:404
```

```ini
# /etc/systemd/system/money-tunnel.service
[Unit]
Description=Cloudflare Named Tunnel for Money Manager dashboard
After=network.target money-webapp.service

[Service]
Type=simple
ExecStart=/usr/bin/cloudflared tunnel run money-manager
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now money-tunnel
```

Your dashboard is now permanently at `https://money.yourdomain.com`. Set
that as `WEB_BASE_URL` (step 2) and re-run `configure_env.sh`.

## 5. Run the web app as a service

```ini
# /etc/systemd/system/money-webapp.service
[Unit]
Description=Money Manager Web Dashboard
After=network.target postgresql.service

[Service]
Type=simple
User=your_user
WorkingDirectory=/path/to/money_manager_bot
EnvironmentFile=/path/to/money_manager_bot/.env
ExecStart=/path/to/money_manager_bot/venv/bin/uvicorn webapp:app --host 127.0.0.1 --port 8000
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
```

Replace `your_user` and `/path/to/money_manager_bot` the same way you did
for `money-bot.service` in the main README — `whoami && pwd` in the
project directory gives you both.

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now money-webapp
sudo systemctl status money-webapp
```

Note `--host 127.0.0.1`: the web app only listens on localhost. The
tunnel (step 4) is what makes it reachable publicly — the app itself is
never directly exposed to the network, so there's no port to firewall.

## 6. Connect Claude (MCP connector, optional)

Same process, same tunnel as the dashboard above — nothing extra to
deploy. `webapp.py` mounts a read-only [MCP](https://modelcontextprotocol.io)
server at `/mcp`: net worth, transactions, budgets, goals, recurring
spend, forecast — Claude can answer questions about your finances, but
none of these tools can add, edit, or delete anything.

In Telegram, send `/mcptoken` to the bot. It replies with a token, the
`/mcp` URL, and the exact command to register it — for Claude Code:

```bash
claude mcp add --transport http money-manager https://your-tunnel-url/mcp \
  --header "Authorization: Bearer <token>"
```

Claude Desktop's custom connector config takes the same URL + header. The
token is permanent (unlike `/webcode`'s 10-minute code) since you configure
it once — send `/mcptoken` again any time to see it, or tap "Regenerate"
if it ever leaks, which immediately invalidates the old one.

## Security notes

- The session cookie is `Secure` (HTTPS-only) by default, which matches
  Cloudflare Tunnel's automatic TLS. If you ever test over plain
  `http://localhost` directly, set `SESSION_HTTPS_ONLY=false` for that
  run only — never in the production `.env`.
- Login has no password: a `/webcode` code from the bot is the only way
  in, single-use, expires in 10 minutes. Nothing else (email, username)
  can authenticate.
- If `SESSION_SECRET` ever leaks, rotate it — this immediately invalidates
  every existing session (everyone gets logged out and needs a fresh
  `/webcode`):
  ```bash
  SESSION_SECRET="$(python3 -c 'import secrets; print(secrets.token_hex(32))')" ./deploy/configure_env.sh
  ```
- This version of the dashboard is read-only — there is nothing on it
  that adds, edits, or deletes data, so a leaked session can expose your
  data but can't corrupt it.
- The MCP connector (`/mcp`) is read-only for the same reason, and its
  token is checked on every request independently of the dashboard's
  session cookie — one leaking doesn't expose the other. If an `/mcptoken`
  token ever leaks, regenerate it from the bot; the old one stops working
  immediately.
