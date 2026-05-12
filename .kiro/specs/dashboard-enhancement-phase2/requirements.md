# Requirements Document

## Introduction

This document specifies the requirements for Dashboard Enhancement Phase 2 of the Crypto Screener System. This phase adds four new contextual metrics to the existing dashboard to make it more actionable for futures traders: ATR (Average True Range) for risk context, Distance to MA50 for price context, Sparkline Trend for time context, and Open Interest Delta for market context. The implementation is divided into two sub-phases: Phase 2a (ATR + Distance to MA50) for low-effort, high-impact improvements, and Phase 2b (Sparkline + OI Delta) for medium-effort, transformative value additions.

## Glossary

- **Screener_System**: The complete cryptocurrency asset screening application
- **Data_Fetcher**: The component responsible for fetching market data from Binance USDT-M Futures via CCXT
- **Visualization_Dashboard**: The static graphical representation of screening results using matplotlib/seaborn
- **ATR**: Average True Range - a volatility indicator measuring the average range between high and low prices over a specified period
- **ATR_Panel**: The visualization panel displaying ATR values with volatility-based color coding
- **MA50**: 50-day Simple Moving Average - the average closing price over the last 50 trading days
- **Distance_To_MA50**: The percentage difference between current price and the 50-day moving average
- **MA50_Panel**: The visualization panel displaying distance to MA50 with directional color coding
- **Sparkline**: A small, inline line chart showing price trend over a short time period
- **Sparkline_Panel**: The visualization panel displaying mini trend charts for each asset
- **Open_Interest**: The total number of outstanding derivative contracts that have not been settled
- **OI_Delta**: The 24-hour percentage change in Open Interest
- **OI_Delta_Panel**: The visualization panel displaying Open Interest changes with market context interpretation
- **OI_Interpretation**: The market context classification based on OI_Delta and price direction combination
- **OHLCV_Data**: Open, High, Low, Close, Volume candlestick data used for technical calculations
- **Binance_Futures_API**: The Binance USDT-M Futures API accessed via CCXT library
- **Asset_Symbol**: The ticker symbol identifying a cryptocurrency asset (e.g., BTC/USDT:USDT)
- **True_Range**: The maximum of (High - Low), |High - Previous Close|, or |Low - Previous Close| for a single period

## Requirements

### Requirement 1: ATR Data Calculation

**User Story:** As a futures trader, I want to see the Average True Range for each asset, so that I can estimate ideal Stop Loss distances and understand current volatility levels.

#### Acceptance Criteria

1. THE Data_Fetcher SHALL calculate a 14-period daily ATR for each Asset_Symbol using OHLCV_Data
2. WHEN calculating ATR, THE Data_Fetcher SHALL fetch at least 15 daily OHLCV candles to compute the 14-period average
3. THE Data_Fetcher SHALL calculate True Range as the maximum of: (High - Low), |High - Previous Close|, |Low - Previous Close|
4. THE Data_Fetcher SHALL calculate ATR as the 14-period simple moving average of True Range values
5. IF OHLCV_Data fetch fails due to API error, timeout, or returns an empty response for an Asset_Symbol, THEN THE Data_Fetcher SHALL set ATR to null and continue processing other assets
6. THE Data_Fetcher SHALL calculate ATR percentage as (ATR / closing price of most recent candle) * 100 for cross-asset comparison
7. IF fewer than 15 OHLCV candles are returned for an Asset_Symbol, THEN THE Data_Fetcher SHALL set ATR to null for that asset

### Requirement 2: ATR Visualization Panel

**User Story:** As a futures trader, I want to see ATR displayed with volatility-based color coding, so that I can quickly identify high-risk and low-risk trading opportunities.

#### Acceptance Criteria

1. THE ATR_Panel SHALL display ATR percentage values as horizontal bars with the X-axis scaled from 0% to the maximum ATR value in the dataset
2. THE ATR_Panel SHALL order Asset_Symbol entries consistently with the Multi_Factor_Score ranking
3. IF ATR percentage is less than 3.00%, THEN THE ATR_Panel SHALL render the bar in green indicating low volatility
4. IF ATR percentage is greater than or equal to 3.00% and less than or equal to 6.00%, THEN THE ATR_Panel SHALL render the bar in yellow indicating medium volatility
5. IF ATR percentage is greater than 6.00%, THEN THE ATR_Panel SHALL render the bar in red indicating high volatility
6. THE ATR_Panel SHALL display numeric ATR percentage values on each bar formatted to 2 decimal places
7. THE ATR_Panel SHALL include a title containing "ATR" and a volatility risk indication
8. IF ATR percentage data is unavailable or invalid for an Asset_Symbol, THEN THE ATR_Panel SHALL display a placeholder bar with text indicating data unavailable

### Requirement 3: Distance to MA50 Data Calculation

**User Story:** As a futures trader, I want to see how far the current price is from the 50-day moving average, so that I can avoid entering at extended prices.

#### Acceptance Criteria

1. THE Data_Fetcher SHALL calculate the 50-day Simple Moving Average for each Asset_Symbol using the closing price from OHLCV_Data
2. WHEN calculating MA50, THE Data_Fetcher SHALL fetch 50 daily OHLCV candles
3. IF fewer than 50 daily OHLCV candles are available for an Asset_Symbol, THEN THE Data_Fetcher SHALL set Distance_To_MA50 to null for that asset
4. THE Data_Fetcher SHALL calculate Distance_To_MA50 as: ((Current_Price - MA50) / MA50) * 100, where Current_Price is the most recent trade price from ticker data, resulting in a positive value when price is above MA50 and a negative value when price is below MA50
5. WHEN OHLCV_Data is unavailable for an Asset_Symbol, THE Data_Fetcher SHALL set Distance_To_MA50 to null and continue processing other assets

### Requirement 4: Distance to MA50 Visualization Panel

**User Story:** As a futures trader, I want to see the distance to MA50 with directional color coding, so that I can quickly identify overextended or undervalued assets.

#### Acceptance Criteria

1. THE MA50_Panel SHALL display Distance_To_MA50 percentage values as horizontal bars
2. THE MA50_Panel SHALL order Asset_Symbol entries consistently with the Multi_Factor_Score ranking
3. WHEN Distance_To_MA50 is positive, THE MA50_Panel SHALL render the bar in green indicating bullish price position
4. WHEN Distance_To_MA50 is negative, THE MA50_Panel SHALL render the bar in red indicating bearish price position
5. WHEN Distance_To_MA50 is exactly zero, THE MA50_Panel SHALL render no bar and display the numeric value at the zero reference line
6. THE MA50_Panel SHALL render a vertical reference line at 0% indicating price at MA50
7. THE MA50_Panel SHALL display numeric Distance_To_MA50 percentage values on each bar rounded to 2 decimal places
8. THE MA50_Panel SHALL include a title containing the text "Distance to MA50" and indicating price position relative to the 50-day moving average

### Requirement 5: Sparkline Trend Data Calculation

**User Story:** As a futures trader, I want to see a mini price chart for each asset, so that I can visually confirm momentum direction at a glance.

#### Acceptance Criteria

1. THE Data_Fetcher SHALL fetch hourly OHLCV_Data for the last 24 hours for each Asset_Symbol, retrieving 24 data points
2. THE Data_Fetcher SHALL extract closing prices from the hourly OHLCV_Data to create sparkline data points
3. IF hourly OHLCV_Data fetch returns an empty result or throws an exception for an Asset_Symbol, THEN THE Data_Fetcher SHALL fall back to 4-hour candles for the last 7 days, retrieving 42 data points
4. THE Data_Fetcher SHALL determine trend direction by comparing the first and last closing price values in the sparkline data
5. WHEN the last closing price is higher than the first closing price, THE trend SHALL be classified as uptrend
6. WHEN the last closing price is lower than or equal to the first closing price, THE trend SHALL be classified as downtrend
7. IF fewer than 2 data points are retrieved from both hourly and fallback timeframes for an Asset_Symbol, THEN THE Data_Fetcher SHALL set sparkline data to null and trend direction to null
8. IF both hourly and 4-hour OHLCV_Data fetches fail for an Asset_Symbol, THEN THE Data_Fetcher SHALL set sparkline data to null and continue processing other assets

### Requirement 6: Sparkline Trend Visualization Panel

**User Story:** As a futures trader, I want to see mini trend charts next to each asset's metrics, so that I can visually confirm momentum direction.

#### Acceptance Criteria

1. THE Sparkline_Panel SHALL display a mini line chart for each Asset_Symbol showing price trend over the most recent 24-hour period
2. THE Sparkline_Panel SHALL order Asset_Symbol entries consistently with the Multi_Factor_Score ranking
3. WHEN the last price in the sparkline data is greater than the first price, THE Sparkline_Panel SHALL render the line in green to indicate uptrend
4. WHEN the last price in the sparkline data is less than the first price, THE Sparkline_Panel SHALL render the line in red to indicate downtrend
5. WHEN the last price in the sparkline data equals the first price, THE Sparkline_Panel SHALL render the line in a neutral color distinct from green and red
6. THE Sparkline_Panel SHALL normalize sparkline data to fit within a consistent vertical space for each asset using min-max scaling across each asset's price range
7. THE Sparkline_Panel SHALL include a descriptive title indicating sparkline content and time context
8. WHEN sparkline data is unavailable for an Asset_Symbol, THE Sparkline_Panel SHALL display a text indicator stating data is unavailable in place of the chart

### Requirement 7: Open Interest Delta Data Calculation

**User Story:** As a futures trader, I want to see the 24-hour change in Open Interest, so that I can understand whether new money is entering or exiting positions.

#### Acceptance Criteria

1. THE Data_Fetcher SHALL fetch current Open_Interest from Binance_Futures_API for each Asset_Symbol
2. THE Data_Fetcher SHALL fetch Open_Interest from 24 hours ago (±5 minutes tolerance based on API data availability) for each Asset_Symbol
3. IF OI_24h_Ago equals zero, THEN THE Data_Fetcher SHALL set OI_Delta to null for that Asset_Symbol
4. IF OI_24h_Ago is greater than zero, THEN THE Data_Fetcher SHALL calculate OI_Delta as: ((Current_OI - OI_24h_Ago) / OI_24h_Ago) * 100, rounded to 2 decimal places
5. WHEN OI_Delta is greater than zero and change_24h is greater than zero, THE Data_Fetcher SHALL set OI_Interpretation to "strong_bullish" indicating new money entering longs
6. WHEN OI_Delta is less than zero and change_24h is greater than zero, THE Data_Fetcher SHALL set OI_Interpretation to "weak_bullish" indicating short covering
7. WHEN OI_Delta is greater than zero and change_24h is less than zero, THE Data_Fetcher SHALL set OI_Interpretation to "strong_bearish" indicating new money entering shorts
8. WHEN OI_Delta is less than zero and change_24h is less than zero, THE Data_Fetcher SHALL set OI_Interpretation to "weak_bearish" indicating long liquidation
9. WHEN OI_Delta equals zero or change_24h equals zero, THE Data_Fetcher SHALL set OI_Interpretation to "neutral"
10. WHEN Open_Interest data is unavailable for an Asset_Symbol, THE Data_Fetcher SHALL set OI_Delta to null, set OI_Interpretation to null, and continue processing other assets

### Requirement 8: Open Interest Delta Visualization Panel

**User Story:** As a futures trader, I want to see OI Delta with market context interpretation, so that I can make informed decisions about position strength.

#### Acceptance Criteria

1. THE OI_Delta_Panel SHALL display OI_Delta percentage values as horizontal bars
2. THE OI_Delta_Panel SHALL order Asset_Symbol entries consistently with the Multi_Factor_Score ranking
3. WHEN OI_Delta is greater than 0%, THE OI_Delta_Panel SHALL render the bar in blue indicating new positions opening
4. WHEN OI_Delta is less than 0%, THE OI_Delta_Panel SHALL render the bar in orange indicating positions closing
5. WHEN OI_Delta is exactly 0%, THE OI_Delta_Panel SHALL render the bar in a neutral gray color indicating no change
6. THE OI_Delta_Panel SHALL render a vertical reference line at 0% indicating no change in Open Interest
7. THE OI_Delta_Panel SHALL display numeric OI_Delta percentage values rounded to 1 decimal place at the end of each bar
8. THE OI_Delta_Panel SHALL include a title containing the text "OI Delta" and a brief market context description
9. WHEN OI_Delta data is null or unavailable for an Asset_Symbol, THE OI_Delta_Panel SHALL display a placeholder bar with a label indicating data unavailable

### Requirement 9: Dashboard Layout Enhancement

**User Story:** As a futures trader, I want all new panels integrated into the existing dashboard, so that I can view all metrics in a single comprehensive view.

#### Acceptance Criteria

1. THE Visualization_Dashboard SHALL display seven horizontal bar chart panels in a single figure arranged vertically in the following order from top to bottom: Multi-Factor Score, Funding Rate, Long/Short Ratio, ATR, Distance to MA50, Sparkline Trend, OI Delta
2. THE Visualization_Dashboard SHALL maintain the existing three panels: Multi-Factor Score, Funding Rate, Long/Short Ratio
3. THE Visualization_Dashboard SHALL add four new panels: ATR, Distance to MA50, Sparkline Trend, OI Delta
4. THE Visualization_Dashboard SHALL use a shared Y-axis across all panels displaying Asset_Symbol values
5. THE Visualization_Dashboard SHALL order Asset_Symbol entries consistently across all panels based on Multi_Factor_Score ranking in descending order with highest scores at the top
6. THE Visualization_Dashboard SHALL use a figure height of at least 18 inches to accommodate seven panels with a minimum bar height of 0.4 inches per asset and font size of at least 9 points for axis labels
7. THE Visualization_Dashboard SHALL render as a static image that can be saved to disk
8. IF any of the four new panel data columns (ATR, Distance to MA50, Sparkline Trend, OI Delta) are missing from the DataFrame, THEN THE Visualization_Dashboard SHALL display a "No data available" message in the corresponding panel and continue rendering the remaining panels

### Requirement 10: Phase 2a Implementation Scope

**User Story:** As a project manager, I want Phase 2a to deliver ATR and Distance to MA50 features first, so that we can achieve quick wins with low effort and high impact.

#### Acceptance Criteria

1. THE Screener_System SHALL calculate ATR (Average True Range) using a 14-period simple moving average of True Range, where True Range for each period is the maximum of: (high minus low), absolute value of (high minus previous close), or absolute value of (low minus previous close)
2. THE Screener_System SHALL calculate Distance to MA50 as the percentage difference between the current closing price and the 50-period simple moving average, using the formula: ((current_close - MA50) / MA50) * 100
3. THE Screener_System SHALL visualize ATR values using a horizontal bar chart panel that displays each asset's ATR value ordered by multi-factor score
4. THE Screener_System SHALL visualize Distance to MA50 values using a horizontal bar chart panel that displays each asset's percentage distance from MA50 ordered by multi-factor score
5. THE Phase 2a implementation SHALL reuse the existing fetch_ohlcv method in Data_Fetcher with the default daily timeframe
6. THE Phase 2a implementation SHALL follow the existing panel class pattern in the visualization module, implementing render methods that accept a matplotlib axes object and a DataFrame
7. IF insufficient OHLCV data is available for ATR calculation (fewer than 15 candles) or MA50 calculation (fewer than 50 candles), THEN THE Screener_System SHALL return a null value for that symbol and log a warning message

### Requirement 11: Phase 2b Implementation Scope

**User Story:** As a project manager, I want Phase 2b to deliver Sparkline and OI Delta features, so that we can add transformative value with medium effort.

#### Acceptance Criteria

1. THE Screener_System SHALL implement Sparkline Trend visualization displaying the most recent 24 data points of hourly price data as a mini line chart within each asset row
2. THE Screener_System SHALL implement OI Delta calculation as the percentage change in Open Interest between the current value and the value from 24 hours prior
3. THE Screener_System SHALL implement OI Delta visualization as a horizontal bar panel following the existing panel class pattern with color coding to distinguish positive delta (increasing OI) from negative delta (decreasing OI)
4. THE Phase 2b implementation SHALL add API endpoint methods to the MarketDataFetcher class for fetching current Open Interest and 24-hour historical Open Interest data per symbol
5. IF Open Interest data is unavailable for a symbol, THEN THE Screener_System SHALL set the OI Delta value to NaN, log a warning with the symbol name, and continue processing remaining symbols
6. THE Phase 2b panel classes SHALL implement a render method accepting matplotlib axes and DataFrame parameters, include column validation, handle empty DataFrames with a "No data available" message, and apply consistent axis labeling

### Requirement 12: Error Handling and Robustness

**User Story:** As a user, I want the system to handle errors gracefully for new metrics, so that partial failures don't crash the entire screening process.

#### Acceptance Criteria

1. WHEN ATR calculation fails for an Asset_Symbol due to an exception or returns a null/NaN result, THE Screener_System SHALL log the error with the Asset_Symbol and error details at ERROR level, and display a horizontal bar placeholder with text indicating data unavailable in the ATR_Panel
2. WHEN Distance_To_MA50 calculation fails for an Asset_Symbol due to an exception or returns a null/NaN result, THE Screener_System SHALL log the error with the Asset_Symbol and error details at ERROR level, and display a horizontal bar placeholder with text indicating data unavailable in the MA50_Panel
3. WHEN Sparkline data fetch fails for an Asset_Symbol due to an exception or returns a null/NaN result, THE Screener_System SHALL log the error with the Asset_Symbol and error details at ERROR level, and display a flat line placeholder with text indicating data unavailable in the Sparkline_Panel
4. WHEN OI_Delta calculation fails for an Asset_Symbol due to an exception or returns a null/NaN result, THE Screener_System SHALL log the error with the Asset_Symbol and error details at ERROR level, and display a horizontal bar placeholder with text indicating data unavailable in the OI_Delta_Panel
5. WHEN all new metric calculations fail for all assets, THE Screener_System SHALL display the original three panels (Multi-Factor Score, Funding Rate, Long/Short Ratio) and render a warning banner at the top of the dashboard indicating that new metric panels could not be loaded
