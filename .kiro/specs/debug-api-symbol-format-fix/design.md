# Debug API Symbol Format Fix - Bugfix Design

## Overview

The Debug API endpoints currently reject valid CCXT unified symbol format (BTC/USDT:USDT) due to overly restrictive validation in the `validate_symbol()` function, which only accepts alphanumeric characters. Additionally, there is inconsistent symbol format handling across endpoints - some CCXT methods (fetch_ticker, fetch_open_interest) require CCXT unified format, while others (fetch_funding_rate) work with Binance native format, and fetch_long_short_ratio requires explicit conversion to Binance native format via the market lookup.

The fix involves two key changes:
1. **Relax validation**: Update `validate_symbol()` to accept `/` and `:` characters present in CCXT unified format
2. **Add format conversion**: Implement intelligent symbol format detection and conversion logic to automatically translate between formats based on what each endpoint requires

This ensures users can provide either format (BTC/USDT:USDT or BTCUSDT) and the system will handle the conversion transparently.

## Glossary

- **Bug_Condition (C)**: The condition that triggers the bug - when valid CCXT unified format symbols (containing `/` or `:`) are rejected by validation, or when Binance native format symbols fail on CCXT methods that require unified format
- **Property (P)**: The desired behavior - both CCXT unified format (BTC/USDT:USDT) and Binance native format (BTCUSDT) should be accepted and automatically converted to the correct format for each exchange method
- **Preservation**: Existing functionality that must remain unchanged - endpoints that currently work with Binance native format (funding rate, long/short ratio) must continue to work, and all error handling and response structures must remain the same
- **CCXT Unified Format**: Symbol format used by CCXT library for futures contracts: `BASE/QUOTE:SETTLE` (e.g., `BTC/USDT:USDT`)
- **Binance Native Format**: Symbol format used directly by Binance API: `BASEQUOTE` (e.g., `BTCUSDT`)
- **validate_symbol()**: Function in `src/api/debug_utils.py` that validates symbol parameters before processing
- **normalize_symbol()**: Function in `src/api/debug_utils.py` that normalizes symbols (trim, uppercase)
- **DebugExchangeService**: Service class in `src/services/debug_exchange_service.py` that fetches raw exchange data

## Bug Details

### Bug Condition

The bug manifests in two scenarios:

**Scenario 1**: When a user provides CCXT unified format (BTC/USDT:USDT), the `validate_symbol()` function rejects it because it contains `/` and `:` characters, which fail the `isalnum()` check.

**Scenario 2**: When a user provides Binance native format (BTCUSDT) to endpoints that use CCXT methods requiring unified format (fetch_ticker, fetch_open_interest), the CCXT library fails to process the symbol because it expects the unified format.

**Formal Specification:**
```
FUNCTION isBugCondition(input)
  INPUT: input of type SymbolRequest with fields (symbol: string, endpoint: string)
  OUTPUT: boolean
  
  RETURN (
    // Scenario 1: CCXT format rejected by validation
    (input.symbol MATCHES /[\/:]/ AND validate_symbol(input.symbol) == False)
    OR
    // Scenario 2: Binance format fails on CCXT methods
    (input.symbol NOT MATCHES /[\/:]/ 
     AND input.endpoint IN ['ticker', 'open-interest'] 
     AND ccxt_method_called_with(input.symbol) == True)
  )
END FUNCTION
```

### Examples

**Scenario 1 - CCXT Format Rejected:**
- Input: `BTC/USDT:USDT` to `/api/v1/debug/exchange/ticker/BTC/USDT:USDT`
- Current behavior: Returns 400 error "Symbol must contain only alphanumeric characters"
- Expected behavior: Accepts the symbol and successfully fetches ticker data

**Scenario 2 - Binance Format Fails on CCXT Methods:**
- Input: `BTCUSDT` to `/api/v1/debug/exchange/ticker/BTCUSDT`
- Current behavior: Passes validation but fetch_ticker fails with CCXT error (symbol not found)
- Expected behavior: Converts to `BTC/USDT:USDT` and successfully fetches ticker data

- Input: `BTCUSDT` to `/api/v1/debug/exchange/open-interest/BTCUSDT`
- Current behavior: Passes validation but fetch_open_interest fails with CCXT error
- Expected behavior: Converts to `BTC/USDT:USDT` and successfully fetches open interest data

**Edge Cases:**
- Input: `BTC/USDT:USDT` to `/api/v1/debug/exchange/funding-rate/BTC/USDT:USDT`
- Expected behavior: Accepts CCXT format (validation passes) and fetch_funding_rate processes it correctly (CCXT handles format internally)

- Input: `BTCUSDT` to `/api/v1/debug/exchange/long-short-ratio/BTCUSDT`
- Expected behavior: Continues to work as before (already uses market lookup for conversion)

## Expected Behavior

### Preservation Requirements

**Unchanged Behaviors:**
- Endpoints that currently work with Binance native format (funding-rate, long-short-ratio) must continue to work exactly as before
- All error handling and HTTP status codes must remain unchanged
- Response structure and data format must remain unchanged
- Invalid symbols (empty strings, special characters other than `/` and `:`, malformed formats) must continue to be rejected with appropriate error messages
- Authentication, timing metadata, field mappings, and all other response components must remain unchanged

**Scope:**
All inputs that do NOT involve the specific bug conditions (valid CCXT format being rejected, or valid Binance format failing on CCXT methods) should be completely unaffected by this fix. This includes:
- Invalid symbols (empty, too long, containing invalid special characters)
- Network errors, timeouts, authentication errors
- Exchange errors and server errors
- All metadata and field mapping functionality

## Hypothesized Root Cause

Based on the bug description and code analysis, the root causes are:

1. **Overly Restrictive Validation**: The `validate_symbol()` function in `src/api/debug_utils.py` uses `isalnum()` check which rejects `/` and `:` characters that are valid in CCXT unified format. This was likely designed for Binance native format only without considering CCXT unified format.

2. **Missing Format Conversion Logic**: There is no automatic conversion between Binance native format and CCXT unified format. The code assumes users will provide the correct format for each endpoint, but:
   - `fetch_ticker()` and `fetch_open_interest()` require CCXT unified format
   - `fetch_funding_rate()` works with both formats (CCXT handles it internally)
   - `fetch_long_short_ratio()` already has conversion logic (uses `market['id']` to get Binance format)

3. **Inconsistent Format Requirements**: Different CCXT methods have different format requirements, but this is not documented or handled transparently for users.

## Correctness Properties

Property 1: Bug Condition - CCXT Unified Format Acceptance

_For any_ input where a valid CCXT unified symbol format (containing `/` and `:` characters in the pattern `BASE/QUOTE:SETTLE`) is provided to any debug endpoint, the fixed validation function SHALL accept it as valid input and the endpoint SHALL process it correctly, returning successful data or appropriate exchange errors (not validation errors).

**Validates: Requirements 2.1, 2.4**

Property 2: Bug Condition - Binance Native Format Conversion

_For any_ input where a valid Binance native symbol format (alphanumeric only, e.g., `BTCUSDT`) is provided to endpoints that use CCXT methods requiring unified format (ticker, open-interest), the fixed system SHALL automatically convert the symbol to CCXT unified format before calling the CCXT method, resulting in successful data retrieval.

**Validates: Requirements 2.2, 2.3, 2.5**

Property 3: Preservation - Existing Endpoint Behavior

_For any_ input that is NOT affected by the bug conditions (funding-rate and long-short-ratio endpoints with Binance native format, or any invalid symbols), the fixed code SHALL produce exactly the same behavior as the original code, preserving all existing functionality including error messages, HTTP status codes, and response structures.

**Validates: Requirements 3.1, 3.2, 3.3, 3.4**

## Fix Implementation

### Changes Required

Assuming our root cause analysis is correct:

**File**: `src/api/debug_utils.py`

**Function**: `validate_symbol()`

**Specific Changes**:
1. **Relax Character Validation**: Replace the `isalnum()` check with a more permissive pattern that accepts:
   - Alphanumeric characters (A-Z, a-z, 0-9)
   - Forward slash (`/`) for CCXT format
   - Colon (`:`) for CCXT format
   - Implementation: Use regex pattern `^[A-Za-z0-9/:]+$` instead of `isalnum()`

2. **Add Format Validation**: Ensure the symbol matches either:
   - Binance native format: `^[A-Z0-9]+$` (alphanumeric uppercase)
   - CCXT unified format: `^[A-Z0-9]+/[A-Z0-9]+:[A-Z0-9]+$` (BASE/QUOTE:SETTLE)
   - This prevents accepting malformed symbols like `BTC//USDT` or `BTC:USDT/`

**File**: `src/api/debug_utils.py`

**New Function**: `convert_symbol_format()`

**Specific Changes**:
3. **Add Symbol Format Detection**: Create a new function to detect whether a symbol is in Binance native or CCXT unified format:
   - If contains `/` and `:` → CCXT unified format
   - If alphanumeric only → Binance native format

4. **Add Format Conversion Logic**: Implement conversion between formats:
   - **Binance → CCXT**: Convert `BTCUSDT` to `BTC/USDT:USDT`
     - Pattern: Split at `USDT` suffix → `BTC` + `/USDT:USDT`
     - Handle edge cases: USDTUSDT, BUSDUSDT, etc.
   - **CCXT → Binance**: Convert `BTC/USDT:USDT` to `BTCUSDT`
     - Pattern: Remove `/` and everything after `:` → `BTCUSDT`

5. **Add Conversion Helper**: Create `ensure_ccxt_format()` function that:
   - Takes a symbol in either format
   - Returns CCXT unified format
   - Used by ticker and open-interest endpoints

**File**: `src/services/debug_exchange_service.py`

**Functions**: `fetch_raw_ticker()`, `fetch_raw_open_interest()`

**Specific Changes**:
6. **Apply Format Conversion**: After validation and normalization, convert the symbol to CCXT unified format before calling CCXT methods:
   ```python
   normalized_symbol = normalize_symbol(symbol)
   ccxt_symbol = ensure_ccxt_format(normalized_symbol)
   raw_data = await self.exchange.fetch_ticker(ccxt_symbol)
   ```

7. **Preserve Existing Behavior**: No changes needed for `fetch_raw_funding_rate()` and `fetch_raw_long_short_ratio()` as they already handle format correctly or have their own conversion logic.

## Testing Strategy

### Validation Approach

The testing strategy follows a two-phase approach: first, surface counterexamples that demonstrate the bug on unfixed code, then verify the fix works correctly and preserves existing behavior.

### Exploratory Bug Condition Checking

**Goal**: Surface counterexamples that demonstrate the bug BEFORE implementing the fix. Confirm or refute the root cause analysis. If we refute, we will need to re-hypothesize.

**Test Plan**: Write tests that attempt to use CCXT unified format and Binance native format on various endpoints. Run these tests on the UNFIXED code to observe failures and understand the root cause.

**Test Cases**:
1. **CCXT Format Validation Test**: Call ticker endpoint with `BTC/USDT:USDT` (will fail on unfixed code with validation error)
2. **Binance Format on Ticker Test**: Call ticker endpoint with `BTCUSDT` (will fail on unfixed code with CCXT error)
3. **Binance Format on OpenInterest Test**: Call open-interest endpoint with `BTCUSDT` (will fail on unfixed code with CCXT error)
4. **CCXT Format on All Endpoints Test**: Call all endpoints with `BTC/USDT:USDT` (ticker and open-interest will fail validation on unfixed code)

**Expected Counterexamples**:
- Validation rejects CCXT format with "Symbol must contain only alphanumeric characters"
- CCXT methods fail with symbol not found errors when given Binance native format
- Possible causes: `isalnum()` check too restrictive, missing format conversion logic

### Fix Checking

**Goal**: Verify that for all inputs where the bug condition holds, the fixed function produces the expected behavior.

**Pseudocode:**
```
FOR ALL input WHERE isBugCondition(input) DO
  result := process_symbol_fixed(input.symbol, input.endpoint)
  ASSERT expectedBehavior(result)
END FOR

FUNCTION expectedBehavior(result)
  RETURN result.success == True 
         OR (result.success == False AND result.error.code != "INVALID_INPUT")
         // Success or non-validation error (e.g., network error, exchange error)
END FUNCTION
```

### Preservation Checking

**Goal**: Verify that for all inputs where the bug condition does NOT hold, the fixed function produces the same result as the original function.

**Pseudocode:**
```
FOR ALL input WHERE NOT isBugCondition(input) DO
  ASSERT process_symbol_original(input) = process_symbol_fixed(input)
END FOR
```

**Testing Approach**: Property-based testing is recommended for preservation checking because:
- It generates many test cases automatically across the input domain
- It catches edge cases that manual unit tests might miss
- It provides strong guarantees that behavior is unchanged for all non-buggy inputs

**Test Plan**: Observe behavior on UNFIXED code first for funding-rate and long-short-ratio endpoints with Binance native format, then write property-based tests capturing that behavior.

**Test Cases**:
1. **Funding Rate Preservation**: Observe that `BTCUSDT` works correctly on funding-rate endpoint with unfixed code, then write test to verify this continues after fix
2. **Long/Short Ratio Preservation**: Observe that `BTCUSDT` works correctly on long-short-ratio endpoint with unfixed code, then write test to verify this continues after fix
3. **Invalid Symbol Preservation**: Observe that invalid symbols (empty, too long, special chars like `@#$`) are rejected with appropriate errors on unfixed code, then write test to verify this continues after fix
4. **Error Response Preservation**: Observe that network errors, timeouts, and exchange errors produce the same response structure on unfixed code, then write test to verify this continues after fix

### Unit Tests

- Test `validate_symbol()` with CCXT unified format symbols (should pass after fix)
- Test `validate_symbol()` with Binance native format symbols (should continue to pass)
- Test `validate_symbol()` with invalid symbols (should continue to fail with appropriate errors)
- Test `convert_symbol_format()` with various Binance native symbols (BTCUSDT, ETHUSDT, USDTUSDT edge case)
- Test `convert_symbol_format()` with various CCXT unified symbols (BTC/USDT:USDT, ETH/USDT:USDT)
- Test `ensure_ccxt_format()` with both input formats
- Test edge cases: empty strings, whitespace, very long symbols, malformed formats

### Property-Based Tests

- Generate random valid CCXT unified format symbols and verify they pass validation and work on all endpoints
- Generate random valid Binance native format symbols and verify they pass validation and work on all endpoints (with automatic conversion)
- Generate random invalid symbols and verify they are rejected consistently
- Generate random valid symbols and verify that funding-rate and long-short-ratio endpoints produce the same results before and after the fix
- Test that all endpoints return the same response structure and metadata format regardless of input symbol format

### Integration Tests

- Test full request flow with CCXT format on ticker endpoint (validation → conversion → CCXT call → response)
- Test full request flow with Binance format on ticker endpoint (validation → conversion → CCXT call → response)
- Test full request flow with CCXT format on open-interest endpoint
- Test full request flow with Binance format on open-interest endpoint
- Test aggregated endpoint (`/all/{symbol}`) with both formats
- Test that error responses (network errors, exchange errors) maintain the same structure with both formats
- Test that authentication, timing metadata, and field mappings work correctly with both formats
