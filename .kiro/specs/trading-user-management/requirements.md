# Requirements Document

## Introduction

Fitur ini menambahkan REST API untuk manajemen user trading, autentikasi berbasis JWT, dan monitoring posisi trading. API ini melengkapi modul `tradingview-webhook-trading` yang sudah ada dengan menambahkan:

- Registrasi dan autentikasi user via JWT (Access Token + Refresh Token)
- Manajemen profil user
- Manajemen konfigurasi webhook per user
- Manajemen kredensial exchange per user
- Monitoring posisi dan riwayat trade

Modul ini menggunakan tabel database yang sudah ada (`users`, `webhook_configs`, `exchange_credentials`, `positions`, `trade_logs`) dengan penambahan kolom pada tabel `users` dan tabel baru `user_tokens` untuk menyimpan refresh token.

## Glossary

- **Auth_Service**: Komponen yang menangani registrasi, login, refresh token, dan logout
- **User_Service**: Komponen yang menangani operasi profil user terautentikasi
- **Webhook_Config_Service**: Komponen yang menangani CRUD konfigurasi passphrase webhook per user
- **Credential_Service**: Komponen yang menangani penyimpanan dan pengelolaan API key exchange per user
- **Position_Service**: Komponen yang menyediakan data monitoring posisi dan riwayat trade
- **JWT_Handler**: Komponen yang membuat, memvalidasi, dan merevoke token JWT
- **Access_Token**: JWT stateless dengan masa berlaku 30 menit, digunakan untuk autentikasi setiap request
- **Refresh_Token**: Token opaque dengan masa berlaku 7 hari, disimpan sebagai hash di tabel `user_tokens`, digunakan untuk mendapatkan Access_Token baru
- **User**: Entitas trader yang memiliki akun di sistem, teridentifikasi unik by email
- **Webhook_Config**: Record di database yang menghubungkan passphrase webhook milik seorang User ke konfigurasi trading-nya
- **Exchange_Credential**: Record terenkripsi yang menyimpan API key dan secret exchange (Binance/OKX) milik seorang User
- **Position**: Record posisi trading yang sedang terbuka atau sudah tertutup milik seorang User
- **Trade_Log**: Record audit setiap eksekusi trade yang dilakukan sistem atas nama seorang User

## Requirements

### Requirement 1: User Registration

**User Story:** As a trader, I want to register a new account, so that I can use the automated trading system.

#### Acceptance Criteria

1. WHEN a POST request is received at `/trading/auth/register` with a valid JSON body containing `email`, `name`, and `password` fields, THE Auth_Service SHALL create a new User record and return a 201 HTTP status response with the created user's `id`, `email`, `name`, and `created_at`
2. WHEN a registration request is received, THE Auth_Service SHALL validate that the `email` field contains exactly one `@` symbol with non-empty local and domain parts; IF the `email` does not satisfy this format, THEN THE Auth_Service SHALL return a 422 validation error identifying the `email` field
3. WHEN a registration request is received, THE Auth_Service SHALL validate that the `password` field is at least 8 characters in length; IF the `password` is shorter than 8 characters, THEN THE Auth_Service SHALL return a 422 validation error identifying the `password` field
4. WHEN a registration request is received, THE Auth_Service SHALL validate that the `name` field is a non-empty string of at least 1 and at most 255 characters; IF the `name` does not satisfy this constraint, THEN THE Auth_Service SHALL return a 422 validation error identifying the `name` field
5. IF the `email` provided in a registration request already exists in the `users` table, THEN THE Auth_Service SHALL return a 409 conflict error response
6. WHEN a valid registration request is processed, THE Auth_Service SHALL hash the `password` using bcrypt before storing it in the `password_hash` column of the `users` table
7. WHEN a valid registration request is processed, THE Auth_Service SHALL set `is_active` to TRUE for the newly created User
8. WHERE `telegram_chat_id` is included in the registration request, THE Auth_Service SHALL store the value in the `telegram_chat_id` column of the `users` table
9. IF any required field (`email`, `name`, or `password`) is missing from the registration request body or is of the wrong type (non-string), THEN THE Auth_Service SHALL return a 422 validation error identifying each missing or malformed field
10. THE Auth_Service SHALL complete the registration process and return a response within 3 seconds of receiving a valid registration request

### Requirement 2: User Login (JWT Authentication)

**User Story:** As a trader, I want to log in with my email and password, so that I receive a JWT token to authenticate subsequent requests.

#### Acceptance Criteria

1. WHEN a POST request is received at `/trading/auth/login` with `email` and `password` fields, THE Auth_Service SHALL look up the User by email and verify the provided password against the stored `password_hash` using bcrypt
2. WHEN login credentials are valid and the User's `is_active` is TRUE, THE Auth_Service SHALL atomically generate both an `access_token` (JWT, 30-minute expiry) and a `refresh_token` (opaque token, 7-day expiry), store the refresh token hash in the database, and return a 200 response containing both tokens and `token_type: "bearer"` — IF generation or storage of either token fails, THE Auth_Service SHALL return a 500 error without persisting any partial token state
4. IF the provided email does not exist in the `users` table or the password does not match the stored hash, THEN THE Auth_Service SHALL return a 401 unauthorized error and SHALL NOT disclose whether the email or password was incorrect
5. IF the User's `is_active` field is FALSE, THEN THE Auth_Service SHALL return a 401 unauthorized error
6. THE Auth_Service SHALL sign Access_Tokens using the JWT secret key stored in the `JWT_SECRET_KEY` environment variable
7. THE Access_Token payload SHALL contain at minimum: `sub` (user UUID), `email`, and `exp` (expiry timestamp as Unix epoch)
8. WHEN a login request is received (regardless of outcome), THE Auth_Service SHALL return a response within 3 seconds
9. IF the request body is missing `email` or `password` fields or contains fields of the wrong type, THEN THE Auth_Service SHALL return a 400 validation error identifying each missing or malformed field

### Requirement 3: Token Refresh

**User Story:** As a trader, I want to exchange my refresh token for a new access token, so that I can maintain an authenticated session without re-entering my credentials.

#### Acceptance Criteria

1. WHEN a POST request is received at `/trading/auth/refresh` with a `refresh_token` field in the request body, THE Auth_Service SHALL validate the token against stored refresh token records
2. WHEN a valid, non-expired Refresh_Token is presented and the associated User's `is_active` is TRUE, THE Auth_Service SHALL return a 200 response containing a new `access_token` with a fresh 30-minute expiry and a new `refresh_token` with a fresh 7-day expiry, and SHALL invalidate the old refresh token
3. IF the `refresh_token` does not match any record in the stored token table, THEN THE Auth_Service SHALL return a 401 unauthorized error
4. IF the matching refresh token record has an `expires_at` timestamp in the past, THEN THE Auth_Service SHALL return a 401 unauthorized error and delete the expired record
5. WHEN a valid Refresh_Token is presented, THE Auth_Service SHALL verify that the associated User's `is_active` is TRUE before issuing new tokens
6. IF the associated User's `is_active` is FALSE, THEN THE Auth_Service SHALL return a 401 unauthorized error and delete the Refresh_Token record
7. IF the request body is missing the `refresh_token` field or the field is empty, THEN THE Auth_Service SHALL return a 400 validation error

### Requirement 4: Logout (Token Revocation)

**User Story:** As a trader, I want to log out, so that my refresh token is invalidated and cannot be used further.

#### Acceptance Criteria

1. WHEN a POST request is received at `/trading/auth/logout` with a `refresh_token` in the request body, THE Auth_Service SHALL delete the matching refresh token record and return a 200 response
2. IF the `refresh_token` provided to the logout endpoint does not match any stored record, THEN THE Auth_Service SHALL return a 200 response (idempotent behavior — no error on double logout)
3. WHEN a logout request is received, THE Auth_Service SHALL return a response within 2 seconds
4. IF the request body is missing the `refresh_token` field or the field is empty, THEN THE Auth_Service SHALL return a 400 validation error

### Requirement 5: Authenticated Request Validation

**User Story:** As a system operator, I want every protected endpoint to verify the caller's identity, so that only authenticated active users can access their data.

#### Acceptance Criteria

1. WHEN a request is received at any endpoint under `/trading/users/me`, THE Auth_Service SHALL extract and validate the JWT from the `Authorization: Bearer <token>` header
2. IF the `Authorization` header is missing or does not use the `Bearer` scheme, THEN THE Auth_Service SHALL return a 401 unauthorized error with a JSON body containing an `error` field
3. IF the JWT signature is invalid, the token is expired, or the token payload cannot be decoded, THEN THE Auth_Service SHALL return a 401 unauthorized error with a JSON body containing an `error` field
4. IF a valid Access_Token is presented, THE Auth_Service SHALL look up the User by the `sub` claim UUID and verify that `is_active` is TRUE
5. IF the User identified by the `sub` claim does not exist or has `is_active` set to FALSE, THEN THE Auth_Service SHALL return a 401 unauthorized error with a JSON body containing an `error` field
6. THE Auth_Service SHALL complete token validation and user lookup within 500ms at the 95th percentile under a load of up to 10 concurrent requests
7. WHEN a valid Access_Token is presented and the User is active, THE Auth_Service SHALL make the authenticated user's `id`, `email`, and `is_active` available to the downstream handler for the duration of that request

### Requirement 6: User Profile Retrieval

**User Story:** As a trader, I want to view my own profile, so that I can see my account details.

#### Acceptance Criteria

1. WHEN an authenticated GET request is received at `/trading/users/me`, THE User_Service SHALL return a 200 response containing the authenticated user's `id`, `email`, `name`, `telegram_chat_id` (nullable), `is_active`, and `created_at`
2. THE User_Service SHALL NOT include the `password_hash` field in any response
3. THE User_Service SHALL only return data belonging to the user identified by the Access_Token's `sub` claim
4. IF the user record identified by the Access_Token's `sub` claim cannot be found in the database, THEN THE User_Service SHALL return a 404 not found error

### Requirement 7: User Profile Update

**User Story:** As a trader, I want to update my profile information, so that I can keep my account details current.

#### Acceptance Criteria

1. WHEN an authenticated PATCH request is received at `/trading/users/me` with one or more of the fields `email`, `name`, `telegram_chat_id`, or `password`, THE User_Service SHALL update only the provided fields for the authenticated user and return a 200 response containing the updated `id`, `email`, `name`, `telegram_chat_id`, and `created_at`
2. IF the new `email` in a profile update request already exists in the `users` table for a different user, THEN THE User_Service SHALL return a 409 conflict error
3. WHEN the `email` field is included in an update request, THE User_Service SHALL validate that it contains exactly one `@` symbol with non-empty local and domain parts and is at most 254 characters; IF validation fails, THE User_Service SHALL return a 422 error identifying the `email` field
4. WHEN the `password` field is included in an update request, THE User_Service SHALL validate that it is at least 8 and at most 128 characters, then hash it with bcrypt before storing it in `password_hash`; IF validation fails, THE User_Service SHALL return a 422 error identifying the `password` field
5. WHEN the `name` field is included in an update request, THE User_Service SHALL validate that it is a non-empty string of at least 1 and at most 100 characters; IF validation fails, THE User_Service SHALL return a 422 error identifying the `name` field
6. IF no valid fields are included in the update request body, THEN THE User_Service SHALL return a 422 validation error
7. WHEN the `telegram_chat_id` field is included in an update request, THE User_Service SHALL validate that it is a string of 1 to 50 characters; IF validation fails, THE User_Service SHALL return a 422 error identifying the `telegram_chat_id` field
8. IF any individual field in the update request fails validation, THEN THE User_Service SHALL return a 422 error identifying which field failed and SHALL NOT apply any partial updates to the database

### Requirement 8: Webhook Config Management

**User Story:** As a trader, I want to manage my webhook passphrase, so that I can control which TradingView alerts trigger my trades.

#### Acceptance Criteria

1. WHEN an authenticated GET request is received at `/trading/users/me/webhook-config`, THE Webhook_Config_Service SHALL validate the Access_Token first, then return a 200 response containing the authenticated user's Webhook_Config record including `id`, `passphrase`, `is_active`, and `created_at`
2. IF the authenticated user has no Webhook_Config record, THEN THE Webhook_Config_Service SHALL return a 404 not found error
3. WHEN an authenticated POST request is received at `/trading/users/me/webhook-config` with a `passphrase` field, THE Webhook_Config_Service SHALL create a new Webhook_Config record for the user and return a 201 response with the created record including `id`, `passphrase`, `is_active`, and `created_at`
4. IF the `passphrase` provided in a create request already exists in the `webhook_configs` table for any user, THEN THE Webhook_Config_Service SHALL return a 409 conflict error
5. IF the authenticated user already has a Webhook_Config record when a POST request is received, THEN THE Webhook_Config_Service SHALL return a 409 conflict error
6. WHEN an authenticated PATCH request is received at `/trading/users/me/webhook-config` with a new `passphrase`, THE Webhook_Config_Service SHALL update the passphrase for the user's existing Webhook_Config record and return a 200 response with the updated record; IF the new passphrase already exists for another user, THE Webhook_Config_Service SHALL return a 409 conflict error
7. IF a PATCH request is received at `/trading/users/me/webhook-config` and the user has no existing Webhook_Config record, THEN THE Webhook_Config_Service SHALL return a 404 not found error
8. WHEN an authenticated DELETE request is received at `/trading/users/me/webhook-config`, THE Webhook_Config_Service SHALL set the `is_active` field to FALSE for the user's Webhook_Config record and return a 200 response
9. IF a DELETE request is received at `/trading/users/me/webhook-config` and the user has no existing Webhook_Config record, THEN THE Webhook_Config_Service SHALL return a 404 not found error
10. WHEN the webhook endpoint `/webhook/tradingview` processes an incoming alert, THE Webhook_Config_Service SHALL verify that the User associated with the matching passphrase has `is_active` set to TRUE before processing the trade

### Requirement 9: Exchange Credential Management via API

**User Story:** As a trader, I want to manage my exchange API keys through a REST API, so that I can configure and update my trading credentials securely.

#### Acceptance Criteria

1. WHEN an authenticated GET request is received at `/trading/users/me/credentials`, THE Credential_Service SHALL return a 200 response containing a list of the user's configured exchanges; IF no credentials are configured, THE Credential_Service SHALL return a 200 response with an empty list; each entry SHALL include only the `exchange` name, `created_at`, and `is_configured: true` — the actual API key and secret values SHALL NOT be included in any response from this endpoint
2. WHEN an authenticated POST request is received at `/trading/users/me/credentials` with `exchange`, `api_key`, and `secret` fields where all three are non-empty strings, THE Credential_Service SHALL encrypt and store the credentials using the existing CredentialStore component and return a 200 response containing the `exchange` name and `created_at`
3. WHERE `api_passphrase` is included in the credentials request as a non-empty string, THE Credential_Service SHALL encrypt and store it alongside the API key and secret (required for OKX)
4. IF the `exchange` field in a credential request is not one of "binance" or "okx", THEN THE Credential_Service SHALL return a 422 validation error identifying the `exchange` field
5. IF the `api_key` or `secret` fields are missing or empty in a credentials POST request, THEN THE Credential_Service SHALL return a 422 validation error identifying each missing or empty field
6. WHEN a valid credentials POST request is received for an exchange that already has stored credentials for the user, THE Credential_Service SHALL overwrite the existing credentials (upsert behavior) and return a 200 response
7. WHEN an authenticated DELETE request is received at `/trading/users/me/credentials/{exchange}`, THE Credential_Service SHALL remove the credential record for the specified exchange and return a 200 response with a confirmation message
8. IF a DELETE request is received for an exchange that has no stored credentials for the user, THEN THE Credential_Service SHALL return a 404 not found error
9. IF the `{exchange}` path parameter in a DELETE request is not one of "binance" or "okx", THEN THE Credential_Service SHALL return a 422 validation error

### Requirement 10: Position Monitoring

**User Story:** As a trader, I want to view my current open positions and trade history, so that I can monitor my automated trading activity.

#### Acceptance Criteria

1. WHEN an authenticated GET request is received at `/trading/users/me/positions`, THE Position_Service SHALL return a 200 response containing a list of all positions with `status = 'open'` belonging to the authenticated user, ordered by `opened_at` descending, including `id`, `symbol`, `side`, `entry_price`, `quantity`, and `opened_at` for each; IF no open positions exist, THE Position_Service SHALL return a 200 response with an empty list
2. WHEN an authenticated GET request is received at `/trading/users/me/positions/history`, THE Position_Service SHALL return a 200 response containing a list of all positions with `status = 'closed'` belonging to the authenticated user, including `id`, `symbol`, `side`, `entry_price`, `exit_price`, `quantity`, `opened_at`, and `closed_at` for each; IF no closed positions exist, THE Position_Service SHALL return a 200 response with an empty list
3. WHEN an authenticated GET request is received at `/trading/users/me/trades`, THE Position_Service SHALL return a 200 response containing a list of all Trade_Log records belonging to the authenticated user, ordered by `created_at` descending, including `id`, `symbol`, `action`, `side`, `exchange`, `size_value`, `status`, `order_id`, `fill_price`, `filled_quantity`, `error_details`, and `created_at` for each; IF no trade logs exist, THE Position_Service SHALL return a 200 response with an empty list
4. THE Position_Service SHALL only return positions and trade logs belonging to the user identified by the Access_Token's `sub` claim
5. WHEN a request is received at `/trading/users/me/positions/history` or `/trading/users/me/trades`, THE Position_Service SHALL support optional `limit` (minimum 1, maximum 200, default 50) and `offset` (minimum 0, default 0) query parameters for pagination
6. IF a request is received at any monitoring endpoint without a valid Access_Token, THEN THE Position_Service SHALL return a 401 unauthorized error and SHALL NOT return any position or trade data
7. IF the `limit` or `offset` query parameters are provided but are non-integer or out of their valid ranges, THEN THE Position_Service SHALL return a 400 error identifying the invalid parameter

### Requirement 11: Database Schema Extensions

**User Story:** As a system operator, I want the database schema extended with the required columns and tables, so that the user management and authentication features work correctly.

#### Acceptance Criteria

1. THE database `users` table SHALL contain the following columns in addition to the existing `id`, `email`, and `created_at`: `name` (TEXT NOT NULL, maximum 255 characters), `password_hash` (TEXT NOT NULL), `telegram_chat_id` (TEXT, nullable), `is_active` (BOOLEAN NOT NULL DEFAULT TRUE), and `deleted_at` (TIMESTAMPTZ, nullable)
2. THE database SHALL contain a `user_tokens` table with columns: `id` (UUID PRIMARY KEY DEFAULT gen_random_uuid()), `user_id` (UUID NOT NULL, FK → users.id ON DELETE CASCADE), `token_hash` (TEXT NOT NULL UNIQUE), `expires_at` (TIMESTAMPTZ NOT NULL), and `created_at` (TIMESTAMPTZ NOT NULL DEFAULT NOW())
3. THE `user_tokens` table SHALL have an index on `user_id`, an index on `expires_at`, and an index on `token_hash` to support efficient lookup and expiry cleanup queries
4. THE `users` table SHALL have a unique constraint on the `email` column
5. THE migration SQL SHALL be idempotent — running it against a database that already has the extended schema SHALL not produce an error and SHALL NOT alter existing data

### Requirement 12: Integration with Existing Webhook Module

**User Story:** As a system operator, I want the new user management module to integrate with the existing webhook trading module, so that user active status is enforced consistently across the system.

#### Acceptance Criteria

1. WHEN the existing `/webhook/tradingview` endpoint processes an incoming alert, THE Auth_Service SHALL verify that the User associated with the matched Webhook_Config has `is_active = TRUE` within 500ms of receiving the request, before any trade execution begins
2. IF the User's `is_active` is FALSE when a webhook alert is received, THEN THE Webhook_Endpoint SHALL return a 401 unauthorized error and SHALL record a Trade_Log entry with `status = 'rejected'` and no exchange order SHALL be placed
3. THE authentication endpoints (`/trading/auth/register`, `/trading/auth/login`, `/trading/auth/refresh`, `/trading/auth/logout`) SHALL process requests and return responses regardless of whether an `Authorization` header is present, without returning a 401 or 403 status due to a missing or invalid token
4. THE Auth_Service JWT secret key SHALL be stored in the `JWT_SECRET_KEY` environment variable and SHALL NOT be hardcoded in source code
5. IF the `JWT_SECRET_KEY` environment variable is absent or empty when the application starts, THEN THE application SHALL fail to start and SHALL log an error message identifying the missing variable
