# Implementation Plan: Trading User Management API

## Overview

Extend `src/trading/` with a full user lifecycle REST API using FastAPI. The implementation builds incrementally: database schema → config/utilities → services → routers → middleware and guard integration → monitoring endpoints → property and unit tests.

## Tasks

- [x] 1. Database schema migrations
  - [x] 1.1 Write SQL migration to extend the `users` table
    - Add `name TEXT NOT NULL DEFAULT ''`, `password_hash TEXT NOT NULL DEFAULT ''`, `telegram_chat_id TEXT`, `is_active BOOLEAN NOT NULL DEFAULT TRUE`, `deleted_at TIMESTAMPTZ`
    - Add `UNIQUE` constraint on `users.email`
    - Create migration file at `src/trading/migrations/001_extend_users.sql`
    - _Requirements: 18.1, 18.3_

  - [x] 1.2 Write SQL migration to create the `user_tokens` table
    - Columns: `id UUID PRIMARY KEY DEFAULT gen_random_uuid()`, `user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE`, `token_hash TEXT NOT NULL UNIQUE`, `expires_at TIMESTAMPTZ NOT NULL`, `created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()`
    - Add index `idx_user_tokens_user_id ON user_tokens(user_id)`
    - Create migration file at `src/trading/migrations/002_create_user_tokens.sql`
    - _Requirements: 18.2, 18.4_

- [x] 2. Config and utility modules
  - [x] 2.1 Extend `TradingSettings` in `src/trading/config.py`
    - Add `jwt_secret: str`, `access_token_expire_minutes: int = 30`, `refresh_token_expire_days: int = 7`
    - Add validator that raises `ValueError` when `jwt_secret` is absent or empty at startup
    - Read `TRADING_JWT_SECRET`, `TRADING_ACCESS_TOKEN_EXPIRE_MINUTES`, `TRADING_REFRESH_TOKEN_EXPIRE_DAYS` from environment
    - _Requirements: 19.1, 19.2_

  - [x] 2.2 Create `src/trading/jwt_utils.py`
    - Implement `create_access_token(user_id, secret, expire_minutes) -> str` producing a signed HS256 JWT with `sub`, `exp`, `iat` claims
    - Implement `decode_access_token(token, secret) -> dict` raising `JWTError` on invalid signature or expiry
    - _Requirements: 2.6, 5.1_

  - [ ]* 2.3 Write property test for JWT claims invariant
    - **Property 3: JWT access token claims invariant**
    - **Validates: Requirements 2.6, 3.1**
    - Use `@given(st.uuids().map(str))` to verify `sub`, `exp`, `iat` claims are correct for any user ID

  - [x] 2.4 Create `src/trading/password_utils.py`
    - Implement `hash_password(plain: str) -> str` using `passlib[bcrypt]`
    - Implement `verify_password(plain: str, hashed: str) -> bool`
    - _Requirements: 1.6, 7.2_

  - [ ]* 2.5 Write property test for bcrypt password storage
    - **Property 2: Password is always stored as a bcrypt hash, never plaintext**
    - **Validates: Requirements 1.6, 7.2**
    - Use `@given(st.text(min_size=8, max_size=72))` to verify stored hash satisfies `bcrypt.checkpw` and is not equal to plaintext

- [x] 3. Pydantic request/response models
  - [x] 3.1 Create `src/trading/user_models.py` with all request/response Pydantic models
    - `RegisterRequest`, `UserProfileResponse`, `LoginRequest`, `TokenResponse`, `AccessTokenResponse`, `RefreshRequest`
    - `ProfileUpdateRequest` with `model_validator` requiring at least one field
    - `WebhookConfigCreateRequest`, `WebhookConfigUpdateRequest`, `WebhookConfigResponse`
    - `CredentialUpsertRequest`, `CredentialSummaryResponse`
    - `OpenPositionResponse`, `ClosedPositionResponse`, `TradeLogResponse`
    - `APIErrorResponse`
    - _Requirements: 20.1, 20.2_

  - [ ]* 3.2 Write property test for response model serialization round-trip
    - **Property 9: Response model serialization round-trip**
    - **Validates: Requirements 20.2**
    - Use `@given(st.builds(...))` for each response model; verify `model_validate(json.loads(json.dumps(model_dump())))` produces identical field values

  - [ ]* 3.3 Write property test for registration input validation
    - **Property 1: Registration input validation rejects out-of-range values**
    - **Validates: Requirements 1.2, 1.4, 1.5**
    - Use `@given` with three `one_of` branches (invalid email, empty name, short password) and verify `RegisterRequest` raises `ValidationError` for each

- [x] 4. `Active_User_Guard` dependency
  - [x] 4.1 Create `src/trading/active_user_guard.py`
    - Implement `active_user_guard` FastAPI dependency: extract Bearer token, verify JWT via `decode_access_token`, query `users.is_active` for the `sub` claim, raise `HTTPException(401)` on any failure
    - Return decoded payload dict on success
    - _Requirements: 5.1, 5.2, 5.3, 5.4, 5.5, 5.6_

- [x] 5. Auth service and router
  - [x] 5.1 Create `src/trading/services/auth_service.py` with `AuthService`
    - Implement `register`: hash password with bcrypt, insert user row, return `UserProfileResponse`; raise 409 on duplicate email
    - Implement `login`: verify password hash, check `is_active`, issue JWT via `create_access_token`, generate `secrets.token_hex(32)` refresh token, persist SHA-256 hash in `user_tokens`, return `TokenResponse`
    - Implement `refresh`: SHA-256 hash incoming token, look up in `user_tokens`, check `expires_at`, delete expired record on failure, issue new JWT, return `AccessTokenResponse`
    - Implement `logout`: delete all `user_tokens` rows for `user_id`
    - _Requirements: 1.1, 1.3, 1.6, 1.7, 1.8, 2.1, 2.2, 2.3, 2.4, 2.5, 3.1, 3.2, 3.3, 3.4, 4.1_

  - [x] 5.2 Create `src/trading/routers/__init__.py` and `src/trading/services/__init__.py`
    - Empty init files to make the sub-packages importable
    - _Requirements: (structural)_

  - [x] 5.3 Create `src/trading/routers/auth_router.py`
    - `APIRouter(prefix="/trading/auth", tags=["Auth"])`
    - `POST /register` → 201 `UserProfileResponse`
    - `POST /login` → 200 `TokenResponse`
    - `POST /refresh` → 200 `AccessTokenResponse`
    - `POST /logout` → 200 `{"message": "Logged out"}` (requires `active_user_guard`)
    - Inject `AuthService` via dependency
    - _Requirements: 1.1, 2.1, 3.1, 4.1, 4.2, 4.3_

  - [ ]* 5.4 Write property test for logout token removal
    - **Property 4: Logout removes all refresh tokens for the user**
    - **Validates: Requirements 4.1**
    - Use `@given(st.integers(min_value=1, max_value=5))` to seed N tokens for a user, call logout, assert zero rows remain in `user_tokens`

- [x] 6. Profile service and users router (base)
  - [x] 6.1 Create `src/trading/services/profile_service.py` with `ProfileService`
    - Implement `get_profile`: query user by ID, return `UserProfileResponse` (no `password_hash`)
    - Implement `update_profile`: update only fields present in `ProfileUpdateRequest`, hash new password if provided, return updated `UserProfileResponse`
    - _Requirements: 6.1, 6.2, 7.1, 7.2, 7.3, 7.4_

  - [x] 6.2 Create `src/trading/routers/users_router.py` with `GET /trading/users/me` and `PATCH /trading/users/me`
    - `APIRouter(prefix="/trading/users/me", tags=["Users"])` with `active_user_guard` on all routes
    - `GET /trading/users/me` → 200 `UserProfileResponse`
    - `PATCH /trading/users/me` → 200 `UserProfileResponse`
    - _Requirements: 6.1, 6.2, 7.1, 7.3, 7.4_

  - [ ]* 6.3 Write property test for profile partial-write invariant
    - **Property 5: Profile update partial-write invariant**
    - **Validates: Requirements 6.2, 7.1**
    - Use `@given` with optional subsets of `{name, telegram_chat_id}`; verify only provided fields change and `password_hash` is absent from response

- [x] 7. Checkpoint — core auth and profile
  - Ensure all tests pass, ask the user if questions arise.

- [x] 8. Webhook config service and routes
  - [x] 8.1 Create `src/trading/services/webhook_config_service.py` with `WebhookConfigService`
    - Implement `get_active`: query active record by user, return `WebhookConfigResponse`; raise 404 if none
    - Implement `create`: validate passphrase ≥ 8 chars, check no existing active config (409), check global passphrase uniqueness (409), insert with `is_active=True`, return 201
    - Implement `update`: check active config exists (404), check global passphrase uniqueness (409), update passphrase, return updated record
    - Implement `deactivate`: check active config exists (404), set `is_active=False`, return updated record
    - _Requirements: 8.1, 8.2, 9.1, 9.2, 9.3, 9.4, 10.1, 10.2, 10.3, 11.1, 11.2_

  - [x] 8.2 Add webhook config routes to `src/trading/routers/users_router.py`
    - `GET /trading/users/me/webhook-config` → 200 `WebhookConfigResponse`
    - `POST /trading/users/me/webhook-config` → 201 `WebhookConfigResponse`
    - `PATCH /trading/users/me/webhook-config` → 200 `WebhookConfigResponse`
    - `DELETE /trading/users/me/webhook-config` → 200 `WebhookConfigResponse`
    - _Requirements: 8.1, 8.2, 9.1, 10.1, 11.1_

- [x] 9. Credential service and routes
  - [x] 9.1 Create `src/trading/services/credential_service.py` with `CredentialService`
    - Implement `list_credentials`: query `exchange_credentials` for user, return list of `CredentialSummaryResponse` (no keys/secrets)
    - Implement `upsert_credentials`: encrypt `api_key`, `secret`, and optional `api_passphrase` using existing `CredentialStore` Fernet mechanism, upsert row, return `CredentialSummaryResponse`
    - Implement `delete_credentials`: validate exchange in `{"binance","okx"}`, delete row, raise 404 if missing; return confirmation dict
    - _Requirements: 12.1, 12.2, 12.3, 13.1, 13.2, 13.3, 13.4, 14.1, 14.2, 14.3_

  - [x] 9.2 Add credential routes to `src/trading/routers/users_router.py`
    - `GET /trading/users/me/credentials` → 200 `list[CredentialSummaryResponse]`
    - `POST /trading/users/me/credentials` → 200 `CredentialSummaryResponse`
    - `DELETE /trading/users/me/credentials/{exchange}` → 200 `{"message": "Credentials removed"}`
    - _Requirements: 12.1, 13.1, 14.1_

  - [ ]* 9.3 Write property test for credential response secrets exclusion
    - **Property 6: Credential responses never expose secrets**
    - **Validates: Requirements 12.2, 13.4**
    - Use `@given` over `{exchange, api_key, secret}` combos; assert response JSON keys do not contain `api_key`, `secret`, or `api_passphrase`

  - [ ]* 9.4 Write property test for exchange field validation
    - **Property 7: Exchange field validation rejects non-supported values**
    - **Validates: Requirements 13.2, 14.2**
    - Use `@given(st.text().filter(lambda s: s not in ("binance", "okx")))` and verify both POST credentials and DELETE credentials/{exchange} return 422

- [x] 10. Monitoring service and routes
  - [x] 10.1 Create `src/trading/services/monitoring_service.py` with `MonitoringService`
    - Implement `get_open_positions`: query open positions for user, return `list[OpenPositionResponse]` (empty list if none)
    - Implement `get_position_history`: query closed positions ordered by `closed_at DESC`, return `list[ClosedPositionResponse]`
    - Implement `get_trade_log`: query trade log ordered by `created_at DESC`, return `list[TradeLogResponse]`
    - _Requirements: 15.1, 15.2, 16.1, 16.2, 16.3, 17.1, 17.2, 17.3_

  - [x] 10.2 Add monitoring routes to `src/trading/routers/users_router.py`
    - `GET /trading/users/me/positions` → 200 `list[OpenPositionResponse]`
    - `GET /trading/users/me/positions/history` → 200 `list[ClosedPositionResponse]`
    - `GET /trading/users/me/trades` → 200 `list[TradeLogResponse]`
    - _Requirements: 15.1, 16.1, 17.1_

  - [ ]* 10.3 Write property test for monitoring list ordering
    - **Property 8: Monitoring lists are ordered by timestamp descending**
    - **Validates: Requirements 16.3, 17.3**
    - Use `@given(st.lists(st.datetimes(timezones=st.just(timezone.utc)), min_size=2, max_size=10))`; verify `response[i].timestamp >= response[i+1].timestamp` for all consecutive pairs

- [x] 11. Middleware, router registration, and webhook guard integration
  - [x] 11.1 Add `ContentSizeLimitMiddleware` to the application factory (1 MB limit)
    - Register middleware globally to reject bodies exceeding 1 MB with 413
    - _Requirements: 20.3_

  - [x] 11.2 Register new routers in the application factory
    - `app.include_router(auth_router)` and `app.include_router(users_router)`
    - _Requirements: (structural)_

  - [x] 11.3 Update `src/trading/router.py` to enforce `is_active` check on webhook endpoint
    - After passphrase-based `authenticate_by_passphrase` resolves the user, query `users.is_active` and raise `HTTPException(401)` if `false`
    - _Requirements: 5.7_

- [x] 12. Checkpoint — full route coverage
  - Ensure all tests pass, ask the user if questions arise.

- [x] 13. Unit tests
  - [ ]* 13.1 Write unit tests for `AuthService`
    - Registration returns 201 with correct fields (Req 1.1)
    - Duplicate email returns 409 (Req 1.3)
    - Login returns 200 with correct shape (Req 2.1)
    - Login with wrong password returns 401 (Req 2.4)
    - Login with inactive user returns 401 (Req 2.5)
    - Refresh deletes expired token record (Req 3.3)
    - Missing `TRADING_JWT_SECRET` raises `ValueError` at startup (Req 19.1)
    - _Requirements: 1.1, 1.3, 2.1, 2.4, 2.5, 3.3, 19.1_

  - [ ]* 13.2 Write unit tests for `ProfileService` and `Active_User_Guard`
    - `GET /users/me` returns all required fields without `password_hash` (Req 6.1, 6.2)
    - `Active_User_Guard` returns 401 for missing `Authorization` header (Req 5.2)
    - `Active_User_Guard` returns 401 for tampered JWT (Req 5.3)
    - `Active_User_Guard` returns 401 for expired JWT (Req 5.4)
    - _Requirements: 5.2, 5.3, 5.4, 6.1, 6.2_

  - [ ]* 13.3 Write unit tests for `WebhookConfigService` and `CredentialService`
    - Webhook config 404 when none exists (Req 8.2)
    - Webhook config 409 on duplicate creation (Req 9.3)
    - Credential list returns empty array when none configured (Req 12.3)
    - DELETE credential returns 404 when none exists (Req 14.3)
    - _Requirements: 8.2, 9.3, 12.3, 14.3_

  - [ ]* 13.4 Write unit tests for `MonitoringService` and webhook guard
    - Open positions returns empty array (Req 15.2)
    - Webhook endpoint returns 401 when `is_active=false` (Req 5.7)
    - _Requirements: 5.7, 15.2_

- [ ] 14. Final checkpoint — ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

## Notes

- Tasks marked with `*` are optional and can be skipped for faster MVP
- Each task references specific requirements for traceability
- Property tests use Hypothesis (`@given`, `@settings(max_examples=100)`) and are tagged with `# Feature: trading-user-management-api, Property N:`
- The existing `auth.py`, `credentials.py`, and `models.py` are not modified except where noted
- Credential encryption reuses the existing `CredentialStore` Fernet mechanism — no new encryption logic needed
- Checkpoints at tasks 7 and 12 ensure incremental validation before building further

## Task Dependency Graph

```json
{
  "waves": [
    { "id": 0, "tasks": ["1.1", "1.2"] },
    { "id": 1, "tasks": ["2.1", "2.2", "2.4", "3.1", "5.2"] },
    { "id": 2, "tasks": ["2.3", "2.5", "3.2", "3.3", "4.1"] },
    { "id": 3, "tasks": ["5.1"] },
    { "id": 4, "tasks": ["5.3", "5.4", "6.1"] },
    { "id": 5, "tasks": ["6.2", "6.3"] },
    { "id": 6, "tasks": ["8.1", "9.1", "10.1"] },
    { "id": 7, "tasks": ["8.2", "9.2", "9.3", "9.4", "10.2", "10.3"] },
    { "id": 8, "tasks": ["11.1", "11.2", "11.3"] },
    { "id": 9, "tasks": ["13.1", "13.2", "13.3", "13.4"] }
  ]
}
```
