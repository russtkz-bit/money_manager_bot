-- ============================================================
-- Money Manager Bot — PostgreSQL schema
-- Run this file once to set up a fresh database.
-- It drops all existing data and recreates the tables.
--
-- NOTE: this file is for manual/reference setup only. The bot itself
-- creates and migrates its schema automatically on startup via
-- database.init_db() — that function is the source of truth.
-- ============================================================

-- Drop existing tables (CASCADE removes dependent objects too)
DROP TABLE IF EXISTS budgets     CASCADE;
DROP TABLE IF EXISTS goals       CASCADE;
DROP TABLE IF EXISTS transactions CASCADE;
DROP TABLE IF EXISTS accounts    CASCADE;
DROP TABLE IF EXISTS users       CASCADE;

-- ── Users ──────────────────────────────────────────────────
CREATE TABLE users (
    user_id       BIGINT PRIMARY KEY,
    language      TEXT NOT NULL DEFAULT 'en',
    base_currency TEXT NOT NULL DEFAULT 'USD',
    created_at    TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- ── Accounts ───────────────────────────────────────────────
CREATE TABLE accounts (
    id              BIGSERIAL PRIMARY KEY,
    user_id         BIGINT NOT NULL
                        REFERENCES users(user_id) ON DELETE CASCADE,
    name            TEXT   NOT NULL,
    currency        TEXT   NOT NULL DEFAULT 'USD',
    initial_balance NUMERIC(18, 4) NOT NULL DEFAULT 0,
    account_type    TEXT   NOT NULL DEFAULT 'bank'
                        CHECK (account_type IN ('bank', 'crypto', 'cash')),
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_accounts_user ON accounts (user_id);

-- ── Transactions ───────────────────────────────────────────
CREATE TABLE transactions (
    id          BIGSERIAL PRIMARY KEY,
    user_id     BIGINT NOT NULL
                    REFERENCES users(user_id) ON DELETE CASCADE,
    account_id  BIGINT REFERENCES accounts(id) ON DELETE SET NULL,
    type        TEXT   NOT NULL CHECK (type IN ('income', 'expense')),
    amount      NUMERIC(18, 4) NOT NULL,
    currency    TEXT   NOT NULL DEFAULT 'USD',
    category    TEXT   NOT NULL,
    description TEXT   NOT NULL DEFAULT '',
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_transactions_user_date ON transactions (user_id, created_at);
CREATE INDEX idx_transactions_user_category ON transactions (user_id, category);

-- ── Goals ──────────────────────────────────────────────────
CREATE TABLE goals (
    id             BIGSERIAL PRIMARY KEY,
    user_id        BIGINT NOT NULL
                       REFERENCES users(user_id) ON DELETE CASCADE,
    title          TEXT   NOT NULL,
    goal_type      TEXT   NOT NULL CHECK (goal_type IN ('save', 'repay')),
    target_amount  NUMERIC(18, 4) NOT NULL,
    current_amount NUMERIC(18, 4) NOT NULL DEFAULT 0,
    currency       TEXT   NOT NULL DEFAULT 'USD',
    deadline       DATE   DEFAULT NULL,
    completed      BOOLEAN NOT NULL DEFAULT FALSE,
    created_at     TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_goals_user ON goals (user_id);

-- ── Budgets (one monthly budget per user+category) ─────────
CREATE TABLE budgets (
    id          BIGSERIAL PRIMARY KEY,
    user_id     BIGINT NOT NULL
                    REFERENCES users(user_id) ON DELETE CASCADE,
    category    TEXT   NOT NULL,
    amount      NUMERIC(18, 4) NOT NULL,
    currency    TEXT   NOT NULL DEFAULT 'USD',
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (user_id, category)
);

CREATE INDEX idx_budgets_user ON budgets (user_id);
