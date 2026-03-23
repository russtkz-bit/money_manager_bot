-- ============================================================
-- Money Manager Bot — PostgreSQL schema
-- Run this file once to set up a fresh database.
-- It drops all existing data and recreates the tables.
-- ============================================================

-- Drop existing tables (CASCADE removes dependent objects too)
DROP TABLE IF EXISTS goals        CASCADE;
DROP TABLE IF EXISTS transactions CASCADE;
DROP TABLE IF EXISTS users        CASCADE;

-- ── Users ──────────────────────────────────────────────────
CREATE TABLE users (
    user_id       BIGINT PRIMARY KEY,
    language      TEXT NOT NULL DEFAULT 'en',
    base_currency TEXT NOT NULL DEFAULT 'USD',
    created_at    TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- ── Transactions ───────────────────────────────────────────
CREATE TABLE transactions (
    id          BIGSERIAL PRIMARY KEY,
    user_id     BIGINT NOT NULL
                    REFERENCES users(user_id) ON DELETE CASCADE,
    type        TEXT   NOT NULL CHECK (type IN ('income', 'expense')),
    amount      NUMERIC(18, 4) NOT NULL,
    currency    TEXT   NOT NULL DEFAULT 'USD',
    category    TEXT   NOT NULL,
    description TEXT   NOT NULL DEFAULT '',
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_transactions_user_date ON transactions (user_id, created_at);

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
