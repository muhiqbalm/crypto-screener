# Implementation Plan: Exchange Debug API

## Overview

This implementation plan creates a diagnostic API system that exposes raw, unprocessed responses from the Binance Futures API. The feature provides transparency into exchange communication by exposing raw JSON responses, timing metrics, field mappings, and detailed error diagnostics. The implementation follows the existing FastAPI architecture pattern used in the crypto-screener application.

## Tasks

- [x] 1. Create Pydantic models for debug API responses
  - Create `src/api/debug_models.py` with all response models
  - Implement `RequestMetadata` model with timestamp, response_time_ms, http_status, and exchange fields
  - Implement `FieldMappingInfo` model with app_field, required, data_type, description, and transformation fields
  - Implement `ErrorInfo` model with message and code fields
  - Implement `DebugResponse` model with success, data, error, metadata, and fieldMapping fields
  - Implement `DataTypeResult` model for individual data type results in aggregated endpoint
  - Implement `AggregatedDebugResponse` model with nested data structure for all four data types
  - Implement `HealthCheckResponse` model with status, exchange info, and available endpoints
  - _Requirements: 7.1, 7.2, 7.3, 7.4, 7.5, 7.6_

- [ ]* 1.1 Write property test for response model structure
  - **Property 5: Response Format Consistency**
  - **Validates: Requirements 7.1, 7.2, 7.3**
  - Test that all response models include success boolean field
  - Test that successful responses include data object
  - Test that error responses include error object with message and code
  - Test that all responses include metadata with required fields

- [x] 2. Implement symbol validation and normalization utilities
  - Create `src/api/debug_utils.py` with validation functions
  - Implement `validate_symbol()` function that checks for empty/whitespace, alphanumeric characters, and max length (20 chars)
  - Implement `normalize_symbol()` function that trims whitespace and converts to uppercase
  - Return tuple of (is_valid, error_message) from validation function
  - _Requirements: 11.1, 11.2, 11.3, 11.4, 11.5_

- [ ]* 2.1 Write property test for symbol validation
  - **Property 6: Symbol Validation and Normalization**
  - **Validates: Requirements 1.7, 11.1, 11.4, 11.5**
  - Test that empty/whitespace symbols are rejected with appropriate error
  - Test that symbols with non-alphanumeric characters are rejected
  - Test that symbols exceeding 20 characters are rejected
  - Test that valid symbols are normalized to uppercase with whitespace trimmed

- [x] 3. Create DebugExchangeService with field mapping initialization
  - Create `src/services/debug_exchange_service.py`
  - Implement `DebugExchangeService` class with constructor accepting ExchangeConnector
  - Implement `_initialize_field_mappings()` method that returns dictionary with field mappings for ticker, open interest, funding rate, and long/short ratio
  - Define field mappings for ticker: last→price, percentage→change_24h, quoteVolume→volume_24h, baseVolume→volume_24h (fallback)
  - Define field mappings for open interest: openInterestAmount→open_interest, openInterest→open_interest (fallback)
  - Define field mappings for funding rate: fundingRate→funding_rate (with transformation note)
  - Define field mappings for long/short ratio: longShortRatio→long_short_ratio
  - Store exchange instance and field_mappings as instance variables
  - _Requirements: 9.1, 9.2, 9.3, 9.4_

- [ ]* 3.1 Write property test for field mapping completeness
  - **Property 3: Field Mapping Documentation**
  - **Validates: Requirements 1.5, 2.3, 3.3, 4.3, 5.3, 7.5, 9.1, 9.2, 9.3, 9.4**
  - Test that field mappings exist for all four data types
  - Test that each field mapping entry contains app_field, required, data_type, and description
  - Test that transformation field is present for fields that undergo transformation

- [x] 4. Implement raw ticker data fetching method
  - [x] 4.1 Implement `fetch_raw_ticker()` method in DebugExchangeService
    - Accept symbol parameter (string)
    - Validate symbol using validation utility
    - Record request timestamp before exchange call
    - Call `exchange.fetch_ticker(symbol)` using CCXT
    - Record response timestamp after exchange call
    - Calculate response_time_ms from timestamps
    - Build DebugResponse with success=True, raw data, metadata, and field mappings
    - Handle exceptions and return appropriate error responses
    - _Requirements: 1.1, 1.2, 1.3, 1.4, 1.5, 8.1, 8.2, 8.3, 8.4_

  - [ ]* 4.2 Write property test for raw ticker data retrieval
    - **Property 1: Raw Data Retrieval**
    - **Validates: Requirements 1.1**
    - Test that valid symbol returns unprocessed exchange response in data field
    - Test that response includes all CCXT ticker fields

  - [ ]* 4.3 Write property test for ticker metadata structure
    - **Property 2: Complete Metadata Structure**
    - **Validates: Requirements 1.2, 1.3, 1.4, 8.1, 8.2, 8.3, 8.4**
    - Test that metadata includes request_timestamp in ISO 8601 format
    - Test that metadata includes response_timestamp in ISO 8601 format
    - Test that metadata includes response_time_ms as positive float with 2+ decimal places
    - Test that response_timestamp is after request_timestamp

- [x] 5. Implement raw open interest data fetching method
  - [x] 5.1 Implement `fetch_raw_open_interest()` method in DebugExchangeService
    - Accept symbol parameter (string)
    - Validate symbol using validation utility
    - Record request and response timestamps
    - Call `exchange.fetch_open_interest(symbol)` using CCXT
    - Calculate response_time_ms
    - Build DebugResponse with raw data, metadata, and field mappings
    - Handle exceptions and return appropriate error responses
    - _Requirements: 2.1, 2.2, 2.3_

  - [ ]* 5.2 Write property test for raw open interest data retrieval
    - **Property 1: Raw Data Retrieval**
    - **Validates: Requirements 2.1**
    - Test that valid symbol returns unprocessed exchange response in data field

- [x] 6. Implement raw funding rate data fetching method
  - [x] 6.1 Implement `fetch_raw_funding_rate()` method in DebugExchangeService
    - Accept symbol parameter (string)
    - Validate symbol using validation utility
    - Record request and response timestamps
    - Call `exchange.fetch_funding_rate(symbol)` using CCXT
    - Calculate response_time_ms
    - Build DebugResponse with raw data, metadata, and field mappings
    - Handle exceptions and return appropriate error responses
    - _Requirements: 3.1, 3.2, 3.3_

  - [ ]* 6.2 Write property test for raw funding rate data retrieval
    - **Property 1: Raw Data Retrieval**
    - **Validates: Requirements 3.1**
    - Test that valid symbol returns unprocessed exchange response in data field

- [x] 7. Implement raw long/short ratio data fetching method
  - [x] 7.1 Implement `fetch_raw_long_short_ratio()` method in DebugExchangeService
    - Accept symbol parameter (string)
    - Validate symbol using validation utility
    - Record request and response timestamps
    - Make direct HTTP request to Binance API for long/short ratio data (not available in CCXT)
    - Use requests library to call Binance top trader long/short ratio endpoint
    - Calculate response_time_ms
    - Build DebugResponse with raw data, metadata, and field mappings
    - Handle exceptions and return appropriate error responses
    - _Requirements: 4.1, 4.2, 4.3_

  - [ ]* 7.2 Write property test for raw long/short ratio data retrieval
    - **Property 1: Raw Data Retrieval**
    - **Validates: Requirements 4.1**
    - Test that valid symbol returns unprocessed exchange response in data field

- [x] 8. Checkpoint - Ensure all individual data fetching methods work correctly
  - Ensure all tests pass, ask the user if questions arise.

- [x] 9. Implement aggregated data fetching with concurrent execution
  - [x] 9.1 Implement `fetch_all_raw_data()` method in DebugExchangeService
    - Accept symbol parameter (string)
    - Validate symbol once before all requests
    - Record overall request timestamp
    - Use `asyncio.gather()` to execute all four fetch methods concurrently
    - Wrap each fetch call with individual error handling to prevent one failure from blocking others
    - Record individual timing for each data type
    - Calculate total response time
    - Build AggregatedDebugResponse with nested data structure containing results for all four data types
    - Include individual_timings in metadata showing response time for each data type
    - Include field mappings for all four data types
    - _Requirements: 5.1, 5.2, 5.3, 5.4, 5.5, 8.5_

  - [ ]* 9.2 Write property test for aggregated endpoint completeness
    - **Property 7: Aggregated Endpoint Completeness**
    - **Validates: Requirements 5.1, 5.2, 5.3, 8.5**
    - Test that response includes results for all four data types
    - Test that individual timing information is included for each data type
    - Test that field mappings are included for all data types

  - [ ]* 9.3 Write property test for graceful partial failure handling
    - **Property 8: Graceful Partial Failure Handling**
    - **Validates: Requirements 5.4**
    - Test that when one data type fails, other successful data types are still returned
    - Test that error information is included for failed requests in their respective sections

  - [ ]* 9.4 Write property test for concurrent execution efficiency
    - **Property 9: Concurrent Execution Efficiency**
    - **Validates: Requirements 5.5**
    - Test that total response time is approximately equal to max individual response time (not sum)
    - Test that overhead is less than 100ms

- [x] 10. Implement exchange health check method
  - [x] 10.1 Implement `check_exchange_health()` method in DebugExchangeService
    - Record request timestamp
    - Call `exchange.fetch_time()` to get server timestamp and verify connectivity
    - Get exchange base URL from exchange instance
    - Build list of available debug endpoints
    - Record response timestamp and calculate response_time_ms
    - Build HealthCheckResponse with status="connected", exchange info, server timestamp, and available endpoints
    - Handle connection failures and return status="disconnected" with 503 status code
    - _Requirements: 6.1, 6.2, 6.3, 6.4, 6.5, 6.6_

  - [ ]* 10.2 Write unit tests for health check endpoint
    - Test successful health check returns status="connected" with 200 status code
    - Test connection failure returns status="disconnected" with 503 status code
    - Test that available endpoints list is complete

- [x] 11. Implement comprehensive error handling for all methods
  - [x] 11.1 Add error handling for validation errors (HTTP 400)
    - Catch validation errors and return 400 status with descriptive error message
    - Include error code "INVALID_INPUT"
    - _Requirements: 1.7, 2.5, 11.2_

  - [x] 11.2 Add error handling for authentication errors (HTTP 401)
    - Catch authentication errors when auth is enabled
    - Return 401 status with error code "UNAUTHORIZED"
    - _Requirements: 12.1, 12.2_

  - [x] 11.3 Add error handling for exchange client errors (HTTP 4xx)
    - Catch CCXT ExchangeError exceptions
    - Preserve original exchange error response in data field
    - Return appropriate status code with error code "EXCHANGE_ERROR"
    - _Requirements: 10.1_

  - [x] 11.4 Add error handling for exchange server errors (HTTP 5xx)
    - Catch CCXT server error exceptions
    - Preserve original exchange error response in data field
    - Return appropriate status code with error code "EXCHANGE_SERVER_ERROR"
    - _Requirements: 10.2_

  - [x] 11.5 Add error handling for connectivity errors (HTTP 503)
    - Catch CCXT NetworkError exceptions
    - Return 503 status with error code "SERVICE_UNAVAILABLE"
    - Include details about DNS errors, connection refused, etc.
    - _Requirements: 6.5, 10.4_

  - [x] 11.6 Add error handling for timeout errors (HTTP 504)
    - Catch CCXT RequestTimeout exceptions
    - Return 504 status with error code "GATEWAY_TIMEOUT"
    - Include timeout duration in error response
    - _Requirements: 10.3_

  - [x] 11.7 Add error handling for internal server errors (HTTP 500)
    - Catch unexpected exceptions
    - Log full stack trace server-side
    - Return sanitized error message to client with error code "INTERNAL_ERROR"
    - _Requirements: 10.6_

  - [ ]* 11.8 Write property test for error response structure
    - **Property 4: Error Response Structure**
    - **Validates: Requirements 1.6, 2.4, 3.4, 4.4, 7.6, 10.5, 10.6**
    - Test that error responses include success=false
    - Test that error responses include error object with message and code
    - Test that original exchange error is preserved in data field when available

  - [ ]* 11.9 Write property test for HTTP status code mapping
    - **Property 10: HTTP Status Code Mapping**
    - **Validates: Requirements 2.5, 10.3, 10.4**
    - Test that invalid input returns 400 status
    - Test that authentication failures return 401 status (when auth enabled)
    - Test that connectivity issues return 503 status
    - Test that timeout errors return 504 status

- [x] 12. Create FastAPI router for debug endpoints
  - Create `src/api/debug_routes.py` with APIRouter
  - Set router prefix to `/api/v1/debug`
  - Import DebugExchangeService and debug response models
  - Add dependency to get or create DebugExchangeService instance from app.state
  - _Requirements: 7.1_

- [x] 13. Implement debug API route handlers
  - [x] 13.1 Implement GET `/exchange/ticker/{symbol}` endpoint
    - Define route handler with symbol path parameter
    - Call `debug_service.fetch_raw_ticker(symbol)`
    - Return DebugResponse with appropriate status code
    - _Requirements: 1.1, 1.2, 1.3, 1.4, 1.5, 1.6, 1.7_

  - [x] 13.2 Implement GET `/exchange/open-interest/{symbol}` endpoint
    - Define route handler with symbol path parameter
    - Call `debug_service.fetch_raw_open_interest(symbol)`
    - Return DebugResponse with appropriate status code
    - _Requirements: 2.1, 2.2, 2.3, 2.4, 2.5_

  - [x] 13.3 Implement GET `/exchange/funding-rate/{symbol}` endpoint
    - Define route handler with symbol path parameter
    - Call `debug_service.fetch_raw_funding_rate(symbol)`
    - Return DebugResponse with appropriate status code
    - _Requirements: 3.1, 3.2, 3.3, 3.4_

  - [x] 13.4 Implement GET `/exchange/long-short-ratio/{symbol}` endpoint
    - Define route handler with symbol path parameter
    - Call `debug_service.fetch_raw_long_short_ratio(symbol)`
    - Return DebugResponse with appropriate status code
    - _Requirements: 4.1, 4.2, 4.3, 4.4_

  - [x] 13.5 Implement GET `/exchange/all/{symbol}` endpoint
    - Define route handler with symbol path parameter
    - Call `debug_service.fetch_all_raw_data(symbol)`
    - Return AggregatedDebugResponse with appropriate status code
    - _Requirements: 5.1, 5.2, 5.3, 5.4, 5.5_

  - [x] 13.6 Implement GET `/health` endpoint
    - Define route handler with no parameters
    - Call `debug_service.check_exchange_health()`
    - Return HealthCheckResponse with appropriate status code
    - _Requirements: 6.1, 6.2, 6.3, 6.4, 6.5, 6.6_

- [x] 14. Register debug router in main application
  - Update `src/api/app.py` to import debug_routes router
  - Register debug router using `app.include_router(debug_router)` in `create_app()` function
  - Initialize DebugExchangeService in lifespan context manager and store in app.state
  - _Requirements: 7.1_

- [x] 15. Implement request logging for debug endpoints
  - [x] 15.1 Add logging for all debug endpoint requests
    - Log request with endpoint, method, symbol parameter, and timestamp
    - Include requester identity when available (from request headers or auth context)
    - Use existing RequestLoggingMiddleware which already logs all requests
    - _Requirements: 12.4_

  - [ ]* 15.2 Write property test for request logging
    - **Property 12: Request Logging**
    - **Validates: Requirements 12.4**
    - Test that all debug endpoint requests are logged with timestamp
    - Test that requester identity is logged when available

- [x] 16. Implement security measures
  - [x] 16.1 Add response sanitization to prevent secrets in responses
    - Review all response building code to ensure API keys and secrets are never included
    - Add explicit checks to filter out sensitive fields from exchange responses
    - _Requirements: 12.3_

  - [ ]* 16.2 Write property test for security
    - **Property 11: Security - No Secrets in Responses**
    - **Validates: Requirements 12.3**
    - Test that responses do not contain API keys, secrets, or authentication tokens
    - Test that sensitive fields are filtered from exchange responses

  - [x] 16.3 Add authentication support (optional, when enabled)
    - Add authentication dependency to debug routes when auth is configured
    - Return 401 status for unauthenticated requests when auth is enabled
    - _Requirements: 12.1, 12.2_

  - [x] 16.4 Add rate limiting support (optional, when configured)
    - Add rate limiting middleware for debug endpoints when configured
    - Enforce rate limits to prevent abuse
    - _Requirements: 12.5_

- [x] 17. Checkpoint - Ensure all endpoints are working correctly
  - Ensure all tests pass, ask the user if questions arise.

- [ ]* 18. Write integration tests for debug API endpoints
  - [ ]* 18.1 Write integration test for ticker endpoint
    - Test successful ticker data retrieval with valid symbol
    - Test error handling with invalid symbol
    - Test response structure matches DebugResponse model

  - [ ]* 18.2 Write integration test for open interest endpoint
    - Test successful open interest data retrieval with valid symbol
    - Test error handling with missing symbol parameter

  - [ ]* 18.3 Write integration test for funding rate endpoint
    - Test successful funding rate data retrieval with valid symbol
    - Test error handling with exchange errors

  - [ ]* 18.4 Write integration test for long/short ratio endpoint
    - Test successful long/short ratio data retrieval with valid symbol
    - Test error handling with network errors

  - [ ]* 18.5 Write integration test for aggregated endpoint
    - Test successful retrieval of all four data types
    - Test partial failure handling (one data type fails, others succeed)
    - Test concurrent execution (timing verification)

  - [ ]* 18.6 Write integration test for health check endpoint
    - Test successful health check with connected exchange
    - Test health check with disconnected exchange

- [x] 19. Create API documentation
  - Add docstrings to all route handlers with parameter descriptions and response examples
  - Update FastAPI app metadata to include debug endpoints in OpenAPI schema
  - Add examples to Pydantic models for better API documentation
  - _Requirements: 7.1_

- [x] 20. Final checkpoint - Complete end-to-end testing
  - Ensure all tests pass, ask the user if questions arise.

## Notes

- Tasks marked with `*` are optional and can be skipped for faster MVP
- Each task references specific requirements for traceability
- Checkpoints ensure incremental validation
- Property tests validate universal correctness properties
- Unit tests and integration tests validate specific examples and edge cases
- The implementation follows the existing FastAPI architecture pattern in the crypto-screener application
- All code uses Python with type hints, async/await, and Pydantic models
- Error handling follows the existing pattern in the application with structured error responses
- The debug API is read-only and does not modify exchange state

## Task Dependency Graph

```json
{
  "waves": [
    { "id": 0, "tasks": ["1", "2", "3"] },
    { "id": 1, "tasks": ["1.1", "2.1", "3.1"] },
    { "id": 2, "tasks": ["4.1", "5.1", "6.1", "7.1"] },
    { "id": 3, "tasks": ["4.2", "4.3", "5.2", "6.2", "7.2"] },
    { "id": 4, "tasks": ["9.1", "10.1"] },
    { "id": 5, "tasks": ["9.2", "9.3", "9.4", "10.2"] },
    { "id": 6, "tasks": ["11.1", "11.2", "11.3", "11.4", "11.5", "11.6", "11.7"] },
    { "id": 7, "tasks": ["11.8", "11.9"] },
    { "id": 8, "tasks": ["12"] },
    { "id": 9, "tasks": ["13.1", "13.2", "13.3", "13.4", "13.5", "13.6"] },
    { "id": 10, "tasks": ["14"] },
    { "id": 11, "tasks": ["15.1", "16.1", "16.3", "16.4"] },
    { "id": 12, "tasks": ["15.2", "16.2"] },
    { "id": 13, "tasks": ["18.1", "18.2", "18.3", "18.4", "18.5", "18.6"] },
    { "id": 14, "tasks": ["19"] }
  ]
}
```
