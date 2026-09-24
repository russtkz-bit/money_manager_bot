# 💰 Money Manager Telegram Bot

A personal finance Telegram bot: multiple accounts, income/expense tracking,
category budgets with overspend warnings, savings/repayment goals, live
currency rates, statistics with charts, and simple recurring-expense
detection. Supports **English** and **Russian** languages.

---

## Features

| Feature | Description |
|---|---|
| 🏦 **Accounts** | Track balances across bank cards, crypto exchanges, and cash — each with its own currency |
| 💸 **Transactions** | Add income/expense per account, with category and description |
| 📐 **Budgets** | Set a monthly limit per category; get warned in-chat when you're near or over it |
| 🎯 **Goals** | Set savings or loan repayment goals with deadlines, tracked against your account balances |
| 🔁 **Recurring & Forecast** | Detects expenses that repeat month over month and estimates next month's recurring spend |
| 💱 **Live Currencies** | Real-time rates: fiat, crypto (BTC/ETH/SOL/TON…), gold & silver |
| 📊 **Statistics** | Balance, income/expense totals and category breakdown — converted into your base currency, with charts |
| 🌐 **Bilingual** | Full English 🇬🇧 and Russian 🇷🇺 support |
| 💱 **Goal Currency Converter** | Convert goal amounts between any supported currency in real-time |

---

## 🚀 Quick Start

### 1. Clone / Copy Project

```bash
mkdir money_manager_bot && cd money_manager_bot
# Copy all files into this directory
```

### 2. Install Dependencies

On Debian/Ubuntu, the system Python is "externally managed" (PEP 668) and
refuses a bare `pip install` — use a virtual environment instead of
`--break-system-packages`, which risks the system's own Python tooling:

```bash
sudo apt install -y python3-venv   # if not already present
python3 -m venv venv
source venv/bin/activate           # run this again in any new shell before using the bot
pip install -r requirements.txt
```

Everything below (`python bot.py`, the systemd service) assumes this venv is
active or referenced directly, as shown.

### 3. Create Your Bot

1. Open Telegram and message **@BotFather**
2. Send `/newbot` and follow the prompts
3. Copy the **Bot Token** you receive

### 4. Set Up a Database

The bot stores everything in **PostgreSQL** (schema is created/migrated
automatically on startup — `schema.sql` is provided only as a reference for
manual setup). Any Postgres instance works, including free hosted tiers
(e.g. Railway, Supabase, Neon).

Running it yourself on an Ubuntu Server instead? `deploy/setup_postgres.sh`
installs and hardens a local, localhost-only PostgreSQL instance (dedicated
non-superuser role, SCRAM auth, no network exposure) in one command — see
[`deploy/POSTGRES_SETUP.md`](deploy/POSTGRES_SETUP.md) for details, backups,
and password rotation.

### 5. Configure Environment

```bash
cp .env.example .env
# then fill in TELEGRAM_BOT_TOKEN and DATABASE_URL
```

### 6. Run the Bot

```bash
venv/bin/python bot.py   # or: source venv/bin/activate && python bot.py
```

---

## 📁 Project Structure

```
money_manager_bot/
├── bot.py              # Main bot logic & Telegram handlers
├── database.py         # PostgreSQL access layer (users, accounts, transactions, budgets, goals)
├── languages.py        # EN/RU translations
├── currencies.py       # Live currency/crypto/metals fetching
├── charts.py           # Chart generation (goals, category pie, income/expense bar)
├── schema.sql          # Reference schema — the source of truth is database.init_db()
├── requirements.txt    # Python dependencies
└── .env.example        # Environment variable template
```

---

## 💱 Supported Currencies

**Fiat:** USD, EUR, RUB, KZT, GBP, JPY, CNY, AED, TRY

**Crypto:** BTC, ETH, BNB, SOL, TON, USDT, XRP

**Metals:** XAU (Gold), XAG (Silver)

---

## 🌐 Free APIs Used

| Service | Purpose | API Key Required |
|---|---|---|
| [open.er-api.com](https://open.er-api.com) | Fiat exchange rates | No |
| [CoinGecko](https://coingecko.com/api) | Crypto prices | No |
| [metals.live](https://metals.live) | Gold & silver prices | No |

---

## ⚙️ Commands

| Command | Description |
|---|---|
| `/start` | Start the bot / choose language |
| `/menu` | Open main menu |
| `/cancel` | Cancel current action |

---

## 🏗️ Running as a Service (Linux)

Create `/etc/systemd/system/money-bot.service`:

```ini
[Unit]
Description=Money Manager Telegram Bot
After=network.target

[Service]
Type=simple
User=your_user
WorkingDirectory=/path/to/money_manager_bot
EnvironmentFile=/path/to/money_manager_bot/.env
ExecStart=/path/to/money_manager_bot/venv/bin/python /path/to/money_manager_bot/bot.py
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl enable money-bot
sudo systemctl start money-bot
sudo systemctl status money-bot
```

---

## 📝 Notes

- The database schema is created/migrated automatically on first run — see `database.init_db()`
- Currency rates are fetched live on demand — no caching, always fresh
- A transaction's currency is always its account's currency, so account balances never mix currencies; amounts are converted to your base currency for statistics, budgets, and the recurring-spend forecast

---

## ⚠️ Disclaimer

This bot is for personal finance tracking only. The code is AI-generated.
