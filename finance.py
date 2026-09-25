"""
finance.py — currency-aware aggregation helpers shared between the
Telegram bot and the web dashboard.

Keeping this logic in exactly one place is deliberate: an earlier bug came
from database.py silently duplicating currencies.py's conversion math with
a different (unsafe) contract on a missing rate. Every frontend (bot.py,
webapp/) must call through here rather than growing its own copy.
"""

from datetime import datetime
from typing import Dict, List, Optional, Tuple

import currencies as cur
import database as db


def month_bounds() -> Tuple[str, str]:
    """Return (start, end) of the current calendar month as YYYY-MM-DD strings."""
    today = datetime.now().date()
    start = today.replace(day=1)
    return start.strftime("%Y-%m-%d"), today.strftime("%Y-%m-%d")


def convert_or_flag(amount: float, from_currency: str, to_currency: str,
                    fiat: dict, crypto: dict, metals: dict) -> Tuple[float, bool]:
    """Convert amount to to_currency; returns (converted_amount, ok).

    ok is False only when a real cross-currency conversion was needed but no
    rate was available — in that case the returned amount is 0.0, so callers
    must track `ok` across all conversions and tell the user the total may
    be incomplete rather than silently presenting a too-low number as final.
    """
    if from_currency == to_currency:
        return amount, True
    conv = cur.convert_amount(amount, from_currency, to_currency, fiat, crypto, metals)
    if conv is not None:
        return conv, True
    return 0.0, False


def spent_this_month(uid: int, category_key: str, target_currency: str,
                     conversion_rates: dict) -> Tuple[float, bool]:
    """Sum this calendar month's expenses in `category_key`, converted to
    target_currency. Returns (total, all_converted)."""
    start, end = month_bounds()
    txns  = db.get_transactions_filtered(uid, start, end)
    fiat   = conversion_rates.get("fiat", {})
    crypto = conversion_rates.get("crypto", {})
    metals = conversion_rates.get("metals", {})
    total = 0.0
    all_converted = True
    for tx in txns:
        if tx["type"] != "expense" or tx["category"] != category_key:
            continue
        amt, ok = convert_or_flag(tx["amount"], tx["currency"], target_currency, fiat, crypto, metals)
        total += amt
        all_converted = all_converted and ok
    return total, all_converted


def detect_recurring(txns: list, base_currency: str,
                     fiat: dict, crypto: dict, metals: dict,
                     min_months: int = 2) -> Tuple[list, bool]:
    """
    Heuristic recurring-expense detector: groups expenses by category, and
    flags a category as recurring when it has spending in at least
    `min_months` distinct calendar months. Returns
    (recurring, all_converted) where recurring is a list of
    {category, avg_amount, months, last_date} sorted by avg_amount desc.

    This is a lightweight stand-in for PocketSmith's recurring-transaction /
    cash-flow forecast — good enough to spot subscriptions, rent, etc.
    without needing merchant-level matching.
    """
    by_cat: Dict[str, dict] = {}
    all_converted = True
    for tx in txns:
        if tx["type"] != "expense":
            continue
        amt, ok = convert_or_flag(tx["amount"], tx["currency"], base_currency, fiat, crypto, metals)
        all_converted = all_converted and ok
        date_str = (tx.get("created_at") or "")[:10]
        month    = date_str[:7]
        cat      = tx["category"]
        entry    = by_cat.setdefault(cat, {"amounts": [], "months": set(), "last_date": date_str})
        entry["amounts"].append(amt)
        if month:
            entry["months"].add(month)
        if date_str > entry["last_date"]:
            entry["last_date"] = date_str

    recurring = []
    for cat, entry in by_cat.items():
        if len(entry["months"]) < min_months:
            continue
        avg = sum(entry["amounts"]) / len(entry["months"])
        recurring.append({
            "category": cat,
            "avg_amount": avg,
            "months": len(entry["months"]),
            "last_date": entry["last_date"],
        })
    recurring.sort(key=lambda r: r["avg_amount"], reverse=True)
    return recurring, all_converted


def net_worth(uid: int, base_currency: str,
             fiat: dict, crypto: dict, metals: dict) -> Tuple[float, bool]:
    """Sum every account's computed balance, converted to base_currency.
    Returns (total, all_converted)."""
    accounts = db.get_accounts_with_balances(uid)
    total = 0.0
    all_converted = True
    for acc in accounts:
        amt, ok = convert_or_flag(acc["computed_balance"], acc["currency"],
                                  base_currency, fiat, crypto, metals)
        total += amt
        all_converted = all_converted and ok
    return total, all_converted
