# Implementation Plan: API Backend Transformation

## Overview

Transform the crypto screener from a standalone matplotlib-based script into a FastAPI REST API backend returning structured JSON data. The implementation wraps existing data processing modules (exchange connector, market data fetcher, signal generator, IC weight calculator, multi-factor scorer, ranking engine) with an HTTP layer, adding caching, structured logging, and graceful error handling.

## Tasks

- [x] 1. Set up project structure, dependencies, and configuration
  - [x] 1.1 Create API project directory structure and package files
    - Create directories: `src/api/`, `src/services/`, `src/config/`
    - Create `__init__.py` files for each new package
    - Create `main_api.py` entry point at project root
    - Create `.env.example` with all configurable environment variables
    - _Requirements: 1.1, 8.1, 8.4, 11.1_

  - [x] 1.2 Update requirements.txt with FastAPI dependencies
    - Add: `fastapi>=0.104.0`, `uvicorn[standard]>=0.24.0`, `pydantic>=2.5.0`, `pydantic-settings>=2.1.0`
    - Add: `cachetools>=5.3.0`, `python-json-logger>=2.0.0`
    - Add test dependencies: `pytest>=7.4.0`, `pytest-asyncio>=0.23.0`, `hypothesis>=6.92.0`, `httpx>=0.25.0`, `pytest-cov>=4.1.0`
    - _Requirements: 1.1, 1.4, 5.4, 11.1_

  - [x] 1.3 Implement configuration module (`src/config/settings.py`)
    - Create `Settings` class extending Pydantic `BaseSettings`
    - Define fields: `api_host`, `api_port`, `cache_ttl`, `log_level`, `symbols`, `mock_mode`, `cors_origins`, `shutdown_timeout`
    - Configure `env_prefix = "SCREENER_"` and `.env` file support
    - Set default values as specified in design
    - _Requirements: 8.1, 8.2, 8.3, 8.4_

  - [x] 1.4 Implement structured logging configuration (`src/config/logging_config.py`)
    - Create `setup_logging()` function with JSON structured format
    - Configure `RotatingFileHandler` with max 10 files, 10MB each
    - Support configurable log level from Settings
    - Log to both file and stdout
    - _Requirements: 9.4, 9.5_

- [x] 2. Implement Pydantic response models and data structures
  - [x] 2.1 Create Pydantic response models (`src/api/models.py`)
    - Implement `ResponseMetadata`, `MarketOverview`, `AssetSummary`, `AssetDetail` models
    - Implement `SummaryData`, `ScreenerResponse`, `AssetDetailResponse` models
    - Implement `HealthResponse`, `ErrorResponse` models
    - Ensure all numeric fields use `Optional[float]` with `None` default
    - _Requirements: 1.4, 3.1, 3.2, 3.3, 3.4, 3.5, 3.6, 4.7, 13.1, 13.2, 13.3, 13.4, 14.2, 14.3_

  - [x] 2.2 Create internal data structures (`src/services/models.py`)
    - Implement `ProcessedResult` dataclass with `data`, `errors`, `processed_at` fields
    - Implement `CacheEntry` dataclass with `is_expired` and `age_seconds` properties
    - _Requirements: 5.1, 5.2_

- [x] 3. Implement Cache Manager service
  - [x] 3.1 Implement Cache Manager (`src/services/cache_manager.py`)
    - Create `CacheManager` class with configurable TTL
    - Implement `get()` method returning `Optional[CacheEntry]`
    - Implement `set()` method storing `ProcessedResult` with timestamp
    - Implement `data_age_seconds`, `is_stale`, `next_refresh_at` properties
    - Use thread-safe implementation for concurrent access
    - _Requirements: 5.1, 5.2, 5.3, 5.4, 5.5, 5.6, 13.2, 13.3, 13.4_

  - [x]* 3.2 Write property test for Cache Manager (Property 5: Cache TTL Correctness)
    - **Property 5: Cache TTL Correctness**
    - Test that cached data is returned before TTL expiry (cache_hit=true)
    - Test that cache miss occurs after TTL expiry (cache_hit=false)
    - Use hypothesis to generate random TTL values and time offsets
    - **Validates: Requirements 5.1, 5.2, 5.3**

- [x] 4. Implement Response Builder service
  - [x] 4.1 Implement Response Builder (`src/services/response_builder.py`)
    - Create `ResponseBuilder` class
    - Implement `build_full_response()` with metadata, summary, and assets
    - Implement `build_summary_only()` omitting assets array
    - Implement `build_asset_detail()` for single asset response
    - Implement `_sanitize_value()` converting NaN/None to null, formatting numeric precision (2-4 decimal places)
    - Build `top_3_assets` from ranked DataFrame
    - Build `market_overview` with avg_change_24h, avg_funding_rate, bullish/bearish counts
    - _Requirements: 3.1, 3.2, 3.3, 3.4, 3.5, 3.6, 7.2, 12.3, 12.4, 13.1, 13.2, 13.3, 13.4_

  - [ ]* 4.2 Write property test for Response Builder (Property 1: Response Structure Completeness)
    - **Property 1: Response Structure Completeness**
    - Generate random DataFrames with valid screener columns
    - Verify all required top-level keys present (metadata, summary, assets)
    - Verify metadata contains all required fields
    - Verify summary contains top_3_assets and market_overview
    - **Validates: Requirements 3.1, 3.2, 3.3, 5.5, 5.6, 7.5, 13.1, 13.4**

  - [ ]* 4.3 Write property test for Response Builder (Property 2: Asset Object Completeness)
    - **Property 2: Asset Object Completeness**
    - Generate random asset rows with all metric columns
    - Verify each asset object contains all required metric fields
    - **Validates: Requirements 3.4**

  - [x]* 4.4 Write property test for Response Builder (Property 3: Value Sanitization)
    - **Property 3: Value Sanitization**
    - Generate DataFrames with mix of valid numbers, NaN, and None values
    - Verify numeric values formatted with 2-4 decimal places
    - Verify NaN/None values converted to JSON null
    - **Validates: Requirements 3.5, 3.6**

  - [ ]* 4.5 Write property test for Response Builder (Property 7: Summary-Only Filter)
    - **Property 7: Summary-Only Filter**
    - Generate random DataFrames and build summary-only response
    - Verify response contains metadata and summary but NOT assets
    - **Validates: Requirements 12.3, 12.4**

  - [ ]* 4.6 Write property test for Response Builder (Property 8: Stale Data Warning)
    - **Property 8: Stale Data Warning**
    - Generate random data_age_seconds values
    - Verify stale_data_warning=true when data_age_seconds > 300
    - Verify stale_data_warning absent/null when data_age_seconds <= 300
    - **Validates: Requirements 13.3**

- [x] 5. Checkpoint - Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

- [x] 6. Implement Data Processor service
  - [x] 6.1 Implement symbol normalization utility (`src/services/symbol_utils.py`)
    - Create `normalize_symbol()` function handling formats: BTCUSDT, BTC/USDT, BTC/USDT:USDT, btcusdt
    - Return canonical CCXT futures format (e.g., BTC/USDT:USDT)
    - Return None if symbol not in configured list after normalization
    - _Requirements: 14.4_

  - [ ]* 6.2 Write property test for symbol normalization (Property 9: Symbol Normalization)
    - **Property 9: Symbol Normalization**
    - Generate valid symbols in all accepted formats
    - Verify all formats resolve to same canonical CCXT futures format
    - Verify resolved symbol is in configured symbols list
    - **Validates: Requirements 14.4**

  - [x] 6.3 Implement Data Processor (`src/services/data_processor.py`)
    - Create `DataProcessor` class wrapping existing modules
    - Implement `process_all()` orchestrating: connect → fetch → signal → score → rank
    - Implement `_fetch_with_error_isolation()` for per-symbol error handling
    - Wrap synchronous modules in `asyncio.to_thread()` for non-blocking execution
    - Implement mock mode returning synthetic DataFrame for testing
    - Collect per-symbol errors without halting pipeline
    - _Requirements: 2.1, 2.2, 2.3, 2.4, 6.3, 6.4, 7.1, 7.2, 7.3, 10.1, 10.2, 10.3, 10.4, 10.5, 10.6, 11.4_

  - [x]* 6.4 Write property test for Data Processor (Property 6: Partial Failure Isolation)
    - **Property 6: Partial Failure Isolation**
    - Generate random subsets of symbols that fail during fetch
    - Verify remaining symbols have valid processed data
    - Verify failed symbols have null metric fields
    - **Validates: Requirements 7.1, 7.2**

- [x] 7. Implement FastAPI application and routes
  - [x] 7.1 Implement FastAPI application factory (`src/api/app.py`)
    - Create `create_app()` function returning configured FastAPI instance
    - Register CORS middleware with configurable origins
    - Register request logging middleware (timestamp, endpoint, response time)
    - Implement lifespan context manager for graceful shutdown
    - Set `shutting_down` flag on SIGTERM, reject new requests with 503
    - Wait max 30 seconds for active requests before exit
    - _Requirements: 1.1, 1.2, 1.3, 2.2, 9.1, 9.2, 9.3, 11.3, 15.1, 15.2, 15.3, 15.4_

  - [x] 7.2 Implement API routes (`src/api/routes.py`)
    - Implement `GET /api/v1/screener/summary` with `summary_only` query parameter
    - Implement `GET /api/v1/screener/assets/{symbol}` with symbol validation
    - Implement `GET /api/v1/health` returning health status, cache status, uptime
    - Return proper HTTP status codes: 200, 404, 500, 503
    - Include error messages in response body for all error responses
    - Log cache hit/miss events and exchange errors
    - _Requirements: 4.1, 4.2, 4.3, 4.4, 4.5, 4.6, 4.7, 5.5, 5.6, 6.1, 6.2, 7.4, 7.5, 9.1, 9.2, 9.3, 12.1, 12.2, 12.3, 12.4, 14.1, 14.2, 14.3, 14.4_

  - [x]* 7.3 Write property test for invalid symbol rejection (Property 4: Invalid Symbol Rejection)
    - **Property 4: Invalid Symbol Rejection**
    - Generate random strings not in configured SYMBOLS list
    - Verify HTTP 404 returned with correct error message format
    - Verify available_symbols field present in error response
    - **Validates: Requirements 4.5, 14.1, 14.2, 14.3**

- [x] 8. Implement API entry point and wiring
  - [x] 8.1 Implement API entry point (`main_api.py`)
    - Import and call `create_app()` from `src/api/app.py`
    - Configure uvicorn with host/port from Settings
    - Support `--reload` flag for development
    - Wire all components: Settings → CacheManager → DataProcessor → ResponseBuilder → Routes
    - _Requirements: 1.1, 1.2, 6.3, 8.1, 8.2, 11.1_

- [x] 9. Checkpoint - Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

- [ ] 10. Write integration tests and test fixtures
  - [x] 10.1 Create test fixtures and conftest (`tests/conftest.py`)
    - Create shared pytest fixtures for mock DataProcessor, mock CacheManager
    - Create fixture for FastAPI test client using httpx AsyncClient
    - Create fixture for sample DataFrames with realistic crypto data
    - Configure mock mode settings for all tests
    - _Requirements: 11.4_

  - [ ]* 10.2 Write unit tests for API routes (`tests/test_api/test_routes.py`)
    - Test GET /health returns 200 with correct structure
    - Test GET /api/v1/screener/summary returns 200 with full data
    - Test GET /api/v1/screener/summary?summary_only=true omits assets
    - Test GET /api/v1/screener/assets/{valid_symbol} returns 200
    - Test GET /api/v1/screener/assets/{invalid_symbol} returns 404
    - Test exchange timeout returns 503
    - _Requirements: 4.1, 4.2, 4.3, 4.4, 4.5, 4.6, 4.7_

  - [ ]* 10.3 Write integration test for full pipeline (`tests/test_services/test_integration.py`)
    - Test end-to-end flow with mock mode enabled
    - Test cache warming and subsequent cache hits
    - Test partial failure scenario (some symbols fail)
    - Test CORS headers present in responses
    - _Requirements: 6.1, 6.2, 7.1, 7.2, 11.3, 11.4_

- [x] 11. Final checkpoint - Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

## Notes

- Tasks marked with `*` are optional and can be skipped for faster MVP
- Each task references specific requirements for traceability
- Checkpoints ensure incremental validation
- Property tests validate universal correctness properties from the design document
- Unit tests validate specific examples and edge cases
- The implementation uses Python with FastAPI, as specified in the design
- Existing modules (exchange, data, signals, ranking) remain unchanged per Requirement 10
- All new code goes in `src/api/`, `src/services/`, and `src/config/` directories

## Task Dependency Graph

```json
{
  "waves": [
    { "id": 0, "tasks": ["1.1", "1.2"] },
    { "id": 1, "tasks": ["1.3", "1.4"] },
    { "id": 2, "tasks": ["2.1", "2.2"] },
    { "id": 3, "tasks": ["3.1", "6.1"] },
    { "id": 4, "tasks": ["3.2", "4.1", "6.2"] },
    { "id": 5, "tasks": ["4.2", "4.3", "4.4", "4.5", "4.6", "6.3"] },
    { "id": 6, "tasks": ["6.4", "7.1"] },
    { "id": 7, "tasks": ["7.2"] },
    { "id": 8, "tasks": ["7.3", "8.1"] },
    { "id": 9, "tasks": ["10.1"] },
    { "id": 10, "tasks": ["10.2", "10.3"] }
  ]
}
```
