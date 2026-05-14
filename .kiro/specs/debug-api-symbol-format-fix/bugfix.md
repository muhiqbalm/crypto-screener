# Bugfix Requirements Document

## Introduction

The Debug API endpoints currently reject valid CCXT unified symbol format (BTC/USDT:USDT) due to overly restrictive validation, and fail to process Binance native format (BTCUSDT) correctly across all endpoints. This causes inconsistent behavior where some endpoints work with Binance format while others fail, and all endpoints reject the CCXT unified format that should be the standard input format.

The root cause is the `validate_symbol()` function in `src/api/debug_utils.py` which only accepts alphanumeric characters, rejecting the `/` and `:` characters present in CCXT unified format. Additionally, there is no symbol format conversion logic to translate between Binance native format and CCXT unified format based on what each exchange method requires.

## Bug Analysis

### Current Behavior (Defect)

1.1 WHEN a user provides `BTC/USDT:USDT` (CCXT unified format) to any debug endpoint THEN the system returns INVALID_INPUT error "Symbol must contain only alphanumeric characters"

1.2 WHEN a user provides `BTCUSDT` (Binance native format) to the ticker endpoint THEN the system returns INTERNAL_ERROR because fetch_ticker expects CCXT unified format

1.3 WHEN a user provides `BTCUSDT` (Binance native format) to the openInterest endpoint THEN the system returns INTERNAL_ERROR because fetch_open_interest expects CCXT unified format

1.4 WHEN the validation function receives a symbol containing `/` or `:` characters THEN the system rejects it before reaching CCXT processing

### Expected Behavior (Correct)

2.1 WHEN a user provides `BTC/USDT:USDT` (CCXT unified format) to any debug endpoint THEN the system SHALL accept it as valid input and process it correctly

2.2 WHEN a user provides `BTCUSDT` (Binance native format) to the ticker endpoint THEN the system SHALL convert it to CCXT unified format and successfully call fetch_ticker

2.3 WHEN a user provides `BTCUSDT` (Binance native format) to the openInterest endpoint THEN the system SHALL convert it to CCXT unified format and successfully call fetch_open_interest

2.4 WHEN the validation function receives a symbol containing `/` or `:` characters THEN the system SHALL accept it as valid CCXT unified format

2.5 WHEN a user provides either `BTCUSDT` or `BTC/USDT:USDT` format THEN the system SHALL automatically convert to the correct format required by each specific exchange method

### Unchanged Behavior (Regression Prevention)

3.1 WHEN a user provides `BTCUSDT` (Binance native format) to the fundingRate endpoint THEN the system SHALL CONTINUE TO process it successfully

3.2 WHEN a user provides `BTCUSDT` (Binance native format) to the longShortRatio endpoint THEN the system SHALL CONTINUE TO process it successfully

3.3 WHEN the system receives invalid symbols (empty strings, special characters other than `/` and `:`, malformed formats) THEN the system SHALL CONTINUE TO reject them with appropriate error messages

3.4 WHEN the system successfully processes a valid request THEN the system SHALL CONTINUE TO return the same response structure and data format
