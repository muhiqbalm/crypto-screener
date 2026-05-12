# Implementation Tasks

## Task 1: Phase 2a - ATR Data Calculation
- [x] 1.1 Add `calculate_atr()` method to `MarketDataFetcher` class in `src/data/fetcher.py`
  - [x] 1.1.1 Implement True Range calculation: max(High-Low, |High-PrevClose|, |Low-PrevClose|)
  - [x] 1.1.2 Implement 14-period SMA of True Range values
  - [x] 1.1.3 Calculate ATR percentage as (ATR / current_price) * 100
  - [x] 1.1.4 Return dict with atr_value, atr_percent, and volatility_level ('low'/'medium'/'high')
  - [x] 1.1.5 Handle insufficient data (< 15 candles) by returning null values
  - [x] 1.1.6 Add error handling for OHLCV fetch failures

## Task 2: Phase 2a - Distance to MA50 Data Calculation
- [x] 2.1 Add `calculate_distance_to_ma50()` method to `MarketDataFetcher` class
  - [x] 2.1.1 Fetch 50 daily OHLCV candles using existing `fetch_ohlcv()` method
  - [x] 2.1.2 Calculate 50-day SMA from closing prices
  - [x] 2.1.3 Get current price from ticker data
  - [x] 2.1.4 Calculate distance as ((current_price - MA50) / MA50) * 100
  - [x] 2.1.5 Return dict with ma50, current_price, distance_percent, and position ('above'/'below')
  - [x] 2.1.6 Handle insufficient data (< 50 candles) by returning null values

## Task 3: Phase 2a - ATR Visualization Panel
- [x] 3.1 Create `ATRPanel` class in `src/visualization/panels.py`
  - [x] 3.1.1 Implement `render(ax, df)` method following existing panel pattern
  - [x] 3.1.2 Create horizontal bar chart with Y-axis showing symbols ordered by multi-factor score
  - [x] 3.1.3 Implement color coding: green (< 3%), yellow (3-6%), red (> 6%)
  - [x] 3.1.4 Display numeric ATR percentage values on each bar (2 decimal places)
  - [x] 3.1.5 Add panel title "ATR (Volatility Risk)"
  - [x] 3.1.6 Handle missing/null ATR data with placeholder text
  - [x] 3.1.7 Add column validation for required 'atr_percent' column

## Task 4: Phase 2a - MA50 Distance Visualization Panel
- [x] 4.1 Create `MA50Panel` class in `src/visualization/panels.py`
  - [x] 4.1.1 Implement `render(ax, df)` method following existing panel pattern
  - [x] 4.1.2 Create horizontal bar chart with Y-axis showing symbols ordered by multi-factor score
  - [x] 4.1.3 Implement color coding: green (positive), red (negative)
  - [x] 4.1.4 Add vertical reference line at 0% (price at MA50)
  - [x] 4.1.5 Display numeric distance percentage values on each bar (2 decimal places)
  - [x] 4.1.6 Add panel title "Distance to MA50 (Price Context)"
  - [x] 4.1.7 Handle missing/null distance data with placeholder text

## Task 5: Phase 2a - Dashboard Builder Update (5 Panels)
- [x] 5.1 Update `DashboardBuilder` class in `src/visualization/dashboard.py`
  - [x] 5.1.1 Import new `ATRPanel` and `MA50Panel` classes
  - [x] 5.1.2 Update `create_dashboard()` to create 5 subplots instead of 3
  - [x] 5.1.3 Increase figure height from 10 to 14 inches for 5 panels
  - [x] 5.1.4 Add ATR panel rendering at axes[3] with error handling
  - [x] 5.1.5 Add MA50 panel rendering at axes[4] with error handling
  - [x] 5.1.6 Update column validation to include optional new columns
  - [x] 5.1.7 Display "No data available" message for panels with missing data

## Task 6: Phase 2a - Data Fetcher Integration
- [x] 6.1 Update `fetch_all_data()` method in `MarketDataFetcher`
  - [x] 6.1.1 Add ATR calculation call for each symbol with error handling
  - [x] 6.1.2 Add MA50 distance calculation call for each symbol with error handling
  - [x] 6.1.3 Add 'atr_percent' column to output DataFrame
  - [x] 6.1.4 Add 'distance_to_ma50' column to output DataFrame
  - [x] 6.1.5 Log warnings for symbols with calculation failures

## Task 7: Phase 2a - Unit Tests
- [x] 7.1 Create tests for ATR calculation in `tests/unit/test_atr.py`
  - [x] 7.1.1 Test True Range calculation with known values
  - [x] 7.1.2 Test ATR SMA calculation with known values
  - [x] 7.1.3 Test ATR percentage conversion
  - [x] 7.1.4 Test volatility level classification thresholds
  - [x] 7.1.5 Test insufficient data handling (< 15 candles)
- [x] 7.2 Create tests for MA50 calculation in `tests/unit/test_ma50.py`
  - [x] 7.2.1 Test MA50 SMA calculation with known values
  - [x] 7.2.2 Test distance percentage calculation (positive and negative)
  - [x] 7.2.3 Test position classification ('above'/'below')
  - [x] 7.2.4 Test insufficient data handling (< 50 candles)
- [x] 7.3 Create tests for new panels in `tests/unit/test_new_panels.py`
  - [x] 7.3.1 Test ATRPanel rendering with valid data
  - [x] 7.3.2 Test ATRPanel color thresholds
  - [x] 7.3.3 Test MA50Panel rendering with valid data
  - [x] 7.3.4 Test MA50Panel reference line at 0%
  - [x] 7.3.5 Test panels with missing data columns

## Task 8: Phase 2b - Sparkline Data Calculation
- [x] 8.1 Add `fetch_sparkline_data()` method to `MarketDataFetcher` class
  - [x] 8.1.1 Fetch 24 hourly OHLCV candles using `fetch_ohlcv(symbol, '1h', limit=24)`
  - [x] 8.1.2 Implement fallback to 4-hour candles (42 candles for 7 days) if hourly fails
  - [x] 8.1.3 Extract closing prices as sparkline data points
  - [x] 8.1.4 Determine trend direction by comparing first and last prices
  - [x] 8.1.5 Return dict with prices list, trend ('uptrend'/'downtrend'), timeframe, and change_percent
  - [x] 8.1.6 Handle fetch failures by returning null values

## Task 9: Phase 2b - Open Interest Delta Calculation
- [x] 9.1 Add `fetch_oi_delta()` method to `MarketDataFetcher` class
  - [x] 9.1.1 Implement `_fetch_current_oi()` helper using Binance API: GET /fapi/v1/openInterest
  - [x] 9.1.2 Implement `_fetch_historical_oi()` helper using Binance API: GET /futures/data/openInterestHist
  - [x] 9.1.3 Calculate OI delta as ((current - 24h_ago) / 24h_ago) * 100
  - [x] 9.1.4 Implement interpretation logic based on OI delta + price change combination
  - [x] 9.1.5 Return dict with current_oi, oi_24h_ago, oi_delta_percent, and interpretation
  - [x] 9.1.6 Handle API errors and zero OI_24h_ago (division by zero)

## Task 10: Phase 2b - Sparkline Visualization Panel
- [x] 10.1 Create `SparklinePanel` class in `src/visualization/panels.py`
  - [x] 10.1.1 Implement `render(ax, df)` method following existing panel pattern
  - [x] 10.1.2 Create mini line charts for each asset row
  - [x] 10.1.3 Implement color coding: green (uptrend), red (downtrend), gray (neutral)
  - [x] 10.1.4 Normalize sparkline data using min-max scaling per asset
  - [x] 10.1.5 Add panel title "24h Price Trend (Sparkline)"
  - [x] 10.1.6 Handle missing sparkline data with "No data" text placeholder
  - [x] 10.1.7 Add column validation for 'sparkline_data' and 'sparkline_trend' columns

## Task 11: Phase 2b - OI Delta Visualization Panel
- [x] 11.1 Create `OIDeltaPanel` class in `src/visualization/panels.py`
  - [x] 11.1.1 Implement `render(ax, df)` method following existing panel pattern
  - [x] 11.1.2 Create horizontal bar chart with Y-axis showing symbols ordered by multi-factor score
  - [x] 11.1.3 Implement color coding: blue (positive OI delta), orange (negative), gray (zero)
  - [x] 11.1.4 Add vertical reference line at 0% (no change)
  - [x] 11.1.5 Display numeric OI delta percentage values on each bar (1 decimal place)
  - [x] 11.1.6 Add panel title "OI Delta 24h (Market Context)"
  - [x] 11.1.7 Handle missing/null OI data with placeholder text

## Task 12: Phase 2b - Dashboard Builder Update (7 Panels)
- [x] 12.1 Update `DashboardBuilder` class for 7-panel layout
  - [x] 12.1.1 Import new `SparklinePanel` and `OIDeltaPanel` classes
  - [x] 12.1.2 Update `create_dashboard()` to create 7 subplots
  - [x] 12.1.3 Increase figure height to 18 inches for 7 panels
  - [x] 12.1.4 Add Sparkline panel rendering at axes[5] with error handling
  - [x] 12.1.5 Add OI Delta panel rendering at axes[6] with error handling
  - [x] 12.1.6 Update column validation to include Phase 2b columns
  - [x] 12.1.7 Add warning banner if all new metrics fail

## Task 13: Phase 2b - Data Fetcher Integration
- [x] 13.1 Update `fetch_all_data()` method for Phase 2b metrics
  - [x] 13.1.1 Add sparkline data fetch call for each symbol with error handling
  - [x] 13.1.2 Add OI delta calculation call for each symbol with error handling
  - [x] 13.1.3 Add 'sparkline_data' column to output DataFrame
  - [x] 13.1.4 Add 'sparkline_trend' column to output DataFrame
  - [x] 13.1.5 Add 'oi_delta_percent' column to output DataFrame
  - [x] 13.1.6 Add 'oi_interpretation' column to output DataFrame

## Task 14: Phase 2b - Unit Tests
- [x] 14.1 Create tests for Sparkline in `tests/unit/test_sparkline.py`
  - [x] 14.1.1 Test hourly data fetch
  - [x] 14.1.2 Test 4-hour fallback mechanism
  - [x] 14.1.3 Test trend classification (uptrend/downtrend)
  - [x] 14.1.4 Test with insufficient data points
- [x] 14.2 Create tests for OI Delta in `tests/unit/test_oi_delta.py`
  - [x] 14.2.1 Test OI delta calculation with known values
  - [x] 14.2.2 Test interpretation matrix (all 4 combinations + neutral)
  - [x] 14.2.3 Test zero OI handling (division by zero)
  - [x] 14.2.4 Test API error handling
- [x] 14.3 Create tests for new panels in `tests/unit/test_phase2b_panels.py`
  - [x] 14.3.1 Test SparklinePanel rendering with valid data
  - [x] 14.3.2 Test SparklinePanel color coding
  - [x] 14.3.3 Test OIDeltaPanel rendering with valid data
  - [x] 14.3.4 Test OIDeltaPanel reference line at 0%

## Task 15: Integration Tests
- [x] 15.1 Create integration tests in `tests/integration/test_phase2_pipeline.py`
  - [x] 15.1.1 Test full pipeline with Phase 2a metrics (5-panel dashboard)
  - [x] 15.1.2 Test full pipeline with Phase 2b metrics (7-panel dashboard)
  - [x] 15.1.3 Test graceful degradation when API fails
  - [x] 15.1.4 Test dashboard output file generation
  - [x] 15.1.5 Test with real Binance API (manual smoke test)
