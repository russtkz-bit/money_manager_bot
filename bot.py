"""
Money Manager Telegram Bot
Tracks income/expenses, goals, currencies, and provides AI market analysis.
"""

import os
import asyncio
import logging
from datetime import datetime
from typing import Optional

from dotenv import load_dotenv
from telegram import (
    Update, InlineKeyboardButton, InlineKeyboardMarkup, BotCommand
)
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler,
    MessageHandler, ConversationHandler, filters, ContextTypes
)
from telegram.constants import ParseMode

import database as db
import currencies as cur
import charts as ch
from languages import t
from io import BytesIO
from datetime import datetime, timedelta

load_dotenv()
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# ─────────────────── CONVERSATION STATES ───────────────────
(
    # Transaction flow
    S_TRANS_TYPE, S_TRANS_AMOUNT, S_TRANS_CURRENCY,
    S_TRANS_CATEGORY, S_TRANS_DESC,
    # Goal flow
    S_GOAL_TYPE, S_GOAL_TITLE, S_GOAL_AMOUNT,
    S_GOAL_CURRENCY, S_GOAL_DEADLINE,
    # Goal delete flow
    S_GOAL_SELECT_DELETE,
    # Goal convert flow
    S_GOAL_SELECT_CONVERT, S_GOAL_NEW_CURRENCY,
    # Settings
    S_SETTINGS_BASE_CURRENCY,
    # Stats custom date range
    S_STATS_CUSTOM_START, S_STATS_CUSTOM_END,
    # Transaction delete flow
    S_TRANS_SELECT_DELETE,
) = range(17)

# Currency keyboard rows
CURRENCY_ROW_1 = ["USD", "EUR", "RUB", "KZT"]
CURRENCY_ROW_2 = ["GBP", "AED", "TRY", "CNY"]
CURRENCY_ROW_3 = ["BTC", "ETH", "SOL", "TON"]
CURRENCY_ROW_4 = ["BNB", "XRP", "XAU", "XAG"]


def lang(uid: int) -> str:
    return db.get_user_lang(uid)


# ─────────────────── KEYBOARDS ───────────────────

def main_menu_keyboard(uid: int) -> InlineKeyboardMarkup:
    l = lang(uid)
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(t(l, "btn_transactions"), callback_data="menu_transactions"),
         InlineKeyboardButton(t(l, "btn_goals"), callback_data="menu_goals")],
        [InlineKeyboardButton(t(l, "btn_currencies"), callback_data="menu_currencies"),
         InlineKeyboardButton(t(l, "btn_statistics"), callback_data="menu_stats")],
        [InlineKeyboardButton(t(l, "btn_settings"), callback_data="menu_settings")],
    ])


def transactions_keyboard(uid: int) -> InlineKeyboardMarkup:
    l = lang(uid)
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(t(l, "btn_add_income"), callback_data="trans_add_income"),
         InlineKeyboardButton(t(l, "btn_add_expense"), callback_data="trans_add_expense")],
        [InlineKeyboardButton(t(l, "btn_view_transactions"), callback_data="trans_view")],
        [InlineKeyboardButton(t(l, "btn_delete_transaction"), callback_data="trans_delete"),
         InlineKeyboardButton(t(l, "btn_clear_transactions"), callback_data="trans_clear")],
        [InlineKeyboardButton(t(l, "back"), callback_data="back_main")],
    ])


def goals_keyboard(uid: int) -> InlineKeyboardMarkup:
    l = lang(uid)
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(t(l, "btn_add_goal"), callback_data="goal_add")],
        [InlineKeyboardButton(t(l, "btn_view_goals"), callback_data="goal_view")],
        [InlineKeyboardButton(t(l, "btn_convert_goal"), callback_data="goal_convert"),
         InlineKeyboardButton(t(l, "btn_delete_goal"), callback_data="goal_delete")],
        [InlineKeyboardButton(t(l, "back"), callback_data="back_main")],
    ])


def currency_keyboard(callback_prefix: str, uid: int) -> InlineKeyboardMarkup:
    rows = []
    for row in [CURRENCY_ROW_1, CURRENCY_ROW_2, CURRENCY_ROW_3, CURRENCY_ROW_4]:
        rows.append([InlineKeyboardButton(c, callback_data=f"{callback_prefix}_{c}") for c in row])
    l = lang(uid)
    rows.append([InlineKeyboardButton(t(l, "cancel"), callback_data="conv_cancel")])
    return InlineKeyboardMarkup(rows)


def category_keyboard(t_type: str, uid: int) -> InlineKeyboardMarkup:
    l = lang(uid)
    if t_type == "income":
        cats = ["cat_salary", "cat_freelance", "cat_investment", "cat_gift", "cat_other"]
    else:
        cats = [
            "cat_food", "cat_transport", "cat_housing", "cat_health",
            "cat_entertainment", "cat_loan_payment", "cat_other"
        ]
    rows = []
    for i in range(0, len(cats), 2):
        row = [InlineKeyboardButton(t(l, cats[i]), callback_data=f"cat_{cats[i]}")]
        if i + 1 < len(cats):
            row.append(InlineKeyboardButton(t(l, cats[i + 1]), callback_data=f"cat_{cats[i + 1]}"))
        rows.append(row)
    rows.append([InlineKeyboardButton(t(l, "cancel"), callback_data="conv_cancel")])
    return InlineKeyboardMarkup(rows)


def goal_type_keyboard(uid: int) -> InlineKeyboardMarkup:
    l = lang(uid)
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(t(l, "goal_type_save"), callback_data="gtype_save"),
         InlineKeyboardButton(t(l, "goal_type_repay"), callback_data="gtype_repay")],
        [InlineKeyboardButton(t(l, "cancel"), callback_data="conv_cancel")],
    ])





def settings_keyboard(uid: int) -> InlineKeyboardMarkup:
    l = lang(uid)
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(t(l, "btn_change_language"), callback_data="settings_language")],
        [InlineKeyboardButton(t(l, "btn_change_currency"), callback_data="settings_base_currency")],
        [InlineKeyboardButton(t(l, "btn_status_notifications"), callback_data="settings_status_notifications")],
        [InlineKeyboardButton(t(l, "back"), callback_data="back_main")],
    ])


def language_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🇬🇧 English", callback_data="setlang_en"),
         InlineKeyboardButton("🇷🇺 Русский", callback_data="setlang_ru")],
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
        [InlineKeyboardButton(t(l, "back"), callback_data="back_main")],
    ])


def goals_select_keyboard(goals: list, callback_prefix: str, uid: int) -> InlineKeyboardMarkup:
    l = lang(uid)
    rows = []
    for g in goals:
        pct = min(100, round(g["current_amount"] / g["target_amount"] * 100)) if g["target_amount"] else 0
        label = f"{g['title']} ({pct}%)"
        rows.append([InlineKeyboardButton(label, callback_data=f"{callback_prefix}_{g['id']}")])
    rows.append([InlineKeyboardButton(t(l, "cancel"), callback_data="conv_cancel")])
    return InlineKeyboardMarkup(rows)


# ─────────────────── HELPERS ───────────────────

async def send_main_menu(update: Update, uid: int, edit: bool = False):
    l = lang(uid)
    text = t(l, "main_menu")
    kb = main_menu_keyboard(uid)
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
        "save": t(l, "goal_type_save"),
        "repay": t(l, "goal_type_repay"),
    }
    for i, g in enumerate(goals, 1):
        pct = min(100, round(g["current_amount"] / g["target_amount"] * 100)) if g["target_amount"] else 0
        deadline = g["deadline"] or "—"
        lines += t(l, "goal_line",
                   n=i, title=g["title"],
                   type=type_labels.get(g["goal_type"], g["goal_type"]),
                   current=f"{g['current_amount']:.2f}",
                   target=f"{g['target_amount']:.2f}",
                   currency=g["currency"],
                   pct=pct,
                   deadline=deadline)
    return lines


# ─────────────────── START / WELCOME ───────────────────

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    db.ensure_user(uid)
    # Auto-detect language from Telegram client; default to English.
    tg_lang = (update.effective_user.language_code or "en").lower()
    initial_lang = "ru" if tg_lang.startswith("ru") else "en"
    db.set_user_language(uid, initial_lang)
    text = t(initial_lang, "welcome")
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("🇬🇧 English", callback_data="setlang_en"),
         InlineKeyboardButton("🇷🇺 Русский", callback_data="setlang_ru")],
    ])
    await update.message.reply_text(text, reply_markup=kb, parse_mode=ParseMode.MARKDOWN)


async def cb_set_language(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    uid = query.from_user.id
    chosen = query.data.split("_")[1]  # en or ru
    db.set_user_language(uid, chosen)
    l = chosen
    await query.edit_message_text(t(l, "language_set"), parse_mode=ParseMode.MARKDOWN)
    await asyncio.sleep(0.5)
    await send_main_menu(update, uid, edit=True)


async def cmd_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    db.ensure_user(uid)
    await send_main_menu(update, uid)


# ─────────────────── BOT STATUS NOTIFICATIONS ───────────────────

async def broadcast_status_notification(app: Application, status: str) -> int:
    """Send bot status notification to all users who opted in."""
    users = db.get_all_users_for_notifications()
    notified_count = 0
    
    for uid in users:
        try:
            l = db.get_user_lang(uid)
            if status == "online":
                message = t(l, "bot_online")
            else:
                message = t(l, "bot_offline")
            
            await app.bot.send_message(
                chat_id=uid,
                text=message,
                parse_mode=ParseMode.MARKDOWN
            )
            notified_count += 1
        except Exception as e:
            logger.warning(f"Failed to notify user {uid}: {e}")
    
    return notified_count


# ─────────────────── MAIN MENU ROUTING ───────────────────

async def cb_main_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    uid = query.from_user.id
    l = lang(uid)

    if query.data == "back_main":
        await send_main_menu(update, uid, edit=True)

    elif query.data == "menu_transactions":
        await query.edit_message_text(
            t(l, "btn_transactions"),
            reply_markup=transactions_keyboard(uid),
            parse_mode=ParseMode.MARKDOWN
        )
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
    elif query.data == "settings_status_notifications":
        await cb_settings_status_notifications(update, context)
    elif query.data.startswith("settings_status_notifications_"):
        await cb_toggle_status_notifications(update, context)
    elif query.data == "trans_view":
        await handle_view_transactions(update, context)
    
    elif query.data == "trans_clear":
        await cb_clear_transactions(update, context)

    elif query.data == "goal_view":
        await handle_view_goals(update, context)


# ─────────────────── CURRENCIES ───────────────────

async def handle_currencies(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    uid = query.from_user.id
    l = lang(uid)
    await query.edit_message_text(t(l, "fetching_rates"), parse_mode=ParseMode.MARKDOWN)

    fiat, crypto, metals = await cur.fetch_all_rates()

    text = t(l, "currencies_header")

    if fiat:
        fiat_lines = "\n".join(
            f"  `{c}`: {v:,.4f}" for c, v in fiat.items() if c != "USD"
        )
        text += t(l, "fiat_rates", rates=fiat_lines)
    else:
        text += t(l, "rates_error") + "\n"

    if crypto:
        crypto_lines = "\n".join(
            f"  `{sym}`: ${price:,.2f}" if price >= 1 else f"  `{sym}`: ${price:.6f}"
            for sym, price in crypto.items()
        )
        text += t(l, "crypto_rates", rates=crypto_lines)

    if metals:
        metals_lines = "\n".join(
            f"  `{sym}`: ${price:,.2f}" for sym, price in metals.items()
        )
        text += t(l, "metals_rates", rates=metals_lines)

    await query.edit_message_text(
        text,
        reply_markup=back_keyboard(uid),
        parse_mode=ParseMode.MARKDOWN
    )


# ─────────────────── STATISTICS ───────────────────

async def handle_statistics(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show period-selection keyboard instead of raw stats."""
    query = update.callback_query
    uid = query.from_user.id
    l = lang(uid)
    await query.edit_message_text(
        t(l, "stats_choose_period"),
        reply_markup=stats_period_keyboard(uid),
        parse_mode=ParseMode.MARKDOWN,
    )


# ── helper: compute date range for a named period ──
def _period_dates(period: str):
    """Return (start_date_str, end_date_str, bar_period_key) for a named period."""
    today = datetime.now().date()
    if period == "week":
        start = today - timedelta(days=6)
        bar   = "week"
    elif period == "month":
        start = today - timedelta(days=29)
        bar   = "month"
    elif period == "6m":
        start = today - timedelta(days=179)
        bar   = "6months"
    elif period == "year":
        start = today - timedelta(days=364)
        bar   = "year"
    else:
        return None, None, None
    return start.strftime("%Y-%m-%d"), today.strftime("%Y-%m-%d"), bar


# ── core: generate and send charts for a given date window ──
async def _send_charts(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    uid: int,
    start_date: str,
    end_date: str,
    bar_period: str,
    period_label: str,
):
    l = lang(uid)
    query = update.callback_query

    # Show spinner
    await query.edit_message_text(
        t(l, "stats_generating"),
        parse_mode=ParseMode.MARKDOWN,
    )

    stats = db.get_statistics_filtered(uid, start_date, end_date)
    txns  = db.get_transactions_filtered(uid, start_date, end_date)
    goals = db.get_goals(uid)

    total_income  = sum(stats["income"].values())
    total_expense = sum(stats["expense"].values())
    balance       = total_income - total_expense

    # ── Text summary ──
    summary = t(l, "stats_period_header", period=period_label)
    summary += t(l, "stats_balance", balance=f"{balance:,.2f}", currency="")
    summary += t(l, "stats_income",  amount=f"{total_income:,.2f}",  currency="")
    summary += t(l, "stats_expense", amount=f"{total_expense:,.2f}", currency="")
    if not txns:
        summary += "\n" + t(l, "stats_no_data_period")

    # ── Send charts, track IDs so Back can delete them ──
    chart_msg_ids: list = []
    sent_any = False

    # 1. Goals progress
    if goals:
        img = ch.generate_goals_chart(goals, title=t(l, "chart_goals_title"))
        if img:
            msg = await context.bot.send_photo(
                chat_id=uid,
                photo=BytesIO(img),
                caption=t(l, "chart_goals_caption"),
            )
            chart_msg_ids.append(msg.message_id)
            sent_any = True

    # 2. Expense pie
    by_cat = stats.get("by_category", {})
    if by_cat:
        img = ch.generate_pie_chart(by_cat, title=t(l, "chart_pie_title"))
        if img:
            msg = await context.bot.send_photo(
                chat_id=uid,
                photo=BytesIO(img),
                caption=t(l, "chart_pie_caption"),
            )
            chart_msg_ids.append(msg.message_id)
            sent_any = True

    # 3. Income vs expenses bar
    if txns:
        img = ch.generate_bar_chart(
            txns, bar_period,
            income_label=t(l, "income"),
            expense_label=t(l, "expense"),
            title=t(l, "chart_bar_title"),
        )
        if img:
            msg = await context.bot.send_photo(
                chat_id=uid,
                photo=BytesIO(img),
                caption=t(l, "chart_bar_caption"),
            )
            chart_msg_ids.append(msg.message_id)
            sent_any = True

    # Store IDs so cb_back_stats can clean them up
    context.user_data["stats_chart_msg_ids"] = chart_msg_ids

    # Edit original message → summary + back button (back_stats clears photos)
    if not sent_any:
        summary += "\n\n" + t(l, "stats_no_charts")

    await query.edit_message_text(
        summary,
        reply_markup=back_keyboard(uid, "back_stats"),
        parse_mode=ParseMode.MARKDOWN,
    )


async def cb_back_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Delete chart photos then return to main menu."""
    query = update.callback_query
    await query.answer()
    uid      = query.from_user.id
    chat_id  = query.message.chat_id

    for msg_id in context.user_data.pop("stats_chart_msg_ids", []):
        try:
            await context.bot.delete_message(chat_id=chat_id, message_id=msg_id)
        except Exception:
            pass

    await send_main_menu(update, uid, edit=True)


# ── callback: named period selected ──
async def cb_stats_period(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    uid  = query.from_user.id
    l    = lang(uid)
    key  = query.data[len("stats_p_"):]   # week / month / 6m / year

    start, end, bar = _period_dates(key)

    labels = {
        "week":  t(l, "stats_period_week"),
        "month": t(l, "stats_period_month"),
        "6m":    t(l, "stats_period_6m"),
        "year":  t(l, "stats_period_year"),
    }
    await _send_charts(update, context, uid, start, end, bar, labels.get(key, key))


# ── conversation: custom date range ──
async def stats_custom_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Entry point: user chose 'Custom Range'."""
    query = update.callback_query
    await query.answer()
    uid = query.from_user.id
    l   = lang(uid)
    await query.edit_message_text(
        t(l, "stats_enter_start_date"),
        parse_mode=ParseMode.MARKDOWN,
    )
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

    days      = (end_dt - start_dt).days
    bar       = ch.period_for_days(days)
    label     = f"{start_str} — {end_str}"

    # We need a fake Update-like object for _send_charts; send directly instead
    # Build a minimal context by sending a placeholder message first
    msg = await update.message.reply_text(
        t(l, "stats_generating"), parse_mode=ParseMode.MARKDOWN
    )

    stats = db.get_statistics_filtered(uid, start_str, end_str)
    txns  = db.get_transactions_filtered(uid, start_str, end_str)
    goals = db.get_goals(uid)

    total_income  = sum(stats["income"].values())
    total_expense = sum(stats["expense"].values())
    balance       = total_income - total_expense

    summary = t(l, "stats_period_header", period=label)
    summary += t(l, "stats_balance", balance=f"{balance:,.2f}", currency="")
    summary += t(l, "stats_income",  amount=f"{total_income:,.2f}",  currency="")
    summary += t(l, "stats_expense", amount=f"{total_expense:,.2f}", currency="")

    sent_any = False
    chart_msg_ids: list = []

    if goals:
        img = ch.generate_goals_chart(goals, title=t(l, "chart_goals_title"))
        if img:
            pm = await update.message.reply_photo(photo=BytesIO(img), caption=t(l, "chart_goals_caption"))
            chart_msg_ids.append(pm.message_id)
            sent_any = True

    by_cat = stats.get("by_category", {})
    if by_cat:
        img = ch.generate_pie_chart(by_cat, title=t(l, "chart_pie_title"))
        if img:
            pm = await update.message.reply_photo(photo=BytesIO(img), caption=t(l, "chart_pie_caption"))
            chart_msg_ids.append(pm.message_id)
            sent_any = True

    if txns:
        img = ch.generate_bar_chart(
            txns, bar,
            income_label=t(l, "income"),
            expense_label=t(l, "expense"),
            title=t(l, "chart_bar_title"),
        )
        if img:
            pm = await update.message.reply_photo(photo=BytesIO(img), caption=t(l, "chart_bar_caption"))
            chart_msg_ids.append(pm.message_id)
            sent_any = True

    if not sent_any:
        summary += "\n\n" + t(l, "stats_no_charts")

    # Store chart IDs so back_stats can clean them up
    context.user_data["stats_chart_msg_ids"] = chart_msg_ids

    await update.message.reply_text(
        summary,
        reply_markup=back_keyboard(uid, "back_stats"),
        parse_mode=ParseMode.MARKDOWN,
    )
    # Delete the "Generating..." placeholder
    try:
        await msg.delete()
    except Exception:
        pass

    return ConversationHandler.END


# ─────────────────── VIEW TRANSACTIONS ───────────────────

async def handle_view_transactions(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    uid = query.from_user.id
    l = lang(uid)
    txns = db.get_transactions(uid)

    if not txns:
        await query.edit_message_text(
            t(l, "no_transactions"),
            reply_markup=back_keyboard(uid, "menu_transactions"),
            parse_mode=ParseMode.MARKDOWN
        )
        return

    text = t(l, "transactions_header")
    for tx in txns:
        emoji = "📈" if tx["type"] == "income" else "📉"
        date_str = tx["created_at"][:10] if tx["created_at"] else "?"
        desc = tx["description"] or "—"
        text += t(l, "transaction_line",
                  emoji=emoji,
                  date=date_str,
                  amount=f"{tx['amount']:,.2f}",
                  currency=tx["currency"],
                  category=tx["category"],
                  description=desc)

    # Telegram has 4096 char limit
    if len(text) > 4000:
        text = text[:4000] + "\n..."

    await query.edit_message_text(
        text,
        reply_markup=back_keyboard(uid, "menu_transactions"),
        parse_mode=ParseMode.MARKDOWN
    )


# ─────────────────── DELETE INDIVIDUAL TRANSACTION ───────────────────

def _trans_select_keyboard(txns: list, uid: int) -> InlineKeyboardMarkup:
    """Build a keyboard where each row is one transaction + a delete button."""
    l = lang(uid)
    rows = []
    for tx in txns:
        emoji    = "📈" if tx["type"] == "income" else "📉"
        date_str = tx["created_at"][:10] if tx["created_at"] else "?"
        label    = f"{emoji} {date_str}  {tx['amount']:,.0f} {tx['currency']}"
        rows.append([InlineKeyboardButton(label, callback_data=f"tdel_{tx['id']}")])
    rows.append([InlineKeyboardButton(t(l, "back"), callback_data="menu_transactions")])
    return InlineKeyboardMarkup(rows)


async def trans_delete_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Entry: show list of transactions to delete."""
    query = update.callback_query
    await query.answer()
    uid = query.from_user.id
    l   = lang(uid)

    txns = db.get_transactions(uid, limit=20)
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
    """Delete chosen transaction and recalculate all goals."""
    query = update.callback_query
    await query.answer()
    uid    = query.from_user.id
    l      = lang(uid)
    tx_id  = int(query.data.split("_")[1])

    db.delete_transaction(tx_id)

    # Recalculate all goals from scratch after deletion
    await query.edit_message_text(t(l, "recalculating_goals"), parse_mode=ParseMode.MARKDOWN)
    conversion_rates = {"fiat": {}, "crypto": {}, "metals": {}}
    try:
        conversion_rates["fiat"], conversion_rates["crypto"], conversion_rates["metals"] = \
            await cur.fetch_all_rates()
    except Exception:
        pass

    db.recalculate_all_goals(uid, conversion_rates)

    await query.edit_message_text(
        t(l, "transaction_deleted"),
        reply_markup=back_keyboard(uid, "menu_transactions"),
        parse_mode=ParseMode.MARKDOWN,
    )
    return ConversationHandler.END


async def cb_clear_transactions(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Ask for confirmation to clear all transactions."""
    query = update.callback_query
    await query.answer()
    uid = query.from_user.id
    l = lang(uid)
    
    await query.edit_message_text(
        t(l, "confirm_clear_transactions"),
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton(t(l, "btn_yes"), callback_data="trans_clear_confirm"),
             InlineKeyboardButton(t(l, "btn_no"), callback_data="back_transactions")],
        ]),
        parse_mode=ParseMode.MARKDOWN
    )


async def cb_clear_transactions_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Actually clear all transactions."""
    query = update.callback_query
    await query.answer()
    uid = query.from_user.id
    l = lang(uid)
    
    count = db.delete_all_transactions(uid)
    
    await query.edit_message_text(
        t(l, "transactions_cleared", count=count),
        reply_markup=back_keyboard(uid, "menu_transactions"),
        parse_mode=ParseMode.MARKDOWN
    )


# ─────────────────── VIEW GOALS ───────────────────

async def handle_view_goals(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    uid = query.from_user.id
    l = lang(uid)
    goals = db.get_goals(uid)
    text = format_goals_text(goals, l)
    await query.edit_message_text(
        text,
        reply_markup=back_keyboard(uid, "menu_goals"),
        parse_mode=ParseMode.MARKDOWN
    )


# ─────────────────── AI ASSISTANT ───────────────────




# ─────────────────── SETTINGS ───────────────────

async def cb_settings_base_currency(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    uid = query.from_user.id
    l = lang(uid)
    await query.edit_message_text(
        t(l, "choose_base_currency"),
        reply_markup=currency_keyboard("setbase", uid),
        parse_mode=ParseMode.MARKDOWN
    )
    return S_SETTINGS_BASE_CURRENCY


async def cb_set_base_currency(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    uid = query.from_user.id
    l = lang(uid)
    chosen = query.data.split("_", 1)[1]  # setbase_USD → USD
    db.set_user_base_currency(uid, chosen)
    await query.edit_message_text(
        t(l, "base_currency_set", currency=chosen),
        reply_markup=back_keyboard(uid),
        parse_mode=ParseMode.MARKDOWN
    )
    return ConversationHandler.END


async def cb_settings_status_notifications(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    uid = query.from_user.id
    l = lang(uid)
    notify = db.get_user_notify_on_status(uid)
    
    if notify:
        text = t(l, "status_notifications_on")
        next_action = "settings_status_notifications_disable"
    else:
        text = t(l, "status_notifications_off")
        next_action = "settings_status_notifications_enable"
    
    await query.edit_message_text(
        text,
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton(
                t(l, "btn_no") if notify else t(l, "btn_yes"),
                callback_data=next_action
            )],
            [InlineKeyboardButton(t(l, "back"), callback_data="back_main")],
        ]),
        parse_mode=ParseMode.MARKDOWN
    )


async def cb_toggle_status_notifications(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    uid = query.from_user.id
    l = lang(uid)
    
    if query.data == "settings_status_notifications_enable":
        db.set_user_notify_on_status(uid, True)
        await query.edit_message_text(
            t(l, "status_notifications_enabled"),
            reply_markup=back_keyboard(uid),
            parse_mode=ParseMode.MARKDOWN
        )
    else:
        db.set_user_notify_on_status(uid, False)
        await query.edit_message_text(
            t(l, "status_notifications_disabled"),
            reply_markup=back_keyboard(uid),
            parse_mode=ParseMode.MARKDOWN
        )


# ─────────────────── ADD TRANSACTION ───────────────────

async def trans_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    uid = query.from_user.id
    l = lang(uid)
    t_type = "income" if query.data == "trans_add_income" else "expense"
    context.user_data["trans_type"] = t_type
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
    l = lang(uid)
    try:
        amount = float(update.message.text.replace(",", "."))
        if amount <= 0:
            raise ValueError
    except ValueError:
        await update.message.reply_text(t(l, "invalid_amount"))
        return S_TRANS_AMOUNT

    context.user_data["trans_amount"] = amount
    await update.message.reply_text(
        t(l, "enter_currency"),
        reply_markup=currency_keyboard("tcur", uid),
        parse_mode=ParseMode.MARKDOWN
    )
    return S_TRANS_CURRENCY


async def trans_currency(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    uid = query.from_user.id
    l = lang(uid)
    chosen = query.data.split("_", 1)[1]
    context.user_data["trans_currency"] = chosen
    t_type = context.user_data.get("trans_type", "expense")
    await query.edit_message_text(
        t(l, "enter_category"),
        reply_markup=category_keyboard(t_type, uid),
        parse_mode=ParseMode.MARKDOWN
    )
    return S_TRANS_CATEGORY


async def trans_category(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    uid = query.from_user.id
    l = lang(uid)
    cat_key = query.data  # cat_cat_food → need to strip prefix
    # callback_data is like "cat_cat_food"
    cat_name_key = query.data[4:]  # removes "cat_"
    cat_name = t(l, cat_name_key)
    context.user_data["trans_category"] = cat_name
    await query.edit_message_text(
        t(l, "enter_description"),
        parse_mode=ParseMode.MARKDOWN
    )
    return S_TRANS_DESC


async def trans_description(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    l = lang(uid)
    desc = "" if update.message.text == "/skip" else update.message.text
    ud = context.user_data
    t_type = ud.get("trans_type", "expense")

    tx_id = db.add_transaction(
        uid,
        t_type,
        ud["trans_amount"],
        ud["trans_currency"],
        ud["trans_category"],
        desc
    )
    
    # Fetch conversion rates for goal currency conversion
    conversion_rates = {
        'fiat': {},
        'crypto': {},
        'metals': {}
    }
    try:
        conversion_rates['fiat'], conversion_rates['crypto'], conversion_rates['metals'] = await cur.fetch_all_rates()
    except:
        pass  # If rates fetch fails, update will still work for matching currencies
    
    # Update goal progress from transaction (with automatic currency conversion)
    updated_goals = db.update_goals_from_transaction(
        uid,
        ud["trans_amount"],
        ud["trans_currency"],
        conversion_rates
    )

    type_label = t(l, "income") if t_type == "income" else t(l, "expense")
    message_text = t(l, "transaction_saved",
          type=type_label,
          amount=f"{ud['trans_amount']:,.2f}",
          currency=ud["trans_currency"],
          category=ud["trans_category"],
          description=desc or "—")
    
    # Add goal progress update info if goals were updated
    if updated_goals:
        message_text += "\n\n📊 " + t(l, "goal_progress_updated") + ":\n"
        for goal in updated_goals:
            status = "✅ " + t(l, "goal_completed") if goal["completed"] else ""
            message_text += f"\n• {goal['title']}: {goal['current_amount']:,.2f}/{goal['target_amount']:,.2f} {goal['currency']} {status}"
    
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
    l = lang(uid)
    await query.edit_message_text(
        t(l, "choose_goal_type"),
        reply_markup=goal_type_keyboard(uid),
        parse_mode=ParseMode.MARKDOWN
    )
    return S_GOAL_TYPE


async def goal_type(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    uid = query.from_user.id
    l = lang(uid)
    chosen = "save" if query.data == "gtype_save" else "repay"
    context.user_data["goal_type"] = chosen
    await query.edit_message_text(
        t(l, "enter_goal_title"),
        parse_mode=ParseMode.MARKDOWN
    )
    return S_GOAL_TITLE


async def goal_title(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    l = lang(uid)
    context.user_data["goal_title"] = update.message.text
    await update.message.reply_text(t(l, "enter_goal_amount"), parse_mode=ParseMode.MARKDOWN)
    return S_GOAL_AMOUNT


async def goal_amount(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    l = lang(uid)
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
    uid = query.from_user.id
    l = lang(uid)
    chosen = query.data.split("_", 1)[1]
    context.user_data["goal_currency"] = chosen
    await query.edit_message_text(t(l, "enter_goal_deadline"), parse_mode=ParseMode.MARKDOWN)
    return S_GOAL_DEADLINE


async def goal_deadline(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    l = lang(uid)
    text = update.message.text
    deadline = None

    if text != "/skip":
        try:
            datetime.strptime(text, "%Y-%m-%d")
            deadline = text
        except ValueError:
            await update.message.reply_text(t(l, "invalid_input"))
            return S_GOAL_DEADLINE

    ud = context.user_data

    # Fetch rates to calculate initial progress from existing transactions
    conversion_rates = {"fiat": {}, "crypto": {}, "metals": {}}
    try:
        conversion_rates["fiat"], conversion_rates["crypto"], conversion_rates["metals"] = \
            await cur.fetch_all_rates()
    except Exception:
        pass

    initial_amount = db.calculate_initial_goal_amount(uid, ud["goal_currency"], conversion_rates)

    goal_id = db.add_goal(uid, ud["goal_title"], ud["goal_type"],
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


# ─────────────────── UPDATE GOAL PROGRESS ───────────────────

# ─────────────────── DELETE GOAL ───────────────────

async def goal_delete_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    uid = query.from_user.id
    l = lang(uid)
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
    query = update.callback_query
    await query.answer()
    uid = query.from_user.id
    l = lang(uid)
    goal_id = int(query.data.split("_")[1])
    db.delete_goal(goal_id)
    await query.edit_message_text(
        t(l, "goal_deleted"),
        reply_markup=back_keyboard(uid, "menu_goals"),
        parse_mode=ParseMode.MARKDOWN
    )
    return ConversationHandler.END


# ─────────────────── CONVERT GOAL CURRENCY ───────────────────

async def goal_convert_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    uid = query.from_user.id
    l = lang(uid)
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
    query = update.callback_query
    await query.answer()
    uid = query.from_user.id
    l = lang(uid)
    goal_id = int(query.data.split("_")[1])
    context.user_data["convert_goal_id"] = goal_id
    await query.edit_message_text(
        t(l, "choose_new_currency"),
        reply_markup=currency_keyboard("gnewcur", uid),
        parse_mode=ParseMode.MARKDOWN
    )
    return S_GOAL_NEW_CURRENCY


async def goal_new_currency(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    uid = query.from_user.id
    l = lang(uid)
    new_currency = query.data.split("_", 1)[1]
    goal_id = context.user_data["convert_goal_id"]
    goal = db.get_goal(goal_id)

    if not goal:
        await query.edit_message_text(t(l, "error"), parse_mode=ParseMode.MARKDOWN)
        return ConversationHandler.END

    # Fetch rates to convert
    await query.edit_message_text(t(l, "fetching_rates"), parse_mode=ParseMode.MARKDOWN)
    fiat, crypto, metals = await cur.fetch_all_rates()

    new_target = cur.convert_amount(
        goal["target_amount"], goal["currency"], new_currency, fiat, crypto, metals
    )
    new_current = cur.convert_amount(
        goal["current_amount"], goal["currency"], new_currency, fiat, crypto, metals
    )

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


# ─────────────────── CANCEL ───────────────────

async def conv_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    uid = query.from_user.id
    l = lang(uid)
    await query.edit_message_text(t(l, "cancelled"), parse_mode=ParseMode.MARKDOWN)
    await asyncio.sleep(0.3)
    await send_main_menu(update, uid, edit=True)
    return ConversationHandler.END


async def text_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    l = lang(uid)
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

    # ── Delete individual transaction conversation ──
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

    # ── Add income/expense conversation ──
    trans_conv = ConversationHandler(
        entry_points=[
            CallbackQueryHandler(trans_start, pattern="^trans_add_(income|expense)$"),
        ],
        states={
            S_TRANS_AMOUNT: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, trans_amount),
            ],
            S_TRANS_CURRENCY: [
                CallbackQueryHandler(trans_currency, pattern="^tcur_"),
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

    # ── Add goal conversation ──
    goal_add_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(goal_add_start, pattern="^goal_add$")],
        states={
            S_GOAL_TYPE: [CallbackQueryHandler(goal_type, pattern="^gtype_")],
            S_GOAL_TITLE: [MessageHandler(filters.TEXT & ~filters.COMMAND, goal_title)],
            S_GOAL_AMOUNT: [MessageHandler(filters.TEXT & ~filters.COMMAND, goal_amount)],
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

    # ── Delete goal conversation ──
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

    # ── Convert goal currency conversation ──
    goal_convert_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(goal_convert_start, pattern="^goal_convert$")],
        states={
            S_GOAL_SELECT_CONVERT: [CallbackQueryHandler(goal_select_convert, pattern="^gconv_")],
            S_GOAL_NEW_CURRENCY: [CallbackQueryHandler(goal_new_currency, pattern="^gnewcur_")],
        },
        fallbacks=[
            CallbackQueryHandler(conv_cancel, pattern="^conv_cancel$"),
            CommandHandler("cancel", text_cancel),
        ],
        per_message=False,
    )

    # ── Settings base currency conversation ──
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

    # ── Custom stats date-range conversation ──
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
        fallbacks=[
            CommandHandler("cancel", text_cancel),
        ],
        per_message=False,
    )

    # Register conversations (order matters — stats_custom_conv first!)
    for conv in [
        stats_custom_conv,
        trans_delete_conv,
        trans_conv, goal_add_conv,
        goal_delete_conv, goal_convert_conv,
        settings_cur_conv,
    ]:
        app.add_handler(conv)

    # ── Non-conversation callbacks ──
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("menu", cmd_menu))

    # Language selection
    app.add_handler(CallbackQueryHandler(cb_set_language, pattern="^setlang_"))

    # Main menu routing
    app.add_handler(CallbackQueryHandler(
        cb_main_menu,
        pattern="^(back_main|menu_transactions|menu_goals|menu_currencies|"
                "menu_stats|menu_settings|settings_language|settings_status_notifications|"
                "trans_view|trans_clear|goal_view)$"
    ))

    # Back from stats — deletes chart photos then goes to main menu
    app.add_handler(CallbackQueryHandler(cb_back_stats, pattern="^back_stats$"))
    
    # Transaction clear confirmation
    app.add_handler(CallbackQueryHandler(cb_clear_transactions_confirm, pattern="^trans_clear_confirm$"))
    app.add_handler(CallbackQueryHandler(cb_main_menu, pattern="^back_transactions$"))

    # Stats period buttons (week / month / 6m / year)
    app.add_handler(CallbackQueryHandler(cb_stats_period, pattern="^stats_p_(week|month|6m|year)$"))

    return app


# Minimum uptime in seconds before an offline notification is sent.
# Prevents a false offline alert when startup fails due to 409 Conflict.
_MIN_UPTIME_FOR_OFFLINE_NOTIFY = 15


async def on_bot_start(app: Application) -> None:
    """Called when bot starts - set commands and notify users."""
    # Record startup time so on_bot_stop can check actual uptime
    app.bot_data["startup_time"] = datetime.now()

    await app.bot.set_my_commands([
        BotCommand("start", "Start / Language select"),
        BotCommand("menu", "Open main menu"),
        BotCommand("cancel", "Cancel current action"),
    ])

    notified = await broadcast_status_notification(app, "online")
    db.log_bot_status("online", notified)
    logger.info(f"\u2705 Bot online notifications sent to {notified} users")


async def on_bot_stop(app: Application) -> None:
    """Called on post_stop - HTTP client is still alive here.

    Guard: if the bot stopped within _MIN_UPTIME_FOR_OFFLINE_NOTIFY seconds
    of starting (e.g. 409 Conflict because another instance is running),
    skip the offline notification. The user already received an online message
    from the surviving instance; sending offline right after would be confusing.
    """
    startup_time = app.bot_data.get("startup_time")
    if startup_time is not None:
        uptime = (datetime.now() - startup_time).total_seconds()
        if uptime < _MIN_UPTIME_FOR_OFFLINE_NOTIFY:
            logger.info(
                f"Skipping offline notification - uptime only {uptime:.1f}s "
                f"(threshold {_MIN_UPTIME_FOR_OFFLINE_NOTIFY}s). "
                f"Likely a startup conflict, not a real shutdown."
            )
            return

    try:
        notified = await broadcast_status_notification(app, "offline")
        db.log_bot_status("offline", notified)
        logger.info(f"\U0001f534 Bot offline notifications sent to {notified} users")
    except Exception as e:
        logger.warning(f"Could not send offline notifications: {e}")


if __name__ == "__main__":
    db.init_db()
    app = build_application()

    # post_init  -> runs after the HTTP client is ready (good for "bot online" msg)
    # post_stop  -> runs before the HTTP client is torn down (good for "bot offline" msg)
    # post_shutdown would be too late - the HTTP client is already closed there
    app.post_init = on_bot_start
    app.post_stop = on_bot_stop

    logger.info("\u2705 Money Manager Bot started!")
    app.run_polling(allowed_updates=Update.ALL_TYPES)
