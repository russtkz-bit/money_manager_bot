"""
database.py — PostgreSQL backend for Money Manager Bot.

Connection is configured via the DATABASE_URL environment variable:
    DATABASE_URL=postgresql://user:password@host:5432/dbname

Install dependency:  pip install psycopg2-binary
"""

import os
import logging
from contextlib import contextmanager
from typing import Optional, List, Dict, Any

import psycopg2
import psycopg2.extras
from psycopg2.extras import RealDictCursor

logger = logging.getLogger(__name__)

DATABASE_URL = os.getenv("DATABASE_URL")


@contextmanager
def get_connection():
    """Yield a psycopg2 connection; auto-commit on success, rollback on error."""
    if not DATABASE_URL:
        raise RuntimeError("DATABASE_URL environment variable is not set")
    conn = psycopg2.connect(DATABASE_URL, cursor_factory=RealDictCursor)
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


# ──────────────── SCHEMA INIT ────────────────

def init_db():
    """Create tables if they don't exist. Safe to call on every startup."""
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                CREATE TABLE IF NOT EXISTS users (
                    user_id       BIGINT PRIMARY KEY,
                    language      TEXT NOT NULL DEFAULT 'en',
                    base_currency TEXT NOT NULL DEFAULT 'USD',
                    created_at    TIMESTAMPTZ NOT NULL DEFAULT NOW()
                );

                CREATE TABLE IF NOT EXISTS transactions (
                    id          BIGSERIAL PRIMARY KEY,
                    user_id     BIGINT NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
                    type        TEXT   NOT NULL CHECK (type IN ('income','expense')),
                    amount      NUMERIC(18,4) NOT NULL,
                    currency    TEXT   NOT NULL DEFAULT 'USD',
                    category    TEXT   NOT NULL,
                    description TEXT   NOT NULL DEFAULT '',
                    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
                );

                CREATE TABLE IF NOT EXISTS goals (
                    id             BIGSERIAL PRIMARY KEY,
                    user_id        BIGINT NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
                    title          TEXT   NOT NULL,
                    goal_type      TEXT   NOT NULL CHECK (goal_type IN ('save','repay')),
                    target_amount  NUMERIC(18,4) NOT NULL,
                    current_amount NUMERIC(18,4) NOT NULL DEFAULT 0,
                    currency       TEXT   NOT NULL DEFAULT 'USD',
                    deadline       DATE   DEFAULT NULL,
                    completed      BOOLEAN NOT NULL DEFAULT FALSE,
                    created_at     TIMESTAMPTZ NOT NULL DEFAULT NOW()
                );

                CREATE INDEX IF NOT EXISTS idx_transactions_user_date
                    ON transactions (user_id, created_at);
                CREATE INDEX IF NOT EXISTS idx_goals_user
                    ON goals (user_id);
            """)
    logger.info("Database schema initialised")


# ──────────────── ROW NORMALISATION ────────────────

def _norm_goal(d: dict) -> dict:
    """Convert PostgreSQL-specific types to plain Python for bot compatibility."""
    d["completed"]      = int(bool(d["completed"]))
    d["target_amount"]  = float(d["target_amount"])
    d["current_amount"] = float(d["current_amount"])
    if d.get("deadline") is not None:
        d["deadline"] = str(d["deadline"])
    if d.get("created_at") is not None:
        d["created_at"] = str(d["created_at"])
    return d


def _norm_tx(d: dict) -> dict:
    d["amount"] = float(d["amount"])
    if d.get("created_at") is not None:
        d["created_at"] = str(d["created_at"])
    return d


# ──────────────── USERS ────────────────

def ensure_user(user_id: int):
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO users (user_id) VALUES (%s) ON CONFLICT DO NOTHING",
                (user_id,)
            )


def get_user(user_id: int) -> Optional[Dict]:
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT * FROM users WHERE user_id = %s", (user_id,))
            row = cur.fetchone()
            return dict(row) if row else None


def set_user_language(user_id: int, lang: str):
    ensure_user(user_id)
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE users SET language = %s WHERE user_id = %s", (lang, user_id)
            )


def set_user_base_currency(user_id: int, currency: str):
    ensure_user(user_id)
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE users SET base_currency = %s WHERE user_id = %s", (currency, user_id)
            )


def get_user_lang(user_id: int) -> str:
    user = get_user(user_id)
    return user["language"] if user else "en"


def get_user_base_currency(user_id: int) -> str:
    user = get_user(user_id)
    return user["base_currency"] if user else "USD"


# ──────────────── TRANSACTIONS ────────────────

def add_transaction(user_id: int, t_type: str, amount: float,
                    currency: str, category: str, description: str = "") -> int:
    ensure_user(user_id)
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO transactions "
                "(user_id, type, amount, currency, category, description) "
                "VALUES (%s,%s,%s,%s,%s,%s) RETURNING id",
                (user_id, t_type, amount, currency, category, description)
            )
            return cur.fetchone()["id"]


def get_transactions(user_id: int, limit: int = 20) -> List[Dict]:
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT * FROM transactions "
                "WHERE user_id = %s ORDER BY created_at DESC LIMIT %s",
                (user_id, limit)
            )
            return [_norm_tx(dict(r)) for r in cur.fetchall()]


def delete_transaction(transaction_id: int):
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM transactions WHERE id = %s", (transaction_id,))


def delete_all_transactions(user_id: int) -> int:
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM transactions WHERE user_id = %s", (user_id,))
            return cur.rowcount


def get_statistics(user_id: int) -> Dict[str, Any]:
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT type, SUM(amount) AS total, currency "
                "FROM transactions WHERE user_id = %s GROUP BY type, currency",
                (user_id,)
            )
            rows = cur.fetchall()
            cur.execute(
                "SELECT category, SUM(amount) AS total "
                "FROM transactions WHERE user_id = %s AND type='expense' "
                "GROUP BY category",
                (user_id,)
            )
            cat_rows = cur.fetchall()

    income: Dict[str, float]  = {}
    expense: Dict[str, float] = {}
    for r in rows:
        val = float(r["total"])
        if r["type"] == "income":
            income[r["currency"]]  = income.get(r["currency"],  0) + val
        else:
            expense[r["currency"]] = expense.get(r["currency"], 0) + val

    by_category: Dict[str, float] = {}
    for r in cat_rows:
        by_category[r["category"]] = by_category.get(r["category"], 0) + float(r["total"])

    return {"income": income, "expense": expense, "by_category": by_category}


# ──────────────── GOALS ────────────────

def add_goal(user_id: int, title: str, goal_type: str,
             target_amount: float, currency: str,
             deadline: Optional[str] = None,
             initial_amount: float = 0.0) -> int:
    ensure_user(user_id)
    completed = initial_amount >= target_amount
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO goals "
                "(user_id, title, goal_type, target_amount, current_amount, "
                " currency, deadline, completed) "
                "VALUES (%s,%s,%s,%s,%s,%s,%s,%s) RETURNING id",
                (user_id, title, goal_type, target_amount,
                 round(initial_amount, 4), currency, deadline or None, completed)
            )
            return cur.fetchone()["id"]


def get_goals(user_id: int) -> List[Dict]:
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT * FROM goals WHERE user_id = %s ORDER BY created_at DESC",
                (user_id,)
            )
            return [_norm_goal(dict(r)) for r in cur.fetchall()]


def get_goal(goal_id: int) -> Optional[Dict]:
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT * FROM goals WHERE id = %s", (goal_id,))
            row = cur.fetchone()
            return _norm_goal(dict(row)) if row else None


def update_goal_progress(goal_id: int, amount: float) -> Dict:
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE goals SET current_amount = current_amount + %s WHERE id = %s",
                (amount, goal_id)
            )
            cur.execute("SELECT * FROM goals WHERE id = %s", (goal_id,))
            goal = _norm_goal(dict(cur.fetchone()))
            if goal["current_amount"] >= goal["target_amount"]:
                cur.execute("UPDATE goals SET completed = TRUE WHERE id = %s", (goal_id,))
                goal["completed"] = 1
    return goal


def delete_goal(goal_id: int):
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM goals WHERE id = %s", (goal_id,))


def update_goal_currency(goal_id: int, new_currency: str,
                         new_target: float, new_current: float):
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE goals SET currency=%s, target_amount=%s, current_amount=%s "
                "WHERE id=%s",
                (new_currency, new_target, new_current, goal_id)
            )


def update_goals_from_transaction(user_id: int, amount: float, currency: str,
                                  conversion_rates: dict = None) -> List[Dict]:
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT * FROM goals WHERE user_id=%s AND completed=FALSE ORDER BY id",
                (user_id,)
            )
            goals = [dict(r) for r in cur.fetchall()]

            updated = []
            for goal in goals:
                goal_currency = goal["currency"]
                amount_to_add = amount

                if currency != goal_currency:
                    if conversion_rates:
                        amount_to_add = convert_currency(
                            amount, currency, goal_currency, conversion_rates
                        )
                    else:
                        continue

                new_current = float(goal["current_amount"]) + amount_to_add
                completed   = new_current >= float(goal["target_amount"])
                cur.execute(
                    "UPDATE goals SET current_amount=%s, completed=%s WHERE id=%s",
                    (new_current, completed, goal["id"])
                )
                goal = _norm_goal(dict(goal))
                goal["current_amount"] = new_current
                goal["completed"]      = int(completed)
                updated.append(goal)

    return updated


# ──────────────── CURRENCY HELPERS ────────────────

def convert_currency(amount: float, from_currency: str, to_currency: str,
                     conversion_rates: dict) -> float:
    if from_currency == to_currency:
        return amount
    fiat   = conversion_rates.get("fiat",   {})
    crypto = conversion_rates.get("crypto", {})
    metals = conversion_rates.get("metals", {})
    from_rate = get_currency_to_usd_rate(from_currency, fiat, crypto, metals)
    to_rate   = get_currency_to_usd_rate(to_currency,   fiat, crypto, metals)
    if from_rate is None or to_rate is None:
        return amount
    return round(amount / from_rate * to_rate, 2)


def get_currency_to_usd_rate(currency: str, fiat: dict,
                              crypto: dict, metals: dict) -> Optional[float]:
    if currency == "USD":
        return 1.0
    if currency in fiat:
        return fiat[currency]
    if currency in crypto:
        p = crypto[currency]
        return (1.0 / p) if p else None
    if currency in metals:
        p = metals[currency]
        return (1.0 / p) if p else None
    return None


# ──────────────── FILTERED QUERIES (statistics) ────────────────

def get_transactions_filtered(user_id: int,
                               start_date: Optional[str] = None,
                               end_date: Optional[str] = None) -> List[Dict]:
    with get_connection() as conn:
        with conn.cursor() as cur:
            if start_date and end_date:
                cur.execute(
                    "SELECT * FROM transactions WHERE user_id=%s "
                    "AND created_at::date BETWEEN %s AND %s ORDER BY created_at ASC",
                    (user_id, start_date, end_date)
                )
            elif start_date:
                cur.execute(
                    "SELECT * FROM transactions WHERE user_id=%s "
                    "AND created_at::date >= %s ORDER BY created_at ASC",
                    (user_id, start_date)
                )
            else:
                cur.execute(
                    "SELECT * FROM transactions WHERE user_id=%s ORDER BY created_at ASC",
                    (user_id,)
                )
            return [_norm_tx(dict(r)) for r in cur.fetchall()]


def get_statistics_filtered(user_id: int,
                             start_date: Optional[str] = None,
                             end_date: Optional[str] = None) -> Dict[str, Any]:
    if start_date and end_date:
        date_clause = "AND created_at::date BETWEEN %s AND %s"
        extra: list = [start_date, end_date]
    elif start_date:
        date_clause = "AND created_at::date >= %s"
        extra = [start_date]
    else:
        date_clause = ""
        extra = []

    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                f"SELECT type, SUM(amount) AS total, currency "
                f"FROM transactions WHERE user_id=%s {date_clause} "
                f"GROUP BY type, currency",
                [user_id] + extra
            )
            rows = cur.fetchall()
            cur.execute(
                f"SELECT category, SUM(amount) AS total "
                f"FROM transactions WHERE user_id=%s AND type='expense' {date_clause} "
                f"GROUP BY category",
                [user_id] + extra
            )
            cat_rows = cur.fetchall()

    income:  Dict[str, float] = {}
    expense: Dict[str, float] = {}
    for r in rows:
        val = float(r["total"])
        if r["type"] == "income":
            income[r["currency"]]  = income.get(r["currency"],  0) + val
        else:
            expense[r["currency"]] = expense.get(r["currency"], 0) + val

    by_category: Dict[str, float] = {}
    for r in cat_rows:
        by_category[r["category"]] = by_category.get(r["category"], 0) + float(r["total"])

    return {"income": income, "expense": expense, "by_category": by_category}


# ──────────────── GOAL RECALCULATION ────────────────

def recalculate_all_goals(user_id: int,
                          conversion_rates: dict = None) -> List[Dict]:
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT * FROM goals WHERE user_id=%s ORDER BY id", (user_id,))
            goals = [dict(r) for r in cur.fetchall()]
            cur.execute(
                "SELECT amount, currency FROM transactions "
                "WHERE user_id=%s AND type='income'",
                (user_id,)
            )
            income_txns = cur.fetchall()

            updated: List[Dict] = []
            for goal in goals:
                total = 0.0
                for tx in income_txns:
                    amt = float(tx["amount"])
                    if tx["currency"] == goal["currency"]:
                        total += amt
                    elif conversion_rates:
                        total += convert_currency(
                            amt, tx["currency"], goal["currency"], conversion_rates
                        )
                total     = round(total, 4)
                completed = total >= float(goal["target_amount"])
                cur.execute(
                    "UPDATE goals SET current_amount=%s, completed=%s WHERE id=%s",
                    (total, completed, goal["id"])
                )
                g = _norm_goal(dict(goal))
                g["current_amount"] = total
                g["completed"]      = int(completed)
                updated.append(g)

    return updated


def calculate_initial_goal_amount(user_id: int,
                                  goal_currency: str,
                                  conversion_rates: dict = None) -> float:
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT amount, currency FROM transactions "
                "WHERE user_id=%s AND type='income'",
                (user_id,)
            )
            rows = cur.fetchall()

    total = 0.0
    for row in rows:
        amt = float(row["amount"])
        if row["currency"] == goal_currency:
            total += amt
        elif conversion_rates:
            total += convert_currency(amt, row["currency"], goal_currency, conversion_rates)

    return round(total, 4)
