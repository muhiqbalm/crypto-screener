-- Migration: 003_add_exchange_to_positions.sql
-- Description: Add missing 'exchange' column to the positions table.
--              The application code queries and inserts this column but it
--              was omitted from the original 001_trading_schema.sql migration.

ALTER TABLE positions
    ADD COLUMN IF NOT EXISTS exchange TEXT NOT NULL DEFAULT '';
