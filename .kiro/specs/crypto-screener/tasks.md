# Implementation Plan: Crypto Screener System

## Overview

This implementation plan breaks down the crypto screener system into discrete coding tasks. The system will be implemented as a self-contained Python script that fetches market data from OKX exchange via CCXT, generates quantitative trading signals, calculates multi-factor scores, and produces static visualization dashboards with three horizontal bar chart panels.

## Tasks

- [x] 1. Set up project structure and dependencies
  - Create main Python script file `crypto_screener.py`
  - Add dependency validation for required libraries (ccxt, pandas, numpy, matplotlib, seaborn)
  - Set up Python logging configuration with appropriate severity levels
  - Create requirements.txt with pinned versions: ccxt, pandas, numpy, matplotlib, seaborn
  - _Requirements: 1.4, 1.5, 9.4, 10.5_

- [x] 2. Implement exchange connection and data ingestion pipeline
  - [x] 2.1 Create ExchangeConnector class
    - Initialize CCXT OKX exchange instance
    - Implement connect() method with error handling for NetworkError and ExchangeError
    - Implement get_exchange() method to return configured exchange
    - Add validation to ensure Binance is NOT used
    - _Requirements: 1.1, 1.2, 1.3, 10.3_
  
  - [x] 2.2 Create MarketDataFetcher class
    - Implement __init__ with exchange and symbol list parameters
    - Implement fetch_ticker_data() to extract price and 24h change from CCXT ticker
    - Implement fetch_funding_rate() to extract funding rate percentage
    - Implement fetch_long_short_ratio() with OKX-specific API or simulation
    - Add inline comments documenting CCXT endpoint mapping for each data field
    - _Requirements: 2.1, 2.3, 2.4, 2.5, 2.6, 9.1_
  
  - [x] 2.3 Implement fetch_all_data() method with error handling
    - Loop through symbol list: ['ZEC/USDT:USDT', 'TAO/USDT:USDT', 'TON/USDT:USDT', 'AAVE/USDT:USDT', 'SOL/USDT:USDT']
    - Catch exceptions per-symbol and log warnings
    - Set null/NaN values for failed fetches and continue processing
    - Return pandas DataFrame with columns: symbol, price, change_24h, funding_rate, long_short_ratio
    - _Requirements: 2.2, 2.7, 10.1, 10.2_
  
  - [ ]* 2.4 Write property test for data ingestion graceful handling
    - **Property 7: Missing Data Graceful Handling**
    - **Validates: Requirements 2.7, 10.2**
    - Use hypothesis to generate DataFrames with random NaN patterns in optional fields
    - Verify pipeline completes without exceptions

- [x] 3. Implement signal processing engine
  - [x] 3.1 Create SignalGenerator class
    - Implement calculate_reversal_signal() using simulated logic: -1 * change_24h
    - Implement calculate_momentum_signal() using simulated logic with random factor
    - Implement normalize_signal() with z-score normalization: (x - mean) / std
    - Handle edge cases: empty DataFrame, single asset, zero variance
    - Add inline comments explaining simulated signal logic
    - _Requirements: 3.1, 3.2, 3.5, 9.3_
  
  - [ ]* 3.2 Write property test for signal generation completeness
    - **Property 1: Signal Generation Completeness**
    - **Validates: Requirements 3.1, 3.2**
    - Use hypothesis to generate random DataFrames with 1-100 assets
    - Verify no exceptions raised and output length matches input
  
  - [ ]* 3.3 Write property test for signal normalization correctness
    - **Property 2: Signal Normalization Correctness**
    - **Validates: Requirements 3.5**
    - Use hypothesis to generate random signal series
    - Verify mean ≈ 0 and std ≈ 1 within floating point tolerance
  
  - [x] 3.4 Create ICWeightCalculator class
    - Initialize with simulated IC weights: {'reversal_1d': 0.3, 'momentum_30d': 0.7}
    - Implement get_weight() method to return weight for signal name
    - _Requirements: 3.3_
  
  - [x] 3.5 Create MultiFactorScorer class
    - Implement calculate_score() to compute weighted combination: w1 * signal1 + w2 * signal2
    - Implement classify_tiers() to assign Tier A (top 50%) and Tier B (bottom 50%)
    - _Requirements: 3.4, 4.3_
  
  - [ ]* 3.6 Write property test for multi-factor score calculation
    - **Property 3: Multi-Factor Score Calculation**
    - **Validates: Requirements 3.3, 3.4**
    - Use hypothesis to generate random signals and weights
    - Verify score equals manual weighted sum calculation
  
  - [ ]* 3.7 Write property test for tier classification consistency
    - **Property 6: Tier Classification Consistency**
    - **Validates: Requirements 4.3**
    - Use hypothesis to generate random score distributions
    - Verify each asset has exactly one tier and higher scores get 'A'

- [x] 4. Implement ranking engine
  - [x] 4.1 Create RankingEngine class
    - Implement rank_assets() to sort DataFrame by multi_factor_score descending
    - Use stable sort to preserve relative order for equal scores
    - Add rank column with position numbers (1 = highest)
    - _Requirements: 4.1, 4.2, 4.4_
  
  - [ ]* 4.2 Write property test for ranking order preservation
    - **Property 4: Ranking Order Preservation**
    - **Validates: Requirements 4.1**
    - Use hypothesis to generate random DataFrames with random scores
    - Verify output is sorted descending (score[i] >= score[i+1] for all pairs)
  
  - [ ]* 4.3 Write property test for stable sort preservation
    - **Property 5: Stable Sort Preservation**
    - **Validates: Requirements 4.2**
    - Use hypothesis to generate DataFrames with intentional duplicate scores
    - Verify assets with equal scores maintain original relative order

- [x] 5. Checkpoint - Verify core data pipeline
  - Ensure all tests pass, ask the user if questions arise.

- [x] 6. Implement visualization components
  - [x] 6.1 Create MultiFactorPanel class
    - Implement render() method to create horizontal bar chart
    - Set Y-axis to asset symbols ordered by score
    - Set X-axis to multi-factor score values
    - Apply color #C85A82 for Tier A, lighter shade for Tier B
    - Display numeric score values on bars
    - Add descriptive panel title
    - Add inline comments explaining visualization logic
    - _Requirements: 6.1, 6.2, 6.3, 6.4, 6.5, 9.2_
  
  - [ ]* 6.2 Write property test for tier-based color mapping
    - **Property 9: Tier-Based Color Mapping**
    - **Validates: Requirements 6.2, 6.3**
    - Use hypothesis to generate DataFrames with mixed tier classifications
    - Extract bar colors and verify Tier A uses #C85A82, Tier B uses lighter shade
  
  - [x] 6.3 Create FundingRatePanel class
    - Implement render() method to create horizontal bar chart
    - Set Y-axis to asset symbols (same order as multi-factor panel)
    - Set X-axis to funding rate percentage
    - Add vertical reference line at 0%
    - Apply green/blue color for negative rates, red/orange for positive rates
    - Add descriptive panel title
    - Add inline comments explaining visualization logic
    - _Requirements: 7.1, 7.2, 7.3, 7.4, 7.5, 9.2_
  
  - [ ]* 6.4 Write property test for sign-based funding rate color mapping
    - **Property 10: Sign-Based Funding Rate Color Mapping**
    - **Validates: Requirements 7.3, 7.4**
    - Use hypothesis to generate DataFrames with positive and negative funding rates
    - Extract bar colors and verify negative values use one color scheme, positive use another
  
  - [x] 6.5 Create LongShortRatioPanel class
    - Implement render() method to create horizontal bar chart
    - Set Y-axis to asset symbols (same order as multi-factor panel)
    - Set X-axis to long/short ratio
    - Add vertical reference lines at 1.0 (neutral) and 1.5 (warning)
    - Apply highlighting to bars exceeding 1.5 threshold
    - Add descriptive panel title
    - Add inline comments explaining visualization logic
    - _Requirements: 8.1, 8.2, 8.3, 8.4, 8.5, 9.2_
  
  - [ ]* 6.6 Write property test for threshold-based long/short highlighting
    - **Property 11: Threshold-Based Long/Short Highlighting**
    - **Validates: Requirements 8.4**
    - Use hypothesis to generate DataFrames with ratios above and below 1.5
    - Extract bar colors/styles and verify ratios >1.5 are highlighted

- [x] 7. Implement dashboard builder
  - [x] 7.1 Create DashboardBuilder class
    - Implement __init__ to accept ranked DataFrame
    - Implement create_dashboard() to create 3-panel figure with shared Y-axis
    - Use matplotlib subplots with vertical stack layout
    - Call render() methods for all three panels
    - Apply tight_layout() for proper spacing
    - Implement save_dashboard() to save figure to disk
    - _Requirements: 5.1, 5.2, 5.4, 5.5_
  
  - [ ]* 7.2 Write property test for visualization order consistency
    - **Property 8: Visualization Order Consistency**
    - **Validates: Requirements 5.3**
    - Use hypothesis to generate random ranked DataFrames
    - Extract y-axis labels from all 3 panels and verify they are identical

- [x] 8. Implement main orchestrator and error handling
  - [x] 8.1 Create main() function
    - Define symbol list: ['ZEC/USDT:USDT', 'TAO/USDT:USDT', 'TON/USDT:USDT', 'AAVE/USDT:USDT', 'SOL/USDT:USDT']
    - Initialize ExchangeConnector and establish connection
    - Create MarketDataFetcher and fetch all data
    - Create SignalGenerator and generate signals
    - Create ICWeightCalculator and MultiFactorScorer
    - Calculate multi-factor scores and classify tiers
    - Create RankingEngine and rank assets
    - Create DashboardBuilder and generate visualization
    - Save dashboard to disk with timestamp in filename
    - Wrap each stage in try-except blocks with appropriate error handling
    - _Requirements: 9.4, 9.5_
  
  - [x] 8.2 Add comprehensive error handling
    - Catch ccxt.NetworkError and ccxt.ExchangeError during connection
    - Log descriptive error messages with exchange name and details
    - Handle visualization rendering failures with descriptive messages
    - Validate required libraries are available before main logic
    - _Requirements: 1.3, 10.1, 10.3, 10.4, 10.5_
  
  - [ ]* 8.3 Write unit tests for error handling scenarios
    - Test connection failure error message format
    - Test exchange unavailability error message
    - Test visualization rendering failure error message
    - Test dependency validation with missing libraries
    - Mock CCXT exceptions to avoid real API calls

- [x] 9. Final checkpoint and integration verification
  - Ensure all tests pass, ask the user if questions arise.

## Notes

- Tasks marked with `*` are optional and can be skipped for faster MVP
- Each task references specific requirements for traceability
- The system uses simulated IC weights and signal logic as a framework for future real quantitative models
- All property tests should use hypothesis library with minimum 100 iterations
- Property test tags follow format: `# Feature: crypto-screener, Property {number}: {property_text}`
- Error handling ensures graceful degradation - missing data for individual assets does not halt processing
- Visualization uses matplotlib/seaborn for static chart generation
- The complete system is implemented as a single self-contained Python script

## Task Dependency Graph

```json
{
  "waves": [
    { "id": 0, "tasks": ["1"] },
    { "id": 1, "tasks": ["2.1"] },
    { "id": 2, "tasks": ["2.2"] },
    { "id": 3, "tasks": ["2.3", "2.4"] },
    { "id": 4, "tasks": ["3.1"] },
    { "id": 5, "tasks": ["3.2", "3.3", "3.4"] },
    { "id": 6, "tasks": ["3.5"] },
    { "id": 7, "tasks": ["3.6", "3.7", "4.1"] },
    { "id": 8, "tasks": ["4.2", "4.3"] },
    { "id": 9, "tasks": ["6.1"] },
    { "id": 10, "tasks": ["6.2", "6.3"] },
    { "id": 11, "tasks": ["6.4", "6.5"] },
    { "id": 12, "tasks": ["6.6", "7.1"] },
    { "id": 13, "tasks": ["7.2", "8.1"] },
    { "id": 14, "tasks": ["8.2"] },
    { "id": 15, "tasks": ["8.3"] }
  ]
}
```
