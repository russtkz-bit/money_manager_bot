# 💰 Money Manager Telegram Bot

A fully-featured personal finance Telegram bot with real-time currency tracking, income/expense tracking, and financial goal management. Supports **English** and **Russian** languages.

---

## Features

| Feature | Description |
|---|---|
| 💸 **Transactions** | Add income/expense with category, currency, and description |
| 🎯 **Goals** | Set savings or loan repayment goals with deadlines |
| 💱 **Live Currencies** | Real-time rates: fiat, crypto (BTC/ETH/SOL/TON…), gold & silver |
| 📊 **Statistics** | Balance, income/expense totals, breakdown by category |
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

```bash
pip install -r requirements.txt
```

### 3. Create Your Bot

1. Open Telegram and message **@BotFather**
2. Send `/newbot` and follow the prompts
3. Copy the **Bot Token** you receive

### 4. Get Your API Keys

- **Telegram Bot Token** — from BotFather (step above)

### 5. Configure Environment

```bash
cp .env.example .env
```

Edit `.env`:
```
TELEGRAM_BOT_TOKEN=your_telegram_bot_token_here
ANTHROPIC_API_KEY=your_anthropic_api_key_here
```

### 6. Run the Bot

```bash
python bot.py
```

---

## 📁 Project Structure

```
money_manager_bot/
├── bot.py              # Main bot logic & Telegram handlers
├── database.py         # SQLite database (users, transactions, goals)
├── languages.py        # EN/RU translations
├── currencies.py       # Live currency/crypto/metals fetching
├── ai_assistant.py     # Anthropic AI with web search integration
├── requirements.txt    # Python dependencies
├── .env.example        # Environment variable template
└── money_manager.db    # SQLite database (auto-created on first run)
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
ExecStart=/usr/bin/python3 /path/to/money_manager_bot/bot.py
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

- The database (`money_manager.db`) is created automatically on first run
- AI features require a valid Anthropic API key; the bot works without it, but AI features will show an error message
- Currency rates are fetched live on demand — no caching, always fresh
- The bot stores all data locally in SQLite

---

## ⚠️ Disclaimer

This bot is for personal finance tracking only. The code is AI-generated.
