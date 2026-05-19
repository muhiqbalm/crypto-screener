-- Migration: 001_trading_schema.sql
-- Description: Initial multi-user trading schema for TradingView webhook trading system
-- Requirements: 10.1, 10.2, 10.3, 10.4, 10.5, 10.6

-- ============================================================
-- Users table
-- Base entity for all user-scoped data in the trading system
-- ============================================================
CREATE TABLE users (
    id         UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    email      TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- ============================================================
-- Webhook configurations
-- Maps a unique passphrase to a user account.
-- One passphrase → exactly one user (UNIQUE on passphrase).
-- ON DELETE RESTRICT prevents removing a user that still has
-- active webhook configs.
-- Requirement 10.3
-- ============================================================
CREATE TABLE webhook_configs (
    id         UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id    UUID        NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
    passphrase TEXT        NOT NULL UNIQUE,
    is_active  BOOLEAN     NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- ============================================================
-- Exchange credentials (encrypted)
-- Stores Fernet-encrypted API keys per user per exchange.
-- Composite unique constraint ensures one credential set per
-- (user, exchange) pair.
-- passphrase_encrypted is nullable because it is only required
-- by OKX; Binance does not use it.
-- ON DELETE RESTRICT prevents removing a user with stored creds.
-- Requirements 10.1, 10.2
-- ============================================================
CREATE TABLE exchange_credentials (
    id                   UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id              UUID        NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
    exchange             TEXT        NOT NULL,          -- 'binance' or 'okx'
    api_key_encrypted    TEXT        NOT NULL,
    secret_encrypted     TEXT        NOT NULL,
    passphrase_encrypted TEXT,                          -- Required for OKX, NULL for Binance
    created_at           TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (user_id, exchange)
);

-- ============================================================
-- Positions
-- Tracks open and closed positions for each user and symbol.
-- One open position per user per symbol is enforced at the
-- database level via a partial unique index (see below).
-- ON DELETE RESTRICT prevents removing a user that still has
-- position records (preserves audit history).
-- Requirements 10.4, 6.1
-- ============================================================
CREATE TABLE positions (
    id          UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id     UUID        NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
    symbol      TEXT        NOT NULL,
    side        TEXT        NOT NULL,       -- 'long' or 'short'
    entry_price NUMERIC     NOT NULL,
    quantity    NUMERIC     NOT NULL,
    status      TEXT        NOT NULL DEFAULT 'open',  -- 'open' or 'closed'
    exit_price  NUMERIC,
    opened_at   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    closed_at   TIMESTAMPTZ
);

-- Partial unique index: only one open position per user per symbol.
-- A second row with status='closed' for the same (user_id, symbol)
-- is allowed, so a plain UNIQUE constraint is not sufficient.
-- Requirement 10.4
CREATE UNIQUE INDEX idx_positions_user_symbol_open
    ON positions (user_id, symbol)
    WHERE status = 'open';

-- ============================================================
-- Trade logs (audit trail)
-- Every trade execution attempt (success, failed, or rejected)
-- is recorded here.  Records must never be deleted to preserve
-- the audit history; ON DELETE RESTRICT on user_id enforces this.
-- error_details is capped at 1024 characters in application code
-- (see TradeLogger), but there is no DB-level CHECK constraint so
-- that the truncation logic lives in a single place.
-- Requirements 10.1, 10.5
-- ============================================================
CREATE TABLE trade_logs (
    id               UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id          UUID        NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
    symbol           TEXT        NOT NULL,
    action           TEXT        NOT NULL,   -- 'open' or 'close'
    side             TEXT        NOT NULL,   -- 'long' or 'short'
    exchange         TEXT        NOT NULL,   -- 'binance' or 'okx'
    size_value       NUMERIC     NOT NULL,
    status           TEXT        NOT NULL,   -- 'success', 'failed', or 'rejected'
    order_id         TEXT,                   -- NULL if order was never submitted to exchange
    fill_price       NUMERIC,
    filled_quantity  NUMERIC,
    error_details    TEXT,                   -- Max 1024 chars (enforced in application layer)
    created_at       TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Index: look up all trade logs for a specific user efficiently.
-- Requirement 10.1
CREATE INDEX idx_trade_logs_user
    ON trade_logs (user_id);

-- Index: look up trade logs by creation time (e.g. for time-range queries).
-- Requirement 10.1
CREATE INDEX idx_trade_logs_created
    ON trade_logs (created_at);
