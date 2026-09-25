"""
webapp.py — read-only web dashboard for Money Manager Bot.

Runs as a separate process from bot.py (same database, same finance.py /
database.py logic — never a second copy of the business rules). Users log
in with a short-lived code from the bot's /webcode command; there is no
password and no public sign-up, since every account already exists as a
Telegram user.

Run directly for local development:
    uvicorn webapp:app --reload --port 8000
In production this is started by systemd — see deploy/POSTGRES_SETUP.md's
sibling doc for the web app, deploy/WEBAPP_SETUP.md.
"""

import os
from datetime import datetime, timedelta
from typing import Optional

from dotenv import load_dotenv

# Same ordering requirement as bot.py: database.py reads DATABASE_URL from
# the environment at import time, so .env must be loaded first.
load_dotenv()

from fastapi import FastAPI, Request, Form, Query
from fastapi.responses import RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware

import charts as ch
import currencies as cur
import database as db
import finance
from languages import t as translate, category_label

VALID_PERIODS = ("week", "month", "6m", "year")

ACCOUNT_TYPE_EMOJI = {"bank": "🏦", "crypto": "₿", "cash": "💵"}
ACCOUNT_TYPE_KEY = {"bank": "account_type_bank", "crypto": "account_type_crypto", "cash": "account_type_cash"}

SESSION_SECRET = os.getenv("SESSION_SECRET")
if not SESSION_SECRET:
    raise ValueError(
        "SESSION_SECRET not set in environment! Generate one with: "
        "python3 -c \"import secrets; print(secrets.token_hex(32))\""
    )

# Cookies are marked Secure (HTTPS-only) by default, matching the intended
# deployment (behind a Cloudflare Tunnel or any TLS-terminating proxy).
# Only disable this for local http://localhost development.
SESSION_HTTPS_ONLY = os.getenv("SESSION_HTTPS_ONLY", "true").lower() != "false"

app = FastAPI(title="Money Manager")
app.add_middleware(
    SessionMiddleware,
    secret_key=SESSION_SECRET,
    session_cookie="mmb_session",
    max_age=30 * 24 * 3600,   # 30 days
    same_site="lax",
    https_only=SESSION_HTTPS_ONLY,
)
app.mount("/static", StaticFiles(directory="static"), name="static")

templates = Jinja2Templates(directory="templates")
templates.env.globals["t"] = translate


def render(request: Request, name: str, **ctx):
    """Jinja2 render helper that always injects the logged-in user's id/lang."""
    user_id = request.session.get("user_id")
    lang = db.get_user_lang(user_id) if user_id else "en"
    return templates.TemplateResponse(
        request, name, {"user_id": user_id, "lang": lang, **ctx}
    )


def require_user(request: Request) -> int:
    """FastAPI dependency: returns the logged-in user_id, or redirects to /login.

    Raising a Starlette HTTPException with a 3xx status + Location header is
    the standard way to short-circuit a dependency into a redirect — the
    default exception handler still emits the Location header, which is all
    a browser needs to follow it, regardless of the body.
    """
    user_id = request.session.get("user_id")
    if not user_id:
        from starlette.exceptions import HTTPException
        raise HTTPException(status_code=303, headers={"Location": "/login"})
    return user_id


# ─────────────────── AUTH ───────────────────

@app.get("/login")
async def login_form(request: Request):
    if request.session.get("user_id"):
        return RedirectResponse("/", status_code=303)
    return render(request, "login.html")


@app.post("/login")
async def login_submit(request: Request, code: str = Form(...)):
    user_id = db.consume_web_login_code(code)
    if not user_id:
        return render(request, "login.html", error="Invalid or expired code / Неверный или просроченный код")
    request.session["user_id"] = user_id
    return RedirectResponse("/", status_code=303)


@app.get("/logout")
async def logout(request: Request):
    request.session.clear()
    return RedirectResponse("/login", status_code=303)


# ─────────────────── DASHBOARD ───────────────────

@app.get("/")
async def dashboard(request: Request):
    user_id = require_user(request)
    base_currency = db.get_user_base_currency(user_id)

    fiat, crypto, metals = {}, {}, {}
    try:
        fiat, crypto, metals = await cur.fetch_all_rates()
    except Exception:
        pass

    accounts = db.get_accounts_with_balances(user_id)
    for acc in accounts:
        acc["emoji"] = ACCOUNT_TYPE_EMOJI.get(acc["account_type"], "🏦")
        acc["type_label"] = translate(db.get_user_lang(user_id), ACCOUNT_TYPE_KEY.get(acc["account_type"], "account_type_bank"))

    total, all_converted = finance.net_worth(user_id, base_currency, fiat, crypto, metals)

    return render(
        request, "dashboard.html", active="dashboard",
        accounts=accounts,
        base_currency=base_currency,
        net_worth=total,
        net_worth_incomplete=not all_converted,
    )


# ─────────────────── TRANSACTIONS ───────────────────

MAX_TRANSACTIONS_SHOWN = 300


@app.get("/transactions")
async def transactions_page(
    request: Request,
    start: Optional[str] = None,
    end: Optional[str] = None,
    t_type: Optional[str] = Query(None, alias="type"),
):
    user_id = require_user(request)
    lang = db.get_user_lang(user_id)

    if not start or not end:
        today = datetime.now().date()
        start = (today - timedelta(days=29)).strftime("%Y-%m-%d")
        end = today.strftime("%Y-%m-%d")

    txns = db.get_transactions_filtered(user_id, start, end)
    txns = sorted(txns, key=lambda tx: tx["created_at"], reverse=True)

    if t_type in ("income", "expense"):
        txns = [tx for tx in txns if tx["type"] == t_type]

    truncated = len(txns) > MAX_TRANSACTIONS_SHOWN
    txns = txns[:MAX_TRANSACTIONS_SHOWN]

    account_names = {a["id"]: a["name"] for a in db.get_accounts(user_id)}
    for tx in txns:
        tx["category_display"] = category_label(tx["category"], lang)
        tx["account_name"] = account_names.get(tx["account_id"], "—")
        tx["date_display"] = (tx["created_at"] or "")[:10]

    return render(
        request, "transactions.html", active="transactions",
        txns=txns, start=start, end=end, type_filter=t_type or "all",
        truncated=truncated, shown_count=len(txns),
    )


# ─────────────────── STATS / CHARTS ───────────────────

async def _fetch_rates_safe():
    try:
        return await cur.fetch_all_rates()
    except Exception:
        return {}, {}, {}


def _stats_period(period: Optional[str]) -> str:
    return period if period in VALID_PERIODS else "month"


def _compute_period_data(user_id: int, start: str, end: str, base_currency: str,
                         fiat: dict, crypto: dict, metals: dict):
    """Returns (total_income, total_expense, by_cat_labeled, txns_base, incomplete),
    all amounts converted to base_currency."""
    lang = db.get_user_lang(user_id)
    txns = db.get_transactions_filtered(user_id, start, end)
    total_income = 0.0
    total_expense = 0.0
    by_cat: dict = {}
    txns_base = []
    incomplete = False
    for tx in txns:
        amt, ok = finance.convert_or_flag(tx["amount"], tx["currency"], base_currency, fiat, crypto, metals)
        incomplete = incomplete or not ok
        if tx["type"] == "income":
            total_income += amt
        else:
            total_expense += amt
            label = category_label(tx["category"], lang)
            by_cat[label] = by_cat.get(label, 0) + amt
        txns_base.append({**tx, "amount": amt, "currency": base_currency})
    return total_income, total_expense, by_cat, txns_base, incomplete


@app.get("/stats")
async def stats_page(request: Request, period: Optional[str] = None):
    user_id = require_user(request)
    period = _stats_period(period)
    base_currency = db.get_user_base_currency(user_id)
    start, end, _ = finance.period_dates(period)

    fiat, crypto, metals = await _fetch_rates_safe()
    total_income, total_expense, by_cat, txns_base, incomplete = _compute_period_data(
        user_id, start, end, base_currency, fiat, crypto, metals
    )
    goals = db.get_goals(user_id)

    return render(
        request, "stats.html", active="stats",
        period=period, start=start, end=end,
        total_income=total_income, total_expense=total_expense,
        balance=total_income - total_expense,
        base_currency=base_currency, incomplete=incomplete,
        has_data=bool(txns_base), has_categories=bool(by_cat), has_goals=bool(goals),
    )


@app.get("/stats/chart/pie.png")
async def chart_pie(request: Request, period: Optional[str] = None):
    user_id = require_user(request)
    period = _stats_period(period)
    base_currency = db.get_user_base_currency(user_id)
    start, end, _ = finance.period_dates(period)
    fiat, crypto, metals = await _fetch_rates_safe()
    _, _, by_cat, _, _ = _compute_period_data(user_id, start, end, base_currency, fiat, crypto, metals)
    lang = db.get_user_lang(user_id)
    img = ch.generate_pie_chart(by_cat, title=translate(lang, "chart_pie_title")) if by_cat else None
    if not img:
        return Response(status_code=204)
    return Response(content=img, media_type="image/png")


@app.get("/stats/chart/bar.png")
async def chart_bar(request: Request, period: Optional[str] = None):
    user_id = require_user(request)
    period = _stats_period(period)
    base_currency = db.get_user_base_currency(user_id)
    start, end, bar_period = finance.period_dates(period)
    fiat, crypto, metals = await _fetch_rates_safe()
    _, _, _, txns_base, _ = _compute_period_data(user_id, start, end, base_currency, fiat, crypto, metals)
    lang = db.get_user_lang(user_id)
    img = ch.generate_bar_chart(
        txns_base, bar_period,
        income_label=translate(lang, "income"), expense_label=translate(lang, "expense"),
        title=translate(lang, "chart_bar_title"),
    ) if txns_base else None
    if not img:
        return Response(status_code=204)
    return Response(content=img, media_type="image/png")


@app.get("/stats/chart/goals.png")
async def chart_goals(request: Request):
    user_id = require_user(request)
    goals = db.get_goals(user_id)
    lang = db.get_user_lang(user_id)
    img = ch.generate_goals_chart(goals, title=translate(lang, "chart_goals_title")) if goals else None
    if not img:
        return Response(status_code=204)
    return Response(content=img, media_type="image/png")
