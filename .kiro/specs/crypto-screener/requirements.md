# Requirements Document

## Introduction

This document specifies the requirements for a real-time cryptocurrency asset screener system. The system fetches market data from cryptocurrency exchanges, applies quantitative scoring algorithms to rank assets, and generates static visualization dashboards to support trading decisions. The system is designed for use in regions where certain exchanges are blocked, requiring flexible exchange configuration.

## Glossary

- **Screener_System**: The complete cryptocurrency asset screening application
- **Data_Ingestion_Pipeline**: The component responsible for fetching real-time market data from exchanges
- **CCXT_Library**: A unified cryptocurrency exchange trading library supporting multiple exchanges
- **OKX_Exchange**: The default cryptocurrency exchange used for fetching perpetual futures data
- **Perpetual_Future**: A derivative contract with no expiration date that tracks the spot price of an asset
- **Funding_Rate**: A periodic payment between long and short position holders to keep perpetual futures prices aligned with spot prices
- **Long_Short_Ratio**: The ratio of long positions to short positions in the market
- **IC_Weight**: Information Coefficient weight used to combine multiple trading signals based on their historical predictive power
- **Multi_Factor_Score**: A composite score calculated by combining multiple weighted trading signals
- **Reversal_Signal**: A trading signal that identifies potential price reversals based on recent price movements
- **Momentum_Signal**: A trading signal that identifies trending price movements over a longer time period
- **Visualization_Dashboard**: A static graphical representation of screening results using horizontal bar charts
- **Asset_Symbol**: The ticker symbol identifying a cryptocurrency asset (e.g., ZEC, TAO, SOL)

## Requirements

### Requirement 1: Exchange Connection and Configuration

**User Story:** As a trader in a region with exchange restrictions, I want the system to connect to accessible exchanges, so that I can screen cryptocurrency assets without using blocked services.

#### Acceptance Criteria

1. THE Data_Ingestion_Pipeline SHALL initialize a connection to OKX_Exchange using CCXT_Library
2. THE Data_Ingestion_Pipeline SHALL NOT use Binance API for any data retrieval operations
3. WHEN the connection to OKX_Exchange fails, THE Data_Ingestion_Pipeline SHALL return a descriptive error message
4. THE Screener_System SHALL use Python as the primary implementation language
5. THE Screener_System SHALL use CCXT_Library for all exchange market data operations

### Requirement 2: Real-Time Market Data Retrieval

**User Story:** As a trader, I want to fetch current market data for multiple cryptocurrency assets, so that I can analyze current market conditions.

#### Acceptance Criteria

1. THE Data_Ingestion_Pipeline SHALL fetch real-time data for a predefined list of Perpetual_Future contracts
2. THE Data_Ingestion_Pipeline SHALL support at minimum the following Asset_Symbol values: ZEC, TAO, TON, AAVE, SOL
3. WHEN fetching market data, THE Data_Ingestion_Pipeline SHALL extract the current price for each Asset_Symbol
4. WHEN fetching market data, THE Data_Ingestion_Pipeline SHALL extract the 24-hour price change percentage for each Asset_Symbol
5. WHEN fetching market data, THE Data_Ingestion_Pipeline SHALL extract the Funding_Rate percentage for each Asset_Symbol
6. WHEN fetching market data, THE Data_Ingestion_Pipeline SHALL extract the Long_Short_Ratio for each Asset_Symbol
7. WHEN any data field is unavailable for an Asset_Symbol, THE Data_Ingestion_Pipeline SHALL use a null or default value and continue processing other assets

### Requirement 3: Quantitative Signal Generation

**User Story:** As a quantitative trader, I want the system to generate multiple trading signals, so that I can identify assets with strong technical characteristics.

#### Acceptance Criteria

1. THE Screener_System SHALL generate a 1-day Reversal_Signal for each Asset_Symbol using simulated logic
2. THE Screener_System SHALL generate a 30-day Momentum_Signal for each Asset_Symbol using simulated logic
3. WHEN generating signals, THE Screener_System SHALL apply simulated IC_Weight values to each signal type
4. THE Screener_System SHALL calculate a Multi_Factor_Score for each Asset_Symbol by combining weighted signals
5. THE Screener_System SHALL normalize signal values to enable meaningful combination across different signal types

### Requirement 4: Asset Ranking and Scoring

**User Story:** As a trader, I want assets ranked by their composite score, so that I can quickly identify the most promising opportunities.

#### Acceptance Criteria

1. THE Screener_System SHALL sort all Asset_Symbol entries by Multi_Factor_Score in descending order
2. WHEN two Asset_Symbol entries have equal Multi_Factor_Score values, THE Screener_System SHALL maintain stable ordering
3. THE Screener_System SHALL classify Asset_Symbol entries into Tier A and Tier B based on Multi_Factor_Score thresholds
4. THE Screener_System SHALL store all calculated scores and rankings in a pandas DataFrame structure

### Requirement 5: Visualization Dashboard Generation

**User Story:** As a trader, I want a visual dashboard showing key metrics, so that I can quickly assess market conditions across multiple assets.

#### Acceptance Criteria

1. THE Visualization_Dashboard SHALL display three horizontal bar chart panels in a single figure
2. THE Visualization_Dashboard SHALL use a shared Y-axis across all panels displaying Asset_Symbol values
3. THE Visualization_Dashboard SHALL order Asset_Symbol entries consistently across all panels based on Multi_Factor_Score ranking
4. THE Screener_System SHALL use matplotlib or seaborn libraries for all visualization operations
5. THE Visualization_Dashboard SHALL render as a static image that can be saved to disk

### Requirement 6: Multi-Factor Score Visualization

**User Story:** As a trader, I want to see the composite score for each asset, so that I can identify which assets have the strongest combined signals.

#### Acceptance Criteria

1. THE Visualization_Dashboard SHALL display Multi_Factor_Score values as horizontal bars in the first panel
2. WHEN an Asset_Symbol is classified as Tier A, THE Visualization_Dashboard SHALL render its bar in darker color #C85A82
3. WHEN an Asset_Symbol is classified as Tier B, THE Visualization_Dashboard SHALL render its bar in a lighter shade of #C85A82
4. THE Visualization_Dashboard SHALL label the first panel with a descriptive title indicating Multi_Factor_Score content
5. THE Visualization_Dashboard SHALL display numeric Multi_Factor_Score values on or near each bar

### Requirement 7: Funding Rate Visualization

**User Story:** As a trader, I want to see funding rates for each asset, so that I can identify potential short squeeze opportunities or crowded positions.

#### Acceptance Criteria

1. THE Visualization_Dashboard SHALL display Funding_Rate percentage values as horizontal bars in the second panel
2. THE Visualization_Dashboard SHALL render a vertical reference line at 0% in the Funding_Rate panel
3. WHEN Funding_Rate is negative, THE Visualization_Dashboard SHALL use a color indicating short bias or squeeze potential
4. WHEN Funding_Rate is positive, THE Visualization_Dashboard SHALL use a color indicating crowded long positions
5. THE Visualization_Dashboard SHALL label the second panel with a descriptive title indicating Funding_Rate content

### Requirement 8: Long/Short Ratio Visualization

**User Story:** As a trader, I want to see the long/short ratio for each asset, so that I can identify overcrowded positions that may reverse.

#### Acceptance Criteria

1. THE Visualization_Dashboard SHALL display Long_Short_Ratio values as horizontal bars in the third panel
2. THE Visualization_Dashboard SHALL render a vertical reference line at 1.0 indicating neutral positioning
3. THE Visualization_Dashboard SHALL render a vertical reference line at 1.5 indicating warning threshold for crowded longs
4. WHEN Long_Short_Ratio exceeds 1.5, THE Visualization_Dashboard SHALL highlight the bar to indicate crowded long positioning
5. THE Visualization_Dashboard SHALL label the third panel with a descriptive title indicating Long_Short_Ratio content

### Requirement 9: Code Documentation and Maintainability

**User Story:** As a developer, I want clear documentation in the code, so that I can understand and modify the system behavior.

#### Acceptance Criteria

1. THE Screener_System SHALL include inline comments explaining CCXT_Library endpoint mapping for each data field
2. THE Screener_System SHALL include inline comments explaining the visualization logic for each panel
3. THE Screener_System SHALL include inline comments explaining the simulated IC_Weight calculation methodology
4. THE Screener_System SHALL be implemented as a self-contained Python script that can be executed independently
5. THE Screener_System SHALL use pandas and numpy libraries for all data manipulation operations

### Requirement 10: Error Handling and Robustness

**User Story:** As a user, I want the system to handle errors gracefully, so that partial failures don't crash the entire screening process.

#### Acceptance Criteria

1. WHEN CCXT_Library raises an exception during data retrieval, THE Data_Ingestion_Pipeline SHALL log the error and continue processing remaining assets
2. WHEN an Asset_Symbol has missing data fields, THE Screener_System SHALL exclude that asset from visualization or use default values
3. WHEN OKX_Exchange is unavailable, THE Screener_System SHALL return a descriptive error message indicating connection failure
4. WHEN visualization rendering fails, THE Screener_System SHALL return a descriptive error message indicating the failure reason
5. THE Screener_System SHALL validate that required Python libraries are available before executing main logic
