# Requirements Document

## Introduction

This feature extends the existing TradingView webhook trading system (`src/trading/`) with a REST API for user registration, JWT-based authentication, profile management, webhook passphrase configuration, exchange credential management, and trading monitoring endpoints. The existing `POST /webhook/tradingview` endpoint is updated to enforce user active status. Authentication uses stateless JWT access tokens (30-minute expiry, signature-verified only) combined with hashed refresh tokens persisted in the `user_tokens` table (7-day expiry).

## Glossary

- **API**: The REST HTTP interface defined by this feature, routed under `/trading/`
- **User**: A registered trading account stored in the `users` table with email, name, password hash, optional Telegram chat ID, and active status
- **Auth_Service**: The component responsible for user registration, login, token issuance, refresh, and logout
- **JWT**: A JSON Web Token used as a stateless access token, signed with `TRADING_JWT_SECRET` and verified by signature only — no database lookup
- **Access_Token**: A stateless JWT with a 30-minute expiry, not stored server-side, verified by signature and subject claim
- **Refresh_Token**: A cryptographically random secure string stored as a bcrypt or SHA-256 hash in the `user_tokens` table, used to obtain new access tokens; expires in 7 days
- **Token_Store**: The `user_tokens` table in Supabase, which persists hashed refresh tokens with expiry timestamps
- **Password_Hasher**: The component that applies bcrypt hashing to plaintext passwords before storage and verifies plaintext passwords against stored hashes
- **Profile_Service**: The component handling retrieval and update of user profile fields (`name`, `telegram_chat_id`, `password`)
- **Webhook_Config**: A database record in the `webhook_configs` table linking a user's plaintext passphrase to their account; passphrase is returned in full in API responses
- **Webhook_Config_Service**: The component managing creation, retrieval, update, and deactivation of a user's Webhook_Config record
- **Credential_Service**: The component managing per-user per-exchange API credentials in the `exchange_credentials` table
- **Monitoring_Service**: The component that queries and returns the user's open positions, closed positions history, and trade log
- **Active_User_Guard**: The per-request check that queries `users.is_active = true` for the authenticated user; applied to every protected endpoint and to the existing webhook endpoint

## Requirements

### Requirement 1: User Registration

**User Story:** As a new trader, I want to register an account with my email, name, and password, so that I can authenticate and access trading features.

#### Acceptance Criteria

1. WHEN a POST request is received at `/trading/auth/register` with a JSON body containing `email`, `name`, and `password`, THE Auth_Service SHALL create a new user record and return a 201 HTTP status with the created user's `id`, `email`, `name`, and `created_at`
2. WHEN the `email` field in a registration request is not a valid email address format, THE Auth_Service SHALL reject the request with a 422 validation error identifying the invalid field
3. WHEN the `email` field in a registration request matches an existing user record, THE Auth_Service SHALL reject the request with a 409 conflict error
4. WHEN the `name` field in a registration request is an empty string or absent, THE Auth_Service SHALL reject the request with a 422 validation error
5. WHEN the `password` field in a registration request is fewer than 8 characters, THE Auth_Service SHALL reject the request with a 422 validation error
6. WHEN a user is created, THE Password_Hasher SHALL store the password as a bcrypt hash and SHALL NOT store the plaintext password
7. WHEN a user is created, THE Auth_Service SHALL set `is_active` to `true` by default
8. THE Auth_Service SHALL accept an optional `telegram_chat_id` field during registration and store it when provided

### Requirement 2: User Login

**User Story:** As a registered trader, I want to log in with my email and password, so that I receive tokens to authenticate subsequent API requests.

#### Acceptance Criteria

1. WHEN a POST request is received at `/trading/auth/login` with a valid `email` and `password` matching an active user, THE Auth_Service SHALL return a 200 HTTP status with an `access_token` (JWT), a `refresh_token` (plaintext random string), `token_type` set to `"bearer"`, and `expires_in` set to 1800 (seconds)
2. WHEN the Auth_Service issues a refresh token, THE Token_Store SHALL persist the token as a hash in the `user_tokens` table with `user_id`, `token_hash`, and `expires_at` set to 7 days from the current UTC time
3. WHEN the `email` field in a login request does not match any user record, THE Auth_Service SHALL reject the request with a 401 error without disclosing whether the email or password was invalid
4. WHEN the Password_Hasher verifies the supplied password and it does not match the stored bcrypt hash, THE Auth_Service SHALL reject the request with a 401 error without disclosing whether the email or password was invalid
5. WHEN the matched user has `is_active` set to `false`, THE Auth_Service SHALL reject the request with a 401 error
6. THE Access_Token SHALL be a signed JWT containing the `sub` claim (user UUID), `exp` claim (30 minutes from issuance), and `iat` claim (issuance timestamp), signed with the `TRADING_JWT_SECRET` environment variable

### Requirement 3: Token Refresh

**User Story:** As an authenticated trader, I want to exchange a refresh token for a new access token, so that I can maintain a session without re-entering my credentials.

#### Acceptance Criteria

1. WHEN a POST request is received at `/trading/auth/refresh` with a JSON body containing a `refresh_token` that hashes to a record in the `user_tokens` table and whose `expires_at` is in the future, THE Auth_Service SHALL return a 200 HTTP status with a new `access_token` and `expires_in` set to 1800
2. IF the `refresh_token` value does not match any record in the `user_tokens` table, THEN THE Auth_Service SHALL return a 401 error
3. IF the matching `user_tokens` record has an `expires_at` in the past, THEN THE Auth_Service SHALL return a 401 error and delete the expired record from the `user_tokens` table
4. WHEN the user associated with the refresh token has `is_active` set to `false`, THE Auth_Service SHALL return a 401 error

### Requirement 4: Logout

**User Story:** As an authenticated trader, I want to log out by revoking my refresh token, so that the token cannot be used to obtain further access tokens.

#### Acceptance Criteria

1. WHEN a POST request is received at `/trading/auth/logout` with a valid Access_Token in the `Authorization: Bearer` header, THE Auth_Service SHALL delete all `user_tokens` records for the authenticated user and return a 200 HTTP status
2. IF no `Authorization: Bearer` header is present on the logout request, THE Auth_Service SHALL return a 401 error
3. IF the Access_Token on the logout request has an invalid signature or is expired, THE Auth_Service SHALL return a 401 error

### Requirement 5: JWT Access Token Verification

**User Story:** As a system operator, I want all protected endpoints to verify the JWT signature, so that only tokens issued by this system are accepted.

#### Acceptance Criteria

1. WHEN a request to any protected endpoint includes a valid `Authorization: Bearer <token>` header whose JWT signature matches `TRADING_JWT_SECRET` and whose `exp` claim is in the future, THE Active_User_Guard SHALL permit the request to proceed
2. WHEN a request to any protected endpoint is missing the `Authorization` header, THE Active_User_Guard SHALL return a 401 error
3. WHEN the JWT in the `Authorization` header has an invalid signature, THE Active_User_Guard SHALL return a 401 error
4. WHEN the JWT `exp` claim is in the past, THE Active_User_Guard SHALL return a 401 error
5. AFTER JWT signature and expiry are verified, THE Active_User_Guard SHALL perform exactly one database query to confirm `users.is_active = true` for the user identified by the `sub` claim
6. IF `users.is_active` is `false` for the authenticated user, THEN THE Active_User_Guard SHALL return a 401 error
7. WHEN the existing `POST /webhook/tradingview` endpoint receives a request, THE Active_User_Guard SHALL verify that the user resolved from the passphrase has `is_active = true`; IF `is_active` is `false`, THEN THE Active_User_Guard SHALL reject the request with a 401 error

### Requirement 6: Get User Profile

**User Story:** As an authenticated trader, I want to retrieve my profile, so that I can review my account details.

#### Acceptance Criteria

1. WHEN a GET request is received at `/trading/users/me` with a valid Access_Token, THE Profile_Service SHALL return a 200 HTTP status with the user's `id`, `email`, `name`, `telegram_chat_id`, `is_active`, and `created_at`
2. THE Profile_Service SHALL NOT include the `password_hash` field in the response

### Requirement 7: Update User Profile

**User Story:** As an authenticated trader, I want to update my profile fields, so that I can change my name, Telegram chat ID, or password.

#### Acceptance Criteria

1. WHEN a PATCH request is received at `/trading/users/me` with a valid Access_Token and a JSON body containing one or more of `name`, `telegram_chat_id`, or `password`, THE Profile_Service SHALL update only the provided fields and return a 200 HTTP status with the updated profile
2. WHEN the `password` field is provided in a profile update, THE Password_Hasher SHALL hash the new password with bcrypt and store the hash, replacing the previous hash
3. WHEN the `name` field in a profile update is an empty string, THE Profile_Service SHALL reject the request with a 422 validation error
4. WHEN a PATCH request body contains no recognized updatable fields, THE Profile_Service SHALL reject the request with a 422 validation error

### Requirement 8: Webhook Config Retrieval

**User Story:** As an authenticated trader, I want to retrieve my active webhook passphrase, so that I can configure it in TradingView.

#### Acceptance Criteria

1. WHEN a GET request is received at `/trading/users/me/webhook-config` with a valid Access_Token and an active Webhook_Config record exists for the user, THE Webhook_Config_Service SHALL return a 200 HTTP status with the `id`, `passphrase` (full plaintext), `is_active`, and `created_at` of the active Webhook_Config
2. IF no active Webhook_Config record exists for the user, THEN THE Webhook_Config_Service SHALL return a 404 error

### Requirement 9: Webhook Config Creation

**User Story:** As an authenticated trader, I want to create a webhook passphrase, so that I can authenticate TradingView alerts to my account.

#### Acceptance Criteria

1. WHEN a POST request is received at `/trading/users/me/webhook-config` with a valid Access_Token and a JSON body containing a `passphrase` field, THE Webhook_Config_Service SHALL create a new Webhook_Config record with `is_active = true` and return a 201 HTTP status with `id`, `passphrase`, `is_active`, and `created_at`
2. WHEN the `passphrase` field is fewer than 8 characters, THE Webhook_Config_Service SHALL reject the request with a 422 validation error
3. WHEN the user already has an active Webhook_Config record, THE Webhook_Config_Service SHALL reject the request with a 409 conflict error
4. WHEN the `passphrase` value matches an existing Webhook_Config record belonging to any user, THE Webhook_Config_Service SHALL reject the request with a 409 conflict error

### Requirement 10: Webhook Config Update

**User Story:** As an authenticated trader, I want to update my webhook passphrase, so that I can rotate my passphrase without deactivating it.

#### Acceptance Criteria

1. WHEN a PATCH request is received at `/trading/users/me/webhook-config` with a valid Access_Token and a JSON body containing a new `passphrase`, THE Webhook_Config_Service SHALL update the passphrase on the user's active Webhook_Config record and return a 200 HTTP status with the updated record
2. WHEN the new `passphrase` value matches an existing Webhook_Config record belonging to any user, THE Webhook_Config_Service SHALL reject the request with a 409 conflict error
3. IF no active Webhook_Config exists for the user when a PATCH is received, THEN THE Webhook_Config_Service SHALL return a 404 error

### Requirement 11: Webhook Config Deactivation

**User Story:** As an authenticated trader, I want to deactivate my webhook passphrase, so that I can stop accepting automated trades from TradingView without deleting my account.

#### Acceptance Criteria

1. WHEN a DELETE request is received at `/trading/users/me/webhook-config` with a valid Access_Token and an active Webhook_Config record exists for the user, THE Webhook_Config_Service SHALL set `is_active = false` on the record and return a 200 HTTP status with the updated record
2. IF no active Webhook_Config exists for the user when a DELETE is received, THEN THE Webhook_Config_Service SHALL return a 404 error

### Requirement 12: List Exchange Credentials

**User Story:** As an authenticated trader, I want to list my configured exchanges, so that I can see which exchanges are ready for trading.

#### Acceptance Criteria

1. WHEN a GET request is received at `/trading/users/me/credentials` with a valid Access_Token, THE Credential_Service SHALL return a 200 HTTP status with an array of configured exchange records, each containing `exchange`, `is_configured` (set to `true`), and `created_at`
2. THE Credential_Service SHALL NOT include the API key or secret values in the response
3. WHEN no exchange credentials are configured for the user, THE Credential_Service SHALL return a 200 HTTP status with an empty array

### Requirement 13: Add or Update Exchange Credentials

**User Story:** As an authenticated trader, I want to store my exchange API credentials, so that the system can execute trades on my behalf.

#### Acceptance Criteria

1. WHEN a POST request is received at `/trading/users/me/credentials` with a valid Access_Token and a JSON body containing `exchange`, `api_key`, and `secret`, THE Credential_Service SHALL encrypt the API key and secret using the existing Fernet encryption mechanism and upsert the record in the `exchange_credentials` table, returning a 200 HTTP status with `exchange`, `is_configured`, and `created_at`
2. WHEN the `exchange` field is not one of "binance" or "okx", THE Credential_Service SHALL reject the request with a 422 validation error
3. WHEN an `api_passphrase` field is included in the request body, THE Credential_Service SHALL encrypt and store it alongside the API key and secret
4. THE Credential_Service SHALL NOT return the API key, secret, or passphrase in the response

### Requirement 14: Remove Exchange Credentials

**User Story:** As an authenticated trader, I want to remove my exchange credentials, so that the system can no longer trade on that exchange on my behalf.

#### Acceptance Criteria

1. WHEN a DELETE request is received at `/trading/users/me/credentials/{exchange}` with a valid Access_Token and the exchange name matches a configured credential record for the user, THE Credential_Service SHALL delete the record and return a 200 HTTP status with a confirmation message
2. WHEN the `{exchange}` path parameter is not one of "binance" or "okx", THE Credential_Service SHALL return a 422 validation error
3. IF no credential record exists for the specified exchange and user, THEN THE Credential_Service SHALL return a 404 error

### Requirement 15: Open Positions

**User Story:** As an authenticated trader, I want to view my current open positions, so that I can monitor my active trades.

#### Acceptance Criteria

1. WHEN a GET request is received at `/trading/users/me/positions` with a valid Access_Token, THE Monitoring_Service SHALL return a 200 HTTP status with an array of the user's open position records, each containing `id`, `symbol`, `side`, `entry_price`, `quantity`, `opened_at`, and `exchange`
2. WHEN the user has no open positions, THE Monitoring_Service SHALL return a 200 HTTP status with an empty array

### Requirement 16: Position History

**User Story:** As an authenticated trader, I want to view my closed position history, so that I can review my completed trades.

#### Acceptance Criteria

1. WHEN a GET request is received at `/trading/users/me/positions/history` with a valid Access_Token, THE Monitoring_Service SHALL return a 200 HTTP status with an array of the user's closed position records, each containing `id`, `symbol`, `side`, `entry_price`, `exit_price`, `quantity`, `opened_at`, `closed_at`, and `exchange`
2. WHEN the user has no closed positions, THE Monitoring_Service SHALL return a 200 HTTP status with an empty array
3. THE Monitoring_Service SHALL return closed positions ordered by `closed_at` descending

### Requirement 17: Trade Log

**User Story:** As an authenticated trader, I want to view my trade log, so that I have a complete audit trail of all automated trade attempts.

#### Acceptance Criteria

1. WHEN a GET request is received at `/trading/users/me/trades` with a valid Access_Token, THE Monitoring_Service SHALL return a 200 HTTP status with an array of the user's trade log records, each containing `id`, `symbol`, `action`, `side`, `exchange`, `size_value`, `status`, `order_id`, `fill_price`, `filled_quantity`, `error_details`, and `created_at`
2. WHEN the user has no trade log entries, THE Monitoring_Service SHALL return a 200 HTTP status with an empty array
3. THE Monitoring_Service SHALL return trade log entries ordered by `created_at` descending

### Requirement 18: Database Schema Extensions

**User Story:** As a system operator, I want the database schema extended for user credentials and token storage, so that the new authentication and profile features are supported.

#### Acceptance Criteria

1. THE database SHALL extend the existing `users` table with the columns `name TEXT NOT NULL`, `password_hash TEXT NOT NULL`, `telegram_chat_id TEXT` (nullable), `is_active BOOLEAN DEFAULT TRUE`, and `deleted_at TIMESTAMPTZ` (nullable)
2. THE database SHALL create a `user_tokens` table with columns: `id UUID PRIMARY KEY DEFAULT gen_random_uuid()`, `user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE`, `token_hash TEXT NOT NULL UNIQUE`, `expires_at TIMESTAMPTZ NOT NULL`, and `created_at TIMESTAMPTZ DEFAULT NOW()`
3. THE database SHALL enforce a `UNIQUE` constraint on `users.email`
4. THE database SHALL create an index on `user_tokens(user_id)` to support efficient lookup of tokens by user during logout

### Requirement 19: Environment Configuration

**User Story:** As a system operator, I want the JWT secret and token expiry values configurable via environment variables, so that I can rotate secrets and adjust expiry without code changes.

#### Acceptance Criteria

1. THE Auth_Service SHALL read the JWT signing secret from the `TRADING_JWT_SECRET` environment variable; IF this variable is absent or empty at startup, THE Auth_Service SHALL raise a configuration error and prevent the application from starting
2. THE Auth_Service SHALL read the access token expiry from `TRADING_ACCESS_TOKEN_EXPIRE_MINUTES` (default: 30) and the refresh token expiry from `TRADING_REFRESH_TOKEN_EXPIRE_DAYS` (default: 7)

### Requirement 20: Request and Response Serialization

**User Story:** As a developer, I want all API request and response bodies to use well-defined Pydantic models, so that malformed requests are caught early and responses are consistent.

#### Acceptance Criteria

1. THE API SHALL parse all request bodies into typed Pydantic models; WHEN a request body cannot be parsed into the expected schema, THE API SHALL return a 422 error response that includes, for each invalid field, the field name and the reason for rejection
2. THE API SHALL use consistent response Pydantic models for all endpoints such that for any valid response object, serializing it to JSON and parsing the result back into the same model produces an object with identical field values (round-trip property)
3. WHEN a request body exceeds 1 MB in size, THE API SHALL reject the request with a 413 error
