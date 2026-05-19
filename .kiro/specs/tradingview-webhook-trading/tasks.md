# Implementation Plan: TradingView Webhook Trading

## Overview

This plan implements a webhook-driven automated trading system that receives TradingView strategy alerts and executes cryptocurrency trades on Binance and OKX exchanges via CCXT. The implementation is structured as a new `src/trading/` module, architecturally separate from the existing screener, sharing only the FastAPI app instance for routing.

## Tasks

- [x] 1. Set up trading module structure and configuration
  - [x] 1.1 Create the `src/trading/` package with `__init__.py` and `TradingSettings` configuration class
    - Create `src/trading/__init__.py` with module exports
    - Create `src/trading/config.py` with `TradingSettings(BaseSettings)` using `env_prefix="TRADING_"` containing: `supabase_url`, `supabase_key`, `encryption_key`, `telegram_bot_token`, `testnet_enabled`, `max_payload_size` (1 MB), `lock_timeout_seconds` (5), `order_timeout_seconds` (5)
    - Update `.env.example` with the new `TRADING_*` environment variables
    - _Requirements: 4.2, 10.1_

  - [x] 1.2 Create the database migration SQL for the multi-user schema
    - Create `src/trading/migrations/001_trading_schema.sql` with tables: `users`, `webhook_configs`, `exchange_credentials`, `positions`, `trade_logs`
    - Include all constraints: unique passphrase, composite unique (user_id, exchange), partial unique index on positions (user_id, symbol) WHERE status='open', ON DELETE RESTRICT foreign keys
    - Include indexes: `idx_trade_logs_user`, `idx_trade_logs_created`
    - _Requirements: 10.1, 10.2, 10.3, 10.4, 10.5, 10.6_

  - [x] 1.3 Create Pydantic models for webhook payload and response types
    - Create `src/trading/models.py` with `WebhookPayload` model using `Literal` types for action, side, size_type, exchange
    - Add `field_validator` for symbol (regex `^[A-Z0-9]+/[A-Z0-9]+:[A-Z0-9]+$`), size_value (> 0), leverage (1-125 or None)
    - Add `model_validator(mode="after")` for cross-field validation: percent size_value ≤ 100, fixed size_value ≤ 10,000,000
    - Create `TradeSuccessResponse` and `TradeErrorResponse` Pydantic models
    - _Requirements: 1.1, 1.2, 1.3, 1.4, 1.5, 1.6, 1.7, 1.8, 1.9, 1.10, 11.1, 11.2, 11.4_

  - [ ]* 1.4 Write property tests for payload validation (Properties 1-5)
    - **Property 1: Payload Serialization Round-Trip** — For any valid WebhookPayload, `model_dump_json()` → `model_validate_json()` produces identical object
    - **Property 2: Valid Payload Acceptance** — For any payload with all fields in valid ranges, Pydantic accepts without error
    - **Property 3: Invalid Enum Field Rejection** — For any payload with invalid enum value, Pydantic rejects with validation error
    - **Property 4: Invalid Numeric Constraint Rejection** — For any payload with out-of-bounds numeric values, Pydantic rejects
    - **Property 5: Invalid Symbol Format Rejection** — For any string not matching CCXT format, Pydantic rejects
    - Create `tests/test_trading/test_payload_properties.py` using Hypothesis with `@settings(max_examples=100)`
    - **Validates: Requirements 1.1, 1.2, 1.3, 1.4, 1.5, 1.6, 1.7, 1.8, 1.9, 1.10, 11.3**

- [x] 2. Implement authentication and credential management
  - [x] 2.1 Implement passphrase authentication module
    - Create `src/trading/auth.py` with `authenticate_by_passphrase(passphrase, supabase)` function
    - Query `webhook_configs` table by passphrase, join with users table to get user_id
    - Return generic 401 "Unauthorized" on mismatch (no information leakage)
    - Return 503 on database connection failure with logged error
    - _Requirements: 2.1, 2.2, 2.3, 2.4_

  - [x] 2.2 Implement encrypted credential store
    - Create `src/trading/credentials.py` with `CredentialStore` class using Fernet encryption
    - Implement `store_credentials(user_id, exchange, api_key, secret, passphrase=None)` — encrypts each field independently before storing
    - Implement `get_credentials(user_id, exchange)` — retrieves and decrypts credentials, raises error on missing credentials or decryption failure
    - Store encryption key from environment variable, not database
    - _Requirements: 3.1, 3.2, 3.3, 3.4, 3.5, 3.6_

  - [ ]* 2.3 Write property test for credential encryption round-trip (Property 6)
    - **Property 6: Credential Encryption Round-Trip** — For any valid API key and secret strings, encrypt then decrypt produces identical strings
    - Create `tests/test_trading/test_credentials_properties.py` using Hypothesis
    - **Validates: Requirements 3.1, 3.2**

- [x] 3. Implement trading connector and order execution
  - [x] 3.1 Implement trading connector module
    - Create `src/trading/connector.py` with `TradingConnector` class
    - Implement `create_exchange(exchange_name, credentials, symbol, leverage=None)` using `ccxt.async_support`
    - Configure testnet (`sandbox: True`) on all instances
    - Support Binance and OKX exchange classes
    - Set leverage on the exchange for the symbol when provided
    - Handle auth failures and leverage-set failures with appropriate errors
    - Ensure complete separation from `src/exchange/connector.py`
    - _Requirements: 4.1, 4.2, 4.3, 4.4, 4.5, 4.6_

  - [x] 3.2 Implement trade executor module
    - Create `src/trading/executor.py` with `TradeExecutor` class
    - Implement `calculate_quantity(size_type, size_value, free_balance, current_price)`:
      - percent: `(free_balance * size_value / 100) / current_price`
      - fixed: `size_value` directly
    - Implement `execute_trade(exchange, payload, position=None)`:
      - For "open" + "long": market buy for calculated quantity
      - For "open" + "short": market sell for calculated quantity
      - For "close": opposite market order for full position quantity
    - Check free margin balance before placing order, raise `InsufficientBalanceError` if insufficient
    - Submit order within 5 seconds timeout, no retry on failure
    - _Requirements: 5.1, 5.2, 5.3, 5.4, 5.5, 5.6, 5.7, 5.8_

  - [ ]* 3.3 Write property tests for executor (Properties 7-8)
    - **Property 7: Percent Quantity Calculation** — For any positive free_balance, percentage (0 < p ≤ 100), and positive price, quantity equals `(free_balance * p / 100) / price`
    - **Property 8: Insufficient Balance Rejection** — For any trade where cost exceeds free balance, executor rejects with insufficient balance error
    - Create `tests/test_trading/test_executor_properties.py` using Hypothesis
    - **Validates: Requirements 5.4, 5.6**

- [x] 4. Implement position management
  - [x] 4.1 Implement position manager module
    - Create `src/trading/position_manager.py` with `PositionManager` class
    - Implement `check_and_lock(user_id, symbol, action)`:
      - Use `pg_advisory_xact_lock` with hash of (user_id, symbol)
      - Set `statement_timeout` to 5 seconds before lock acquisition
      - For "open": verify no existing open position, raise `DuplicatePositionError` if exists
      - For "close": verify open position exists, raise `NoPositionError` if not, return position record
      - Raise `LockTimeoutError` if lock cannot be acquired within timeout
    - Implement `open_position(user_id, symbol, side, entry_price, quantity)` — create position record
    - Implement `close_position(user_id, symbol, exit_price)` — mark position closed with exit_price and closed_at timestamp
    - Handle partial fills: only create/close based on actual filled quantity from exchange
    - _Requirements: 6.1, 6.2, 6.3, 6.4, 6.5, 6.6, 9.2, 9.4_

  - [ ]* 4.2 Write property tests for position management (Properties 9-10)
    - **Property 9: One Position Per Symbol Per User Invariant** — For any user+symbol with existing open position, opening another is rejected before order placement
    - **Property 10: Close Non-Existent Position Rejection** — For any user+symbol with no open position, close is rejected before order placement
    - Create `tests/test_trading/test_position_properties.py` using Hypothesis
    - **Validates: Requirements 6.1, 6.2, 6.3**

- [x] 5. Checkpoint - Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

- [x] 6. Implement notifications and trade logging
  - [x] 6.1 Implement Telegram notifier module
    - Create `src/trading/notifier.py` with `TelegramNotifier` class
    - Implement `send_trade_notification(chat_id, trade_result, position=None)` using `httpx.AsyncClient` with 10-second timeout
    - Format message with: symbol, side, quantity, execution price, exchange name
    - For close orders: calculate and include PnL (`(exit - entry) * qty` for long, `(entry - exit) * qty` for short)
    - Skip notification if no chat_id configured (log warning)
    - No retry on failure, log error silently
    - Dispatch as FastAPI `BackgroundTask` for non-blocking execution
    - _Requirements: 7.1, 7.2, 7.3, 7.4, 7.5_

  - [ ]* 6.2 Write property tests for notifier (Properties 11-12)
    - **Property 11: Notification Message Completeness** — For any trade result with symbol, side, quantity, price, exchange, the message contains all five values
    - **Property 12: PnL Calculation Correctness** — For any closed position, PnL equals `(exit - entry) * qty` for long, `(entry - exit) * qty` for short
    - Create `tests/test_trading/test_notifier_properties.py` using Hypothesis
    - **Validates: Requirements 7.1, 7.2**

  - [x] 6.3 Implement trade logger module
    - Create `src/trading/trade_logger.py` with `TradeLogger` class
    - Implement `log_trade(user_id, symbol, action, side, exchange, size_value, status, order_id=None, fill_price=None, filled_quantity=None, error_details=None)`
    - Truncate `error_details` to 1024 characters
    - Persist to `trade_logs` table before webhook response is returned
    - Retry once on database write failure; if retry fails, raise error so webhook returns 500
    - Record ISO 8601 UTC timestamp
    - _Requirements: 8.1, 8.2, 8.3, 8.4, 8.5_

  - [ ]* 6.4 Write property tests for trade logger (Properties 13-14)
    - **Property 13: Trade Log Record Completeness** — For any trade attempt, the log record contains non-null user_id, symbol, action, side, exchange, size_value, status, and created_at
    - **Property 14: Error Message Truncation** — For any error string of any length, stored error_details has length ≤ 1024
    - Create `tests/test_trading/test_trade_logger_properties.py` using Hypothesis
    - **Validates: Requirements 8.1, 8.2**

- [x] 7. Wire webhook endpoint and integrate all components
  - [x] 7.1 Implement the webhook router with full processing pipeline
    - Create `src/trading/router.py` with FastAPI `APIRouter(prefix="/webhook", tags=["Trading Webhook"])`
    - Implement `POST /tradingview` endpoint:
      1. Check Content-Type header and body size (reject >1 MB with 413, non-JSON with 422)
      2. Parse body into `WebhookPayload` (Pydantic handles 422 with field-level errors)
      3. Call `authenticate_by_passphrase` (401 or 503 on failure)
      4. Call `credential_store.get_credentials` (error on missing/corrupt credentials)
      5. Call `trading_connector.create_exchange` (error on auth/leverage failure)
      6. Call `position_manager.check_and_lock` (409 duplicate, 404 no position, 409 lock timeout)
      7. Call `executor.execute_trade` (400 insufficient balance, 502 exchange error)
      8. Call `position_manager.open_position` or `close_position` based on action
      9. Call `trade_logger.log_trade` (500 if log fails after retry)
      10. Dispatch `notifier.send_trade_notification` as BackgroundTask
      11. Return `TradeSuccessResponse`
    - Handle all error cases per the design error handling table
    - _Requirements: 1.1, 1.11, 9.1, 9.3, 11.5, 11.6_

  - [x] 7.2 Register the trading router in the FastAPI application
    - Update `src/api/app.py` to import and include the trading router
    - Ensure the trading module is initialized with its dependencies (Supabase client, settings)
    - _Requirements: 4.3_

  - [ ]* 7.3 Write integration tests for the webhook endpoint
    - Create `tests/test_trading/test_webhook_integration.py`
    - Test happy path: valid payload → 200 with order details (mock exchange)
    - Test validation errors: invalid fields → 422 with field-level details
    - Test auth failure: bad passphrase → 401 generic error
    - Test concurrent requests: 10 simultaneous requests processed independently
    - Test lock contention: same user-symbol pair → 409 conflict
    - Test payload size limit: >1 MB → 413
    - _Requirements: 1.1, 2.2, 9.1, 9.2, 9.4, 11.6_

- [x] 8. Final checkpoint - Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

## Notes

- Tasks marked with `*` are optional and can be skipped for faster MVP
- Each task references specific requirements for traceability
- Checkpoints ensure incremental validation
- Property tests validate universal correctness properties from the design document
- Unit tests validate specific examples and edge cases
- The implementation uses Python with FastAPI, Pydantic, CCXT (async), Hypothesis, httpx, and cryptography (Fernet)
- All exchange connections use testnet mode (`sandbox: True`)
- The trading module is fully separate from the existing screener module under `src/exchange/`

## Task Dependency Graph

```json
{
  "waves": [
    { "id": 0, "tasks": ["1.1", "1.2", "1.3"] },
    { "id": 1, "tasks": ["1.4", "2.1", "2.2"] },
    { "id": 2, "tasks": ["2.3", "3.1", "3.2"] },
    { "id": 3, "tasks": ["3.3", "4.1"] },
    { "id": 4, "tasks": ["4.2", "6.1", "6.3"] },
    { "id": 5, "tasks": ["6.2", "6.4", "7.1"] },
    { "id": 6, "tasks": ["7.2"] },
    { "id": 7, "tasks": ["7.3"] }
  ]
}
```
