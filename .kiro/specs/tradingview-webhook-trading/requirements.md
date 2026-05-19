# Requirements Document

## Introduction

This feature adds a webhook API endpoint that receives TradingView strategy alerts and automatically executes trades on cryptocurrency exchanges (Binance and OKX) via the CCXT library. The system supports multiple users from the start, with each user identified by a unique passphrase in the webhook payload. It manages positions, sends Telegram notifications on trade execution, and logs all activity for audit purposes. The trading module is architecturally separate from the existing screener functionality.

## Glossary

- **Webhook_Endpoint**: The HTTP POST endpoint that receives TradingView alert payloads
- **Trading_Connector**: An authenticated CCXT exchange connection used for placing orders (separate from the existing read-only screener connector)
- **Executor**: The component responsible for validating order parameters, checking balances, and submitting market orders to the exchange
- **Position_Manager**: The component that tracks open positions per user per symbol and enforces the one-position-per-symbol-per-user constraint
- **Notifier**: The component that sends Telegram messages to users upon trade execution events
- **Credential_Store**: The encrypted storage of exchange API keys per user per exchange in Supabase
- **Webhook_Config**: A database record linking a user's passphrase to their trading configuration
- **Trade_Log**: An audit record of every trade execution attempt including status, timestamps, and order details
- **CCXT_Unified_Symbol**: The canonical symbol format used by CCXT (e.g., "BTC/USDT:USDT") which CCXT translates to native exchange formats internally
- **Payload**: The JSON body sent by TradingView to the webhook endpoint
- **Passphrase**: A user-unique secret string used to authenticate and identify the user in webhook payloads

## Requirements

### Requirement 1: Webhook Endpoint Reception

**User Story:** As a trader, I want to send TradingView alerts to a webhook endpoint, so that my trading strategies can be executed automatically.

#### Acceptance Criteria

1. WHEN a POST request is received at `/webhook/tradingview` with a valid JSON payload containing `action`, `symbol`, `side`, `size_type`, `size_value`, `leverage`, `exchange`, and `passphrase` fields that pass all validation rules, THE Webhook_Endpoint SHALL accept the request and return a 200 HTTP status response
2. WHEN the payload `action` field is not one of "open" or "close", THE Webhook_Endpoint SHALL reject the request with a 422 validation error
3. WHEN the payload `side` field is not one of "long" or "short", THE Webhook_Endpoint SHALL reject the request with a 422 validation error
4. WHEN the payload `size_type` field is not one of "percent" or "fixed", THE Webhook_Endpoint SHALL reject the request with a 422 validation error
5. WHEN the payload `exchange` field is not one of "binance" or "okx", THE Webhook_Endpoint SHALL reject the request with a 422 validation error
6. WHEN the payload `symbol` field does not match CCXT_Unified_Symbol format, THE Webhook_Endpoint SHALL reject the request with a 422 validation error
7. WHEN the payload `size_value` field is less than or equal to zero, THE Webhook_Endpoint SHALL reject the request with a 422 validation error
8. WHEN the payload `size_type` is "percent" and `size_value` exceeds 100, THE Webhook_Endpoint SHALL reject the request with a 422 validation error
9. WHEN the payload `size_type` is "fixed" and `size_value` exceeds 10,000,000, THE Webhook_Endpoint SHALL reject the request with a 422 validation error
10. WHEN the payload `leverage` field is provided and its value is not an integer between 1 and 125 inclusive, THE Webhook_Endpoint SHALL reject the request with a 422 validation error
11. WHEN the request body is not valid JSON or exceeds 10 KB in size, THE Webhook_Endpoint SHALL reject the request with a 400 error indicating a malformed payload

### Requirement 2: Passphrase Authentication and User Lookup

**User Story:** As a trader, I want my webhook to be secured with a unique passphrase, so that only my TradingView alerts trigger trades on my account.

#### Acceptance Criteria

1. WHEN a webhook payload is received, THE Webhook_Endpoint SHALL look up the user by matching the `passphrase` field against the Webhook_Config table and retrieve the associated user ID and trading configuration
2. IF the passphrase does not match any Webhook_Config record, THEN THE Webhook_Endpoint SHALL reject the request with a 401 unauthorized error and SHALL NOT disclose whether the passphrase was invalid or the user does not exist
3. IF the database is unavailable during passphrase lookup, THEN THE Webhook_Endpoint SHALL reject the request with a 503 service unavailable error and log the database connection failure
4. THE Webhook_Endpoint SHALL complete passphrase lookup within 500ms at the 95th percentile under a load of up to 10 concurrent webhook requests

### Requirement 3: Exchange Credential Management

**User Story:** As a trader, I want my exchange API keys stored securely, so that my credentials are protected from unauthorized access.

#### Acceptance Criteria

1. THE Credential_Store SHALL encrypt exchange API keys and secrets before storing them in the database such that stored values are not retrievable as plaintext by direct database query
2. WHEN the Executor requires exchange credentials for a user, THE Credential_Store SHALL decrypt and provide the API key and secret for the specified exchange within 2 seconds
3. IF the user does not have credentials configured for the requested exchange, THEN THE Executor SHALL reject the trade with an error indicating the missing exchange name and user identifier, and log the failure to the Trade_Log
4. THE Credential_Store SHALL store credentials per user per exchange, allowing each user to have separate API keys for Binance and OKX
5. IF decryption of stored credentials fails due to data corruption or key mismatch, THEN THE Credential_Store SHALL reject the credential retrieval with an error indicating a decryption failure and log the error details
6. THE Credential_Store SHALL store at minimum the API key and secret for each exchange credential record, and additionally a passphrase field when required by the exchange

### Requirement 4: Trading Connector Initialization

**User Story:** As a trader, I want my trades executed on testnet first, so that I can validate my strategies without risking real funds.

#### Acceptance Criteria

1. WHEN the Executor receives a trade request, THE Trading_Connector SHALL create an authenticated CCXT exchange instance using the user's decrypted credentials within 10 seconds
2. THE Trading_Connector SHALL configure the CCXT exchange instance to use testnet API endpoints
3. THE Trading_Connector SHALL be a separate module that does not share class hierarchy or exchange instances with the existing read-only screener ExchangeConnector
4. WHEN the `leverage` field is provided in the payload with a value between 1 and 125 inclusive, THE Trading_Connector SHALL set the leverage for the symbol on the exchange before placing the order
5. IF authentication with the exchange fails during instance creation, THEN THE Trading_Connector SHALL reject the trade with an error indicating invalid or expired credentials and log the failure
6. IF setting leverage on the exchange fails, THEN THE Trading_Connector SHALL reject the trade with an error indicating the leverage configuration failure and not place the order

### Requirement 5: Order Execution

**User Story:** As a trader, I want my TradingView alerts to result in market orders on the exchange, so that I get immediate execution at current market prices.

#### Acceptance Criteria

1. WHEN the action is "open" and side is "long", THE Executor SHALL place a market buy order on the specified exchange for the calculated order quantity using the CCXT_Unified_Symbol from the payload
2. WHEN the action is "open" and side is "short", THE Executor SHALL place a market sell order on the specified exchange for the calculated order quantity using the CCXT_Unified_Symbol from the payload
3. WHEN the action is "close", THE Executor SHALL close the existing position for the specified symbol by placing an opposite market order for the full position quantity as recorded by the Position_Manager
4. WHEN the size_type is "percent", THE Executor SHALL calculate the order quantity by applying the specified percentage to the user's free margin balance for the quote currency of the trading pair, divided by the current market price to derive the base currency quantity
5. WHEN the size_type is "fixed", THE Executor SHALL use the size_value directly as the order quantity in base currency units (e.g., 0.5 BTC for BTC/USDT:USDT)
6. IF the user's free margin balance for the quote currency is less than the cost of the calculated order quantity at current market price, THEN THE Executor SHALL reject the trade with an error indicating insufficient balance and log the attempt to the Trade_Log
7. IF the exchange returns an error during order placement, THEN THE Executor SHALL log the error details to the Trade_Log and return a failure response to the webhook caller without retrying the order
8. WHEN the Executor places a market order, THE Executor SHALL submit the order within 5 seconds of receiving the validated trade request from the Webhook_Endpoint

### Requirement 6: Position Management

**User Story:** As a trader, I want the system to track my open positions, so that duplicate positions are prevented and closes are handled correctly.

#### Acceptance Criteria

1. THE Position_Manager SHALL enforce a maximum of one open position per symbol per user
2. IF an "open" action is received and the user already has an open position for the same symbol, THEN THE Position_Manager SHALL reject the trade with a duplicate position error before any order is placed on the exchange
3. IF a "close" action is received and no open position exists for the symbol, THEN THE Position_Manager SHALL reject the trade with a no-position-found error before any order is placed on the exchange
4. WHEN an "open" order executes successfully, THE Position_Manager SHALL create a position record with the user ID, symbol, side, fill price from the exchange response as entry price, filled quantity from the exchange response, and timestamp
5. WHEN a "close" order executes successfully, THE Position_Manager SHALL mark the position record as closed with the fill price from the exchange response as exit price and timestamp
6. IF an order is submitted but the exchange returns a partial fill or rejection after the position check passed, THEN THE Position_Manager SHALL only create or close the position record based on the actual filled quantity returned by the exchange

### Requirement 7: Telegram Notifications

**User Story:** As a trader, I want to receive Telegram notifications when trades execute, so that I stay informed about my automated trading activity.

#### Acceptance Criteria

1. WHEN an order executes successfully, THE Notifier SHALL send a Telegram message to the user's configured Telegram chat ID containing the symbol, side, quantity, execution price, and exchange name
2. WHEN a "close" order executes successfully, THE Notifier SHALL include the realized PnL (calculated as the difference between exit price and entry price multiplied by quantity) in the notification message
3. IF the Telegram API does not respond within 10 seconds or returns a non-2xx status code, THEN THE Notifier SHALL log the notification failure including the error details and shall not retry the delivery, without affecting the trade execution result
4. THE Notifier SHALL send notifications asynchronously so that notification delivery does not block the webhook response
5. IF the user does not have a Telegram chat ID configured, THEN THE Notifier SHALL skip notification delivery and log a warning indicating the missing configuration

### Requirement 8: Trade Logging

**User Story:** As a trader, I want all trade activity logged, so that I have a complete audit trail of my automated trades.

#### Acceptance Criteria

1. THE Trade_Log SHALL record every trade execution attempt with: user ID, symbol, action, side, exchange, order size, execution status (one of "success", "failed", or "rejected"), UTC timestamp in ISO 8601 format, and order ID from the exchange (or null if the order was not submitted to the exchange)
2. WHEN an order fails, THE Trade_Log SHALL record the failure reason and error details returned by the exchange, truncated to a maximum of 1024 characters
3. WHEN an order succeeds, THE Trade_Log SHALL record the fill price and filled quantity from the exchange response
4. THE Trade_Log SHALL be persisted to the database before the webhook response is returned to ensure no trade activity is lost
5. IF the Trade_Log database write fails, THEN THE Webhook_Endpoint SHALL return an error response indicating the trade was executed but the log could not be saved, and SHALL retry the log write once before abandoning

### Requirement 9: Concurrent Webhook Processing

**User Story:** As a system operator, I want the webhook endpoint to handle multiple simultaneous alerts, so that trades from different users or symbols are not delayed.

#### Acceptance Criteria

1. THE Webhook_Endpoint SHALL process at least 10 incoming webhook requests concurrently, where each request proceeds through validation, execution, and response independently of other in-flight requests
2. WHILE processing concurrent requests for the same user and symbol, THE Position_Manager SHALL acquire a database-level row lock scoped to the specific user-symbol pair with a lock wait timeout of 5 seconds
3. THE Webhook_Endpoint SHALL return a response within 30 seconds for each request, measured from request receipt to response delivery, excluding time spent waiting for exchange API responses that exceed 10 seconds
4. IF the Position_Manager cannot acquire the database lock within the 5-second lock wait timeout, THEN THE Position_Manager SHALL reject the trade request with a conflict error indicating the symbol is currently being processed for that user

### Requirement 10: Database Schema (Multi-User)

**User Story:** As a system operator, I want a multi-user database schema from the start, so that the system scales to multiple traders without architectural changes.

#### Acceptance Criteria

1. THE Credential_Store SHALL use a Supabase PostgreSQL database with tables for: users, exchange_credentials, webhook_configs, positions, and trade_logs
2. THE Credential_Store SHALL associate exchange_credentials records with a user ID and exchange name as a composite unique constraint
3. THE Webhook_Config SHALL associate each passphrase with exactly one user via a unique constraint on the passphrase column
4. THE Position_Manager SHALL store position records with foreign key references to the users table and SHALL enforce a unique constraint on (user_id, symbol) for records in "open" status to prevent duplicate open positions at the database level
5. THE Trade_Log SHALL store trade log records with foreign key references to the users table
6. IF a user record is referenced by existing exchange_credentials, webhook_configs, positions, or trade_logs records, THEN THE database SHALL reject deletion of that user record (restrict cascading) to preserve referential integrity and audit history

### Requirement 11: Webhook Payload Serialization

**User Story:** As a developer, I want the webhook payload to be parsed and validated using a well-defined schema, so that malformed requests are caught early.

#### Acceptance Criteria

1. THE Webhook_Endpoint SHALL parse incoming JSON payloads of up to 1 MB into a typed Pydantic model containing the fields defined in Requirement 1 (`action`, `symbol`, `side`, `size_type`, `size_value`, `leverage`, `exchange`, `passphrase`)
2. WHEN the JSON payload cannot be parsed into the expected Pydantic schema, THE Webhook_Endpoint SHALL return a 422 error response that includes, for each invalid field, the field name and the reason for rejection
3. THE Webhook_Endpoint SHALL ensure that for any valid Payload object, serializing it to JSON and parsing the result back into the Pydantic model produces an object with identical field names and values (round-trip property)
4. THE Webhook_Endpoint SHALL treat the `leverage` field as optional with no default value applied when omitted, representing it as None in the parsed model
5. IF the request body is not valid JSON or the Content-Type header is not `application/json`, THEN THE Webhook_Endpoint SHALL return a 422 error response indicating that the body could not be parsed as JSON
6. IF the request body exceeds 1 MB, THEN THE Webhook_Endpoint SHALL reject the request with a 413 error response indicating the payload is too large
