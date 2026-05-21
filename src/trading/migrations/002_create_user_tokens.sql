-- Migration: 002_create_user_tokens.sql
-- Description: Create the user_tokens table for persisting hashed refresh tokens
-- Requirements: 18.2, 18.4

-- ============================================================
-- user_tokens table
-- Stores hashed refresh tokens for JWT-based authentication.
-- Each row represents a single active session for a user.
-- token_hash stores a SHA-256 hex digest of the plaintext
-- refresh token — never the plaintext itself.
-- ON DELETE CASCADE ensures tokens are removed automatically
-- when the parent user record is deleted.
-- Requirement 18.2
-- ============================================================
CREATE TABLE IF NOT EXISTS user_tokens (
    id         UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id    UUID        NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    token_hash TEXT        NOT NULL UNIQUE,
    expires_at TIMESTAMPTZ NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Index: efficient lookup of tokens by user during logout
-- (DELETE FROM user_tokens WHERE user_id = ?) and token refresh.
-- Requirement 18.4
CREATE INDEX IF NOT EXISTS idx_user_tokens_user_id ON user_tokens(user_id);
