import sqlite3
import os
from datetime import datetime
from typing import Optional, List, Dict, Any

DB_PATH = os.path.join(os.path.dirname(__file__), "money_manager.db")


def get_connection() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    """Initialize database tables and run any pending migrations."""
    with get_connection() as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS users (
                user_id     INTEGER PRIMARY KEY,
                language    TEXT    DEFAULT 'en',
                base_currency TEXT  DEFAULT 'USD',
                created_at  TEXT    DEFAULT (datetime('now'))
            );

            CREATE TABLE IF NOT EXISTS transactions (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id     INTEGER NOT NULL,
                type        TEXT    NOT NULL,
                amount      REAL    NOT NULL,
                currency    TEXT    NOT NULL DEFAULT 'USD',
                category    TEXT    NOT NULL,
                description TEXT    DEFAULT '',
                created_at  TEXT    DEFAULT (datetime('now')),
                FOREIGN KEY (user_id) REFERENCES users(user_id)
            );

            CREATE TABLE IF NOT EXISTS goals (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id         INTEGER NOT NULL,
                title           TEXT    NOT NULL,
                goal_type       TEXT    NOT NULL,
                target_amount   REAL    NOT NULL,
                current_amount  REAL    DEFAULT 0,
                currency        TEXT    NOT NULL DEFAULT 'USD',
                deadline        TEXT    DEFAULT NULL,
                completed       INTEGER DEFAULT 0,
                created_at      TEXT    DEFAULT (datetime('now')),
                FOREIGN KEY (user_id) REFERENCES users(user_id)
            );
        """)
        conn.commit()

    # Run migrations to handle databases created before new columns were added
    _run_migrations()


def _run_migrations():
    """Safely add columns/tables that may not exist in older databases."""
    with get_connection() as conn:
        # Get existing column names for the users table
        existing_cols = {
            row[1]
            for row in conn.execute("PRAGMA table_info(users)").fetchall()
        }

        # List of (column_name, ALTER TABLE sql) to apply if missing
        migrations = [
            ("base_currency",
             "ALTER TABLE users ADD COLUMN base_currency TEXT DEFAULT 'USD'"),
        ]

        for col, sql in migrations:
            if col not in existing_cols:
                conn.execute(sql)

        conn.commit()


# ──────────────── USERS ────────────────

def ensure_user(user_id: int):
    with get_connection() as conn:
        conn.execute(
            "INSERT OR IGNORE INTO users (user_id) VALUES (?)", (user_id,)
        )
        conn.commit()


def get_user(user_id: int) -> Optional[Dict]:
    with get_connection() as conn:
        row = conn.execute("SELECT * FROM users WHERE user_id = ?", (user_id,)).fetchone()
        return dict(row) if row else None


def set_user_language(user_id: int, lang: str):
    ensure_user(user_id)
    with get_connection() as conn:
        conn.execute("UPDATE users SET language = ? WHERE user_id = ?", (lang, user_id))
        conn.commit()


def set_user_base_currency(user_id: int, currency: str):
    ensure_user(user_id)
    with get_connection() as conn:
        conn.execute("UPDATE users SET base_currency = ? WHERE user_id = ?", (currency, user_id))
        conn.commit()


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
        cursor = conn.execute(
            "INSERT INTO transactions (user_id, type, amount, currency, category, description) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (user_id, t_type, amount, currency, category, description)
        )
        conn.commit()
        return cursor.lastrowid


def get_transactions(user_id: int, limit: int = 20) -> List[Dict]:
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT * FROM transactions WHERE user_id = ? ORDER BY created_at DESC LIMIT ?",
            (user_id, limit)
        ).fetchall()
        return [dict(r) for r in rows]


def get_statistics(user_id: int) -> Dict[str, Any]:
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT type, SUM(amount) as total, currency FROM transactions "
            "WHERE user_id = ? GROUP BY type, currency",
            (user_id,)
        ).fetchall()

        cat_rows = conn.execute(
            "SELECT category, SUM(amount) as total, currency FROM transactions "
            "WHERE user_id = ? AND type = 'expense' GROUP BY category, currency",
            (user_id,)
        ).fetchall()

    income = {}
    expense = {}
    for r in rows:
        if r["type"] == "income":
            income[r["currency"]] = income.get(r["currency"], 0) + r["total"]
        else:
            expense[r["currency"]] = expense.get(r["currency"], 0) + r["total"]

    by_category = {}
    for r in cat_rows:
        key = f"{r['category']} ({r['currency']})"
        by_category[key] = by_category.get(key, 0) + r["total"]

    return {"income": income, "expense": expense, "by_category": by_category}


# ──────────────── GOALS ────────────────

def add_goal(user_id: int, title: str, goal_type: str,
             target_amount: float, currency: str, deadline: Optional[str] = None,
             initial_amount: float = 0.0) -> int:
    ensure_user(user_id)
    completed = 1 if initial_amount >= target_amount else 0
    with get_connection() as conn:
        cursor = conn.execute(
            "INSERT INTO goals "
            "(user_id, title, goal_type, target_amount, current_amount, currency, deadline, completed) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (user_id, title, goal_type, target_amount,
             round(initial_amount, 4), currency, deadline, completed)
        )
        conn.commit()
        return cursor.lastrowid


def get_goals(user_id: int) -> List[Dict]:
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT * FROM goals WHERE user_id = ? ORDER BY created_at DESC",
            (user_id,)
        ).fetchall()
        return [dict(r) for r in rows]


def get_goal(goal_id: int) -> Optional[Dict]:
    with get_connection() as conn:
        row = conn.execute("SELECT * FROM goals WHERE id = ?", (goal_id,)).fetchone()
        return dict(row) if row else None


def update_goal_progress(goal_id: int, amount: float) -> Dict:
    with get_connection() as conn:
        conn.execute(
            "UPDATE goals SET current_amount = current_amount + ? WHERE id = ?",
            (amount, goal_id)
        )
        conn.commit()
        row = conn.execute("SELECT * FROM goals WHERE id = ?", (goal_id,)).fetchone()
        goal = dict(row)
        if goal["current_amount"] >= goal["target_amount"]:
            conn.execute("UPDATE goals SET completed = 1 WHERE id = ?", (goal_id,))
            conn.commit()
            goal["completed"] = 1
        return goal


def delete_goal(goal_id: int):
    with get_connection() as conn:
        conn.execute("DELETE FROM goals WHERE id = ?", (goal_id,))
        conn.commit()


def delete_transaction(transaction_id: int):
    """Delete a single transaction."""
    with get_connection() as conn:
        conn.execute("DELETE FROM transactions WHERE id = ?", (transaction_id,))
        conn.commit()


def delete_all_transactions(user_id: int) -> int:
    """Delete all transactions for a user. Returns count of deleted transactions."""
    with get_connection() as conn:
        cursor = conn.execute("DELETE FROM transactions WHERE user_id = ?", (user_id,))
        conn.commit()
        return cursor.rowcount


def update_goal_currency(goal_id: int, new_currency: str,
                         new_target: float, new_current: float):
    with get_connection() as conn:
        conn.execute(
            "UPDATE goals SET currency = ?, target_amount = ?, current_amount = ? WHERE id = ?",
            (new_currency, new_target, new_current, goal_id)
        )
        conn.commit()


def update_goals_from_transaction(user_id: int, amount: float, currency: str, 
                                  conversion_rates: dict = None) -> List[Dict]:
    """Update goal progress based on a new transaction with automatic currency conversion.
    
    Args:
        user_id: The user ID
        amount: Transaction amount
        currency: Transaction currency
        conversion_rates: Dict with 'fiat', 'crypto', 'metals' keys containing exchange rates
        
    Returns:
        List of updated goals
    """
    with get_connection() as conn:
        # Get all incomplete goals for this user
        goals = conn.execute(
            "SELECT * FROM goals WHERE user_id = ? AND completed = 0 ORDER BY id",
            (user_id,)
        ).fetchall()
        
        updated_goals = []
        for goal in goals:
            goal_dict = dict(goal)
            goal_currency = goal_dict["currency"]
            
            # Calculate amount to add to goal
            amount_to_add = amount
            
            # If currencies don't match and we have conversion rates, convert
            if currency != goal_currency and conversion_rates:
                amount_to_add = convert_currency(
                    amount, currency, goal_currency, conversion_rates
                )
            elif currency != goal_currency:
                # Skip if currencies don't match and we don't have rates
                continue
            
            # Update the goal's progress
            new_current = goal_dict["current_amount"] + amount_to_add
            
            conn.execute(
                "UPDATE goals SET current_amount = ? WHERE id = ?",
                (new_current, goal_dict["id"])
            )
            
            # Check if goal is completed
            if new_current >= goal_dict["target_amount"]:
                conn.execute("UPDATE goals SET completed = 1 WHERE id = ?", (goal_dict["id"],))
                goal_dict["completed"] = 1
            
            goal_dict["current_amount"] = new_current
            updated_goals.append(goal_dict)
        
        conn.commit()
        return updated_goals


def convert_currency(amount: float, from_currency: str, to_currency: str, 
                    conversion_rates: dict) -> float:
    """Convert amount from one currency to another using provided rates.
    
    Args:
        amount: Amount to convert
        from_currency: Source currency
        to_currency: Target currency
        conversion_rates: Dict with 'fiat', 'crypto', 'metals' keys
        
    Returns:
        Converted amount (or original if conversion not possible)
    """
    if from_currency == to_currency:
        return amount
    
    fiat_rates = conversion_rates.get('fiat', {})
    crypto_rates = conversion_rates.get('crypto', {})
    metals_rates = conversion_rates.get('metals', {})
    
    # Get rates to USD
    from_to_usd = get_currency_to_usd_rate(from_currency, fiat_rates, crypto_rates, metals_rates)
    usd_to_target = get_currency_to_usd_rate(to_currency, fiat_rates, crypto_rates, metals_rates)
    
    if from_to_usd is None or usd_to_target is None:
        return amount  # Can't convert, return original
    
    # amount in from_currency -> convert to USD -> convert to to_currency
    usd_amount = amount / from_to_usd
    result = usd_amount * usd_to_target
    
    return round(result, 2)


def get_currency_to_usd_rate(currency: str, fiat: dict, crypto: dict, metals: dict) -> float:
    """Get how many units of currency equal 1 USD.

    Fiat rates from the API are already in 'units per USD' (e.g. EUR=0.91 means
    1 USD = 0.91 EUR).  Crypto/metals prices are 'USD per unit', so we invert
    them to get 'units per USD', keeping the formula consistent.
    """
    if currency == "USD":
        return 1.0
    if currency in fiat:
        return fiat[currency]                        # already units/USD
    if currency in crypto:
        price = crypto[currency]                     # USD per coin
        return (1.0 / price) if price else None      # → coins per USD
    if currency in metals:
        price = metals[currency]                     # USD per troy oz
        return (1.0 / price) if price else None      # → oz per USD
    return None


# ──────────────── FILTERED QUERIES (for statistics charts) ────────────────

def get_transactions_filtered(
    user_id: int,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
) -> List[Dict]:
    """Return all transactions for a user, optionally bounded by date.

    Dates are strings in 'YYYY-MM-DD' format.
    Results are ordered oldest-first (needed for bar chart grouping).
    """
    with get_connection() as conn:
        if start_date and end_date:
            rows = conn.execute(
                "SELECT * FROM transactions WHERE user_id = ?"
                " AND DATE(created_at) BETWEEN ? AND ?"
                " ORDER BY created_at ASC",
                (user_id, start_date, end_date),
            ).fetchall()
        elif start_date:
            rows = conn.execute(
                "SELECT * FROM transactions WHERE user_id = ?"
                " AND DATE(created_at) >= ?"
                " ORDER BY created_at ASC",
                (user_id, start_date),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM transactions WHERE user_id = ?"
                " ORDER BY created_at ASC",
                (user_id,),
            ).fetchall()
        return [dict(r) for r in rows]


def get_statistics_filtered(
    user_id: int,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
) -> Dict[str, Any]:
    """Aggregate income/expense totals and category breakdown for a date range."""
    date_clause = ""
    params: list = [user_id]

    if start_date and end_date:
        date_clause = " AND DATE(created_at) BETWEEN ? AND ?"
        params += [start_date, end_date]
    elif start_date:
        date_clause = " AND DATE(created_at) >= ?"
        params.append(start_date)

    with get_connection() as conn:
        rows = conn.execute(
            f"SELECT type, SUM(amount) as total, currency"
            f" FROM transactions WHERE user_id = ?{date_clause}"
            f" GROUP BY type, currency",
            params,
        ).fetchall()

        cat_rows = conn.execute(
            f"SELECT category, SUM(amount) as total"
            f" FROM transactions"
            f" WHERE user_id = ? AND type = 'expense'{date_clause}"
            f" GROUP BY category",
            params,
        ).fetchall()

    income: Dict[str, float]  = {}
    expense: Dict[str, float] = {}
    for r in rows:
        if r["type"] == "income":
            income[r["currency"]]  = income.get(r["currency"],  0) + r["total"]
        else:
            expense[r["currency"]] = expense.get(r["currency"], 0) + r["total"]

    by_category: Dict[str, float] = {}
    for r in cat_rows:
        by_category[r["category"]] = by_category.get(r["category"], 0) + r["total"]

    return {"income": income, "expense": expense, "by_category": by_category}


# ──────────────── GOAL RECALCULATION ────────────────

def recalculate_all_goals(user_id: int, conversion_rates: dict = None) -> List[Dict]:
    """Recompute current_amount for every goal from scratch.

    Called after deleting a transaction so goal progress stays accurate.
    Sums all income transactions (converted to each goal's currency).
    """
    with get_connection() as conn:
        goals = conn.execute(
            "SELECT * FROM goals WHERE user_id = ? ORDER BY id",
            (user_id,),
        ).fetchall()

        income_txns = conn.execute(
            "SELECT amount, currency FROM transactions"
            " WHERE user_id = ? AND type = 'income'",
            (user_id,),
        ).fetchall()

        updated: List[Dict] = []
        for goal in goals:
            g = dict(goal)
            goal_currency = g["currency"]
            total = 0.0

            for tx in income_txns:
                amount      = tx["amount"]
                tx_currency = tx["currency"]
                if tx_currency == goal_currency:
                    total += amount
                elif conversion_rates:
                    converted = convert_currency(amount, tx_currency,
                                                 goal_currency, conversion_rates)
                    total += converted

            total     = round(total, 4)
            completed = 1 if total >= g["target_amount"] else 0
            conn.execute(
                "UPDATE goals SET current_amount = ?, completed = ? WHERE id = ?",
                (total, completed, g["id"]),
            )
            g["current_amount"] = total
            g["completed"]      = completed
            updated.append(g)

        conn.commit()
        return updated


def calculate_initial_goal_amount(
    user_id: int,
    goal_currency: str,
    conversion_rates: dict = None,
) -> float:
    """Return the total of all existing income transactions converted to goal_currency.

    Used to pre-populate current_amount when a new goal is created, so the user
    doesn't start from zero if they already have transactions.
    """
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT amount, currency FROM transactions"
            " WHERE user_id = ? AND type = 'income'",
            (user_id,),
        ).fetchall()

    total = 0.0
    for row in rows:
        amount      = row["amount"]
        tx_currency = row["currency"]
        if tx_currency == goal_currency:
            total += amount
        elif conversion_rates:
            converted = convert_currency(amount, tx_currency,
                                         goal_currency, conversion_rates)
            total += converted

    return round(total, 4)
