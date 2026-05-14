# Implementation Plan

- [x] 1. Write bug condition exploration test
  - **Property 1: Bug Condition** - CCXT Unified Format Acceptance and Binance Format Conversion
  - **CRITICAL**: This test MUST FAIL on unfixed code - failure confirms the bug exists
  - **DO NOT attempt to fix the test or the code when it fails**
  - **NOTE**: This test encodes the expected behavior - it will validate the fix when it passes after implementation
  - **GOAL**: Surface counterexamples that demonstrate the bug exists
  - **Scoped PBT Approach**: Scope the property to concrete failing cases - CCXT unified format (BTC/USDT:USDT) being rejected by validation, and Binance native format (BTCUSDT) failing on ticker and open-interest endpoints
  - Test Scenario 1: CCXT format validation rejection
    - Test that `BTC/USDT:USDT` is rejected by `validate_symbol()` with "Symbol must contain only alphanumeric characters" error
    - Test that ticker endpoint returns 400 error when given `BTC/USDT:USDT`
    - Test that open-interest endpoint returns 400 error when given `BTC/USDT:USDT`
  - Test Scenario 2: Binance format fails on CCXT methods
    - Test that `BTCUSDT` passes validation but ticker endpoint fails with CCXT error (symbol not found)
    - Test that `BTCUSDT` passes validation but open-interest endpoint fails with CCXT error
  - The test assertions should match the Expected Behavior Properties from design (both formats accepted and converted correctly)
  - Run test on UNFIXED code
  - **EXPECTED OUTCOME**: Test FAILS (this is correct - it proves the bug exists)
  - Document counterexamples found to understand root cause
  - Verify root cause by inspecting `src/api/debug_utils.py` validate_symbol() function for `isalnum()` check
  - Verify that no format conversion logic exists in `src/services/debug_exchange_service.py`
  - Mark task complete when test is written, run, and failure is documented
  - _Requirements: 1.1, 1.2, 1.3, 1.4, 2.1, 2.2, 2.3, 2.4, 2.5_

- [x] 2. Write preservation property tests (BEFORE implementing fix)
  - **Property 2: Preservation** - Existing Endpoint Behavior
  - **IMPORTANT**: Follow observation-first methodology
  - Observe behavior on UNFIXED code for funding-rate endpoint with Binance native format (BTCUSDT)
  - Observe behavior on UNFIXED code for long-short-ratio endpoint with Binance native format (BTCUSDT)
  - Observe that invalid symbols (empty strings, special characters like `@#$`, symbols exceeding 20 chars) are rejected with appropriate error messages on unfixed code
  - Observe that error handling (network errors, timeouts, exchange errors) produces the same response structure on unfixed code
  - Write property-based tests capturing observed behavior patterns from Preservation Requirements
  - Property-based testing generates many test cases for stronger guarantees
  - Test that funding-rate endpoint with `BTCUSDT` produces identical results before and after fix
  - Test that long-short-ratio endpoint with `BTCUSDT` produces identical results before and after fix
  - Test that invalid symbols continue to be rejected with the same error messages
  - Test that error response structure (HTTP status codes, error codes, metadata) remains unchanged
  - Test that authentication, timing metadata, and field mappings remain unchanged
  - Run tests on UNFIXED code
  - **EXPECTED OUTCOME**: Tests PASS (this confirms baseline behavior to preserve)
  - Mark task complete when tests are written, run, and passing on unfixed code
  - _Requirements: 3.1, 3.2, 3.3, 3.4_

- [x] 3. Fix for symbol format validation and conversion

  - [x] 3.1 Relax validation to accept CCXT unified format
    - Open `src/api/debug_utils.py` and locate the `validate_symbol()` function
    - Replace the `isalnum()` check with regex pattern `^[A-Za-z0-9/:]+$` to accept `/` and `:` characters
    - Add format validation to ensure symbol matches either:
      - Binance native format: `^[A-Z0-9]+$` (alphanumeric uppercase)
      - CCXT unified format: `^[A-Z0-9]+/[A-Z0-9]+:[A-Z0-9]+$` (BASE/QUOTE:SETTLE)
    - Prevent accepting malformed symbols like `BTC//USDT` or `BTC:USDT/`
    - Keep existing validation for empty strings, whitespace, and max length (20 chars for Binance format, longer for CCXT format)
    - Update error messages to reflect new validation rules
    - _Bug_Condition: isBugCondition(input) where input.symbol MATCHES /[\/:]/ AND validate_symbol(input.symbol) == False_
    - _Expected_Behavior: validate_symbol() should accept both CCXT unified format (BTC/USDT:USDT) and Binance native format (BTCUSDT)_
    - _Preservation: Invalid symbols (empty, malformed, special chars other than / and :) must continue to be rejected_
    - _Requirements: 2.1, 2.4, 3.3_

  - [x] 3.2 Add symbol format detection and conversion functions
    - Open `src/api/debug_utils.py` and add new function `detect_symbol_format(symbol: str) -> str`
    - Return "ccxt" if symbol contains `/` and `:`, otherwise return "binance"
    - Add new function `convert_to_ccxt_format(symbol: str) -> str`
    - Convert Binance native format to CCXT unified format:
      - Pattern: Split at `USDT` suffix → `BTC` + `/USDT:USDT`
      - Handle edge cases: USDTUSDT, BUSDUSDT, etc.
    - Add new function `convert_to_binance_format(symbol: str) -> str`
    - Convert CCXT unified format to Binance native format:
      - Pattern: Remove `/` and everything after `:` → `BTCUSDT`
    - Add new function `ensure_ccxt_format(symbol: str) -> str`
    - If symbol is already in CCXT format, return as-is
    - If symbol is in Binance format, convert to CCXT format
    - _Bug_Condition: No format conversion logic exists, causing Binance format to fail on CCXT methods_
    - _Expected_Behavior: Automatic conversion between formats based on input and endpoint requirements_
    - _Preservation: No impact on existing functionality as these are new functions_
    - _Requirements: 2.2, 2.3, 2.5_

  - [x] 3.3 Apply format conversion in ticker endpoint
    - Open `src/services/debug_exchange_service.py` and locate the `fetch_raw_ticker()` method
    - After validation and normalization, add format conversion:
      ```python
      normalized_symbol = normalize_symbol(symbol)
      ccxt_symbol = ensure_ccxt_format(normalized_symbol)
      raw_data = await self.exchange.fetch_ticker(ccxt_symbol)
      ```
    - Import the new `ensure_ccxt_format()` function from debug_utils
    - Handle any conversion errors gracefully
    - _Bug_Condition: fetch_ticker() fails when given Binance native format_
    - _Expected_Behavior: fetch_ticker() should work with both formats via automatic conversion_
    - _Preservation: Existing behavior with CCXT format (if it worked) should remain unchanged_
    - _Requirements: 2.2, 2.5_

  - [x] 3.4 Apply format conversion in open-interest endpoint
    - Open `src/services/debug_exchange_service.py` and locate the `fetch_raw_open_interest()` method
    - After validation and normalization, add format conversion:
      ```python
      normalized_symbol = normalize_symbol(symbol)
      ccxt_symbol = ensure_ccxt_format(normalized_symbol)
      raw_data = await self.exchange.fetch_open_interest(ccxt_symbol)
      ```
    - Import the new `ensure_ccxt_format()` function from debug_utils
    - Handle any conversion errors gracefully
    - _Bug_Condition: fetch_open_interest() fails when given Binance native format_
    - _Expected_Behavior: fetch_open_interest() should work with both formats via automatic conversion_
    - _Preservation: Existing behavior should remain unchanged_
    - _Requirements: 2.3, 2.5_

  - [x] 3.5 Verify funding-rate and long-short-ratio endpoints remain unchanged
    - Open `src/services/debug_exchange_service.py` and verify `fetch_raw_funding_rate()` method
    - Confirm that no changes are needed (CCXT handles format internally)
    - Verify `fetch_raw_long_short_ratio()` method
    - Confirm that existing market lookup conversion logic remains unchanged
    - Add comments documenting that these endpoints already handle format correctly
    - _Bug_Condition: Not applicable - these endpoints don't have the bug_
    - _Expected_Behavior: These endpoints should continue to work exactly as before_
    - _Preservation: No changes to these endpoints_
    - _Requirements: 3.1, 3.2_

  - [x] 3.6 Update aggregated endpoint to handle both formats
    - Open `src/services/debug_exchange_service.py` and locate the `fetch_all_raw_data()` method
    - Verify that format conversion is applied before calling individual fetch methods
    - Since individual methods now handle conversion, no changes should be needed
    - Test that aggregated endpoint works with both CCXT and Binance formats
    - _Bug_Condition: Aggregated endpoint inherits the bug from individual endpoints_
    - _Expected_Behavior: Aggregated endpoint should work with both formats_
    - _Preservation: Response structure and timing behavior should remain unchanged_
    - _Requirements: 2.5_

  - [x] 3.7 Verify bug condition exploration test now passes
    - **Property 1: Expected Behavior** - CCXT Unified Format Acceptance and Binance Format Conversion
    - **IMPORTANT**: Re-run the SAME test from task 1 - do NOT write a new test
    - The test from task 1 encodes the expected behavior
    - When this test passes, it confirms the expected behavior is satisfied
    - Run bug condition exploration test from step 1
    - Verify that `BTC/USDT:USDT` is accepted by validation and works on all endpoints
    - Verify that `BTCUSDT` is accepted by validation and works on ticker and open-interest endpoints (with automatic conversion)
    - Verify that both formats work on funding-rate and long-short-ratio endpoints
    - Verify that aggregated endpoint works with both formats
    - **EXPECTED OUTCOME**: Test PASSES (confirms bug is fixed)
    - _Requirements: 2.1, 2.2, 2.3, 2.4, 2.5_

  - [x] 3.8 Verify preservation tests still pass
    - **Property 2: Preservation** - Existing Endpoint Behavior
    - **IMPORTANT**: Re-run the SAME tests from task 2 - do NOT write new tests
    - Run preservation property tests from step 2
    - Verify that funding-rate endpoint with `BTCUSDT` produces identical results before and after fix
    - Verify that long-short-ratio endpoint with `BTCUSDT` produces identical results before and after fix
    - Verify that invalid symbols continue to be rejected with the same error messages
    - Verify that error response structure (HTTP status codes, error codes, metadata) remains unchanged
    - Verify that authentication, timing metadata, and field mappings remain unchanged
    - **EXPECTED OUTCOME**: Tests PASS (confirms no regressions)
    - Confirm all tests still pass after fix (no regressions)
    - _Requirements: 3.1, 3.2, 3.3, 3.4_

- [x] 4. Checkpoint - Ensure all tests pass
  - Run all bug condition exploration tests and verify they pass
  - Run all preservation property tests and verify they pass
  - Run any existing unit tests and integration tests to ensure no regressions
  - Verify that all debug endpoints accept both CCXT unified format and Binance native format
  - Verify that format conversion works correctly for ticker and open-interest endpoints
  - Verify that funding-rate and long-short-ratio endpoints continue to work as before
  - Verify that invalid symbols are still rejected with appropriate error messages
  - If any tests fail, investigate and fix the issues before proceeding
  - Ask the user if questions arise
