"""
Money Manager Telegram Bot
Tracks income/expenses via accounts, manages goals, currencies, and financial statistics.
"""

import os
import asyncio
import csv
import logging
from collections import Counter
from datetime import datetime, timedelta
from typing import Optional
from io import BytesIO, StringIO

import aiohttp
from dotenv import load_dotenv

# Must run before importing database: database.py reads DATABASE_URL from
# the environment at *import time* (a module-level constant), so loading
# .env after that import is too late — the constant is already bound to
# None regardless of what .env contains.
load_dotenv()

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, BotCommand, InputFile
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler,
    MessageHandler, ConversationHandler, filters, ContextTypes
)
from telegram.constants import ParseMode

import database as db
import currencies as cur
import charts as ch
import finance
import csv_import
from languages import t, category_label

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# ─────────────────── CONVERSATION STATES ───────────────────
(
    # Transaction flow
    # (no currency-picker state: a transaction's currency is locked to its
    # account's currency, so account balances never mix currencies)
    S_TRANS_TYPE, S_TRANS_AMOUNT,
    S_TRANS_CATEGORY, S_TRANS_DESC,
    S_TRANS_ACCOUNT,

    # Goal flow
    S_GOAL_TYPE, S_GOAL_TITLE, S_GOAL_AMOUNT,
    S_GOAL_CURRENCY, S_GOAL_DEADLINE,

    # Goal delete / convert / edit
    S_GOAL_SELECT_DELETE,
    S_GOAL_SELECT_CONVERT, S_GOAL_NEW_CURRENCY,
    S_GOAL_SELECT_EDIT, S_GOAL_EDIT_AMOUNT,

    # Settings
    S_SETTINGS_BASE_CURRENCY,

    # Stats custom date range
    S_STATS_CUSTOM_START, S_STATS_CUSTOM_END,

    # Transaction delete
    S_TRANS_SELECT_DELETE,

    # Account flow
    S_ACCOUNT_TYPE, S_ACCOUNT_NAME, S_ACCOUNT_CURRENCY, S_ACCOUNT_BALANCE,
    S_ACCOUNT_SELECT_DELETE,

    # Budget flow
    S_BUDGET_CATEGORY, S_BUDGET_AMOUNT, S_BUDGET_SELECT_DELETE,

    # CSV statement import
    S_IMPORT_ACCOUNT, S_IMPORT_FILE, S_IMPORT_CONFIRM,

    # Edit account initial balance
    S_ACCOUNT_EDIT_SELECT, S_ACCOUNT_EDIT_BALANCE,

    # Edit transaction category
    S_TRANS_SELECT_EDIT_CATEGORY, S_TRANS_EDIT_CATEGORY_PICK,

    # Custom categories
    S_CATEGORY_TYPE, S_CATEGORY_NAME, S_CATEGORY_EMOJI,
    S_CATEGORY_SELECT_DELETE,

    # Split transaction
    S_TRANS_SELECT_SPLIT, S_SPLIT_AMOUNT, S_SPLIT_CATEGORY,

    # Transaction tags
    S_TRANS_SELECT_TAGS, S_TAGS_MANAGE, S_TAGS_ADD_INPUT, S_TAGS_REMOVE_PICK,
    S_TAGS_BROWSE_PICK,
) = range(46)

# Currency rows for keyboard
CURRENCY_ROW_1 = ["USD", "EUR", "RUB", "KZT"]
CURRENCY_ROW_2 = ["GBP", "AED", "TRY", "CNY"]
CURRENCY_ROW_3 = ["BTC", "ETH", "SOL", "TON"]
CURRENCY_ROW_4 = ["BNB", "XRP", "XAU", "XAG"]

ACCOUNT_TYPE_EMOJI = {"bank": "🏦", "crypto": "₿", "cash": "💵"}

# Canonical (language-independent) category keys. Translated only for display
# via category_label() — this is what actually gets stored in the DB, so
# switching language never orphans existing transactions/budgets.
INCOME_CATEGORY_KEYS  = ["salary", "freelance", "investment", "gift", "other"]
EXPENSE_CATEGORY_KEYS = ["food", "transport", "housing", "health",
                         "entertainment", "loan_payment", "other"]


def lang(uid: int) -> str:
    return db.get_user_lang(uid)


# ─────────────────── KEYBOARDS ───────────────────

def main_menu_keyboard(uid: int) -> InlineKeyboardMarkup:
    l = lang(uid)
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(t(l, "btn_transactions"), callback_data="menu_transactions"),
         InlineKeyboardButton(t(l, "btn_goals"),        callback_data="menu_goals")],
        [InlineKeyboardButton(t(l, "btn_accounts"),     callback_data="menu_accounts"),
         InlineKeyboardButton(t(l, "btn_budgets"),      callback_data="menu_budgets")],
        [InlineKeyboardButton(t(l, "btn_currencies"),   callback_data="menu_currencies"),
         InlineKeyboardButton(t(l, "btn_statistics"),   callback_data="menu_stats")],
        [InlineKeyboardButton(t(l, "btn_categories"),   callback_data="menu_categories"),
         InlineKeyboardButton(t(l, "btn_settings"),     callback_data="menu_settings")],
    ])


def transactions_keyboard(uid: int) -> InlineKeyboardMarkup:
    l = lang(uid)
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(t(l, "btn_add_income"),          callback_data="trans_add_income"),
         InlineKeyboardButton(t(l, "btn_add_expense"),         callback_data="trans_add_expense")],
        [InlineKeyboardButton(t(l, "btn_view_transactions"),   callback_data="trans_view")],
        [InlineKeyboardButton(t(l, "btn_transaction_history"), callback_data="trans_history")],
        [InlineKeyboardButton(t(l, "btn_edit_transaction_category"), callback_data="trans_edit_category")],
        [InlineKeyboardButton(t(l, "btn_split_transaction"),   callback_data="trans_split")],
        [InlineKeyboardButton(t(l, "btn_transaction_tags"),    callback_data="trans_tags"),
         InlineKeyboardButton(t(l, "btn_browse_by_tag"),       callback_data="trans_browse_tag")],
        [InlineKeyboardButton(t(l, "btn_delete_transaction"),  callback_data="trans_delete"),
         InlineKeyboardButton(t(l, "btn_clear_transactions"),  callback_data="trans_clear")],
        [InlineKeyboardButton(t(l, "back"),                    callback_data="back_main")],
    ])


def accounts_keyboard(uid: int) -> InlineKeyboardMarkup:
    l = lang(uid)
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(t(l, "btn_add_account"),    callback_data="account_add")],
        [InlineKeyboardButton(t(l, "btn_view_accounts"),  callback_data="account_view")],
        [InlineKeyboardButton(t(l, "btn_edit_account_balance"), callback_data="account_edit_balance")],
        [InlineKeyboardButton(t(l, "btn_delete_account"), callback_data="account_delete")],
        [InlineKeyboardButton(t(l, "btn_import_csv"),     callback_data="account_import_csv")],
        [InlineKeyboardButton(t(l, "back"),               callback_data="back_main")],
    ])


def budgets_keyboard(uid: int) -> InlineKeyboardMarkup:
    l = lang(uid)
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(t(l, "btn_set_budget"),    callback_data="budget_add")],
        [InlineKeyboardButton(t(l, "btn_view_budgets"),  callback_data="budget_view")],
        [InlineKeyboardButton(t(l, "btn_delete_budget"), callback_data="budget_delete")],
        [InlineKeyboardButton(t(l, "back"),              callback_data="back_main")],
    ])


def goals_keyboard(uid: int) -> InlineKeyboardMarkup:
    l = lang(uid)
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(t(l, "btn_add_goal"),    callback_data="goal_add")],
        [InlineKeyboardButton(t(l, "btn_view_goals"),  callback_data="goal_view")],
        [InlineKeyboardButton(t(l, "btn_edit_goal"),   callback_data="goal_edit")],
        [InlineKeyboardButton(t(l, "btn_convert_goal"), callback_data="goal_convert"),
         InlineKeyboardButton(t(l, "btn_delete_goal"), callback_data="goal_delete")],
        [InlineKeyboardButton(t(l, "back"),            callback_data="back_main")],
    ])


def currency_keyboard(callback_prefix: str, uid: int) -> InlineKeyboardMarkup:
    rows = []
    for row in [CURRENCY_ROW_1, CURRENCY_ROW_2, CURRENCY_ROW_3, CURRENCY_ROW_4]:
        rows.append([InlineKeyboardButton(c, callback_data=f"{callback_prefix}_{c}") for c in row])
    l = lang(uid)
    rows.append([InlineKeyboardButton(t(l, "cancel"), callback_data="conv_cancel")])
    return InlineKeyboardMarkup(rows)


def _category_items(t_type: str, uid: int) -> list:
    """(key, label) pairs for every category a transaction of this type can
    use — the built-in fixed set plus this user's custom ones (their own
    'both'-type categories included)."""
    l = lang(uid)
    base_keys = INCOME_CATEGORY_KEYS if t_type == "income" else EXPENSE_CATEGORY_KEYS
    items = [(k, t(l, f"cat_{k}")) for k in base_keys]
    items += [(c["key"], f"{c['emoji']} {c['name']}") for c in db.get_custom_categories(uid, t_type)]
    return items


def category_keyboard(t_type: str, uid: int) -> InlineKeyboardMarkup:
    l = lang(uid)
    items = _category_items(t_type, uid)
    rows = []
    for i in range(0, len(items), 2):
        row = [InlineKeyboardButton(items[i][1], callback_data=f"cat_{items[i][0]}")]
        if i + 1 < len(items):
            row.append(InlineKeyboardButton(items[i + 1][1], callback_data=f"cat_{items[i + 1][0]}"))
        rows.append(row)
    rows.append([InlineKeyboardButton(t(l, "cancel"), callback_data="conv_cancel")])
    return InlineKeyboardMarkup(rows)


def budget_category_keyboard(uid: int, existing_categories: set) -> InlineKeyboardMarkup:
    """Category picker for budgets — expense (+ 'both' custom) categories only,
    marks ones that already have a budget."""
    l = lang(uid)
    items = _category_items("expense", uid)
    rows = []
    for i in range(0, len(items), 2):
        row = [InlineKeyboardButton(_budget_cat_btn_label(items[i], existing_categories),
                                     callback_data=f"bcat_{items[i][0]}")]
        if i + 1 < len(items):
            row.append(InlineKeyboardButton(_budget_cat_btn_label(items[i + 1], existing_categories),
                                             callback_data=f"bcat_{items[i + 1][0]}"))
        rows.append(row)
    rows.append([InlineKeyboardButton(t(l, "cancel"), callback_data="conv_cancel")])
    return InlineKeyboardMarkup(rows)


def _budget_cat_btn_label(item: tuple, existing_categories: set) -> str:
    key, label = item
    mark = "✅ " if key in existing_categories else ""
    return mark + label


def budgets_select_keyboard(budgets: list, uid: int) -> InlineKeyboardMarkup:
    l = lang(uid)
    rows = []
    for b in budgets:
        label = f"{category_label(b['category'], l)} — {b['amount']:,.2f} {b['currency']}"
        rows.append([InlineKeyboardButton(label, callback_data=f"bdel_{b['id']}")])
    rows.append([InlineKeyboardButton(t(l, "cancel"), callback_data="conv_cancel")])
    return InlineKeyboardMarkup(rows)


def categories_keyboard(uid: int) -> InlineKeyboardMarkup:
    l = lang(uid)
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(t(l, "btn_add_category"),    callback_data="customcat_add")],
        [InlineKeyboardButton(t(l, "btn_view_categories"), callback_data="customcat_view")],
        [InlineKeyboardButton(t(l, "btn_delete_category"), callback_data="customcat_delete")],
        [InlineKeyboardButton(t(l, "back"),                callback_data="back_main")],
    ])


def category_type_keyboard(uid: int) -> InlineKeyboardMarkup:
    l = lang(uid)
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(t(l, "category_type_income"),  callback_data="cattype_income"),
         InlineKeyboardButton(t(l, "category_type_expense"), callback_data="cattype_expense")],
        [InlineKeyboardButton(t(l, "category_type_both"),    callback_data="cattype_both")],
        [InlineKeyboardButton(t(l, "cancel"),                callback_data="conv_cancel")],
    ])


def categories_select_keyboard(categories: list, uid: int) -> InlineKeyboardMarkup:
    l = lang(uid)
    rows = []
    for c in categories:
        rows.append([InlineKeyboardButton(
            f"{c['emoji']} {c['name']}", callback_data=f"ccatdel_{c['key']}"
        )])
    rows.append([InlineKeyboardButton(t(l, "cancel"), callback_data="conv_cancel")])
    return InlineKeyboardMarkup(rows)


def goal_type_keyboard(uid: int) -> InlineKeyboardMarkup:
    l = lang(uid)
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(t(l, "goal_type_save"),  callback_data="gtype_save"),
         InlineKeyboardButton(t(l, "goal_type_repay"), callback_data="gtype_repay")],
        [InlineKeyboardButton(t(l, "cancel"),          callback_data="conv_cancel")],
    ])


def account_type_keyboard(uid: int) -> InlineKeyboardMarkup:
    l = lang(uid)
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(t(l, "account_type_bank"),   callback_data="atype_bank"),
         InlineKeyboardButton(t(l, "account_type_crypto"), callback_data="atype_crypto")],
        [InlineKeyboardButton(t(l, "account_type_cash"),   callback_data="atype_cash")],
        [InlineKeyboardButton(t(l, "cancel"),              callback_data="conv_cancel")],
    ])


def accounts_select_keyboard(accounts: list, callback_prefix: str, uid: int) -> InlineKeyboardMarkup:
    l = lang(uid)
    rows = []
    for acc in accounts:
        emoji = ACCOUNT_TYPE_EMOJI.get(acc["account_type"], "🏦")
        bal   = acc.get("computed_balance", acc["initial_balance"])
        label = f"{emoji} {acc['name']} — {bal:,.2f} {acc['currency']}"
        rows.append([InlineKeyboardButton(label, callback_data=f"{callback_prefix}_{acc['id']}")])
    rows.append([InlineKeyboardButton(t(l, "cancel"), callback_data="conv_cancel")])
    return InlineKeyboardMarkup(rows)


def settings_keyboard(uid: int) -> InlineKeyboardMarkup:
    l = lang(uid)
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(t(l, "btn_change_language"), callback_data="settings_language")],
        [InlineKeyboardButton(t(l, "btn_change_currency"), callback_data="settings_base_currency")],
        [InlineKeyboardButton(t(l, "back"),                callback_data="back_main")],
    ])


def language_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🇬🇧 English", callback_data="setlang_en"),
         InlineKeyboardButton("🇷🇺 Русский",  callback_data="setlang_ru")],
    ])


def back_keyboard(uid: int, callback: str = "back_main") -> InlineKeyboardMarkup:
    l = lang(uid)
    return InlineKeyboardMarkup([[InlineKeyboardButton(t(l, "back"), callback_data=callback)]])


def stats_period_keyboard(uid: int) -> InlineKeyboardMarkup:
    l = lang(uid)
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(t(l, "stats_period_week"),   callback_data="stats_p_week"),
         InlineKeyboardButton(t(l, "stats_period_month"),  callback_data="stats_p_month")],
        [InlineKeyboardButton(t(l, "stats_period_6m"),     callback_data="stats_p_6m"),
         InlineKeyboardButton(t(l, "stats_period_year"),   callback_data="stats_p_year")],
        [InlineKeyboardButton(t(l, "stats_period_custom"), callback_data="stats_p_custom")],
        [InlineKeyboardButton(t(l, "stats_recurring"),     callback_data="stats_recurring")],
        [InlineKeyboardButton(t(l, "btn_forecast"),        callback_data="stats_forecast")],
        [InlineKeyboardButton(t(l, "back"),                callback_data="back_main")],
    ])


def history_period_keyboard(uid: int) -> InlineKeyboardMarkup:
    l = lang(uid)
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(t(l, "stats_period_week"),  callback_data="hist_p_week"),
         InlineKeyboardButton(t(l, "stats_period_month"), callback_data="hist_p_month")],
        [InlineKeyboardButton(t(l, "stats_period_6m"),    callback_data="hist_p_6m"),
         InlineKeyboardButton(t(l, "stats_period_year"),  callback_data="hist_p_year")],
        [InlineKeyboardButton(t(l, "back"),               callback_data="menu_transactions")],
    ])


def stats_chart_type_keyboard(uid: int, selected: set) -> InlineKeyboardMarkup:
    l = lang(uid)

    def btn(label_key: str, key: str) -> InlineKeyboardButton:
        mark = "✅" if key in selected else "⬜"
        return InlineKeyboardButton(
            f"{mark} {t(l, label_key)}",
            callback_data=f"schrt_toggle_{key}",
        )

    return InlineKeyboardMarkup([
        [btn("chart_goals_caption", "goals"),
         btn("chart_pie_caption",   "pie")],
        [btn("chart_bar_caption",   "bar")],
        [InlineKeyboardButton(t(l, "stats_generate"),  callback_data="schrt_generate")],
        [InlineKeyboardButton(t(l, "back"),            callback_data="back_stats")],
    ])


def goals_select_keyboard(goals: list, callback_prefix: str, uid: int) -> InlineKeyboardMarkup:
    l = lang(uid)
    rows = []
    for g in goals:
        pct   = min(100, round(g["current_amount"] / g["target_amount"] * 100)) if g["target_amount"] else 0
        label = f"{g['title']} ({pct}%)"
        rows.append([InlineKeyboardButton(label, callback_data=f"{callback_prefix}_{g['id']}")])
    rows.append([InlineKeyboardButton(t(l, "cancel"), callback_data="conv_cancel")])
    return InlineKeyboardMarkup(rows)


MAX_TRANS_SELECT_DETAIL_LEN = 22


def _trans_select_keyboard(txns: list, uid: int, callback_prefix: str = "tdel") -> InlineKeyboardMarkup:
    l = lang(uid)
    rows = []
    for tx in txns:
        emoji    = "📈" if tx["type"] == "income" else "📉"
        date_str = tx["created_at"][:10] if tx["created_at"] else "?"
        # Date + amount alone doesn't distinguish same-day transactions of the
        # same amount (e.g. two identical CSV-imported charges) — description
        # (falling back to the category) is what actually tells them apart.
        detail = (tx.get("description") or "").strip() or category_label(tx["category"], l)
        if len(detail) > MAX_TRANS_SELECT_DETAIL_LEN:
            detail = detail[:MAX_TRANS_SELECT_DETAIL_LEN - 1] + "…"
        label = f"{emoji} {date_str} {tx['amount']:,.0f} {tx['currency']} — {detail}"
        rows.append([InlineKeyboardButton(label, callback_data=f"{callback_prefix}_{tx['id']}")])
    rows.append([InlineKeyboardButton(t(l, "back"), callback_data="menu_transactions")])
    return InlineKeyboardMarkup(rows)


# ─────────────────── HELPERS ───────────────────

async def send_main_menu(update: Update, uid: int, edit: bool = False):
    l   = lang(uid)
    text = t(l, "main_menu")
    kb  = main_menu_keyboard(uid)
    if edit and update.callback_query:
        await update.callback_query.edit_message_text(text, reply_markup=kb, parse_mode=ParseMode.MARKDOWN)
    else:
        target = update.message or update.callback_query.message
        await target.reply_text(text, reply_markup=kb, parse_mode=ParseMode.MARKDOWN)


def format_goals_text(goals: list, l: str) -> str:
    if not goals:
        return t(l, "no_goals")
    lines = t(l, "goals_header")
    type_labels = {
        "save":  t(l, "goal_type_save"),
        "repay": t(l, "goal_type_repay"),
    }
    for i, g in enumerate(goals, 1):
        pct      = min(100, round(g["current_amount"] / g["target_amount"] * 100)) if g["target_amount"] else 0
        deadline = g["deadline"] or "—"
        lines   += t(l, "goal_line",
                     n=i, title=g["title"],
                     type=type_labels.get(g["goal_type"], g["goal_type"]),
                     current=f"{g['current_amount']:,.2f}",
                     target=f"{g['target_amount']:,.2f}",
                     currency=g["currency"],
                     pct=pct, deadline=deadline)
    return lines


def _account_type_label(account_type: str, l: str) -> str:
    key_map = {"bank": "account_type_bank", "crypto": "account_type_crypto", "cash": "account_type_cash"}
    return t(l, key_map.get(account_type, "account_type_bank"))


async def _fetch_rates_if_needed(needed: bool) -> dict:
    """Fetch live conversion rates only when something actually depends on
    them. cur.fetch_all_rates() is three external HTTP calls (each with a
    10s timeout) — worth skipping on routine actions (delete a transaction,
    add an account, ...) for users who have no goals and no budget that
    would need converting."""
    conversion_rates = {"fiat": {}, "crypto": {}, "metals": {}}
    if needed:
        try:
            conversion_rates["fiat"], conversion_rates["crypto"], conversion_rates["metals"] = \
                await cur.fetch_all_rates()
        except Exception:
            pass
    return conversion_rates


def _budget_warning_text(uid: int, category_key: str, conversion_rates: dict, l: str) -> str:
    """Returns an extra message chunk warning about budget overspend, or ''.

    The incomplete-conversion note is surfaced independently of the
    exceeded/near-limit thresholds: a failed conversion makes `spent`
    undercount (missing amounts contribute 0, see finance.spent_this_month), which
    makes it *less* likely to cross either threshold — exactly backwards
    from what should happen when we can't be sure of the real total, so a
    real overspend must never be hidden behind a conversion failure.
    """
    budget = db.get_budget_by_category(uid, category_key)
    if not budget or not budget["amount"]:
        return ""
    spent, all_converted = finance.spent_this_month(uid, category_key, budget["currency"], conversion_rates)
    pct   = spent / budget["amount"] * 100
    cat   = category_label(category_key, l)
    fmt_args = dict(category=cat, spent=f"{spent:,.2f}",
                    amount=f"{budget['amount']:,.2f}", currency=budget["currency"],
                    pct=round(pct))

    lines = []
    if spent >= budget["amount"]:
        lines.append(t(l, "budget_exceeded", **fmt_args))
    elif pct >= 80:
        lines.append(t(l, "budget_near_limit", **fmt_args))
    if not all_converted:
        lines.append(t(l, "rates_incomplete_note"))
    return ("\n\n" + "\n".join(lines)) if lines else ""


# ─────────────────── START / WELCOME ───────────────────

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    db.ensure_user(uid)
    tg_lang      = (update.effective_user.language_code or "en").lower()
    initial_lang = "ru" if tg_lang.startswith("ru") else "en"
    db.set_user_language(uid, initial_lang)
    text = t(initial_lang, "welcome")
    kb   = InlineKeyboardMarkup([
        [InlineKeyboardButton("🇬🇧 English", callback_data="setlang_en"),
         InlineKeyboardButton("🇷🇺 Русский",  callback_data="setlang_ru")],
    ])
    await update.message.reply_text(text, reply_markup=kb, parse_mode=ParseMode.MARKDOWN)


async def cb_set_language(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    uid    = query.from_user.id
    chosen = query.data.split("_")[1]
    db.set_user_language(uid, chosen)
    await query.edit_message_text(t(chosen, "language_set"), parse_mode=ParseMode.MARKDOWN)
    await asyncio.sleep(0.5)
    await send_main_menu(update, uid, edit=True)


async def cmd_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    db.ensure_user(uid)
    await send_main_menu(update, uid)


async def _current_web_url() -> str:
    """Best-effort discovery of the dashboard's current public URL.

    A Cloudflare *quick* tunnel (the zero-config option in
    deploy/WEBAPP_SETUP.md) prints a fresh random *.trycloudflare.com
    hostname every time it restarts, so a URL baked into WEB_BASE_URL at
    setup time silently goes stale on the next restart. cloudflared's
    local metrics server exposes the live quick-tunnel hostname at
    /quicktunnel, so that's tried first — it only answers for an actual
    quick tunnel, so a named tunnel (stable custom domain, no such
    endpoint) falls straight through to WEB_BASE_URL below, which is the
    right source there since that URL never changes.
    """
    metrics_port = os.getenv("CLOUDFLARED_METRICS_PORT", "20241")
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(
                f"http://127.0.0.1:{metrics_port}/quicktunnel",
                timeout=aiohttp.ClientTimeout(total=1.5)
            ) as resp:
                if resp.status == 200:
                    data = await resp.json(content_type=None)
                    hostname = data.get("hostname")
                    if hostname:
                        return f"https://{hostname}"
    except Exception:
        pass
    return os.getenv("WEB_BASE_URL", "").rstrip("/")


async def cmd_webcode(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Issues a short-lived, single-use code for logging into the web dashboard."""
    uid = update.effective_user.id
    db.ensure_user(uid)
    l    = lang(uid)
    code = db.create_web_login_code(uid)
    web_url = await _current_web_url()
    if web_url:
        text = t(l, "webcode_sent_with_link", code=code, url=f"{web_url}/login")
    else:
        text = t(l, "webcode_sent", code=code)
    await update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN, disable_web_page_preview=True)


# ─────────────────── MAIN MENU ROUTING ───────────────────

async def cb_main_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    uid = query.from_user.id
    l   = lang(uid)

    if query.data == "back_main":
        await send_main_menu(update, uid, edit=True)

    elif query.data == "menu_transactions":
        await query.edit_message_text(
            t(l, "btn_transactions"),
            reply_markup=transactions_keyboard(uid),
            parse_mode=ParseMode.MARKDOWN
        )
    elif query.data == "menu_accounts":
        await query.edit_message_text(
            t(l, "accounts_menu_header"),
            reply_markup=accounts_keyboard(uid),
            parse_mode=ParseMode.MARKDOWN
        )
    elif query.data == "menu_budgets":
        await query.edit_message_text(
            t(l, "budgets_menu_header"),
            reply_markup=budgets_keyboard(uid),
            parse_mode=ParseMode.MARKDOWN
        )
    elif query.data == "budget_view":
        await handle_view_budgets(update, context)
    elif query.data == "menu_goals":
        await query.edit_message_text(
            t(l, "btn_goals"),
            reply_markup=goals_keyboard(uid),
            parse_mode=ParseMode.MARKDOWN
        )
    elif query.data == "menu_currencies":
        await handle_currencies(update, context)

    elif query.data == "menu_stats":
        await handle_statistics(update, context)

    elif query.data == "menu_settings":
        await query.edit_message_text(
            t(l, "settings_header"),
            reply_markup=settings_keyboard(uid),
            parse_mode=ParseMode.MARKDOWN
        )
    elif query.data == "settings_language":
        await query.edit_message_text(
            t(l, "choose_language"),
            reply_markup=language_keyboard(),
            parse_mode=ParseMode.MARKDOWN
        )
    elif query.data == "trans_view":
        await handle_view_transactions(update, context)

    elif query.data == "trans_clear":
        await cb_clear_transactions(update, context)

    elif query.data == "goal_view":
        await handle_view_goals(update, context)

    elif query.data == "account_view":
        await handle_view_accounts(update, context)

    elif query.data == "menu_categories":
        await query.edit_message_text(
            t(l, "categories_menu_header"),
            reply_markup=categories_keyboard(uid),
            parse_mode=ParseMode.MARKDOWN
        )
    elif query.data == "customcat_view":
        await handle_view_categories(update, context)


# ─────────────────── CURRENCIES ───────────────────

async def handle_currencies(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    uid   = query.from_user.id
    l     = lang(uid)
    await query.edit_message_text(t(l, "fetching_rates"), parse_mode=ParseMode.MARKDOWN)
    fiat, crypto, metals = await cur.fetch_all_rates()
    text = t(l, "currencies_header")
    if fiat:
        fiat_lines = "\n".join(f" `{c}`: {v:,.4f}" for c, v in fiat.items() if c != "USD")
        text += t(l, "fiat_rates", rates=fiat_lines)
    else:
        text += t(l, "rates_error") + "\n"
    if crypto:
        crypto_lines = "\n".join(
            f" `{sym}`: ${price:,.2f}" if price >= 1 else f" `{sym}`: ${price:.6f}"
            for sym, price in crypto.items()
        )
        text += t(l, "crypto_rates", rates=crypto_lines)
    if metals:
        metals_lines = "\n".join(f" `{sym}`: ${price:,.2f}" for sym, price in metals.items())
        text += t(l, "metals_rates", rates=metals_lines)
    await query.edit_message_text(text, reply_markup=back_keyboard(uid), parse_mode=ParseMode.MARKDOWN)


# ─────────────────── STATISTICS ───────────────────

async def handle_statistics(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    uid   = query.from_user.id
    l     = lang(uid)
    await query.edit_message_text(
        t(l, "stats_choose_period"),
        reply_markup=stats_period_keyboard(uid),
        parse_mode=ParseMode.MARKDOWN,
    )


_period_dates = finance.period_dates


async def _send_charts(update, context, uid, start_date, end_date, bar_period, period_label, chart_types=None):
    l     = lang(uid)
    query = update.callback_query
    await query.edit_message_text(t(l, "stats_generating"), parse_mode=ParseMode.MARKDOWN)

    txns  = db.get_transactions_filtered(uid, start_date, end_date)
    goals = db.get_goals(uid)

    # Transactions can be in different currencies (one per account), so
    # totals and the category breakdown are converted into the user's base
    # currency before summing — adding raw amounts across currencies would
    # otherwise produce a meaningless number.
    base_currency = db.get_user_base_currency(uid)
    fiat, crypto, metals = {}, {}, {}
    try:
        fiat, crypto, metals = await cur.fetch_all_rates()
    except Exception:
        pass

    agg = finance.aggregate_transactions(txns, base_currency, l, fiat, crypto, metals)
    total_income   = agg["total_income"]
    total_expense  = agg["total_expense"]
    by_cat         = agg["by_category"]
    txns_base      = agg["txns_base"]
    any_incomplete = not agg["all_converted"]
    balance = total_income - total_expense

    summary  = t(l, "stats_period_header", period=period_label)
    summary += t(l, "stats_balance", balance=f"{balance:,.2f}", currency=base_currency)
    summary += t(l, "stats_income",  amount=f"{total_income:,.2f}",  currency=base_currency)
    summary += t(l, "stats_expense", amount=f"{total_expense:,.2f}", currency=base_currency)
    if not txns:
        summary += "\n" + t(l, "stats_no_data_period")
    if any_incomplete:
        summary += "\n" + t(l, "rates_incomplete_note")

    if chart_types is None:
        chart_types = {"goals", "pie", "bar"}

    chart_msg_ids: list = []
    sent_any = False

    if "goals" in chart_types and goals:
        try:
            img = ch.generate_goals_chart(goals, title=t(l, "chart_goals_title"))
            if img:
                msg = await context.bot.send_photo(
                    chat_id=uid, photo=BytesIO(img),
                    caption=t(l, "chart_goals_caption"), parse_mode=ParseMode.MARKDOWN,
                )
                chart_msg_ids.append(msg.message_id)
                sent_any = True
        except Exception as e:
            logger.warning(f"Goals chart failed: {e}")

    if "pie" in chart_types and by_cat:
        try:
            img = ch.generate_pie_chart(by_cat, title=t(l, "chart_pie_title"))
            if img:
                msg = await context.bot.send_photo(
                    chat_id=uid, photo=BytesIO(img),
                    caption=t(l, "chart_pie_caption"), parse_mode=ParseMode.MARKDOWN,
                )
                chart_msg_ids.append(msg.message_id)
                sent_any = True
        except Exception as e:
            logger.warning(f"Pie chart failed: {e}")

    if "bar" in chart_types and txns:
        try:
            img = ch.generate_bar_chart(
                txns_base, bar_period,
                income_label=t(l, "income"),
                expense_label=t(l, "expense"),
                title=t(l, "chart_bar_title"),
            )
            if img:
                msg = await context.bot.send_photo(
                    chat_id=uid, photo=BytesIO(img),
                    caption=t(l, "chart_bar_caption"), parse_mode=ParseMode.MARKDOWN,
                )
                chart_msg_ids.append(msg.message_id)
                sent_any = True
        except Exception as e:
            logger.warning(f"Bar chart failed: {e}")

    context.user_data["stats_chart_msg_ids"] = chart_msg_ids
    if not sent_any:
        summary += "\n\n" + t(l, "stats_no_charts")
    await query.edit_message_text(
        summary,
        reply_markup=back_keyboard(uid, "back_stats"),
        parse_mode=ParseMode.MARKDOWN,
    )


async def cb_back_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query   = update.callback_query
    await query.answer()
    uid     = query.from_user.id
    chat_id = query.message.chat_id
    for msg_id in context.user_data.pop("stats_chart_msg_ids", []):
        try:
            await context.bot.delete_message(chat_id=chat_id, message_id=msg_id)
        except Exception:
            pass
    await send_main_menu(update, uid, edit=True)


async def cb_stats_recurring(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    uid = query.from_user.id
    l   = lang(uid)
    await query.edit_message_text(t(l, "stats_generating"), parse_mode=ParseMode.MARKDOWN)

    base_currency = db.get_user_base_currency(uid)
    fiat, crypto, metals = {}, {}, {}
    try:
        fiat, crypto, metals = await cur.fetch_all_rates()
    except Exception:
        pass

    # Look back 90 days — enough to catch monthly recurring spend in ~3 cycles.
    since = (datetime.now().date() - timedelta(days=89)).strftime("%Y-%m-%d")
    txns  = db.get_transactions_filtered(uid, since)
    recurring, all_converted = finance.detect_recurring(txns, base_currency, fiat, crypto, metals)

    if not recurring:
        await query.edit_message_text(
            t(l, "no_recurring"),
            reply_markup=back_keyboard(uid, "back_stats"),
            parse_mode=ParseMode.MARKDOWN
        )
        return

    text = t(l, "recurring_header")
    total = 0.0
    for r in recurring:
        total += r["avg_amount"]
        text += t(l, "recurring_line",
                  category=category_label(r["category"], l),
                  amount=f"{r['avg_amount']:,.2f}", currency=base_currency,
                  months=r["months"], last_date=r["last_date"])
    text += t(l, "recurring_forecast", amount=f"{total:,.2f}", currency=base_currency)
    if not all_converted:
        text += "\n" + t(l, "rates_incomplete_note")

    await query.edit_message_text(
        text,
        reply_markup=back_keyboard(uid, "back_stats"),
        parse_mode=ParseMode.MARKDOWN
    )


async def cb_stats_forecast(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    uid = query.from_user.id
    l   = lang(uid)
    await query.edit_message_text(t(l, "forecast_generating"), parse_mode=ParseMode.MARKDOWN)

    base_currency = db.get_user_base_currency(uid)
    accounts = db.get_accounts_with_balances(uid)
    if not accounts:
        await query.edit_message_text(
            t(l, "forecast_no_data"),
            reply_markup=back_keyboard(uid, "back_stats"),
            parse_mode=ParseMode.MARKDOWN
        )
        return

    fiat, crypto, metals = {}, {}, {}
    try:
        fiat, crypto, metals = await cur.fetch_all_rates()
    except Exception:
        pass

    forecast = finance.forecast_net_worth(uid, base_currency, fiat, crypto, metals, accounts=accounts)

    text = t(l, "forecast_header")
    text += t(l, "forecast_current", amount=f"{forecast['current']:,.2f}", currency=base_currency)
    history_months = forecast["history_months"]
    if history_months > 0:
        history_change = forecast["current"] - forecast["points"][0][1]
        history_key = "forecast_history_positive" if history_change >= 0 else "forecast_history_negative"
        text += t(l, history_key, months=history_months,
                 amount=f"{abs(history_change):,.2f}", currency=base_currency)
    if forecast["monthly_net"] >= 0:
        text += t(l, "forecast_monthly_net_positive", amount=f"{forecast['monthly_net']:,.2f}", currency=base_currency)
    else:
        text += t(l, "forecast_monthly_net_negative", amount=f"{forecast['monthly_net']:,.2f}", currency=base_currency)
    months_ahead = forecast["points"][-1][0]
    text += t(l, "forecast_projection",
             months=months_ahead, amount=f"{forecast['points'][-1][1]:,.2f}", currency=base_currency)
    if not forecast["all_converted"]:
        text += "\n" + t(l, "rates_incomplete_note")

    img = ch.generate_forecast_chart(forecast["points"], base_currency, title=t(l, "forecast_chart_title"))
    if img:
        await context.bot.send_photo(chat_id=uid, photo=BytesIO(img))
    await context.bot.send_message(
        chat_id=uid, text=text,
        reply_markup=back_keyboard(uid, "back_stats"),
        parse_mode=ParseMode.MARKDOWN
    )


async def cb_stats_period(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    uid   = query.from_user.id
    l     = lang(uid)
    key   = query.data[len("stats_p_"):]
    start, end, bar = _period_dates(key)
    labels = {
        "week":  t(l, "stats_period_week"),
        "month": t(l, "stats_period_month"),
        "6m":    t(l, "stats_period_6m"),
        "year":  t(l, "stats_period_year"),
    }
    label = labels.get(key, key)
    context.user_data["stats_pending"]      = {"start": start, "end": end, "bar": bar, "label": label}
    if "stats_chart_types" not in context.user_data:
        context.user_data["stats_chart_types"] = {"goals", "pie", "bar"}
    await query.edit_message_text(
        t(l, "stats_choose_charts"),
        reply_markup=stats_chart_type_keyboard(uid, context.user_data["stats_chart_types"]),
        parse_mode=ParseMode.MARKDOWN,
    )


async def cb_schrt_toggle(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    uid   = query.from_user.id
    key   = query.data[len("schrt_toggle_"):]
    selected: set = context.user_data.get("stats_chart_types", {"goals", "pie", "bar"})
    if key in selected:
        selected.discard(key)
    else:
        selected.add(key)
    context.user_data["stats_chart_types"] = selected
    await query.edit_message_reply_markup(reply_markup=stats_chart_type_keyboard(uid, selected))


async def cb_schrt_generate(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    uid     = query.from_user.id
    l       = lang(uid)
    pending = context.user_data.get("stats_pending")
    if not pending:
        await query.edit_message_text(t(l, "error"), parse_mode=ParseMode.MARKDOWN)
        return
    selected: set = context.user_data.get("stats_chart_types", {"goals", "pie", "bar"})
    if not selected:
        await query.answer(t(l, "stats_no_chart_selected"), show_alert=True)
        return
    await _send_charts(update, context, uid,
                       pending["start"], pending["end"], pending["bar"], pending["label"],
                       chart_types=selected)


async def stats_custom_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    uid = query.from_user.id
    l   = lang(uid)
    await query.edit_message_text(t(l, "stats_enter_start_date"), parse_mode=ParseMode.MARKDOWN)
    return S_STATS_CUSTOM_START


async def stats_custom_got_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    l   = lang(uid)
    try:
        datetime.strptime(update.message.text.strip(), "%Y-%m-%d")
    except ValueError:
        await update.message.reply_text(t(l, "stats_invalid_date"))
        return S_STATS_CUSTOM_START
    context.user_data["stats_start"] = update.message.text.strip()
    await update.message.reply_text(t(l, "stats_enter_end_date"), parse_mode=ParseMode.MARKDOWN)
    return S_STATS_CUSTOM_END


async def stats_custom_got_end(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    l   = lang(uid)
    try:
        end_dt = datetime.strptime(update.message.text.strip(), "%Y-%m-%d")
    except ValueError:
        await update.message.reply_text(t(l, "stats_invalid_date"))
        return S_STATS_CUSTOM_END
    start_str = context.user_data.get("stats_start", "")
    end_str   = update.message.text.strip()
    try:
        start_dt = datetime.strptime(start_str, "%Y-%m-%d")
    except ValueError:
        await update.message.reply_text(t(l, "error"))
        return ConversationHandler.END
    if end_dt < start_dt:
        await update.message.reply_text(t(l, "stats_end_before_start"))
        return S_STATS_CUSTOM_END
    days  = (end_dt - start_dt).days
    bar   = ch.period_for_days(days)
    label = f"{start_str} — {end_str}"
    context.user_data["stats_pending"] = {"start": start_str, "end": end_str, "bar": bar, "label": label}
    if "stats_chart_types" not in context.user_data:
        context.user_data["stats_chart_types"] = {"goals", "pie", "bar"}
    await update.message.reply_text(
        t(l, "stats_choose_charts"),
        reply_markup=stats_chart_type_keyboard(uid, context.user_data["stats_chart_types"]),
        parse_mode=ParseMode.MARKDOWN,
    )
    return ConversationHandler.END


# ─────────────────── VIEW TRANSACTIONS ───────────────────

async def handle_view_transactions(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    uid   = query.from_user.id
    l     = lang(uid)
    txns  = db.get_transactions(uid)
    if not txns:
        await query.edit_message_text(
            t(l, "no_transactions"),
            reply_markup=back_keyboard(uid, "menu_transactions"),
            parse_mode=ParseMode.MARKDOWN
        )
        return
    tags_by_tx = db.get_tags_for_transactions([tx["id"] for tx in txns])
    text = t(l, "transactions_header")
    for tx in txns:
        emoji    = "📈" if tx["type"] == "income" else "📉"
        date_str = tx["created_at"][:10] if tx["created_at"] else "?"
        desc     = tx["description"] or "—"
        account  = tx.get("account_name") or "—"
        text    += t(l, "transaction_line",
                     emoji=emoji, date=date_str,
                     amount=f"{tx['amount']:,.2f}", currency=tx["currency"],
                     category=category_label(tx["category"], l), account=account, description=desc,
                     tags=_format_tags_suffix(tags_by_tx.get(tx["id"], [])))
    if len(text) > 4000:
        text = text[:4000] + "\n..."
    await query.edit_message_text(
        text,
        reply_markup=back_keyboard(uid, "menu_transactions"),
        parse_mode=ParseMode.MARKDOWN
    )


# ─────────────────── TRANSACTION HISTORY BY PERIOD ───────────────────

def _build_history_csv(uid: int, txns: list, l: str) -> bytes:
    """CSV of a period's full transaction history — column headers in the
    user's own language since this file is for them, not for re-import.
    utf-8-sig (BOM) so Excel opens Cyrillic text correctly instead of
    guessing the wrong codepage."""
    account_names = {a["id"]: a["name"] for a in db.get_accounts(uid)}
    tags_by_tx = db.get_tags_for_transactions([tx["id"] for tx in txns])
    buf = StringIO()
    writer = csv.writer(buf)
    writer.writerow([
        t(l, "history_col_date"), t(l, "history_col_type"), t(l, "history_col_category"),
        t(l, "history_col_account"), t(l, "history_col_amount"), t(l, "history_col_currency"),
        t(l, "history_col_description"), t(l, "history_col_tags"),
    ])
    for tx in txns:
        writer.writerow([
            (tx["created_at"] or "")[:10],
            t(l, "income") if tx["type"] == "income" else t(l, "expense"),
            category_label(tx["category"], l),
            account_names.get(tx["account_id"], "—"),
            f"{tx['amount']:.2f}",
            tx["currency"],
            tx["description"] or "",
            ", ".join(tags_by_tx.get(tx["id"], [])),
        ])
    return buf.getvalue().encode("utf-8-sig")


async def trans_history_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    uid = query.from_user.id
    l   = lang(uid)
    await query.edit_message_text(
        t(l, "choose_history_period"),
        reply_markup=history_period_keyboard(uid),
        parse_mode=ParseMode.MARKDOWN
    )


async def cb_trans_history_period(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query  = update.callback_query
    await query.answer()
    uid    = query.from_user.id
    l      = lang(uid)
    period = query.data[len("hist_p_"):]

    start, end, _ = finance.period_dates(period)
    txns = db.get_transactions_filtered(uid, start, end)
    txns.sort(key=lambda tx: tx["created_at"], reverse=True)

    if not txns:
        await query.edit_message_text(
            t(l, "no_transactions"),
            reply_markup=back_keyboard(uid, "menu_transactions"),
            parse_mode=ParseMode.MARKDOWN
        )
        return

    if period == "week":
        # Short enough to just show inline, same as the "last 20" view.
        account_names = {a["id"]: a["name"] for a in db.get_accounts(uid)}
        tags_by_tx = db.get_tags_for_transactions([tx["id"] for tx in txns])
        text = t(l, "transactions_header")
        for tx in txns:
            emoji    = "📈" if tx["type"] == "income" else "📉"
            date_str = tx["created_at"][:10] if tx["created_at"] else "?"
            text    += t(l, "transaction_line",
                         emoji=emoji, date=date_str,
                         amount=f"{tx['amount']:,.2f}", currency=tx["currency"],
                         category=category_label(tx["category"], l),
                         account=account_names.get(tx["account_id"], "—"),
                         description=tx["description"] or "—",
                         tags=_format_tags_suffix(tags_by_tx.get(tx["id"], [])))
        if len(text) > 4000:
            text = text[:4000] + "\n..."
        await query.edit_message_text(
            text,
            reply_markup=back_keyboard(uid, "menu_transactions"),
            parse_mode=ParseMode.MARKDOWN
        )
        return

    # month / 6m / year: a wall of chat text doesn't work at this size —
    # send a personal CSV file instead.
    await query.edit_message_text(t(l, "history_generating"), parse_mode=ParseMode.MARKDOWN)
    csv_bytes = _build_history_csv(uid, txns, l)
    filename  = f"transactions_{start}_{end}.csv"
    await context.bot.send_document(
        chat_id=uid,
        document=InputFile(BytesIO(csv_bytes), filename=filename),
        caption=t(l, "history_file_caption", start=start, end=end, count=len(txns)),
        parse_mode=ParseMode.MARKDOWN,
    )
    await query.edit_message_text(
        t(l, "history_file_sent"),
        reply_markup=back_keyboard(uid, "menu_transactions"),
        parse_mode=ParseMode.MARKDOWN
    )


# ─────────────────── DELETE INDIVIDUAL TRANSACTION ───────────────────

async def trans_delete_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    uid   = query.from_user.id
    l     = lang(uid)
    txns  = db.get_transactions(uid, limit=20)
    if not txns:
        await query.edit_message_text(
            t(l, "no_transactions"),
            reply_markup=back_keyboard(uid, "menu_transactions"),
            parse_mode=ParseMode.MARKDOWN,
        )
        return ConversationHandler.END
    await query.edit_message_text(
        t(l, "choose_transaction_to_delete"),
        reply_markup=_trans_select_keyboard(txns, uid),
        parse_mode=ParseMode.MARKDOWN,
    )
    return S_TRANS_SELECT_DELETE


async def trans_select_delete(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    uid   = query.from_user.id
    l     = lang(uid)
    tx_id = int(query.data.split("_")[1])
    db.delete_transaction(tx_id)
    await query.edit_message_text(t(l, "recalculating_goals"), parse_mode=ParseMode.MARKDOWN)
    conversion_rates = await _fetch_rates_if_needed(bool(db.get_goals(uid)))
    db.recalculate_all_goals(uid, conversion_rates)
    await query.edit_message_text(
        t(l, "transaction_deleted"),
        reply_markup=back_keyboard(uid, "menu_transactions"),
        parse_mode=ParseMode.MARKDOWN,
    )
    return ConversationHandler.END


# ─── Edit transaction category ───

async def trans_edit_category_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    uid   = query.from_user.id
    l     = lang(uid)
    txns  = db.get_transactions(uid, limit=20)
    if not txns:
        await query.edit_message_text(
            t(l, "no_transactions"),
            reply_markup=back_keyboard(uid, "menu_transactions"),
            parse_mode=ParseMode.MARKDOWN,
        )
        return ConversationHandler.END
    await query.edit_message_text(
        t(l, "choose_transaction_to_edit_category"),
        reply_markup=_trans_select_keyboard(txns, uid, callback_prefix="tcatedit"),
        parse_mode=ParseMode.MARKDOWN,
    )
    return S_TRANS_SELECT_EDIT_CATEGORY


async def trans_select_edit_category(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    uid   = query.from_user.id
    l     = lang(uid)
    tx_id = int(query.data.split("_")[1])
    tx    = db.get_transaction(tx_id)
    if not tx:
        await query.edit_message_text(
            t(l, "error"),
            reply_markup=back_keyboard(uid, "menu_transactions"),
            parse_mode=ParseMode.MARKDOWN,
        )
        return ConversationHandler.END
    context.user_data["edit_category_tx_id"]   = tx_id
    context.user_data["edit_category_tx_type"] = tx["type"]
    await query.edit_message_text(
        t(l, "choose_new_category"),
        reply_markup=category_keyboard(tx["type"], uid),
        parse_mode=ParseMode.MARKDOWN,
    )
    return S_TRANS_EDIT_CATEGORY_PICK


async def trans_edit_category_picked(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query    = update.callback_query
    await query.answer()
    uid      = query.from_user.id
    l        = lang(uid)
    cat_key  = query.data[len("cat_"):]
    tx_id    = context.user_data.get("edit_category_tx_id")
    t_type   = context.user_data.get("edit_category_tx_type", "expense")
    db.update_transaction_category(tx_id, cat_key)

    message_text = t(l, "transaction_category_updated", category=category_label(cat_key, l))

    if t_type == "expense":
        needs_rates = db.get_budget_by_category(uid, cat_key) is not None
        conversion_rates = await _fetch_rates_if_needed(needs_rates)
        message_text += _budget_warning_text(uid, cat_key, conversion_rates, l)

    context.user_data.pop("edit_category_tx_id", None)
    context.user_data.pop("edit_category_tx_type", None)

    await query.edit_message_text(
        message_text,
        reply_markup=back_keyboard(uid, "menu_transactions"),
        parse_mode=ParseMode.MARKDOWN,
    )
    return ConversationHandler.END


# ─── Split transaction into multiple categories ───

SPLIT_REMAINDER_EPSILON = 0.01


def _split_amount_keyboard(uid: int, remaining: float, currency: str) -> InlineKeyboardMarkup:
    l = lang(uid)
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(
            t(l, "split_finish_btn", amount=f"{remaining:,.2f}", currency=currency),
            callback_data="split_finish",
        )],
        [InlineKeyboardButton(t(l, "cancel"), callback_data="conv_cancel")],
    ])


async def trans_split_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    uid   = query.from_user.id
    l     = lang(uid)
    txns  = db.get_transactions(uid, limit=20)
    if not txns:
        await query.edit_message_text(
            t(l, "no_transactions"),
            reply_markup=back_keyboard(uid, "menu_transactions"),
            parse_mode=ParseMode.MARKDOWN,
        )
        return ConversationHandler.END
    await query.edit_message_text(
        t(l, "choose_transaction_to_split"),
        reply_markup=_trans_select_keyboard(txns, uid, callback_prefix="tsplit"),
        parse_mode=ParseMode.MARKDOWN,
    )
    return S_TRANS_SELECT_SPLIT


async def trans_select_split(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    uid   = query.from_user.id
    l     = lang(uid)
    tx_id = int(query.data.split("_")[1])
    tx    = db.get_transaction(tx_id)
    if not tx:
        await query.edit_message_text(
            t(l, "error"),
            reply_markup=back_keyboard(uid, "menu_transactions"),
            parse_mode=ParseMode.MARKDOWN,
        )
        return ConversationHandler.END

    context.user_data["split_tx_id"]         = tx_id
    context.user_data["split_type"]          = tx["type"]
    context.user_data["split_currency"]      = tx["currency"]
    context.user_data["split_original_amount"] = tx["amount"]
    context.user_data["split_remaining"]     = tx["amount"]
    context.user_data["split_parts"]         = []

    await query.edit_message_text(
        t(l, "split_enter_amount",
          total=f"{tx['amount']:,.2f}", currency=tx["currency"],
          remaining=f"{tx['amount']:,.2f}"),
        reply_markup=_split_amount_keyboard(uid, tx["amount"], tx["currency"]),
        parse_mode=ParseMode.MARKDOWN,
    )
    return S_SPLIT_AMOUNT


async def split_amount_entered(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    l   = lang(uid)
    remaining = context.user_data.get("split_remaining", 0.0)
    currency  = context.user_data.get("split_currency", "")
    try:
        amount = float(update.message.text.replace(",", "."))
        if amount <= 0 or amount > remaining + SPLIT_REMAINDER_EPSILON:
            raise ValueError
    except ValueError:
        await update.message.reply_text(
            t(l, "split_invalid_amount", remaining=f"{remaining:,.2f}", currency=currency)
        )
        return S_SPLIT_AMOUNT

    context.user_data["split_pending_amount"] = min(amount, remaining)
    await update.message.reply_text(
        t(l, "choose_new_category"),
        reply_markup=category_keyboard(context.user_data.get("split_type", "expense"), uid),
        parse_mode=ParseMode.MARKDOWN,
    )
    return S_SPLIT_CATEGORY


async def split_finish_clicked(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    uid = query.from_user.id
    l   = lang(uid)
    context.user_data["split_pending_amount"] = context.user_data.get("split_remaining", 0.0)
    await query.edit_message_text(
        t(l, "choose_new_category"),
        reply_markup=category_keyboard(context.user_data.get("split_type", "expense"), uid),
        parse_mode=ParseMode.MARKDOWN,
    )
    return S_SPLIT_CATEGORY


async def split_category_picked(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query    = update.callback_query
    await query.answer()
    uid      = query.from_user.id
    l        = lang(uid)
    cat_key  = query.data[len("cat_"):]
    amount   = context.user_data.get("split_pending_amount", 0.0)
    currency = context.user_data.get("split_currency", "")

    parts = context.user_data.setdefault("split_parts", [])
    parts.append({"amount": amount, "category": cat_key})
    remaining = max(0.0, context.user_data.get("split_remaining", 0.0) - amount)
    context.user_data["split_remaining"] = remaining

    if remaining <= SPLIT_REMAINDER_EPSILON:
        return await _finalize_split(query, context, uid, l)

    await query.edit_message_text(
        t(l, "split_enter_amount",
          total=f"{context.user_data.get('split_original_amount', 0.0):,.2f}", currency=currency,
          remaining=f"{remaining:,.2f}"),
        reply_markup=_split_amount_keyboard(uid, remaining, currency),
        parse_mode=ParseMode.MARKDOWN,
    )
    return S_SPLIT_AMOUNT


async def _finalize_split(query, context: ContextTypes.DEFAULT_TYPE, uid: int, l: str):
    tx_id    = context.user_data.get("split_tx_id")
    parts    = context.user_data.get("split_parts", [])
    t_type   = context.user_data.get("split_type", "expense")
    currency = context.user_data.get("split_currency", "")

    db.split_transaction(tx_id, parts)

    lines = "\n".join(
        f"• {category_label(p['category'], l)}: {p['amount']:,.2f} {currency}"
        for p in parts
    )
    message_text = t(l, "split_done", count=len(parts)) + "\n\n" + lines

    if t_type == "expense":
        touched_categories = {p["category"] for p in parts}
        needs_rates = any(db.get_budget_by_category(uid, c) is not None for c in touched_categories)
        conversion_rates = await _fetch_rates_if_needed(needs_rates)
        for c in touched_categories:
            message_text += _budget_warning_text(uid, c, conversion_rates, l)

    for key in ("split_tx_id", "split_type", "split_currency", "split_original_amount",
                "split_remaining", "split_parts", "split_pending_amount"):
        context.user_data.pop(key, None)

    await query.edit_message_text(
        message_text,
        reply_markup=back_keyboard(uid, "menu_transactions"),
        parse_mode=ParseMode.MARKDOWN,
    )
    return ConversationHandler.END


# ─── Transaction tags ───

MAX_TAGS_PER_SUBMIT = 10
MAX_TAG_LEN = 30


def _format_tags_suffix(tags: list) -> str:
    return f" 🏷{', '.join(tags)}" if tags else ""


def _tags_manage_keyboard(uid: int, has_tags: bool) -> InlineKeyboardMarkup:
    l = lang(uid)
    rows = [[InlineKeyboardButton(t(l, "tagop_add_btn"), callback_data="tagop_add")]]
    if has_tags:
        rows.append([InlineKeyboardButton(t(l, "tagop_remove_btn"), callback_data="tagop_remove")])
    rows.append([InlineKeyboardButton(t(l, "tagop_done_btn"), callback_data="tagop_done")])
    return InlineKeyboardMarkup(rows)


def _tags_remove_keyboard(tags: list, uid: int) -> InlineKeyboardMarkup:
    l = lang(uid)
    rows = [[InlineKeyboardButton(f"🗑 {tg}", callback_data=f"tagrm_{i}")] for i, tg in enumerate(tags)]
    rows.append([InlineKeyboardButton(t(l, "back"), callback_data="tagop_back")])
    return InlineKeyboardMarkup(rows)


def _tags_manage_view(uid: int, l: str, tx_id: int):
    tags = db.get_transaction_tags(tx_id)
    tags_text = ", ".join(tags) if tags else t(l, "no_tags_yet")
    return t(l, "tags_manage_header", tags=tags_text), _tags_manage_keyboard(uid, bool(tags))


async def trans_tags_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    uid  = query.from_user.id
    l    = lang(uid)
    txns = db.get_transactions(uid, limit=20)
    if not txns:
        await query.edit_message_text(
            t(l, "no_transactions"),
            reply_markup=back_keyboard(uid, "menu_transactions"),
            parse_mode=ParseMode.MARKDOWN,
        )
        return ConversationHandler.END
    await query.edit_message_text(
        t(l, "choose_transaction_to_tag"),
        reply_markup=_trans_select_keyboard(txns, uid, callback_prefix="ttags"),
        parse_mode=ParseMode.MARKDOWN,
    )
    return S_TRANS_SELECT_TAGS


async def trans_select_tags(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    uid   = query.from_user.id
    l     = lang(uid)
    tx_id = int(query.data.split("_")[1])
    if not db.get_transaction(tx_id):
        await query.edit_message_text(
            t(l, "error"),
            reply_markup=back_keyboard(uid, "menu_transactions"),
            parse_mode=ParseMode.MARKDOWN,
        )
        return ConversationHandler.END
    context.user_data["tags_tx_id"] = tx_id
    text, kb = _tags_manage_view(uid, l, tx_id)
    await query.edit_message_text(text, reply_markup=kb, parse_mode=ParseMode.MARKDOWN)
    return S_TAGS_MANAGE


async def tags_manage_router(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query  = update.callback_query
    await query.answer()
    uid    = query.from_user.id
    l      = lang(uid)
    action = query.data
    tx_id  = context.user_data.get("tags_tx_id")

    if action == "tagop_done":
        context.user_data.pop("tags_tx_id", None)
        await query.edit_message_text(
            t(l, "tags_done"),
            reply_markup=back_keyboard(uid, "menu_transactions"),
            parse_mode=ParseMode.MARKDOWN,
        )
        return ConversationHandler.END

    if action == "tagop_add":
        await query.edit_message_text(
            t(l, "enter_tags"),
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton(t(l, "cancel"), callback_data="conv_cancel")]
            ]),
            parse_mode=ParseMode.MARKDOWN,
        )
        return S_TAGS_ADD_INPUT

    # action == "tagop_remove"
    tags = db.get_transaction_tags(tx_id)
    context.user_data["tags_current"] = tags
    await query.edit_message_text(
        t(l, "choose_tag_to_remove"),
        reply_markup=_tags_remove_keyboard(tags, uid),
        parse_mode=ParseMode.MARKDOWN,
    )
    return S_TAGS_REMOVE_PICK


async def tags_add_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid   = update.effective_user.id
    l     = lang(uid)
    tx_id = context.user_data.get("tags_tx_id")

    candidates = [tg.strip()[:MAX_TAG_LEN] for tg in update.message.text.split(",")]
    candidates = [tg for tg in candidates if tg][:MAX_TAGS_PER_SUBMIT]
    if not candidates:
        await update.message.reply_text(t(l, "invalid_tags"))
        return S_TAGS_ADD_INPUT

    db.add_transaction_tags(tx_id, candidates)
    text, kb = _tags_manage_view(uid, l, tx_id)
    await update.message.reply_text(text, reply_markup=kb, parse_mode=ParseMode.MARKDOWN)
    return S_TAGS_MANAGE


async def tags_remove_pick(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    uid   = query.from_user.id
    l     = lang(uid)
    tx_id = context.user_data.get("tags_tx_id")

    if query.data != "tagop_back":
        idx  = int(query.data[len("tagrm_"):])
        tags = context.user_data.get("tags_current", [])
        if 0 <= idx < len(tags):
            db.remove_transaction_tag(tx_id, tags[idx])

    text, kb = _tags_manage_view(uid, l, tx_id)
    await query.edit_message_text(text, reply_markup=kb, parse_mode=ParseMode.MARKDOWN)
    return S_TAGS_MANAGE


async def trans_browse_tag_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    uid  = query.from_user.id
    l    = lang(uid)
    tags = db.get_user_tags(uid)
    if not tags:
        await query.edit_message_text(
            t(l, "no_tags_yet_global"),
            reply_markup=back_keyboard(uid, "menu_transactions"),
            parse_mode=ParseMode.MARKDOWN,
        )
        return ConversationHandler.END
    context.user_data["browse_tags_list"] = tags
    rows = [[InlineKeyboardButton(f"🏷 {tg}", callback_data=f"tagbrowse_{i}")] for i, tg in enumerate(tags)]
    rows.append([InlineKeyboardButton(t(l, "cancel"), callback_data="conv_cancel")])
    await query.edit_message_text(
        t(l, "choose_tag_to_browse"),
        reply_markup=InlineKeyboardMarkup(rows),
        parse_mode=ParseMode.MARKDOWN,
    )
    return S_TAGS_BROWSE_PICK


async def trans_browse_tag_picked(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    uid  = query.from_user.id
    l    = lang(uid)
    idx  = int(query.data[len("tagbrowse_"):])
    tags = context.user_data.get("browse_tags_list", [])
    if not (0 <= idx < len(tags)):
        await query.edit_message_text(
            t(l, "error"),
            reply_markup=back_keyboard(uid, "menu_transactions"),
            parse_mode=ParseMode.MARKDOWN,
        )
        return ConversationHandler.END

    tag = tags[idx]
    txns = db.get_transactions_by_tag(uid, tag)[:20]
    account_names = {a["id"]: a["name"] for a in db.get_accounts(uid)}
    tags_by_tx = db.get_tags_for_transactions([tx["id"] for tx in txns])

    text = t(l, "tag_transactions_header", tag=tag)
    for tx in txns:
        emoji    = "📈" if tx["type"] == "income" else "📉"
        date_str = tx["created_at"][:10] if tx["created_at"] else "?"
        text    += t(l, "transaction_line",
                     emoji=emoji, date=date_str,
                     amount=f"{tx['amount']:,.2f}", currency=tx["currency"],
                     category=category_label(tx["category"], l),
                     account=account_names.get(tx["account_id"], "—"),
                     description=tx["description"] or "—",
                     tags=_format_tags_suffix(tags_by_tx.get(tx["id"], [])))
    if len(text) > 4000:
        text = text[:4000] + "\n..."

    context.user_data.pop("browse_tags_list", None)
    await query.edit_message_text(
        text,
        reply_markup=back_keyboard(uid, "menu_transactions"),
        parse_mode=ParseMode.MARKDOWN,
    )
    return ConversationHandler.END


async def cb_clear_transactions(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    uid = query.from_user.id
    l   = lang(uid)
    await query.edit_message_text(
        t(l, "confirm_clear_transactions"),
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton(t(l, "btn_yes"), callback_data="trans_clear_confirm"),
             InlineKeyboardButton(t(l, "btn_no"),  callback_data="back_transactions")],
        ]),
        parse_mode=ParseMode.MARKDOWN
    )


async def cb_clear_transactions_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    uid   = query.from_user.id
    l     = lang(uid)
    count = db.delete_all_transactions(uid)
    # Recalculate goals after clearing all transactions
    conversion_rates = await _fetch_rates_if_needed(bool(db.get_goals(uid)))
    db.recalculate_all_goals(uid, conversion_rates)
    await query.edit_message_text(
        t(l, "transactions_cleared", count=count),
        reply_markup=back_keyboard(uid, "menu_transactions"),
        parse_mode=ParseMode.MARKDOWN
    )


# ─────────────────── ACCOUNTS ───────────────────

async def handle_view_accounts(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query    = update.callback_query
    uid      = query.from_user.id
    l        = lang(uid)
    accounts = db.get_accounts_with_balances(uid)
    if not accounts:
        await query.edit_message_text(
            t(l, "no_accounts"),
            reply_markup=back_keyboard(uid, "menu_accounts"),
            parse_mode=ParseMode.MARKDOWN
        )
        return
    text = t(l, "accounts_header")
    for acc in accounts:
        emoji = ACCOUNT_TYPE_EMOJI.get(acc["account_type"], "🏦")
        text += t(l, "account_line",
                  emoji=emoji, name=acc["name"],
                  type=_account_type_label(acc["account_type"], l),
                  balance=acc["computed_balance"], currency=acc["currency"])
    await query.edit_message_text(
        text,
        reply_markup=back_keyboard(uid, "menu_accounts"),
        parse_mode=ParseMode.MARKDOWN
    )


# ─── Add account conversation ───

async def account_add_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    uid = query.from_user.id
    l   = lang(uid)
    await query.edit_message_text(
        t(l, "choose_account_type"),
        reply_markup=account_type_keyboard(uid),
        parse_mode=ParseMode.MARKDOWN
    )
    return S_ACCOUNT_TYPE


async def account_type_chosen(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    uid   = query.from_user.id
    l     = lang(uid)
    atype = query.data.split("_")[1]   # bank / crypto / cash
    context.user_data["account_type"] = atype
    await query.edit_message_text(t(l, "enter_account_name"), parse_mode=ParseMode.MARKDOWN)
    return S_ACCOUNT_NAME


async def account_name_entered(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid  = update.effective_user.id
    l    = lang(uid)
    name = update.message.text.strip()
    if not name:
        await update.message.reply_text(t(l, "invalid_input"))
        return S_ACCOUNT_NAME
    context.user_data["account_name"] = name
    await update.message.reply_text(
        t(l, "enter_account_currency"),
        reply_markup=currency_keyboard("acur", uid),
        parse_mode=ParseMode.MARKDOWN
    )
    return S_ACCOUNT_CURRENCY


async def account_currency_chosen(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query    = update.callback_query
    await query.answer()
    uid      = query.from_user.id
    l        = lang(uid)
    currency = query.data.split("_", 1)[1]
    context.user_data["account_currency"] = currency
    await query.edit_message_text(t(l, "enter_account_balance"), parse_mode=ParseMode.MARKDOWN)
    return S_ACCOUNT_BALANCE


async def account_balance_entered(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    l   = lang(uid)
    try:
        balance = float(update.message.text.replace(",", "."))
        if balance < 0:
            raise ValueError
    except ValueError:
        await update.message.reply_text(t(l, "invalid_amount"))
        return S_ACCOUNT_BALANCE

    ud       = context.user_data
    atype    = ud["account_type"]
    name     = ud["account_name"]
    currency = ud["account_currency"]

    db.add_account(uid, name, currency, balance, atype)

    # Recalculate goal progress now that a new account with balance exists
    conversion_rates = await _fetch_rates_if_needed(bool(db.get_goals(uid)))
    db.recalculate_all_goals(uid, conversion_rates)

    emoji     = ACCOUNT_TYPE_EMOJI.get(atype, "🏦")
    type_label = _account_type_label(atype, l)
    await update.message.reply_text(
        t(l, "account_saved",
          name=f"{emoji} {name}", type=type_label,
          balance=f"{balance:,.2f}", currency=currency),
        reply_markup=back_keyboard(uid, "menu_accounts"),
        parse_mode=ParseMode.MARKDOWN
    )
    return ConversationHandler.END


# ─── Delete account conversation ───

async def account_delete_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query    = update.callback_query
    await query.answer()
    uid      = query.from_user.id
    l        = lang(uid)
    accounts = db.get_accounts_with_balances(uid)
    if not accounts:
        await query.edit_message_text(
            t(l, "no_accounts"),
            reply_markup=back_keyboard(uid, "menu_accounts"),
            parse_mode=ParseMode.MARKDOWN
        )
        return ConversationHandler.END
    await query.edit_message_text(
        t(l, "choose_account_to_delete"),
        reply_markup=accounts_select_keyboard(accounts, "adel", uid),
        parse_mode=ParseMode.MARKDOWN
    )
    return S_ACCOUNT_SELECT_DELETE


async def account_select_delete(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query      = update.callback_query
    await query.answer()
    uid        = query.from_user.id
    l          = lang(uid)
    account_id = int(query.data.split("_")[1])
    db.delete_account(account_id)
    # Recalculate goals after account deletion
    conversion_rates = await _fetch_rates_if_needed(bool(db.get_goals(uid)))
    db.recalculate_all_goals(uid, conversion_rates)
    await query.edit_message_text(
        t(l, "account_deleted"),
        reply_markup=back_keyboard(uid, "menu_accounts"),
        parse_mode=ParseMode.MARKDOWN
    )
    return ConversationHandler.END


# ─────────────────── EDIT ACCOUNT BALANCE ───────────────────

async def account_edit_balance_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    uid = query.from_user.id
    l   = lang(uid)
    accounts = db.get_accounts_with_balances(uid)
    if not accounts:
        await query.edit_message_text(
            t(l, "no_accounts"),
            reply_markup=back_keyboard(uid, "menu_accounts"),
            parse_mode=ParseMode.MARKDOWN
        )
        return ConversationHandler.END
    await query.edit_message_text(
        t(l, "choose_account_to_edit_balance"),
        reply_markup=accounts_select_keyboard(accounts, "aeditbal", uid),
        parse_mode=ParseMode.MARKDOWN
    )
    return S_ACCOUNT_EDIT_SELECT


async def account_edit_balance_selected(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query      = update.callback_query
    await query.answer()
    uid        = query.from_user.id
    l          = lang(uid)
    account_id = int(query.data.split("_")[1])
    acc = db.get_account(account_id)
    context.user_data["edit_balance_account_id"]   = account_id
    context.user_data["edit_balance_account_name"] = acc["name"] if acc else "?"
    context.user_data["edit_balance_currency"]      = acc["currency"] if acc else "USD"
    await query.edit_message_text(
        t(l, "enter_new_initial_balance",
          name=acc["name"] if acc else "?",
          current=f"{acc['initial_balance']:,.2f}" if acc else "0.00",
          currency=acc["currency"] if acc else ""),
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton(t(l, "cancel"), callback_data="conv_cancel")]
        ]),
        parse_mode=ParseMode.MARKDOWN
    )
    return S_ACCOUNT_EDIT_BALANCE


async def account_edit_balance_entered(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    l   = lang(uid)
    try:
        balance = float(update.message.text.replace(",", "."))
        if balance < 0:
            raise ValueError
    except ValueError:
        await update.message.reply_text(t(l, "invalid_amount"))
        return S_ACCOUNT_EDIT_BALANCE

    account_id = context.user_data["edit_balance_account_id"]
    name       = context.user_data.get("edit_balance_account_name", "?")
    currency   = context.user_data.get("edit_balance_currency", "")
    db.update_account_initial_balance(account_id, balance)

    # The account's computed balance depends on this, so goal progress
    # (which tracks account balances) needs to catch up.
    conversion_rates = await _fetch_rates_if_needed(bool(db.get_goals(uid)))
    db.recalculate_all_goals(uid, conversion_rates)

    context.user_data.pop("edit_balance_account_id", None)
    context.user_data.pop("edit_balance_account_name", None)
    context.user_data.pop("edit_balance_currency", None)

    await update.message.reply_text(
        t(l, "account_balance_updated", name=name, balance=f"{balance:,.2f}", currency=currency),
        reply_markup=back_keyboard(uid, "menu_accounts"),
        parse_mode=ParseMode.MARKDOWN
    )
    return ConversationHandler.END


# ─────────────────── CSV STATEMENT IMPORT ───────────────────

async def import_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    uid = query.from_user.id
    l   = lang(uid)
    accounts = db.get_accounts_with_balances(uid)
    if not accounts:
        await query.edit_message_text(
            t(l, "no_accounts"),
            reply_markup=back_keyboard(uid, "menu_accounts"),
            parse_mode=ParseMode.MARKDOWN
        )
        return ConversationHandler.END
    await query.edit_message_text(
        t(l, "import_choose_account"),
        reply_markup=accounts_select_keyboard(accounts, "impacc", uid),
        parse_mode=ParseMode.MARKDOWN
    )
    return S_IMPORT_ACCOUNT


async def import_account_chosen(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query      = update.callback_query
    await query.answer()
    uid        = query.from_user.id
    l          = lang(uid)
    account_id = int(query.data.split("_")[1])
    acc = db.get_account(account_id)
    context.user_data["import_account_id"]       = account_id
    context.user_data["import_account_name"]     = acc["name"] if acc else "?"
    context.user_data["import_account_currency"] = acc["currency"] if acc else "USD"
    await query.edit_message_text(
        t(l, "import_send_file"),
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton(t(l, "cancel"), callback_data="conv_cancel")]
        ]),
        parse_mode=ParseMode.MARKDOWN
    )
    return S_IMPORT_FILE


async def import_file_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    l   = lang(uid)
    doc = update.message.document
    if not doc or not (doc.file_name or "").lower().endswith(".csv"):
        await update.message.reply_text(t(l, "import_wrong_file_type"))
        return S_IMPORT_FILE

    tg_file = await context.bot.get_file(doc.file_id)
    raw = bytes(await tg_file.download_as_bytearray())

    try:
        rows, errors = csv_import.parse_statement(raw)
    except csv_import.CsvImportError as e:
        key = f"import_parse_error_{e}"
        translated = t(l, key)
        await update.message.reply_text(translated if translated != key else t(l, "import_parse_error_generic"))
        return S_IMPORT_FILE

    if not rows:
        await update.message.reply_text(t(l, "import_no_valid_rows"))
        return S_IMPORT_FILE

    account_id = context.user_data["import_account_id"]
    dates = [r["date"] for r in rows]
    existing = db.get_existing_transaction_signatures(uid, account_id, min(dates), max(dates))

    # existing is a count per signature, not just a yes/no set — two rows in
    # this file that happen to share a signature (e.g. two identical same-day
    # coffee purchases) must each be checked against how many matches are
    # already in the DB, or a real repeat transaction gets skipped as a
    # false duplicate. `seen` tracks how many duplicate-credits this file
    # has already consumed per signature.
    seen = Counter()
    to_import = []
    duplicates = 0
    for r in rows:
        sig = (r["date"], r["amount"], r["type"], r["description"])
        seen[sig] += 1
        if seen[sig] <= existing.get(sig, 0):
            duplicates += 1
            continue
        to_import.append(r)

    income_n  = sum(1 for r in rows if r["type"] == "income")
    expense_n = sum(1 for r in rows if r["type"] == "expense")
    account_name = context.user_data.get("import_account_name", "?")

    if not to_import:
        await update.message.reply_text(
            t(l, "import_preview",
              found=len(rows), income=income_n, expense=expense_n,
              duplicates=duplicates, errors=len(errors),
              to_import=0, account=account_name),
            parse_mode=ParseMode.MARKDOWN,
        )
        return ConversationHandler.END

    context.user_data["import_rows"] = to_import
    await update.message.reply_text(
        t(l, "import_preview",
          found=len(rows), income=income_n, expense=expense_n,
          duplicates=duplicates, errors=len(errors),
          to_import=len(to_import), account=account_name),
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton(t(l, "import_confirm_btn"), callback_data="import_confirm")],
            [InlineKeyboardButton(t(l, "cancel"),              callback_data="conv_cancel")],
        ]),
        parse_mode=ParseMode.MARKDOWN,
    )
    return S_IMPORT_CONFIRM


async def import_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    uid = query.from_user.id
    l   = lang(uid)
    account_id    = context.user_data.get("import_account_id")
    currency      = context.user_data.get("import_account_currency", "USD")
    account_name  = context.user_data.get("import_account_name", "?")
    rows          = context.user_data.get("import_rows", [])

    db.add_transactions_bulk(uid, account_id, currency, rows)

    conversion_rates = await _fetch_rates_if_needed(bool(db.get_goals(uid)))
    db.recalculate_all_goals(uid, conversion_rates)

    context.user_data.pop("import_rows", None)
    context.user_data.pop("import_account_id", None)
    context.user_data.pop("import_account_name", None)
    context.user_data.pop("import_account_currency", None)

    await query.edit_message_text(
        t(l, "import_done", count=len(rows), account=account_name),
        reply_markup=back_keyboard(uid, "menu_accounts"),
        parse_mode=ParseMode.MARKDOWN
    )
    return ConversationHandler.END


# ─────────────────── CUSTOM CATEGORIES ───────────────────

MAX_CATEGORY_NAME_LEN = 40
MAX_CATEGORY_EMOJI_LEN = 8


async def handle_view_categories(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    uid   = query.from_user.id
    l     = lang(uid)
    categories = db.get_custom_categories(uid)
    if not categories:
        await query.edit_message_text(
            t(l, "no_custom_categories"),
            reply_markup=back_keyboard(uid, "menu_categories"),
            parse_mode=ParseMode.MARKDOWN
        )
        return
    type_labels = {
        "income": t(l, "category_type_income"),
        "expense": t(l, "category_type_expense"),
        "both": t(l, "category_type_both"),
    }
    text = t(l, "categories_header")
    for c in categories:
        text += t(l, "category_line",
                  emoji=c["emoji"], name=c["name"],
                  type=type_labels.get(c["category_type"], c["category_type"]))
    await query.edit_message_text(
        text,
        reply_markup=back_keyboard(uid, "menu_categories"),
        parse_mode=ParseMode.MARKDOWN
    )


async def category_add_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    uid = query.from_user.id
    l   = lang(uid)
    await query.edit_message_text(
        t(l, "choose_category_type"),
        reply_markup=category_type_keyboard(uid),
        parse_mode=ParseMode.MARKDOWN
    )
    return S_CATEGORY_TYPE


async def category_type_chosen(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    uid = query.from_user.id
    l   = lang(uid)
    context.user_data["new_category_type"] = query.data[len("cattype_"):]
    await query.edit_message_text(
        t(l, "enter_category_name"),
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton(t(l, "cancel"), callback_data="conv_cancel")]
        ]),
        parse_mode=ParseMode.MARKDOWN
    )
    return S_CATEGORY_NAME


async def category_name_entered(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid  = update.effective_user.id
    l    = lang(uid)
    name = update.message.text.strip()
    if not name or len(name) > MAX_CATEGORY_NAME_LEN:
        await update.message.reply_text(t(l, "invalid_category_name", max=MAX_CATEGORY_NAME_LEN))
        return S_CATEGORY_NAME
    context.user_data["new_category_name"] = name
    await update.message.reply_text(t(l, "enter_category_emoji"), parse_mode=ParseMode.MARKDOWN)
    return S_CATEGORY_EMOJI


async def category_emoji_entered(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid   = update.effective_user.id
    l     = lang(uid)
    emoji = update.message.text.strip()
    if not emoji or len(emoji) > MAX_CATEGORY_EMOJI_LEN:
        await update.message.reply_text(t(l, "invalid_category_emoji", max=MAX_CATEGORY_EMOJI_LEN))
        return S_CATEGORY_EMOJI

    name          = context.user_data.get("new_category_name", "?")
    category_type = context.user_data.get("new_category_type", "both")
    db.add_custom_category(uid, name, emoji, category_type)

    context.user_data.pop("new_category_type", None)
    context.user_data.pop("new_category_name", None)

    await update.message.reply_text(
        t(l, "category_added", emoji=emoji, name=name),
        reply_markup=back_keyboard(uid, "menu_categories"),
        parse_mode=ParseMode.MARKDOWN
    )
    return ConversationHandler.END


async def category_delete_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    uid = query.from_user.id
    l   = lang(uid)
    categories = db.get_custom_categories(uid)
    if not categories:
        await query.edit_message_text(
            t(l, "no_custom_categories"),
            reply_markup=back_keyboard(uid, "menu_categories"),
            parse_mode=ParseMode.MARKDOWN
        )
        return ConversationHandler.END
    await query.edit_message_text(
        t(l, "choose_category_to_delete"),
        reply_markup=categories_select_keyboard(categories, uid),
        parse_mode=ParseMode.MARKDOWN
    )
    return S_CATEGORY_SELECT_DELETE


async def category_select_delete(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    uid = query.from_user.id
    l   = lang(uid)
    key = query.data[len("ccatdel_"):]
    db.delete_custom_category(uid, key)
    await query.edit_message_text(
        t(l, "category_deleted"),
        reply_markup=back_keyboard(uid, "menu_categories"),
        parse_mode=ParseMode.MARKDOWN
    )
    return ConversationHandler.END


# ─────────────────── BUDGETS ───────────────────

async def handle_view_budgets(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query   = update.callback_query
    uid     = query.from_user.id
    l       = lang(uid)
    budgets = db.get_budgets(uid)
    if not budgets:
        await query.edit_message_text(
            t(l, "no_budgets"),
            reply_markup=back_keyboard(uid, "menu_budgets"),
            parse_mode=ParseMode.MARKDOWN
        )
        return

    await query.edit_message_text(t(l, "fetching_rates"), parse_mode=ParseMode.MARKDOWN)
    conversion_rates = {"fiat": {}, "crypto": {}, "metals": {}}
    try:
        conversion_rates["fiat"], conversion_rates["crypto"], conversion_rates["metals"] = \
            await cur.fetch_all_rates()
    except Exception:
        pass

    text = t(l, "budgets_header")
    any_incomplete = False
    for b in budgets:
        spent, all_converted = finance.spent_this_month(uid, b["category"], b["currency"], conversion_rates)
        any_incomplete = any_incomplete or not all_converted
        pct = min(999, round(spent / b["amount"] * 100)) if b["amount"] else 0
        bar = _progress_bar(pct)
        text += t(l, "budget_line",
                  category=category_label(b["category"], l),
                  spent=f"{spent:,.2f}", amount=f"{b['amount']:,.2f}",
                  currency=b["currency"], pct=pct, bar=bar)
    if any_incomplete:
        text += "\n" + t(l, "rates_incomplete_note")

    await query.edit_message_text(
        text,
        reply_markup=back_keyboard(uid, "menu_budgets"),
        parse_mode=ParseMode.MARKDOWN
    )


def _progress_bar(pct: int, length: int = 10) -> str:
    filled = min(length, round(pct / 100 * length))
    return "🟥" * filled + "⬜" * (length - filled) if pct >= 100 else "🟩" * filled + "⬜" * (length - filled)


# ─── Add / update budget conversation ───

async def budget_add_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    uid   = query.from_user.id
    l     = lang(uid)
    existing = {b["category"] for b in db.get_budgets(uid)}
    await query.edit_message_text(
        t(l, "choose_budget_category"),
        reply_markup=budget_category_keyboard(uid, existing),
        parse_mode=ParseMode.MARKDOWN
    )
    return S_BUDGET_CATEGORY


async def budget_category_chosen(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query    = update.callback_query
    await query.answer()
    uid      = query.from_user.id
    l        = lang(uid)
    cat_key  = query.data[len("bcat_"):]
    context.user_data["budget_category"] = cat_key
    await query.edit_message_text(
        t(l, "enter_budget_amount", category=category_label(cat_key, l)),
        parse_mode=ParseMode.MARKDOWN
    )
    return S_BUDGET_AMOUNT


async def budget_amount_entered(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    l   = lang(uid)
    try:
        amount = float(update.message.text.replace(",", "."))
        if amount <= 0:
            raise ValueError
    except ValueError:
        await update.message.reply_text(t(l, "invalid_amount"))
        return S_BUDGET_AMOUNT

    cat_key  = context.user_data.get("budget_category")
    currency = db.get_user_base_currency(uid)
    db.set_budget(uid, cat_key, amount, currency)

    await update.message.reply_text(
        t(l, "budget_saved",
          category=category_label(cat_key, l),
          amount=f"{amount:,.2f}", currency=currency),
        reply_markup=back_keyboard(uid, "menu_budgets"),
        parse_mode=ParseMode.MARKDOWN
    )
    return ConversationHandler.END


# ─── Delete budget conversation ───

async def budget_delete_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query   = update.callback_query
    await query.answer()
    uid     = query.from_user.id
    l       = lang(uid)
    budgets = db.get_budgets(uid)
    if not budgets:
        await query.edit_message_text(
            t(l, "no_budgets"),
            reply_markup=back_keyboard(uid, "menu_budgets"),
            parse_mode=ParseMode.MARKDOWN
        )
        return ConversationHandler.END
    await query.edit_message_text(
        t(l, "choose_budget_to_delete"),
        reply_markup=budgets_select_keyboard(budgets, uid),
        parse_mode=ParseMode.MARKDOWN
    )
    return S_BUDGET_SELECT_DELETE


async def budget_select_delete(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query      = update.callback_query
    await query.answer()
    uid        = query.from_user.id
    l          = lang(uid)
    budget_id  = int(query.data.split("_")[1])
    db.delete_budget(budget_id)
    await query.edit_message_text(
        t(l, "budget_deleted"),
        reply_markup=back_keyboard(uid, "menu_budgets"),
        parse_mode=ParseMode.MARKDOWN
    )
    return ConversationHandler.END


# ─────────────────── ADD TRANSACTION ───────────────────

async def trans_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Entry: check accounts exist, then ask to pick one."""
    query = update.callback_query
    await query.answer()
    uid   = query.from_user.id
    l     = lang(uid)

    # Require at least one account
    accounts = db.get_accounts_with_balances(uid)
    if not accounts:
        await query.edit_message_text(
            t(l, "no_accounts_for_transaction"),
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton(t(l, "btn_add_account"), callback_data="account_add")],
                [InlineKeyboardButton(t(l, "back"),            callback_data="menu_transactions")],
            ]),
            parse_mode=ParseMode.MARKDOWN
        )
        return ConversationHandler.END

    t_type = "income" if query.data == "trans_add_income" else "expense"
    context.user_data["trans_type"]     = t_type
    context.user_data["trans_accounts"] = accounts   # cache for next step

    await query.edit_message_text(
        t(l, "choose_account_for_transaction"),
        reply_markup=accounts_select_keyboard(accounts, "tacc", uid),
        parse_mode=ParseMode.MARKDOWN
    )
    return S_TRANS_ACCOUNT


async def trans_account_selected(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query      = update.callback_query
    await query.answer()
    uid        = query.from_user.id
    l          = lang(uid)
    account_id = int(query.data.split("_")[1])

    # Fetch the chosen account so we know its currency
    acc = db.get_account(account_id)
    context.user_data["trans_account_id"]       = account_id
    context.user_data["trans_account_name"]     = acc["name"] if acc else "?"
    context.user_data["trans_account_currency"] = acc["currency"] if acc else "USD"

    await query.edit_message_text(
        t(l, "enter_amount"),
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton(t(l, "cancel"), callback_data="conv_cancel")]
        ]),
        parse_mode=ParseMode.MARKDOWN
    )
    return S_TRANS_AMOUNT


async def trans_amount(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    l   = lang(uid)
    try:
        amount = float(update.message.text.replace(",", "."))
        if amount <= 0:
            raise ValueError
    except ValueError:
        await update.message.reply_text(t(l, "invalid_amount"))
        return S_TRANS_AMOUNT
    context.user_data["trans_amount"] = amount
    # A transaction's currency is always its account's currency — this keeps
    # account balances (a plain sum of transaction amounts) meaningful, and
    # skips an extra tap since we already know the account.
    context.user_data["trans_currency"] = context.user_data.get("trans_account_currency", "USD")
    t_type = context.user_data.get("trans_type", "expense")
    await update.message.reply_text(
        t(l, "enter_category"),
        reply_markup=category_keyboard(t_type, uid),
        parse_mode=ParseMode.MARKDOWN
    )
    return S_TRANS_CATEGORY


async def trans_category(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query      = update.callback_query
    await query.answer()
    uid        = query.from_user.id
    l          = lang(uid)
    cat_key    = query.data[len("cat_"):]     # "cat_food" → "food"
    context.user_data["trans_category"] = cat_key
    await query.edit_message_text(t(l, "enter_description"), parse_mode=ParseMode.MARKDOWN)
    return S_TRANS_DESC


async def trans_description(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid  = update.effective_user.id
    l    = lang(uid)
    desc = "" if update.message.text == "/skip" else update.message.text
    ud   = context.user_data

    t_type     = ud.get("trans_type", "expense")
    account_id = ud.get("trans_account_id")
    acc_name   = ud.get("trans_account_name", "—")

    db.add_transaction(
        uid, t_type,
        ud["trans_amount"], ud["trans_currency"],
        ud["trans_category"], desc,
        account_id=account_id
    )

    # Recalculate all goal progress from account balances. Rates are also
    # needed to check an expense against a budget in a different currency,
    # even for a user with no goals at all.
    needs_rates = bool(db.get_goals(uid)) or (
        t_type == "expense" and db.get_budget_by_category(uid, ud["trans_category"]) is not None
    )
    conversion_rates = await _fetch_rates_if_needed(needs_rates)

    updated_goals = db.update_goals_from_transaction(
        uid, ud["trans_amount"], ud["trans_currency"], conversion_rates
    )

    type_label   = t(l, "income") if t_type == "income" else t(l, "expense")
    message_text = t(l, "transaction_saved",
                     type=type_label,
                     account=acc_name,
                     amount=f"{ud['trans_amount']:,.2f}",
                     currency=ud["trans_currency"],
                     category=category_label(ud["trans_category"], l),
                     description=desc or "—")

    if updated_goals:
        message_text += f"\n\n📊 {t(l, 'goal_progress_updated')}:\n"
        for goal in updated_goals:
            status        = "✅ " + t(l, "goal_completed") if goal["completed"] else ""
            message_text += f"\n• {goal['title']}: {goal['current_amount']:,.2f}/{goal['target_amount']:,.2f} {goal['currency']} {status}"

    if t_type == "expense":
        message_text += _budget_warning_text(uid, ud["trans_category"], conversion_rates, l)

    await update.message.reply_text(
        message_text,
        reply_markup=back_keyboard(uid, "menu_transactions"),
        parse_mode=ParseMode.MARKDOWN
    )
    return ConversationHandler.END


# ─────────────────── ADD GOAL ───────────────────

async def goal_add_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    uid = query.from_user.id
    l   = lang(uid)
    await query.edit_message_text(
        t(l, "choose_goal_type"),
        reply_markup=goal_type_keyboard(uid),
        parse_mode=ParseMode.MARKDOWN
    )
    return S_GOAL_TYPE


async def goal_type(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    uid    = query.from_user.id
    l      = lang(uid)
    chosen = "save" if query.data == "gtype_save" else "repay"
    context.user_data["goal_type"] = chosen
    await query.edit_message_text(t(l, "enter_goal_title"), parse_mode=ParseMode.MARKDOWN)
    return S_GOAL_TITLE


async def goal_title(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    l   = lang(uid)
    context.user_data["goal_title"] = update.message.text
    await update.message.reply_text(t(l, "enter_goal_amount"), parse_mode=ParseMode.MARKDOWN)
    return S_GOAL_AMOUNT


async def goal_amount(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    l   = lang(uid)
    try:
        amount = float(update.message.text.replace(",", "."))
        if amount <= 0:
            raise ValueError
    except ValueError:
        await update.message.reply_text(t(l, "invalid_amount"))
        return S_GOAL_AMOUNT
    context.user_data["goal_amount"] = amount
    await update.message.reply_text(
        t(l, "enter_goal_currency"),
        reply_markup=currency_keyboard("gcur", uid),
        parse_mode=ParseMode.MARKDOWN
    )
    return S_GOAL_CURRENCY


async def goal_currency(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    uid    = query.from_user.id
    l      = lang(uid)
    chosen = query.data.split("_", 1)[1]
    context.user_data["goal_currency"] = chosen
    await query.edit_message_text(t(l, "enter_goal_deadline"), parse_mode=ParseMode.MARKDOWN)
    return S_GOAL_DEADLINE


async def goal_deadline(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid      = update.effective_user.id
    l        = lang(uid)
    text     = update.message.text
    deadline = None

    if text != "/skip":
        try:
            datetime.strptime(text, "%Y-%m-%d")
            deadline = text
        except ValueError:
            await update.message.reply_text(t(l, "invalid_input"))
            return S_GOAL_DEADLINE

    ud = context.user_data
    conversion_rates = {"fiat": {}, "crypto": {}, "metals": {}}
    try:
        conversion_rates["fiat"], conversion_rates["crypto"], conversion_rates["metals"] = \
            await cur.fetch_all_rates()
    except Exception:
        pass

    initial_amount = db.calculate_initial_goal_amount(uid, ud["goal_currency"], conversion_rates)

    db.add_goal(uid, ud["goal_title"], ud["goal_type"],
                ud["goal_amount"], ud["goal_currency"], deadline,
                initial_amount=initial_amount)

    pct = min(100, round(initial_amount / ud["goal_amount"] * 100)) if ud["goal_amount"] else 0

    await update.message.reply_text(
        t(l, "goal_saved",
          title=ud["goal_title"],
          amount=f"{ud['goal_amount']:,.2f}",
          currency=ud["goal_currency"],
          deadline=deadline or "—",
          initial=f"{initial_amount:,.2f}",
          pct=pct),
        reply_markup=back_keyboard(uid, "menu_goals"),
        parse_mode=ParseMode.MARKDOWN
    )
    return ConversationHandler.END


# ─────────────────── VIEW GOALS ───────────────────

async def handle_view_goals(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    uid   = query.from_user.id
    l     = lang(uid)
    goals = db.get_goals(uid)
    text  = format_goals_text(goals, l)
    await query.edit_message_text(
        text,
        reply_markup=back_keyboard(uid, "menu_goals"),
        parse_mode=ParseMode.MARKDOWN
    )


# ─────────────────── DELETE GOAL ───────────────────

async def goal_delete_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    uid   = query.from_user.id
    l     = lang(uid)
    goals = db.get_goals(uid)
    if not goals:
        await query.edit_message_text(
            t(l, "no_goals"),
            reply_markup=back_keyboard(uid, "menu_goals"),
            parse_mode=ParseMode.MARKDOWN
        )
        return ConversationHandler.END
    await query.edit_message_text(
        t(l, "choose_goal_to_delete"),
        reply_markup=goals_select_keyboard(goals, "gdel", uid),
        parse_mode=ParseMode.MARKDOWN
    )
    return S_GOAL_SELECT_DELETE


async def goal_select_delete(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query   = update.callback_query
    await query.answer()
    uid     = query.from_user.id
    l       = lang(uid)
    goal_id = int(query.data.split("_")[1])
    db.delete_goal(goal_id)
    await query.edit_message_text(
        t(l, "goal_deleted"),
        reply_markup=back_keyboard(uid, "menu_goals"),
        parse_mode=ParseMode.MARKDOWN
    )
    return ConversationHandler.END


# ─────────────────── EDIT GOAL TARGET AMOUNT ───────────────────

async def goal_edit_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    uid   = query.from_user.id
    l     = lang(uid)
    goals = db.get_goals(uid)
    if not goals:
        await query.edit_message_text(
            t(l, "no_goals"),
            reply_markup=back_keyboard(uid, "menu_goals"),
            parse_mode=ParseMode.MARKDOWN
        )
        return ConversationHandler.END
    await query.edit_message_text(
        t(l, "choose_goal_to_edit"),
        reply_markup=goals_select_keyboard(goals, "gedit", uid),
        parse_mode=ParseMode.MARKDOWN
    )
    return S_GOAL_SELECT_EDIT


async def goal_select_edit(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query   = update.callback_query
    await query.answer()
    uid     = query.from_user.id
    l       = lang(uid)
    goal_id = int(query.data.split("_")[1])
    goal    = db.get_goal(goal_id)
    context.user_data["edit_goal_id"] = goal_id
    await query.edit_message_text(
        t(l, "enter_new_goal_amount",
          title=goal["title"],
          current_target=f"{goal['target_amount']:,.2f}",
          currency=goal["currency"]),
        parse_mode=ParseMode.MARKDOWN
    )
    return S_GOAL_EDIT_AMOUNT


async def goal_edit_amount(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid     = update.effective_user.id
    l       = lang(uid)
    goal_id = context.user_data.get("edit_goal_id")
    if not goal_id:
        await update.message.reply_text(t(l, "error"))
        return ConversationHandler.END

    try:
        new_target = float(update.message.text.replace(",", "."))
        if new_target <= 0:
            raise ValueError
    except ValueError:
        await update.message.reply_text(t(l, "invalid_amount"))
        return S_GOAL_EDIT_AMOUNT

    # Fetch current goal to pass current_amount to update function
    goal = db.get_goal(goal_id)
    if not goal:
        await update.message.reply_text(t(l, "error"))
        return ConversationHandler.END

    # Update target and re-evaluate completed flag
    updated_goal = db.update_goal_target(goal_id, new_target, goal["current_amount"])

    # Full recalc so all other goals stay consistent
    conversion_rates = {"fiat": {}, "crypto": {}, "metals": {}}
    try:
        conversion_rates["fiat"], conversion_rates["crypto"], conversion_rates["metals"] = \
            await cur.fetch_all_rates()
    except Exception:
        pass
    db.recalculate_all_goals(uid, conversion_rates)

    # Re-fetch after recalc to show up-to-date progress
    updated_goal = db.get_goal(goal_id)
    pct = min(100, round(updated_goal["current_amount"] / updated_goal["target_amount"] * 100)) \
          if updated_goal["target_amount"] else 0
    status = ("✅ " + t(l, "goal_completed")) if updated_goal["completed"] else ""

    await update.message.reply_text(
        t(l, "goal_target_updated",
          title=updated_goal["title"],
          new_target=f"{updated_goal['target_amount']:,.2f}",
          current=f"{updated_goal['current_amount']:,.2f}",
          currency=updated_goal["currency"],
          pct=pct,
          status=status),
        reply_markup=back_keyboard(uid, "menu_goals"),
        parse_mode=ParseMode.MARKDOWN
    )
    return ConversationHandler.END


# ─────────────────── CONVERT GOAL CURRENCY ───────────────────

async def goal_convert_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    uid   = query.from_user.id
    l     = lang(uid)
    goals = db.get_goals(uid)
    if not goals:
        await query.edit_message_text(
            t(l, "no_goals"),
            reply_markup=back_keyboard(uid, "menu_goals"),
            parse_mode=ParseMode.MARKDOWN
        )
        return ConversationHandler.END
    await query.edit_message_text(
        t(l, "choose_goal_to_convert"),
        reply_markup=goals_select_keyboard(goals, "gconv", uid),
        parse_mode=ParseMode.MARKDOWN
    )
    return S_GOAL_SELECT_CONVERT


async def goal_select_convert(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query   = update.callback_query
    await query.answer()
    uid     = query.from_user.id
    l       = lang(uid)
    goal_id = int(query.data.split("_")[1])
    context.user_data["convert_goal_id"] = goal_id
    await query.edit_message_text(
        t(l, "choose_new_currency"),
        reply_markup=currency_keyboard("gnewcur", uid),
        parse_mode=ParseMode.MARKDOWN
    )
    return S_GOAL_NEW_CURRENCY


async def goal_new_currency(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query        = update.callback_query
    await query.answer()
    uid          = query.from_user.id
    l            = lang(uid)
    new_currency = query.data.split("_", 1)[1]
    goal_id      = context.user_data["convert_goal_id"]
    goal         = db.get_goal(goal_id)

    if not goal:
        await query.edit_message_text(t(l, "error"), parse_mode=ParseMode.MARKDOWN)
        return ConversationHandler.END

    await query.edit_message_text(t(l, "fetching_rates"), parse_mode=ParseMode.MARKDOWN)
    fiat, crypto, metals = await cur.fetch_all_rates()

    new_target  = cur.convert_amount(goal["target_amount"],  goal["currency"], new_currency, fiat, crypto, metals)
    new_current = cur.convert_amount(goal["current_amount"], goal["currency"], new_currency, fiat, crypto, metals)

    if new_target is None:
        await query.edit_message_text(t(l, "rates_error"), parse_mode=ParseMode.MARKDOWN)
        return ConversationHandler.END

    db.update_goal_currency(goal_id, new_currency, round(new_target, 4), round(new_current or 0, 4))

    await query.edit_message_text(
        t(l, "goal_converted",
          title=goal["title"],
          amount=f"{new_target:,.4f}",
          currency=new_currency),
        reply_markup=back_keyboard(uid, "menu_goals"),
        parse_mode=ParseMode.MARKDOWN
    )
    return ConversationHandler.END


# ─────────────────── SETTINGS ───────────────────

async def cb_settings_base_currency(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    uid = query.from_user.id
    l   = lang(uid)
    await query.edit_message_text(
        t(l, "choose_base_currency"),
        reply_markup=currency_keyboard("setbase", uid),
        parse_mode=ParseMode.MARKDOWN
    )
    return S_SETTINGS_BASE_CURRENCY


async def cb_set_base_currency(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query  = update.callback_query
    await query.answer()
    uid    = query.from_user.id
    l      = lang(uid)
    chosen = query.data.split("_", 1)[1]
    db.set_user_base_currency(uid, chosen)
    await query.edit_message_text(
        t(l, "base_currency_set", currency=chosen),
        reply_markup=back_keyboard(uid),
        parse_mode=ParseMode.MARKDOWN
    )
    return ConversationHandler.END


# ─────────────────── CANCEL ───────────────────

async def conv_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    uid = query.from_user.id
    l   = lang(uid)
    await query.edit_message_text(t(l, "cancelled"), parse_mode=ParseMode.MARKDOWN)
    await asyncio.sleep(0.3)
    await send_main_menu(update, uid, edit=True)
    return ConversationHandler.END


async def text_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    l   = lang(uid)
    await update.message.reply_text(
        t(l, "cancelled"),
        reply_markup=main_menu_keyboard(uid),
        parse_mode=ParseMode.MARKDOWN
    )
    return ConversationHandler.END


# ─────────────────── MAIN ───────────────────

def build_application() -> Application:
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    if not token:
        raise ValueError("TELEGRAM_BOT_TOKEN not set in environment!")

    app = Application.builder().token(token).build()

    # ── Delete individual transaction ──
    trans_delete_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(trans_delete_start, pattern="^trans_delete$")],
        states={
            S_TRANS_SELECT_DELETE: [CallbackQueryHandler(trans_select_delete, pattern="^tdel_")],
        },
        fallbacks=[
            CallbackQueryHandler(conv_cancel, pattern="^conv_cancel$"),
            CommandHandler("cancel", text_cancel),
        ],
        per_message=False,
    )

    # ── Edit transaction category ──
    trans_edit_category_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(trans_edit_category_start, pattern="^trans_edit_category$")],
        states={
            S_TRANS_SELECT_EDIT_CATEGORY: [
                CallbackQueryHandler(trans_select_edit_category, pattern="^tcatedit_"),
            ],
            S_TRANS_EDIT_CATEGORY_PICK: [
                CallbackQueryHandler(trans_edit_category_picked, pattern="^cat_"),
            ],
        },
        fallbacks=[
            CallbackQueryHandler(conv_cancel, pattern="^conv_cancel$"),
            CommandHandler("cancel", text_cancel),
        ],
        per_message=False,
    )

    # ── Split transaction into multiple categories ──
    trans_split_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(trans_split_start, pattern="^trans_split$")],
        states={
            S_TRANS_SELECT_SPLIT: [
                CallbackQueryHandler(trans_select_split, pattern="^tsplit_"),
            ],
            S_SPLIT_AMOUNT: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, split_amount_entered),
                CallbackQueryHandler(split_finish_clicked, pattern="^split_finish$"),
            ],
            S_SPLIT_CATEGORY: [
                CallbackQueryHandler(split_category_picked, pattern="^cat_"),
            ],
        },
        fallbacks=[
            CallbackQueryHandler(conv_cancel, pattern="^conv_cancel$"),
            CommandHandler("cancel", text_cancel),
        ],
        per_message=False,
    )

    # ── Manage a transaction's tags ──
    trans_tags_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(trans_tags_start, pattern="^trans_tags$")],
        states={
            S_TRANS_SELECT_TAGS: [
                CallbackQueryHandler(trans_select_tags, pattern="^ttags_"),
            ],
            S_TAGS_MANAGE: [
                CallbackQueryHandler(tags_manage_router, pattern="^tagop_(add|remove|done)$"),
            ],
            S_TAGS_ADD_INPUT: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, tags_add_input),
            ],
            S_TAGS_REMOVE_PICK: [
                CallbackQueryHandler(tags_remove_pick, pattern="^tagrm_|^tagop_back$"),
            ],
        },
        fallbacks=[
            CallbackQueryHandler(conv_cancel, pattern="^conv_cancel$"),
            CommandHandler("cancel", text_cancel),
        ],
        per_message=False,
    )

    # ── Browse transactions by tag ──
    trans_browse_tag_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(trans_browse_tag_start, pattern="^trans_browse_tag$")],
        states={
            S_TAGS_BROWSE_PICK: [
                CallbackQueryHandler(trans_browse_tag_picked, pattern="^tagbrowse_"),
            ],
        },
        fallbacks=[
            CallbackQueryHandler(conv_cancel, pattern="^conv_cancel$"),
            CommandHandler("cancel", text_cancel),
        ],
        per_message=False,
    )

    # ── Add transaction (requires account selection first) ──
    trans_conv = ConversationHandler(
        entry_points=[
            CallbackQueryHandler(trans_start, pattern="^trans_add_(income|expense)$"),
        ],
        states={
            S_TRANS_ACCOUNT: [
                CallbackQueryHandler(trans_account_selected, pattern="^tacc_"),
            ],
            S_TRANS_AMOUNT: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, trans_amount),
            ],
            S_TRANS_CATEGORY: [
                CallbackQueryHandler(trans_category, pattern="^cat_"),
            ],
            S_TRANS_DESC: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, trans_description),
                CommandHandler("skip", trans_description),
            ],
        },
        fallbacks=[
            CallbackQueryHandler(conv_cancel, pattern="^conv_cancel$"),
            CommandHandler("cancel", text_cancel),
        ],
        per_message=False,
    )

    # ── Add account ──
    account_add_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(account_add_start, pattern="^account_add$")],
        states={
            S_ACCOUNT_TYPE:     [CallbackQueryHandler(account_type_chosen,     pattern="^atype_")],
            S_ACCOUNT_NAME:     [MessageHandler(filters.TEXT & ~filters.COMMAND, account_name_entered)],
            S_ACCOUNT_CURRENCY: [CallbackQueryHandler(account_currency_chosen, pattern="^acur_")],
            S_ACCOUNT_BALANCE:  [MessageHandler(filters.TEXT & ~filters.COMMAND, account_balance_entered)],
        },
        fallbacks=[
            CallbackQueryHandler(conv_cancel, pattern="^conv_cancel$"),
            CommandHandler("cancel", text_cancel),
        ],
        per_message=False,
    )

    # ── Import CSV statement ──
    import_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(import_start, pattern="^account_import_csv$")],
        states={
            S_IMPORT_ACCOUNT: [
                CallbackQueryHandler(import_account_chosen, pattern="^impacc_"),
            ],
            S_IMPORT_FILE: [
                MessageHandler(filters.Document.ALL, import_file_received),
            ],
            S_IMPORT_CONFIRM: [
                CallbackQueryHandler(import_confirm, pattern="^import_confirm$"),
            ],
        },
        fallbacks=[
            CallbackQueryHandler(conv_cancel, pattern="^conv_cancel$"),
            CommandHandler("cancel", text_cancel),
        ],
        per_message=False,
    )

    # ── Delete account ──
    account_delete_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(account_delete_start, pattern="^account_delete$")],
        states={
            S_ACCOUNT_SELECT_DELETE: [
                CallbackQueryHandler(account_select_delete, pattern="^adel_")
            ],
        },
        fallbacks=[
            CallbackQueryHandler(conv_cancel, pattern="^conv_cancel$"),
            CommandHandler("cancel", text_cancel),
        ],
        per_message=False,
    )

    # ── Edit account initial balance ──
    account_edit_balance_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(account_edit_balance_start, pattern="^account_edit_balance$")],
        states={
            S_ACCOUNT_EDIT_SELECT: [
                CallbackQueryHandler(account_edit_balance_selected, pattern="^aeditbal_"),
            ],
            S_ACCOUNT_EDIT_BALANCE: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, account_edit_balance_entered),
            ],
        },
        fallbacks=[
            CallbackQueryHandler(conv_cancel, pattern="^conv_cancel$"),
            CommandHandler("cancel", text_cancel),
        ],
        per_message=False,
    )

    # ── Add custom category ──
    category_add_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(category_add_start, pattern="^customcat_add$")],
        states={
            S_CATEGORY_TYPE: [
                CallbackQueryHandler(category_type_chosen, pattern="^cattype_"),
            ],
            S_CATEGORY_NAME: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, category_name_entered),
            ],
            S_CATEGORY_EMOJI: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, category_emoji_entered),
            ],
        },
        fallbacks=[
            CallbackQueryHandler(conv_cancel, pattern="^conv_cancel$"),
            CommandHandler("cancel", text_cancel),
        ],
        per_message=False,
    )

    # ── Delete custom category ──
    category_delete_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(category_delete_start, pattern="^customcat_delete$")],
        states={
            S_CATEGORY_SELECT_DELETE: [
                CallbackQueryHandler(category_select_delete, pattern="^ccatdel_"),
            ],
        },
        fallbacks=[
            CallbackQueryHandler(conv_cancel, pattern="^conv_cancel$"),
            CommandHandler("cancel", text_cancel),
        ],
        per_message=False,
    )

    # ── Add / update budget ──
    budget_add_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(budget_add_start, pattern="^budget_add$")],
        states={
            S_BUDGET_CATEGORY: [CallbackQueryHandler(budget_category_chosen, pattern="^bcat_")],
            S_BUDGET_AMOUNT:   [MessageHandler(filters.TEXT & ~filters.COMMAND, budget_amount_entered)],
        },
        fallbacks=[
            CallbackQueryHandler(conv_cancel, pattern="^conv_cancel$"),
            CommandHandler("cancel", text_cancel),
        ],
        per_message=False,
    )

    # ── Delete budget ──
    budget_delete_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(budget_delete_start, pattern="^budget_delete$")],
        states={
            S_BUDGET_SELECT_DELETE: [CallbackQueryHandler(budget_select_delete, pattern="^bdel_")],
        },
        fallbacks=[
            CallbackQueryHandler(conv_cancel, pattern="^conv_cancel$"),
            CommandHandler("cancel", text_cancel),
        ],
        per_message=False,
    )

    # ── Add goal ──
    goal_add_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(goal_add_start, pattern="^goal_add$")],
        states={
            S_GOAL_TYPE:     [CallbackQueryHandler(goal_type,     pattern="^gtype_")],
            S_GOAL_TITLE:    [MessageHandler(filters.TEXT & ~filters.COMMAND, goal_title)],
            S_GOAL_AMOUNT:   [MessageHandler(filters.TEXT & ~filters.COMMAND, goal_amount)],
            S_GOAL_CURRENCY: [CallbackQueryHandler(goal_currency, pattern="^gcur_")],
            S_GOAL_DEADLINE: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, goal_deadline),
                CommandHandler("skip", goal_deadline),
            ],
        },
        fallbacks=[
            CallbackQueryHandler(conv_cancel, pattern="^conv_cancel$"),
            CommandHandler("cancel", text_cancel),
        ],
        per_message=False,
    )

    # ── Edit goal target amount ──
    goal_edit_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(goal_edit_start, pattern="^goal_edit$")],
        states={
            S_GOAL_SELECT_EDIT: [CallbackQueryHandler(goal_select_edit, pattern="^gedit_")],
            S_GOAL_EDIT_AMOUNT: [MessageHandler(filters.TEXT & ~filters.COMMAND, goal_edit_amount)],
        },
        fallbacks=[
            CallbackQueryHandler(conv_cancel, pattern="^conv_cancel$"),
            CommandHandler("cancel", text_cancel),
        ],
        per_message=False,
    )

    # ── Delete goal ──
    goal_delete_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(goal_delete_start, pattern="^goal_delete$")],
        states={
            S_GOAL_SELECT_DELETE: [CallbackQueryHandler(goal_select_delete, pattern="^gdel_")],
        },
        fallbacks=[
            CallbackQueryHandler(conv_cancel, pattern="^conv_cancel$"),
            CommandHandler("cancel", text_cancel),
        ],
        per_message=False,
    )

    # ── Convert goal currency ──
    goal_convert_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(goal_convert_start, pattern="^goal_convert$")],
        states={
            S_GOAL_SELECT_CONVERT: [CallbackQueryHandler(goal_select_convert, pattern="^gconv_")],
            S_GOAL_NEW_CURRENCY:   [CallbackQueryHandler(goal_new_currency,   pattern="^gnewcur_")],
        },
        fallbacks=[
            CallbackQueryHandler(conv_cancel, pattern="^conv_cancel$"),
            CommandHandler("cancel", text_cancel),
        ],
        per_message=False,
    )

    # ── Settings base currency ──
    settings_cur_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(cb_settings_base_currency, pattern="^settings_base_currency$")],
        states={
            S_SETTINGS_BASE_CURRENCY: [CallbackQueryHandler(cb_set_base_currency, pattern="^setbase_")],
        },
        fallbacks=[
            CallbackQueryHandler(conv_cancel, pattern="^conv_cancel$"),
            CommandHandler("cancel", text_cancel),
        ],
        per_message=False,
    )

    # ── Custom stats date-range ──
    stats_custom_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(stats_custom_start, pattern="^stats_p_custom$")],
        states={
            S_STATS_CUSTOM_START: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, stats_custom_got_start),
            ],
            S_STATS_CUSTOM_END: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, stats_custom_got_end),
            ],
        },
        fallbacks=[CommandHandler("cancel", text_cancel)],
        per_message=False,
    )

    # Register conversations (stats_custom_conv first — most specific entry pattern)
    for conv in [
        stats_custom_conv,
        trans_delete_conv, trans_edit_category_conv, trans_split_conv,
        trans_tags_conv, trans_browse_tag_conv, trans_conv,
        account_add_conv, account_delete_conv, account_edit_balance_conv, import_conv,
        budget_add_conv, budget_delete_conv,
        goal_add_conv, goal_edit_conv, goal_delete_conv, goal_convert_conv,
        settings_cur_conv,
        category_add_conv, category_delete_conv,
    ]:
        app.add_handler(conv)

    # ── Non-conversation handlers ──
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("menu",  cmd_menu))
    app.add_handler(CommandHandler("webcode", cmd_webcode))

    app.add_handler(CallbackQueryHandler(cb_set_language, pattern="^setlang_"))

    app.add_handler(CallbackQueryHandler(
        cb_main_menu,
        pattern="^(back_main|menu_transactions|menu_goals|menu_accounts|menu_budgets|menu_currencies|"
                "menu_stats|menu_settings|menu_categories|settings_language|"
                "trans_view|trans_clear|goal_view|account_view|budget_view|customcat_view)$"
    ))

    app.add_handler(CallbackQueryHandler(cb_back_stats,               pattern="^back_stats$"))
    app.add_handler(CallbackQueryHandler(cb_clear_transactions_confirm, pattern="^trans_clear_confirm$"))
    app.add_handler(CallbackQueryHandler(cb_main_menu,                pattern="^back_transactions$"))

    app.add_handler(CallbackQueryHandler(cb_stats_period,    pattern="^stats_p_(week|month|6m|year)$"))
    app.add_handler(CallbackQueryHandler(cb_stats_recurring, pattern="^stats_recurring$"))
    app.add_handler(CallbackQueryHandler(cb_stats_forecast,  pattern="^stats_forecast$"))
    app.add_handler(CallbackQueryHandler(cb_schrt_toggle,    pattern="^schrt_toggle_"))
    app.add_handler(CallbackQueryHandler(cb_schrt_generate,  pattern="^schrt_generate$"))

    app.add_handler(CallbackQueryHandler(trans_history_start,      pattern="^trans_history$"))
    app.add_handler(CallbackQueryHandler(cb_trans_history_period,  pattern="^hist_p_(week|month|6m|year)$"))

    return app


async def on_bot_start(app: Application) -> None:
    await app.bot.set_my_commands([
        BotCommand("start",    "Start / Language select"),
        BotCommand("menu",     "Open main menu"),
        BotCommand("webcode",  "Get a login code for the web dashboard"),
        BotCommand("cancel",   "Cancel current action"),
    ])
    logger.info("✅ Money Manager Bot commands registered")


if __name__ == "__main__":
    db.init_db()
    app = build_application()
    app.post_init = on_bot_start
    logger.info("✅ Money Manager Bot started!")
    app.run_polling(allowed_updates=Update.ALL_TYPES)
