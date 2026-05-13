# Bugfix Requirements Document

## Introduction

This document specifies the requirements for fixing a bug where `volume_24h` and `open_interest` fields return null values in the `/api/v1/screener/summary` API response. While other market data fields (price, change_24h, funding_rate, long_short_ratio, rsi, macd_signal, volatility) are populated correctly, these two critical trading metrics are missing, preventing users from performing complete market analysis and making informed trading decisions.

The bug affects both individual asset details in the `assets` array and the aggregated `total_volume` field in `market_overview`, which depends on `volume_24h` values.

## Bug Analysis

### Current Behavior (Defect)

1.1 WHEN the `/api/v1/screener/summary` endpoint is called with a GET request, THE system returns the `volume_24h` field with a `null` value (JSON null, not string "null" or undefined) for each asset object in the `assets` array

1.2 WHEN the `/api/v1/screener/summary` endpoint is called with a successful response (HTTP 200), THEN the system returns the `open_interest` field with a `null` value for each asset object in the `assets` array, regardless of whether open interest data exists in the upstream exchange data source

1.3 WHEN the `/api/v1/screener/summary` endpoint is called with a valid HTTP GET request THEN the system returns HTTP status 200 AND the response body contains `market_overview.total_volume: null`

### Current Behavior (Defect) 1.4

1.4.1 WHEN the `/api/v1/screener/assets/{symbol}` endpoint is called with a valid symbol THEN the system returns HTTP status 200

1.4.2 WHEN the `/api/v1/screener/assets/{symbol}` endpoint is called with a valid symbol THEN the system returns a JSON response containing the field `volume_24h` with value `null`

1.4.3 WHEN the `/api/v1/screener/assets/{symbol}` endpoint is called with a valid symbol THEN the system returns other asset detail fields (price, change_24h, funding_rate) with non-null values where data is available

### Current Behavior (Defect) 1.5

**User Story:** As a QA tester, I want to verify that the open_interest field returns null in the asset detail endpoint, so that I can confirm the defect exists before the fix is applied.

#### Acceptance Criteria

1. WHEN the `/api/v1/screener/assets/{symbol}` endpoint is called with a valid symbol (matching pattern `^[A-Z0-9]+$` with length 1 to 20 characters), THEN the system SHALL return HTTP status code 200

2. WHEN the `/api/v1/screener/assets/{symbol}` endpoint returns HTTP status code 200, THEN the response body SHALL contain a field named `open_interest`

3. WHEN the response body contains the `open_interest` field, THEN the value SHALL be `null` (JSON null type, not string "null" or undefined)

4. WHEN the `/api/v1/screener/assets/{symbol}` endpoint is called with any valid symbol from the supported exchange, THEN the `open_interest` field SHALL consistently return `null` across all symbols

5. WHEN the `/api/v1/screener/assets/{symbol}` endpoint is called with an invalid symbol (not matching pattern `^[A-Z0-9]+$` or length exceeding 20 characters), THEN the system SHALL return HTTP status code 404 with an error message indicating symbol not found

### Expected Behavior (Correct)

2.1 WHEN the `/api/v1/screener/summary` endpoint is called, THE system SHALL return `volume_24h` as non-negative numeric values with up to 2 decimal places for each asset where trading volume data is available from the exchange

2.2 WHEN the `/api/v1/screener/summary` endpoint is called AND open interest data is available from the exchange, THE system SHALL return `open_interest` as a non-negative numeric value between 0 and 999999999999.99 with up to 2 decimal places for each asset

2.2.1 IF the `/api/v1/screener/summary` endpoint is called AND open interest data is not available from the exchange for a specific asset, THEN the system SHALL return `open_interest: null` for that asset

2.2.2 WHEN the `/api/v1/screener/summary` endpoint is called AND open interest data is available from the exchange, THE system SHALL round the `open_interest` value to 2 decimal places using standard rounding rules (0.5 rounds up)

### Requirement 2.3: Total Volume Calculation

**User Story:** As an API consumer, I want the `/api/v1/screener/summary` endpoint to provide aggregated market volume data, so that I can assess overall market activity.

#### Acceptance Criteria

1. WHEN the `/api/v1/screener/summary` endpoint is called AND at least one asset has a non-null `volume_24h` value THEN the system SHALL calculate `total_volume` in the `market_overview` section as the sum of all non-null `volume_24h` values from the `assets` array, rounded to 2 decimal places

2. WHEN the `/api/v1/screener/summary` endpoint is called AND all assets have null `volume_24h` values THEN the system SHALL return `total_volume: null` in the `market_overview` section

3. WHEN the `/api/v1/screener/summary` endpoint is called AND the `assets` array is empty THEN the system SHALL return `total_volume: 0.0` in the `market_overview` section

### Requirement 2.4: Volume Data Retrieval

**User Story:** As an API consumer, I want to retrieve 24-hour trading volume data for cryptocurrency symbols, so that I can analyze trading activity.

#### Acceptance Criteria

1. WHEN the `/api/v1/screener/assets/{symbol}` endpoint is called with a valid symbol AND trading volume data is available from the exchange, THEN the system SHALL return `volume_24h` as a non-negative numeric value with up to 8 decimal places.

2. IF the `/api/v1/screener/assets/{symbol}` endpoint is called with a valid symbol AND trading volume data is not available from the exchange, THEN the system SHALL return `volume_24h` as null.

3. IF the `/api/v1/screener/assets/{symbol}` endpoint is called with an invalid or unsupported symbol, THEN the system SHALL return an error response indicating the symbol is not found.

### Requirement 2.5: Open Interest Data Retrieval

**User Story:** As an API consumer, I want to retrieve open interest data for cryptocurrency symbols, so that I can analyze market positioning.

#### Acceptance Criteria

1. WHEN the `/api/v1/screener/assets/{symbol}` endpoint is called with a valid symbol AND open interest data is available from the exchange, THEN the system SHALL return `open_interest` as a non-negative numeric value with up to 8 decimal places within 5 seconds

2. IF the `/api/v1/screener/assets/{symbol}` endpoint is called with a valid symbol AND open interest data is not available from the exchange, THEN the system SHALL return `open_interest: null`

3. IF the `/api/v1/screener/assets/{symbol}` endpoint is called with an invalid symbol (not matching pattern `^[A-Z0-9]+/[A-Z0-9]+:[A-Z0-9]+$`), THEN the system SHALL return HTTP status 404 with error message "Symbol not found"

### Requirement 2.6-2.8: Handling Unavailable or Invalid Data

**User Story:** As an API consumer, I want the system to handle missing or invalid exchange data gracefully, so that I can still access other available metrics.

#### Acceptance Criteria

2.6 IF the exchange API does not return `volume_24h` or `open_interest` fields in the response for a specific asset, THEN the system SHALL return `null` for those specific fields in the API response while maintaining valid values for other available metrics (price, change_24h, funding_rate, long_short_ratio, rsi, macd_signal, volatility)

2.7 IF the exchange API returns `volume_24h` or `open_interest` with non-numeric values (e.g., string, boolean, object) OR negative values OR values exceeding 999999999999.99, THEN the system SHALL return `null` for those specific fields while maintaining valid values for other available metrics

2.8 IF the exchange API request for `volume_24h` or `open_interest` exceeds 5 seconds timeout, THEN the system SHALL return `null` for those specific fields while maintaining valid values for other available metrics

### Unchanged Behavior (Regression Prevention)

3.1 WHEN the `/api/v1/screener/summary` endpoint is called THEN the system SHALL CONTINUE TO return valid values for `price`, `change_24h`, `funding_rate`, `long_short_ratio`, `rsi`, `macd_signal`, and `volatility` fields

3.2 WHEN the `/api/v1/screener/summary` endpoint is called THEN the system SHALL CONTINUE TO return correct `rank` and `composite_score` values for all assets

3.3 WHEN the `/api/v1/screener/summary` endpoint is called THEN the system SHALL CONTINUE TO return correct `top_3_assets` in the summary section based on composite scores

3.4 WHEN the `/api/v1/screener/summary` endpoint is called THEN the system SHALL CONTINUE TO return correct `bullish_count`, `bearish_count`, and `neutral_count` in the `market_overview` section

3.5 WHEN the `/api/v1/screener/summary` endpoint is called THEN the system SHALL CONTINUE TO return correct `avg_change_24h` and `avg_funding_rate` in the `market_overview` section

3.6 WHEN the `/api/v1/screener/assets/{symbol}` endpoint is called THEN the system SHALL CONTINUE TO return all other metric fields with correct values

3.7 WHEN cache is hit THEN the system SHALL CONTINUE TO return cached data with correct `cache_hit` and `data_age_seconds` metadata

3.8 WHEN exchange errors occur THEN the system SHALL CONTINUE TO handle errors gracefully and return appropriate HTTP status codes (503 for exchange errors, 500 for internal errors)

3.9 WHEN invalid symbols are requested THEN the system SHALL CONTINUE TO return 404 status with appropriate error messages

3.10 WHEN the `/api/v1/health` endpoint is called THEN the system SHALL CONTINUE TO return correct health status and cache information
