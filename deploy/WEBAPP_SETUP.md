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
`WEB_BASE_URL` is optional; set it once you know your public URL (step 4)
so `/webcode` messages include a clickable link:

```bash
WEB_BASE_URL='https://your-tunnel-url' ./deploy/configure_env.sh
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
tradeoff: **the URL changes every time this restarts**, so it's fine for
trying things out but annoying to rely on long-term (you'd have to check
the new URL each time and re-set `WEB_BASE_URL`).

To run it as a background service and be able to find the current URL
later:

```ini
# /etc/systemd/system/money-tunnel.service
[Unit]
Description=Cloudflare Quick Tunnel for Money Manager dashboard
After=network.target money-webapp.service

[Service]
Type=simple
ExecStart=/usr/bin/cloudflared tunnel --url http://localhost:8000
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now money-tunnel
# find today's URL:
sudo journalctl -u money-tunnel -n 50 --no-pager | grep -o 'https://[a-z-]*\.trycloudflare\.com'
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
