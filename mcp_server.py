"""
mcp_server.py — read-only MCP (Model Context Protocol) connector for Claude.

Lets Claude (Desktop, Code, or a compatible client) answer questions about
your finances — net worth, transactions, budgets, goals, recurring spend,
forecast — using the exact same database.py/finance.py logic as the bot and
web dashboard. Deliberately read-only: no tool here can add, edit, or
delete anything, so a leaked token can expose data but never corrupt it
(same posture as the web dashboard).

Mounted into webapp.py at /mcp, behind that process's own bearer-token
middleware — this module has no HTTP/auth handling of its own, only the
`current_user_id` contextvar the middleware sets per request before a tool
runs. It is never run standalone.
"""

from contextvars import ContextVar
from datetime import datetime, timedelta
from typing import Optional

from mcp.server.fastmcp import FastMCP

import currencies as cur
import database as db
import finance
from languages import category_label

current_user_id: ContextVar[int] = ContextVar("current_user_id")

mcp = FastMCP(
    "Money Manager",
    instructions=(
        "Read-only access to one person's personal finance data (accounts, "
        "transactions, budgets, goals, recurring spend, net worth forecast). "
        "Amounts are in each account's own currency unless a tool converts "
        "to the user's base currency, which each tool's result makes clear."
    ),
    stateless_http=True,
    streamable_http_path="/",
)


async def _rates_safe():
    try:
        return await cur.fetch_all_rates()
    except Exception:
        return {}, {}, {}


def _valid_date(value: Optional[str]) -> Optional[str]:
    if not value:
        return None
    try:
        datetime.strptime(value, "%Y-%m-%d")
    except ValueError:
        return None
    return value


@mcp.tool()
async def get_net_worth() -> dict:
    """Total net worth: every account's balance converted to the user's base
    currency and summed."""
    uid = current_user_id.get()
    base_currency = db.get_user_base_currency(uid)
    fiat, crypto, metals = await _rates_safe()
    total, all_converted = finance.net_worth(uid, base_currency, fiat, crypto, metals)
    return {
        "net_worth": round(total, 2),
        "currency": base_currency,
        "rates_incomplete": not all_converted,
    }


@mcp.tool()
async def list_accounts() -> dict:
    """List every account with its current balance (in the account's own
    currency, not converted)."""
    uid = current_user_id.get()
    accounts = db.get_accounts_with_balances(uid)
    return {
        "accounts": [
            {
                "id": a["id"],
                "name": a["name"],
                "type": a["account_type"],
                "currency": a["currency"],
                "balance": round(a["computed_balance"], 2),
            }
            for a in accounts
        ]
    }


@mcp.tool()
async def list_transactions(
    start: Optional[str] = None,
    end: Optional[str] = None,
    type: Optional[str] = None,
    limit: int = 100,
) -> dict:
    """List transactions, most recent first.

    start/end: YYYY-MM-DD (default: last 30 days if both omitted).
    type: "income", "expense", or omit for both.
    limit: max rows to return (capped at 500) — narrow the date range for
    a fuller picture instead of raising this if there's a lot of history.
    """
    uid = current_user_id.get()
    lang = db.get_user_lang(uid)
    start = _valid_date(start)
    end = _valid_date(end)
    if not start or not end or start > end:
        today = datetime.now().date()
        start = (today - timedelta(days=29)).strftime("%Y-%m-%d")
        end = today.strftime("%Y-%m-%d")

    txns = db.get_transactions_filtered(uid, start, end)
    txns = sorted(txns, key=lambda t: t["created_at"], reverse=True)
    if type in ("income", "expense"):
        txns = [t for t in txns if t["type"] == type]

    limit = max(1, min(limit, 500))
    truncated = len(txns) > limit
    txns = txns[:limit]

    account_names = {a["id"]: a["name"] for a in db.get_accounts(uid)}
    return {
        "start": start,
        "end": end,
        "count": len(txns),
        "truncated": truncated,
        "transactions": [
            {
                "date": (t["created_at"] or "")[:10],
                "type": t["type"],
                "amount": t["amount"],
                "currency": t["currency"],
                "category": category_label(t["category"], lang),
                "description": t["description"],
                "account": account_names.get(t["account_id"], "—"),
            }
            for t in txns
        ],
    }


@mcp.tool()
async def get_statistics(period: str = "month") -> dict:
    """Income/expense totals and category breakdown, converted to the
    user's base currency. period: "week", "month", "6m", or "year"."""
    uid = current_user_id.get()
    lang = db.get_user_lang(uid)
    base_currency = db.get_user_base_currency(uid)
    start, end, _ = finance.period_dates(period if period in ("week", "month", "6m", "year") else "month")
    fiat, crypto, metals = await _rates_safe()
    txns = db.get_transactions_filtered(uid, start, end)
    agg = finance.aggregate_transactions(txns, base_currency, lang, fiat, crypto, metals)
    return {
        "start": start,
        "end": end,
        "currency": base_currency,
        "total_income": round(agg["total_income"], 2),
        "total_expense": round(agg["total_expense"], 2),
        "balance": round(agg["total_income"] - agg["total_expense"], 2),
        "by_category": {k: round(v, 2) for k, v in agg["by_category"].items()},
        "rates_incomplete": not agg["all_converted"],
    }


@mcp.tool()
async def list_budgets() -> dict:
    """Monthly budgets per category: limit, amount spent so far this month,
    and whether it's been exceeded."""
    uid = current_user_id.get()
    lang = db.get_user_lang(uid)
    budgets = db.get_budgets(uid)
    if not budgets:
        return {"budgets": []}
    fiat, crypto, metals = await _rates_safe()
    conversion_rates = {"fiat": fiat, "crypto": crypto, "metals": metals}
    rows = []
    for b in budgets:
        spent, all_converted = finance.spent_this_month(uid, b["category"], b["currency"], conversion_rates)
        rows.append({
            "category": category_label(b["category"], lang),
            "limit": b["amount"],
            "spent": round(spent, 2),
            "currency": b["currency"],
            "over_limit": spent >= b["amount"],
            "rates_incomplete": not all_converted,
        })
    return {"budgets": rows}


@mcp.tool()
async def list_goals() -> dict:
    """Savings/repayment goals with progress toward their target amount."""
    uid = current_user_id.get()
    goals = db.get_goals(uid)
    return {
        "goals": [
            {
                "title": g["title"],
                "type": g["goal_type"],
                "target_amount": g["target_amount"],
                "current_amount": round(g["current_amount"], 2),
                "currency": g["currency"],
                "progress_pct": min(100, round(g["current_amount"] / g["target_amount"] * 100)) if g["target_amount"] else 0,
                "deadline": g["deadline"],
                "completed": bool(g["completed"]),
            }
            for g in goals
        ]
    }


@mcp.tool()
async def get_recurring_expenses() -> dict:
    """Expense categories detected as recurring (spending in the same
    category across at least 2 of the last ~3 months) with their average
    monthly amount — a lightweight subscriptions/rent finder."""
    uid = current_user_id.get()
    lang = db.get_user_lang(uid)
    base_currency = db.get_user_base_currency(uid)
    fiat, crypto, metals = await _rates_safe()
    since = (datetime.now().date() - timedelta(days=89)).strftime("%Y-%m-%d")
    txns = db.get_transactions_filtered(uid, since)
    recurring, all_converted = finance.detect_recurring(txns, base_currency, fiat, crypto, metals)
    return {
        "currency": base_currency,
        "total_monthly": round(sum(r["avg_amount"] for r in recurring), 2),
        "rates_incomplete": not all_converted,
        "items": [
            {
                "category": category_label(r["category"], lang),
                "avg_monthly_amount": round(r["avg_amount"], 2),
                "seen_in_months": r["months"],
                "last_date": r["last_date"],
            }
            for r in recurring
        ],
    }


@mcp.tool()
async def get_net_worth_forecast(months_ahead: int = 6) -> dict:
    """"If nothing changes" net worth projection: extends the recent
    average monthly net cash flow (last 90 days) forward from today's
    actual net worth. months_ahead: how far out to project (1-24)."""
    uid = current_user_id.get()
    base_currency = db.get_user_base_currency(uid)
    fiat, crypto, metals = await _rates_safe()
    months_ahead = max(1, min(months_ahead, 24))
    forecast = finance.forecast_net_worth(uid, base_currency, fiat, crypto, metals, months_ahead=months_ahead)
    return {
        "currency": base_currency,
        "current_net_worth": round(forecast["current"], 2),
        "avg_monthly_net": round(forecast["monthly_net"], 2),
        "months_ahead": months_ahead,
        "projected_net_worth": round(forecast["points"][-1][1], 2),
        "rates_incomplete": not forecast["all_converted"],
    }
