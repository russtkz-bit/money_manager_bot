"""
database.py — PostgreSQL backend for Money Manager Bot.

Connection is configured via the DATABASE_URL environment variable:
    DATABASE_URL=postgresql://user:password@host:5432/dbname
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
    """Create / migrate schema. Safe to call on every startup."""
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                CREATE TABLE IF NOT EXISTS users (
                    user_id       BIGINT PRIMARY KEY,
                    language      TEXT NOT NULL DEFAULT 'en',
                    base_currency TEXT NOT NULL DEFAULT 'USD',
                    created_at    TIMESTAMPTZ NOT NULL DEFAULT NOW()
                );

                CREATE TABLE IF NOT EXISTS accounts (
                    id              BIGSERIAL PRIMARY KEY,
                    user_id         BIGINT NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
                    name            TEXT   NOT NULL,
                    currency        TEXT   NOT NULL DEFAULT 'USD',
                    initial_balance NUMERIC(18,4) NOT NULL DEFAULT 0,
                    account_type    TEXT   NOT NULL DEFAULT 'bank'
                                        CHECK (account_type IN ('bank','crypto','cash')),
                    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
                );
                CREATE INDEX IF NOT EXISTS idx_accounts_user ON accounts (user_id);

                CREATE TABLE IF NOT EXISTS transactions (
                    id          BIGSERIAL PRIMARY KEY,
                    user_id     BIGINT NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
                    account_id  BIGINT REFERENCES accounts(id) ON DELETE SET NULL,
                    type        TEXT   NOT NULL CHECK (type IN ('income','expense')),
                    amount      NUMERIC(18,4) NOT NULL,
                    currency    TEXT   NOT NULL DEFAULT 'USD',
                    category    TEXT   NOT NULL,
                    description TEXT   NOT NULL DEFAULT '',
                    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
                );
                CREATE INDEX IF NOT EXISTS idx_transactions_user_date
                    ON transactions (user_id, created_at);
                CREATE INDEX IF NOT EXISTS idx_transactions_user_category
                    ON transactions (user_id, category);

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
                CREATE INDEX IF NOT EXISTS idx_goals_user ON goals (user_id);

                CREATE TABLE IF NOT EXISTS budgets (
                    id          BIGSERIAL PRIMARY KEY,
                    user_id     BIGINT NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
                    category    TEXT   NOT NULL,
                    amount      NUMERIC(18,4) NOT NULL,
                    currency    TEXT   NOT NULL DEFAULT 'USD',
                    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    UNIQUE (user_id, category)
                );
                CREATE INDEX IF NOT EXISTS idx_budgets_user ON budgets (user_id);
            """)
            # Migration: add account_id to transactions if it doesn't exist yet
            cur.execute("""
                ALTER TABLE transactions
                ADD COLUMN IF NOT EXISTS account_id BIGINT
                    REFERENCES accounts(id) ON DELETE SET NULL;
            """)
    logger.info("Database schema initialised")


# ──────────────── ROW NORMALISATION ────────────────

def _norm_goal(d: dict) -> dict:
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


def _norm_account(d: dict) -> dict:
    d["initial_balance"] = float(d["initial_balance"])
    if d.get("created_at") is not None:
        d["created_at"] = str(d["created_at"])
    return d


def _norm_budget(d: dict) -> dict:
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
            cur.execute("UPDATE users SET language=%s WHERE user_id=%s", (lang, user_id))


def set_user_base_currency(user_id: int, currency: str):
    ensure_user(user_id)
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("UPDATE users SET base_currency=%s WHERE user_id=%s", (currency, user_id))


def get_user_lang(user_id: int) -> str:
    user = get_user(user_id)
    return user["language"] if user else "en"


def get_user_base_currency(user_id: int) -> str:
    user = get_user(user_id)
    return user["base_currency"] if user else "USD"


# ──────────────── ACCOUNTS ────────────────

def add_account(user_id: int, name: str, currency: str,
                initial_balance: float, account_type: str) -> int:
    ensure_user(user_id)
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO accounts (user_id, name, currency, initial_balance, account_type) "
                "VALUES (%s,%s,%s,%s,%s) RETURNING id",
                (user_id, name, currency, round(initial_balance, 4), account_type)
            )
            return cur.fetchone()["id"]


def get_accounts(user_id: int) -> List[Dict]:
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT * FROM accounts WHERE user_id=%s ORDER BY created_at ASC",
                (user_id,)
            )
            return [_norm_account(dict(r)) for r in cur.fetchall()]


def get_account(account_id: int) -> Optional[Dict]:
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT * FROM accounts WHERE id=%s", (account_id,))
            row = cur.fetchone()
            return _norm_account(dict(row)) if row else None


def delete_account(account_id: int):
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM accounts WHERE id=%s", (account_id,))


def _compute_balance_in_cur(cur, account_id: int, initial_balance: float) -> float:
    """Compute account balance = initial_balance + income - expenses (uses open cursor)."""
    cur.execute(
        "SELECT type, COALESCE(SUM(amount), 0) AS total "
        "FROM transactions WHERE account_id=%s GROUP BY type",
        (account_id,)
    )
    balance = initial_balance
    for row in cur.fetchall():
        if row["type"] == "income":
            balance += float(row["total"])
        else:
            balance -= float(row["total"])
    return balance


def get_accounts_with_balances(user_id: int) -> List[Dict]:
    """Return accounts list with extra 'computed_balance' field each."""
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT * FROM accounts WHERE user_id=%s ORDER BY created_at ASC",
                (user_id,)
            )
            accounts = [_norm_account(dict(r)) for r in cur.fetchall()]
            for acc in accounts:
                acc["computed_balance"] = _compute_balance_in_cur(
                    cur, acc["id"], acc["initial_balance"]
                )
    return accounts


# ──────────────── TRANSACTIONS ────────────────

def add_transaction(user_id: int, t_type: str, amount: float,
                    currency: str, category: str, description: str = "",
                    account_id: Optional[int] = None) -> int:
    ensure_user(user_id)
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO transactions "
                "(user_id, account_id, type, amount, currency, category, description) "
                "VALUES (%s,%s,%s,%s,%s,%s,%s) RETURNING id",
                (user_id, account_id, t_type, amount, currency, category, description)
            )
            return cur.fetchone()["id"]


def get_transactions(user_id: int, limit: int = 20) -> List[Dict]:
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT t.*, a.name AS account_name "
                "FROM transactions t "
                "LEFT JOIN accounts a ON t.account_id = a.id "
                "WHERE t.user_id=%s ORDER BY t.created_at DESC LIMIT %s",
                (user_id, limit)
            )
            return [_norm_tx(dict(r)) for r in cur.fetchall()]


def delete_transaction(transaction_id: int):
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM transactions WHERE id=%s", (transaction_id,))


def delete_all_transactions(user_id: int) -> int:
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM transactions WHERE user_id=%s", (user_id,))
            return cur.rowcount


def get_statistics(user_id: int) -> Dict[str, Any]:
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT type, SUM(amount) AS total, currency "
                "FROM transactions WHERE user_id=%s GROUP BY type, currency",
                (user_id,)
            )
            rows = cur.fetchall()
            cur.execute(
                "SELECT category, SUM(amount) AS total "
                "FROM transactions WHERE user_id=%s AND type='expense' GROUP BY category",
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
                "SELECT * FROM goals WHERE user_id=%s ORDER BY created_at DESC",
                (user_id,)
            )
            return [_norm_goal(dict(r)) for r in cur.fetchall()]


def get_goal(goal_id: int) -> Optional[Dict]:
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT * FROM goals WHERE id=%s", (goal_id,))
            row = cur.fetchone()
            return _norm_goal(dict(row)) if row else None


def delete_goal(goal_id: int):
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM goals WHERE id=%s", (goal_id,))


def update_goal_target(goal_id: int, new_target: float,
                       current_amount: float) -> Dict:
    """Update target_amount for a goal and re-evaluate completed flag."""
    completed = current_amount >= new_target
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE goals "
                "SET target_amount=%s, completed=%s "
                "WHERE id=%s",
                (round(new_target, 4), completed, goal_id)
            )
            cur.execute("SELECT * FROM goals WHERE id=%s", (goal_id,))
            return _norm_goal(dict(cur.fetchone()))


def update_goal_currency(goal_id: int, new_currency: str,
                         new_target: float, new_current: float):
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE goals SET currency=%s, target_amount=%s, current_amount=%s WHERE id=%s",
                (new_currency, new_target, new_current, goal_id)
            )


# ──────────────── CURRENCY HELPERS ────────────────

def _currency_to_usd_rate(currency: str, fiat: dict,
                           crypto: dict, metals: dict) -> Optional[float]:
    """Return how many units of `currency` equal 1 USD.
    Fiat: N units per USD.  Crypto/metals: stored as USD-per-unit, so invert."""
    if currency == "USD":
        return 1.0
    if currency in fiat:
        return fiat[currency]
    if currency in crypto:
        price = crypto[currency]
        return (1.0 / price) if price else None
    if currency in metals:
        price = metals[currency]
        return (1.0 / price) if price else None
    return None


def convert_currency(amount: float, from_currency: str, to_currency: str,
                     conversion_rates: dict) -> float:
    """Convert amount between any two supported currencies using USD as pivot."""
    if from_currency == to_currency:
        return amount
    fiat   = conversion_rates.get("fiat",   {})
    crypto = conversion_rates.get("crypto", {})
    metals = conversion_rates.get("metals", {})
    from_rate = _currency_to_usd_rate(from_currency, fiat, crypto, metals)
    to_rate   = _currency_to_usd_rate(to_currency,   fiat, crypto, metals)
    if not from_rate or not to_rate:
        return amount
    usd = amount / from_rate
    return round(usd * to_rate, 4)


# ──────────────── GOAL RECALCULATION ────────────────

def recalculate_all_goals(user_id: int,
                          conversion_rates: dict = None) -> List[Dict]:
    """
    Recalculate every goal's current_amount based on the total balance across
    all user accounts.

      account balance = initial_balance + SUM(income txns) - SUM(expense txns)
      goal progress   = SUM over all accounts of (balance converted to goal currency)

    This means:
      - Adding income to an account increases the balance → goals go UP.
      - Adding an expense to an account decreases the balance → goals go DOWN.
    """
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT * FROM accounts WHERE user_id=%s ORDER BY id",
                (user_id,)
            )
            accounts = [_norm_account(dict(r)) for r in cur.fetchall()]

            # Compute live balance for each account
            account_balances: List[Dict] = []
            for acc in accounts:
                balance = _compute_balance_in_cur(cur, acc["id"], acc["initial_balance"])
                account_balances.append({
                    "currency": acc["currency"],
                    "balance": max(0.0, balance),
                })

            cur.execute(
                "SELECT * FROM goals WHERE user_id=%s ORDER BY id",
                (user_id,)
            )
            goals = [dict(r) for r in cur.fetchall()]

            updated: List[Dict] = []
            for goal in goals:
                total = 0.0
                for acc_data in account_balances:
                    bal = acc_data["balance"]
                    if bal <= 0:
                        continue
                    if acc_data["currency"] == goal["currency"]:
                        total += bal
                    elif conversion_rates:
                        total += convert_currency(
                            bal, acc_data["currency"],
                            goal["currency"], conversion_rates
                        )

                total     = max(0.0, round(total, 4))
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


def update_goals_from_transaction(user_id: int, amount: float, currency: str,
                                  conversion_rates: dict = None) -> List[Dict]:
    """Called after adding/deleting a transaction. Fully recalculates all goals."""
    return recalculate_all_goals(user_id, conversion_rates)


def calculate_initial_goal_amount(user_id: int,
                                  goal_currency: str,
                                  conversion_rates: dict = None) -> float:
    """How much of a new goal is already covered by existing account balances."""
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT * FROM accounts WHERE user_id=%s ORDER BY id",
                (user_id,)
            )
            accounts = [_norm_account(dict(r)) for r in cur.fetchall()]

            total = 0.0
            for acc in accounts:
                balance = max(0.0, _compute_balance_in_cur(
                    cur, acc["id"], acc["initial_balance"]
                ))
                if balance <= 0:
                    continue
                if acc["currency"] == goal_currency:
                    total += balance
                elif conversion_rates:
                    total += convert_currency(
                        balance, acc["currency"], goal_currency, conversion_rates
                    )
    return round(total, 4)


# ──────────────── BUDGETS ────────────────

def set_budget(user_id: int, category: str, amount: float, currency: str) -> int:
    """Create or update this user's monthly budget for a category (upsert)."""
    ensure_user(user_id)
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO budgets (user_id, category, amount, currency) "
                "VALUES (%s,%s,%s,%s) "
                "ON CONFLICT (user_id, category) "
                "DO UPDATE SET amount=EXCLUDED.amount, currency=EXCLUDED.currency "
                "RETURNING id",
                (user_id, category, round(amount, 4), currency)
            )
            return cur.fetchone()["id"]


def get_budgets(user_id: int) -> List[Dict]:
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT * FROM budgets WHERE user_id=%s ORDER BY created_at ASC",
                (user_id,)
            )
            return [_norm_budget(dict(r)) for r in cur.fetchall()]


def get_budget(budget_id: int) -> Optional[Dict]:
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT * FROM budgets WHERE id=%s", (budget_id,))
            row = cur.fetchone()
            return _norm_budget(dict(row)) if row else None


def get_budget_by_category(user_id: int, category: str) -> Optional[Dict]:
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT * FROM budgets WHERE user_id=%s AND category=%s",
                (user_id, category)
            )
            row = cur.fetchone()
            return _norm_budget(dict(row)) if row else None


def delete_budget(budget_id: int):
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM budgets WHERE id=%s", (budget_id,))


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
                "SELECT type, SUM(amount) AS total, currency FROM transactions "
                "WHERE user_id=%s " + date_clause + " GROUP BY type, currency",
                [user_id] + extra
            )
            rows = cur.fetchall()
            cur.execute(
                "SELECT category, SUM(amount) AS total FROM transactions "
                "WHERE user_id=%s AND type='expense' " + date_clause + " GROUP BY category",
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
