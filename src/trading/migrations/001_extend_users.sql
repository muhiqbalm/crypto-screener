-- Migration: 001_extend_users.sql
-- Description: Extend the users table with profile, authentication, and soft-delete columns
-- Requirements: 18.1, 18.3

-- ============================================================
-- Extend users table with new columns
-- Adds name, password_hash, telegram_chat_id, is_active,
-- and deleted_at to the existing users table.
-- IF NOT EXISTS guards make this migration idempotent.
-- Requirement 18.1
-- ============================================================
ALTER TABLE users
    ADD COLUMN IF NOT EXISTS name             TEXT         NOT NULL DEFAULT '',
    ADD COLUMN IF NOT EXISTS password_hash    TEXT         NOT NULL DEFAULT '',
    ADD COLUMN IF NOT EXISTS telegram_chat_id TEXT,
    ADD COLUMN IF NOT EXISTS is_active        BOOLEAN      NOT NULL DEFAULT TRUE,
    ADD COLUMN IF NOT EXISTS deleted_at       TIMESTAMPTZ;

-- ============================================================
-- Unique constraint on users.email
-- Enforces that each email address is registered at most once.
-- The DO NOTHING form prevents an error if the constraint was
-- already added by a previous migration run.
-- Requirement 18.3
-- ============================================================
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM   pg_constraint
        WHERE  conname = 'users_email_unique'
    ) THEN
        ALTER TABLE users
            ADD CONSTRAINT users_email_unique UNIQUE (email);
    END IF;
END;
$$;
