# Null Volume and Open Interest Bugfix Design

## Overview

This design addresses the bug where `volume_24h` and `open_interest` fields return null values in both the `/api/v1/screener/summary` and `/api/v1/screener/assets/{symbol}` API endpoints. The root cause is that these fields are hardcoded to `None` in the `ResponseBuilder._build_asset()` method, despite the underlying exchange API (CCXT) providing this data in the ticker response. The fix involves extracting these fields from the CCXT ticker data in the `MarketDataFetcher` and mapping them correctly in the `ResponseBuilder`.

## Glossary

- **Bug_Condition (C)**: The condition that triggers the bug - when the API response is built, `volume_24h` and `open_interest` are always set to `None` regardless of whether the exchange provides this data
- **Property (P)**: The desired behavior - when exchange data is available, these fields should contain numeric values; when unavailable, they should be `null`
- **Preservation**: All other API response fields (price, change_24h, funding_rate, long_short_ratio, rsi, macd_signal, volatility, composite_score, rank, signal) must continue to work exactly as before
- **CCXT Ticker**: The ticker object returned by `exchange.fetch_ticker(symbol)` which contains market data including volume and other metrics
- **MarketDataFetcher**: The class in `src/data/fetcher.py` that fetches raw market data from the exchange using CCXT
- **ResponseBuilder**: The class in `src/services/response_builder.py` that transforms DataFrame data into API response models
- **DataFrame Column**: The pandas DataFrame columns that store fetched market data before being transformed into API responses

## Bug Details

### Bug Condition

The bug manifests when the API response is constructed in the `ResponseBuilder._build_asset()` method. The method hardcodes `volume_24h` and `open_interest` to `None` with comments stating "Not fetched in current implementation", even though:
1. The CCXT ticker response includes volume data in the `baseVolume` or `quoteVolume` fields
2. CCXT provides an `exchange.fetch_open_interest(symbol)` method to retrieve open interest data
3. The DataFrame structure and API models already support these fields

**Formal Specification:**
```
FUNCTION isBugCondition(api_request)
  INPUT: api_request of type APIRequest (either /screener/summary or /screener/assets/{symbol})
  OUTPUT: boolean
  
  RETURN api_request.endpoint IN ['/api/v1/screener/summary', '/api/v1/screener/assets/{symbol}']
         AND response_contains_asset_data(api_request)
         AND response.asset.volume_24h == null
         AND response.asset.open_interest == null
END FUNCTION
```

### Examples

**Example 1: Summary Endpoint**
- **Request**: `GET /api/v1/screener/summary`
- **Current Behavior**: Response contains `assets[0].volume_24h: null` and `assets[0].open_interest: null`
- **Expected Behavior**: Response contains `assets[0].volume_24h: 28000000000.0` and `assets[0].open_interest: 18000000000.0` (when data is available from exchange)

**Example 2: Asset Detail Endpoint**
- **Request**: `GET /api/v1/screener/assets/BTC/USDT:USDT`
- **Current Behavior**: Response contains `asset.volume_24h: null` and `asset.open_interest: null`
- **Expected Behavior**: Response contains `asset.volume_24h: 28000000000.0` and `asset.open_interest: 18000000000.0` (when data is available from exchange)

**Example 3: Total Volume Calculation**
- **Request**: `GET /api/v1/screener/summary`
- **Current Behavior**: Response contains `market_overview.total_volume: null` because all `volume_24h` values are null
- **Expected Behavior**: Response contains `market_overview.total_volume: 47750000000.0` (sum of all non-null volume_24h values)

**Example 4: Exchange Data Unavailable**
- **Request**: `GET /api/v1/screener/assets/NEWCOIN/USDT:USDT`
- **Current Behavior**: Response contains `asset.volume_24h: null` and `asset.open_interest: null`
- **Expected Behavior**: Same - should return `null` when exchange doesn't provide the data (graceful degradation)

## Expected Behavior

### Preservation Requirements

**Unchanged Behaviors:**
- All other metric fields (price, change_24h, funding_rate, long_short_ratio, rsi, macd_signal, volatility) must continue to return correct values
- Composite score calculation and ranking must remain unchanged
- Signal derivation (BULLISH/BEARISH/NEUTRAL) must remain unchanged
- Market overview aggregations (avg_change_24h, avg_funding_rate, bullish_count, bearish_count, neutral_count) must remain unchanged
- Cache behavior and metadata (cache_hit, data_age_seconds, stale_data_warning) must remain unchanged
- Error handling for exchange errors (503) and internal errors (500) must remain unchanged
- Symbol validation and 404 responses for invalid symbols must remain unchanged
- Health check endpoint must remain unchanged

**Scope:**
All API requests that do NOT involve `volume_24h` or `open_interest` fields should be completely unaffected by this fix. This includes:
- Requests that only use other metric fields for analysis
- Requests to the `/api/v1/health` endpoint
- Error responses (404, 500, 503)
- Cache hit responses (should now include volume_24h and open_interest if cached data has them)

## Hypothesized Root Cause

Based on the code analysis, the root causes are:

1. **Missing Data Extraction in MarketDataFetcher**: The `fetch_ticker_data()` method in `src/data/fetcher.py` only extracts `price` and `change_24h` from the CCXT ticker response, ignoring the `baseVolume` or `quoteVolume` fields that contain 24-hour trading volume data.

2. **No Open Interest Fetching**: The `fetch_all_data()` method in `src/data/fetcher.py` does not call any method to fetch open interest data, even though CCXT provides `exchange.fetch_open_interest(symbol)` for this purpose.

3. **Hardcoded None Values in ResponseBuilder**: The `_build_asset()` method in `src/services/response_builder.py` (lines 296 and 298) explicitly sets `volume_24h=None` and `open_interest=None` with comments indicating these fields are "Not fetched in current implementation".

4. **Missing DataFrame Columns**: The `fetch_all_data()` method creates a DataFrame with columns for `volume_24h` and `open_interest` initialized to `np.nan`, but never populates them with actual data from the exchange.

## Correctness Properties

Property 1: Bug Condition - Volume and Open Interest Data Population

_For any_ API request where the bug condition holds (volume_24h and open_interest are null) AND the exchange provides this data, the fixed API SHALL return non-null numeric values for volume_24h and open_interest fields, with volume_24h containing the 24-hour trading volume and open_interest containing the current open interest value.

**Validates: Requirements 2.1, 2.2, 2.3, 2.4, 2.5**

Property 2: Preservation - Non-Volume/OI Field Behavior

_For any_ API request, the fixed code SHALL produce exactly the same values for all non-volume/open-interest fields (price, change_24h, funding_rate, long_short_ratio, rsi, macd_signal, volatility, composite_score, rank, signal, market_overview aggregations) as the original code, preserving all existing functionality for these metrics.

**Validates: Requirements 3.1, 3.2, 3.3, 3.4, 3.5, 3.6, 3.7, 3.8, 3.9, 3.10**

## Fix Implementation

### Changes Required

Assuming our root cause analysis is correct:

**File**: `src/data/fetcher.py`

**Function**: `fetch_ticker_data()`

**Specific Changes**:
1. **Extract Volume from Ticker**: Modify the `fetch_ticker_data()` method to extract the 24-hour trading volume from the CCXT ticker response
   - CCXT ticker objects contain volume data in the `baseVolume` field (volume in base currency) or `quoteVolume` field (volume in quote currency)
   - For crypto screener purposes, we should use `quoteVolume` (volume in USDT) as it's more relevant for comparing across different assets
   - Add extraction: `volume_24h = ticker.get('quoteVolume', None)`
   - Return volume_24h in the dictionary alongside price and change_24h

2. **Create Open Interest Fetching Method**: Add a new method `fetch_open_interest(symbol: str) -> float` to fetch open interest data
   - Use CCXT's `exchange.fetch_open_interest(symbol)` method
   - Extract the `openInterestAmount` or `openInterest` field from the response
   - Handle exceptions gracefully (return None if data unavailable)
   - Add appropriate logging for debugging

3. **Update fetch_all_data() Method**: Modify the `fetch_all_data()` method to populate volume_24h and open_interest columns
   - Extract volume_24h from the ticker_data dictionary returned by `fetch_ticker_data()`
   - Call the new `fetch_open_interest()` method for each symbol
   - Store both values in the DataFrame record
   - Handle None values gracefully (set to np.nan in DataFrame)

4. **Error Handling**: Ensure graceful degradation when exchange doesn't provide data
   - If `quoteVolume` is not in ticker response, try `baseVolume` as fallback
   - If both are unavailable, set volume_24h to None
   - If `fetch_open_interest()` raises an exception or returns None, set open_interest to np.nan
   - Log warnings for missing data but continue processing other symbols

**File**: `src/services/response_builder.py`

**Function**: `_build_asset()`

**Specific Changes**:
1. **Map volume_24h from DataFrame**: Replace the hardcoded `volume_24h=None` line with:
   ```python
   volume_24h=self._sanitize_value(row.get("volume_24h"), decimals=2),
   ```

2. **Map open_interest from DataFrame**: Replace the hardcoded `open_interest=None` line with:
   ```python
   open_interest=self._sanitize_value(row.get("open_interest"), decimals=2),
   ```

3. **Remove Comments**: Delete the comments "# Not fetched in current implementation" as they will no longer be accurate

## Testing Strategy

### Validation Approach

The testing strategy follows a two-phase approach: first, surface counterexamples that demonstrate the bug on unfixed code, then verify the fix works correctly and preserves existing behavior.

### Exploratory Bug Condition Checking

**Goal**: Surface counterexamples that demonstrate the bug BEFORE implementing the fix. Confirm or refute the root cause analysis. If we refute, we will need to re-hypothesize.

**Test Plan**: Write tests that call the API endpoints and assert that volume_24h and open_interest are null. Run these tests on the UNFIXED code to observe failures and confirm the bug exists. Then examine the fetcher and response builder code to verify our hypothesis about hardcoded None values.

**Test Cases**:
1. **Summary Endpoint Null Volume Test**: Call `/api/v1/screener/summary` and assert that all assets have `volume_24h: null` (will pass on unfixed code, confirming bug)
2. **Summary Endpoint Null Open Interest Test**: Call `/api/v1/screener/summary` and assert that all assets have `open_interest: null` (will pass on unfixed code, confirming bug)
3. **Asset Detail Null Volume Test**: Call `/api/v1/screener/assets/BTC/USDT:USDT` and assert `volume_24h: null` (will pass on unfixed code, confirming bug)
4. **Asset Detail Null Open Interest Test**: Call `/api/v1/screener/assets/BTC/USDT:USDT` and assert `open_interest: null` (will pass on unfixed code, confirming bug)
5. **Total Volume Null Test**: Call `/api/v1/screener/summary` and assert `market_overview.total_volume: null` (will pass on unfixed code, confirming bug)
6. **Code Inspection Test**: Read `src/services/response_builder.py` line 296 and 298 to confirm hardcoded None values (will confirm root cause)

**Expected Counterexamples**:
- All volume_24h and open_interest fields return null in API responses
- ResponseBuilder._build_asset() contains hardcoded `volume_24h=None` and `open_interest=None`
- MarketDataFetcher.fetch_ticker_data() does not extract volume from ticker response
- MarketDataFetcher.fetch_all_data() does not fetch open interest data

### Fix Checking

**Goal**: Verify that for all inputs where the bug condition holds, the fixed function produces the expected behavior.

**Pseudocode:**
```
FOR ALL api_request WHERE isBugCondition(api_request) DO
  response := handle_request_fixed(api_request)
  ASSERT expectedBehavior(response)
END FOR

FUNCTION expectedBehavior(response)
  IF exchange_provides_volume_data THEN
    ASSERT response.asset.volume_24h IS NOT null
    ASSERT response.asset.volume_24h >= 0
    ASSERT response.asset.volume_24h <= 999999999999.99
  ELSE
    ASSERT response.asset.volume_24h IS null
  END IF
  
  IF exchange_provides_open_interest_data THEN
    ASSERT response.asset.open_interest IS NOT null
    ASSERT response.asset.open_interest >= 0
    ASSERT response.asset.open_interest <= 999999999999.99
  ELSE
    ASSERT response.asset.open_interest IS null
  END IF
  
  IF at_least_one_asset_has_volume THEN
    ASSERT response.market_overview.total_volume IS NOT null
    ASSERT response.market_overview.total_volume == sum_of_all_non_null_volumes
  END IF
END FUNCTION
```

### Preservation Checking

**Goal**: Verify that for all inputs where the bug condition does NOT hold (i.e., requests that don't involve volume_24h or open_interest), the fixed function produces the same result as the original function.

**Pseudocode:**
```
FOR ALL api_request WHERE NOT involves_volume_or_oi_fields(api_request) DO
  ASSERT handle_request_original(api_request) = handle_request_fixed(api_request)
END FOR

FOR ALL api_request WHERE involves_volume_or_oi_fields(api_request) DO
  response_original := handle_request_original(api_request)
  response_fixed := handle_request_fixed(api_request)
  
  // Verify all non-volume/OI fields are identical
  ASSERT response_fixed.asset.price == response_original.asset.price
  ASSERT response_fixed.asset.change_24h == response_original.asset.change_24h
  ASSERT response_fixed.asset.funding_rate == response_original.asset.funding_rate
  ASSERT response_fixed.asset.long_short_ratio == response_original.asset.long_short_ratio
  ASSERT response_fixed.asset.rsi == response_original.asset.rsi
  ASSERT response_fixed.asset.macd_signal == response_original.asset.macd_signal
  ASSERT response_fixed.asset.volatility == response_original.asset.volatility
  ASSERT response_fixed.asset.composite_score == response_original.asset.composite_score
  ASSERT response_fixed.asset.rank == response_original.asset.rank
  ASSERT response_fixed.asset.signal == response_original.asset.signal
  
  // Verify market overview non-volume fields are identical
  ASSERT response_fixed.market_overview.avg_change_24h == response_original.market_overview.avg_change_24h
  ASSERT response_fixed.market_overview.avg_funding_rate == response_original.market_overview.avg_funding_rate
  ASSERT response_fixed.market_overview.bullish_count == response_original.market_overview.bullish_count
  ASSERT response_fixed.market_overview.bearish_count == response_original.market_overview.bearish_count
  ASSERT response_fixed.market_overview.neutral_count == response_original.market_overview.neutral_count
END FOR
```

**Testing Approach**: Property-based testing is recommended for preservation checking because:
- It generates many test cases automatically across the input domain
- It catches edge cases that manual unit tests might miss
- It provides strong guarantees that behavior is unchanged for all non-buggy inputs

**Test Plan**: Observe behavior on UNFIXED code first for non-volume/OI fields, then write property-based tests capturing that behavior.

**Test Cases**:
1. **Price Field Preservation**: Verify that price values remain identical before and after fix across all symbols
2. **Change 24h Preservation**: Verify that change_24h values remain identical before and after fix
3. **Funding Rate Preservation**: Verify that funding_rate values remain identical before and after fix
4. **Long/Short Ratio Preservation**: Verify that long_short_ratio values remain identical before and after fix
5. **Composite Score Preservation**: Verify that composite_score and rank remain identical before and after fix
6. **Signal Preservation**: Verify that signal derivation (BULLISH/BEARISH/NEUTRAL) remains identical before and after fix
7. **Market Overview Preservation**: Verify that avg_change_24h, avg_funding_rate, and sentiment counts remain identical before and after fix
8. **Cache Behavior Preservation**: Verify that cache_hit, data_age_seconds, and stale_data_warning remain identical before and after fix
9. **Error Handling Preservation**: Verify that 404, 500, and 503 error responses remain identical before and after fix
10. **Health Endpoint Preservation**: Verify that /api/v1/health response remains identical before and after fix

### Unit Tests

- Test `fetch_ticker_data()` extracts volume_24h correctly from CCXT ticker response
- Test `fetch_open_interest()` retrieves open interest data correctly from CCXT
- Test `fetch_all_data()` populates volume_24h and open_interest columns in DataFrame
- Test `_build_asset()` maps volume_24h and open_interest from DataFrame to API response
- Test `_build_market_overview()` calculates total_volume correctly when volume_24h values are present
- Test graceful degradation when exchange doesn't provide volume or open interest data
- Test edge cases: zero volume, extremely large volume, negative values (should be rejected), non-numeric values (should be rejected)

### Property-Based Tests

- Generate random ticker responses with various volume values and verify correct extraction
- Generate random DataFrames with volume_24h and open_interest columns and verify correct API response construction
- Generate random combinations of null and non-null volume values and verify total_volume calculation
- Test that all non-volume/OI fields remain unchanged across many randomly generated scenarios
- Test that error handling remains consistent across many randomly generated error scenarios

### Integration Tests

- Test full API flow: fetch data from exchange → process → build response → verify volume_24h and open_interest are present
- Test cache behavior: verify that cached responses include volume_24h and open_interest after fix
- Test multiple symbols: verify that volume_24h and open_interest are correctly populated for all symbols in the summary response
- Test error scenarios: verify graceful degradation when exchange API fails for volume or open interest
- Test data validation: verify that invalid volume/open interest values (negative, non-numeric, exceeding max) are rejected and set to null
