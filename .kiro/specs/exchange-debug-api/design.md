# Design Document: Exchange Debug API

## Overview

The Exchange Debug API is a diagnostic system that exposes raw, unprocessed responses from the Binance Futures API. This feature enables developers and operations teams to inspect exchange data in its original form, troubleshoot data transformation issues, verify field availability, and diagnose connectivity problems.

### Purpose

The primary purpose of this feature is to provide transparency into the exchange communication layer by:
- Exposing raw JSON responses from Binance Futures API endpoints
- Including request/response timing metrics for performance analysis
- Documenting field mappings between exchange responses and application data models
- Providing detailed error diagnostics when exchange requests fail
- Enabling verification of data availability and format from the exchange

### Key Design Decisions

1. **Read-Only Diagnostic Interface**: All endpoints are GET requests that retrieve data without modifying exchange state
2. **Minimal Data Transformation**: Responses preserve the original exchange data structure with minimal wrapping
3. **Concurrent Request Execution**: The aggregated endpoint fetches multiple data types concurrently to minimize latency
4. **Graceful Error Handling**: Individual endpoint failures in the aggregated endpoint do not prevent other data from being returned
5. **Field Mapping Documentation**: Each response includes metadata showing which exchange fields are used by the application
6. **Symbol Validation**: Input validation occurs before exchange requests to provide clear error messages

### Technology Stack

- **Framework**: FastAPI (existing application framework)
- **Exchange Library**: CCXT (existing exchange connector)
- **HTTP Client**: requests library (for direct Binance API calls where CCXT is insufficient)
- **Data Validation**: Pydantic models for request/response validation
- **Testing**: pytest with Hypothesis for property-based testing

## Architecture

### Component Structure

```
┌─────────────────────────────────────────────────────────────┐
│                     FastAPI Application                      │
│  ┌───────────────────────────────────────────────────────┐  │
│  │              Debug API Router                         │  │
│  │  /api/v1/debug/exchange/*                            │  │
│  └───────────────────────────────────────────────────────┘  │
│                           │                                  │
│                           ▼                                  │
│  ┌───────────────────────────────────────────────────────┐  │
│  │           DebugExchangeService                        │  │
│  │  - fetch_raw_ticker()                                 │  │
│  │  - fetch_raw_open_interest()                          │  │
│  │  - fetch_raw_funding_rate()                           │  │
│  │  - fetch_raw_long_short_ratio()                       │  │
│  │  - fetch_all_raw_data()                               │  │
│  │  - check_exchange_health()                            │  │
│  └───────────────────────────────────────────────────────┘  │
│                           │                                  │
│                           ▼                                  │
│  ┌───────────────────────────────────────────────────────┐  │
│  │         ExchangeConnector (existing)                  │  │
│  │  - CCXT Binance USDT-M Futures instance              │  │
│  └───────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────┘
                           │
                           ▼
              ┌────────────────────────┐
              │   Binance Futures API  │
              │  - Ticker              │
              │  - Open Interest       │
              │  - Funding Rate        │
              │  - Long/Short Ratio    │
              └────────────────────────┘
```

### Request Flow

1. **Client Request**: HTTP GET request to debug endpoint with symbol parameter
2. **Input Validation**: Symbol parameter validated (alphanumeric, length, required)
3. **Symbol Normalization**: Symbol converted to uppercase and trimmed
4. **Timing Start**: Request timestamp recorded
5. **Exchange Request**: Raw request sent to Binance via CCXT or direct HTTP
6. **Timing End**: Response timestamp recorded, latency calculated
7. **Response Construction**: Raw data wrapped with metadata and field mappings
8. **Error Handling**: Exceptions caught and converted to structured error responses
9. **Client Response**: JSON response with raw data, metadata, and field mappings

### Concurrency Model

For the aggregated endpoint (`/api/v1/debug/exchange/all/{symbol}`):
- Uses `asyncio.gather()` to execute all four exchange requests concurrently
- Each request has independent error handling
- Failed requests return error information without blocking successful requests
- Total response time is approximately equal to the slowest individual request

## Components and Interfaces

### API Endpoints

#### 1. Raw Ticker Data Endpoint

**Route**: `GET /api/v1/debug/exchange/ticker/{symbol}`

**Path Parameters**:
- `symbol` (string, required): Trading pair symbol (e.g., "BTCUSDT", "ETHUSDT")

**Response Model**:
```python
{
    "success": bool,
    "data": {
        # Raw CCXT ticker response
        "symbol": str,
        "last": float,
        "percentage": float,
        "quoteVolume": float,
        "baseVolume": float,
        # ... other CCXT ticker fields
    },
    "metadata": {
        "request_timestamp": str,  # ISO 8601
        "response_timestamp": str,  # ISO 8601
        "response_time_ms": float,
        "http_status": int,
        "exchange": str
    },
    "fieldMapping": {
        "last": {
            "app_field": "price",
            "required": true,
            "data_type": "float",
            "description": "Most recent trade price"
        },
        "percentage": {
            "app_field": "change_24h",
            "required": true,
            "data_type": "float",
            "description": "24-hour percentage change"
        },
        "quoteVolume": {
            "app_field": "volume_24h",
            "required": true,
            "data_type": "float",
            "description": "24-hour trading volume in quote currency (USDT)"
        }
    }
}
```

**Error Response**:
```python
{
    "success": false,
    "error": {
        "message": str,
        "code": str
    },
    "metadata": {
        "request_timestamp": str,
        "response_timestamp": str,
        "response_time_ms": float
    }
}
```

#### 2. Raw Open Interest Data Endpoint

**Route**: `GET /api/v1/debug/exchange/open-interest/{symbol}`

**Path Parameters**:
- `symbol` (string, required): Trading pair symbol

**Response Model**: Similar structure to ticker endpoint with open interest specific fields

**Field Mapping**:
```python
"fieldMapping": {
    "openInterestAmount": {
        "app_field": "open_interest",
        "required": false,
        "data_type": "float",
        "description": "Total outstanding derivative contracts"
    },
    "openInterest": {
        "app_field": "open_interest",
        "required": false,
        "data_type": "float",
        "description": "Fallback field for open interest"
    }
}
```

#### 3. Raw Funding Rate Data Endpoint

**Route**: `GET /api/v1/debug/exchange/funding-rate/{symbol}`

**Path Parameters**:
- `symbol` (string, required): Trading pair symbol

**Field Mapping**:
```python
"fieldMapping": {
    "fundingRate": {
        "app_field": "funding_rate",
        "required": true,
        "data_type": "float",
        "description": "Funding rate as decimal (e.g., 0.0001)",
        "transformation": "Multiply by 100 to convert to percentage"
    }
}
```

#### 4. Raw Long/Short Ratio Data Endpoint

**Route**: `GET /api/v1/debug/exchange/long-short-ratio/{symbol}`

**Path Parameters**:
- `symbol` (string, required): Trading pair symbol

**Field Mapping**:
```python
"fieldMapping": {
    "longShortRatio": {
        "app_field": "long_short_ratio",
        "required": true,
        "data_type": "float",
        "description": "Ratio of long positions to short positions from Binance top trader data"
    }
}
```

#### 5. Aggregated Raw Data Endpoint

**Route**: `GET /api/v1/debug/exchange/all/{symbol}`

**Path Parameters**:
- `symbol` (string, required): Trading pair symbol

**Response Model**:
```python
{
    "success": bool,
    "data": {
        "ticker": {
            "success": bool,
            "data": {...},  # Raw ticker response
            "error": {...} | null
        },
        "openInterest": {
            "success": bool,
            "data": {...},  # Raw open interest response
            "error": {...} | null
        },
        "fundingRate": {
            "success": bool,
            "data": {...},  # Raw funding rate response
            "error": {...} | null
        },
        "longShortRatio": {
            "success": bool,
            "data": {...},  # Raw long/short ratio response
            "error": {...} | null
        }
    },
    "metadata": {
        "request_timestamp": str,
        "response_timestamp": str,
        "total_response_time_ms": float,
        "individual_timings": {
            "ticker_ms": float,
            "open_interest_ms": float,
            "funding_rate_ms": float,
            "long_short_ratio_ms": float
        }
    },
    "fieldMapping": {
        "ticker": {...},
        "openInterest": {...},
        "fundingRate": {...},
        "longShortRatio": {...}
    }
}
```

#### 6. Exchange Health Check Endpoint

**Route**: `GET /api/v1/debug/health`

**Response Model**:
```python
{
    "success": bool,
    "data": {
        "status": "connected" | "disconnected",
        "exchange": "binanceusdm",
        "base_url": str,
        "server_timestamp": int,  # Exchange server time in milliseconds
        "available_endpoints": [
            "/api/v1/debug/exchange/ticker/{symbol}",
            "/api/v1/debug/exchange/open-interest/{symbol}",
            "/api/v1/debug/exchange/funding-rate/{symbol}",
            "/api/v1/debug/exchange/long-short-ratio/{symbol}",
            "/api/v1/debug/exchange/all/{symbol}"
        ]
    },
    "metadata": {
        "request_timestamp": str,
        "response_timestamp": str,
        "response_time_ms": float
    }
}
```

### Service Layer

#### DebugExchangeService

**Purpose**: Encapsulates all exchange interaction logic for debug endpoints

**Dependencies**:
- `ExchangeConnector`: Existing CCXT wrapper for Binance Futures
- `requests`: For direct Binance API calls (long/short ratio)

**Methods**:

```python
class DebugExchangeService:
    def __init__(self, exchange_connector: ExchangeConnector):
        self.exchange = exchange_connector.get_exchange()
        self.field_mappings = self._initialize_field_mappings()
    
    async def fetch_raw_ticker(self, symbol: str) -> DebugResponse:
        """Fetch raw ticker data with timing and field mapping."""
        
    async def fetch_raw_open_interest(self, symbol: str) -> DebugResponse:
        """Fetch raw open interest data with timing and field mapping."""
        
    async def fetch_raw_funding_rate(self, symbol: str) -> DebugResponse:
        """Fetch raw funding rate data with timing and field mapping."""
        
    async def fetch_raw_long_short_ratio(self, symbol: str) -> DebugResponse:
        """Fetch raw long/short ratio data with timing and field mapping."""
        
    async def fetch_all_raw_data(self, symbol: str) -> AggregatedDebugResponse:
        """Fetch all raw data types concurrently."""
        
    async def check_exchange_health(self) -> HealthCheckResponse:
        """Check exchange connectivity and return health status."""
        
    def _initialize_field_mappings(self) -> dict:
        """Initialize field mapping documentation for all data types."""
        
    def _measure_request(self, request_func, *args, **kwargs) -> tuple:
        """Wrapper to measure request timing and capture response."""
```

### Data Models

#### Pydantic Models

```python
from pydantic import BaseModel, Field
from typing import Optional, Dict, Any, List
from datetime import datetime

class RequestMetadata(BaseModel):
    request_timestamp: datetime
    response_timestamp: datetime
    response_time_ms: float
    http_status: Optional[int] = None
    exchange: str = "binanceusdm"

class FieldMappingInfo(BaseModel):
    app_field: str
    required: bool
    data_type: str
    description: str
    transformation: Optional[str] = None

class ErrorInfo(BaseModel):
    message: str
    code: str

class DebugResponse(BaseModel):
    success: bool
    data: Optional[Dict[str, Any]] = None
    error: Optional[ErrorInfo] = None
    metadata: RequestMetadata
    fieldMapping: Optional[Dict[str, FieldMappingInfo]] = None

class DataTypeResult(BaseModel):
    success: bool
    data: Optional[Dict[str, Any]] = None
    error: Optional[ErrorInfo] = None

class AggregatedDebugResponse(BaseModel):
    success: bool
    data: Dict[str, DataTypeResult]
    metadata: Dict[str, Any]
    fieldMapping: Dict[str, Dict[str, FieldMappingInfo]]

class HealthCheckResponse(BaseModel):
    success: bool
    data: Dict[str, Any]
    metadata: RequestMetadata
```

### Symbol Validation

**Validation Rules**:
1. Symbol must not be empty or whitespace-only
2. Symbol must contain only alphanumeric characters
3. Symbol must not exceed 20 characters
4. Symbol is trimmed of leading/trailing whitespace
5. Symbol is converted to uppercase before exchange request

**Implementation**:
```python
def validate_symbol(symbol: str) -> tuple[bool, Optional[str]]:
    """
    Validate symbol parameter.
    
    Returns:
        tuple: (is_valid, error_message)
    """
    if not symbol or symbol.strip() == "":
        return False, "Symbol parameter is required"
    
    symbol = symbol.strip()
    
    if len(symbol) > 20:
        return False, "Symbol parameter exceeds maximum length"
    
    if not symbol.isalnum():
        return False, "Symbol must contain only alphanumeric characters"
    
    return True, None

def normalize_symbol(symbol: str) -> str:
    """Normalize symbol to uppercase and trim whitespace."""
    return symbol.strip().upper()
```

## Data Models

### Exchange Response Structures

#### CCXT Ticker Response
```python
{
    "symbol": "BTC/USDT:USDT",
    "timestamp": 1234567890000,
    "datetime": "2024-01-01T00:00:00.000Z",
    "high": 50000.0,
    "low": 49000.0,
    "bid": 49500.0,
    "ask": 49510.0,
    "last": 49505.0,
    "close": 49505.0,
    "baseVolume": 1000.0,
    "quoteVolume": 49505000.0,
    "percentage": 2.5,
    "change": 1200.0,
    "average": 49250.0,
    "info": {...}  # Raw exchange response
}
```

#### CCXT Open Interest Response
```python
{
    "symbol": "BTC/USDT:USDT",
    "timestamp": 1234567890000,
    "datetime": "2024-01-01T00:00:00.000Z",
    "openInterestAmount": 1000000.0,
    "openInterest": 1000000.0,
    "info": {...}  # Raw exchange response
}
```

#### CCXT Funding Rate Response
```python
{
    "symbol": "BTC/USDT:USDT",
    "timestamp": 1234567890000,
    "datetime": "2024-01-01T00:00:00.000Z",
    "fundingRate": 0.0001,
    "fundingTimestamp": 1234567890000,
    "fundingDatetime": "2024-01-01T00:00:00.000Z",
    "info": {...}  # Raw exchange response
}
```

#### Binance Long/Short Ratio Response
```python
[
    {
        "symbol": "BTCUSDT",
        "longShortRatio": 1.5,
        "longAccount": 0.6,
        "shortAccount": 0.4,
        "timestamp": 1234567890000
    }
]
```

### Field Mapping Structure

The field mapping provides documentation of how exchange fields are used by the application:

```python
{
    "exchange_field_name": {
        "app_field": "application_field_name",
        "required": true | false,
        "data_type": "float" | "int" | "str" | "bool",
        "description": "Human-readable description",
        "transformation": "Optional description of transformation applied"
    }
}
```

**Example for Ticker**:
```python
{
    "last": {
        "app_field": "price",
        "required": true,
        "data_type": "float",
        "description": "Most recent trade price"
    },
    "percentage": {
        "app_field": "change_24h",
        "required": true,
        "data_type": "float",
        "description": "24-hour percentage change"
    },
    "quoteVolume": {
        "app_field": "volume_24h",
        "required": true,
        "data_type": "float",
        "description": "24-hour trading volume in quote currency (USDT)"
    },
    "baseVolume": {
        "app_field": "volume_24h",
        "required": false,
        "data_type": "float",
        "description": "Fallback: 24-hour trading volume in base currency"
    }
}
```


## Correctness Properties

*A property is a characteristic or behavior that should hold true across all valid executions of a system—essentially, a formal statement about what the system should do. Properties serve as the bridge between human-readable specifications and machine-verifiable correctness guarantees.*

### Property Reflection

After analyzing all acceptance criteria, I identified the following patterns of redundancy:

**Metadata Properties (1.2, 1.3, 1.4, 2.2, 3.2, 4.2, 7.4, 8.1, 8.3, 8.4)**: Multiple criteria test that metadata fields exist in responses. These can be consolidated into a single comprehensive property about metadata structure.

**Field Mapping Properties (1.5, 2.3, 3.3, 4.3, 5.3, 7.5, 9.1, 9.2, 9.3)**: Multiple criteria test that field mappings are present and properly structured. These can be combined into one property about field mapping completeness.

**Error Handling Properties (1.6, 2.4, 3.4, 4.4, 7.6, 10.5)**: Multiple criteria test that errors are properly included in responses. These can be consolidated into a single property about error response structure.

**Raw Data Return Properties (1.1, 2.1, 3.1, 4.1)**: Each endpoint has a criterion for returning raw data. These can be combined into one property that applies to all data endpoints.

**Response Format Properties (7.1, 7.2, 7.3)**: These test basic response structure and can be combined into one property about response format consistency.

**Symbol Validation Properties (11.1, 11.4, 11.5)**: These test different aspects of symbol validation and normalization that can be combined.

After consolidation, the unique properties are:

1. Raw data retrieval for all endpoint types
2. Complete metadata in all responses
3. Field mapping documentation in data responses
4. Error information in error responses
5. Response format consistency
6. Symbol validation and normalization
7. Concurrent execution efficiency (aggregated endpoint)
8. Timing precision and accuracy
9. Security (no secrets in responses)
10. Request logging

### Property 1: Raw Data Retrieval

*For any* valid symbol and any data endpoint (ticker, open interest, funding rate, long/short ratio), the Debug API SHALL return the unprocessed exchange response in the data field.

**Validates: Requirements 1.1, 2.1, 3.1, 4.1**

### Property 2: Complete Metadata Structure

*For any* request to any debug endpoint, the response SHALL include a metadata object containing request_timestamp (ISO 8601 format), response_timestamp (ISO 8601 format), response_time_ms (positive float with at least 2 decimal places), and exchange identifier, where response_timestamp is after request_timestamp.

**Validates: Requirements 1.2, 1.3, 1.4, 2.2, 3.2, 4.2, 7.4, 8.1, 8.2, 8.3, 8.4**

### Property 3: Field Mapping Documentation

*For any* data endpoint response (ticker, open interest, funding rate, long/short ratio), the response SHALL include a fieldMapping object where each entry contains app_field (string), required (boolean), data_type (string), description (string), and optionally transformation (string) for fields that undergo transformation.

**Validates: Requirements 1.5, 2.3, 3.3, 4.3, 5.3, 7.5, 9.1, 9.2, 9.3, 9.4**

### Property 4: Error Response Structure

*For any* request that results in an error, the response SHALL include success=false, an error object with message and code fields, and SHALL preserve the original exchange error response in the data field when available.

**Validates: Requirements 1.6, 2.4, 3.4, 4.4, 7.6, 10.5, 10.6**

### Property 5: Response Format Consistency

*For any* debug endpoint, the response SHALL be in JSON format with Content-Type application/json, SHALL include a success boolean field, and SHALL include either a data object (on success) or an error object (on failure).

**Validates: Requirements 7.1, 7.2, 7.3**

### Property 6: Symbol Validation and Normalization

*For any* symbol parameter provided to a data endpoint, the Debug API SHALL trim whitespace, convert to uppercase, validate that it contains only alphanumeric characters and does not exceed 20 characters, and return a 400 status with descriptive error message if validation fails.

**Validates: Requirements 1.7, 11.1, 11.4, 11.5**

### Property 7: Aggregated Endpoint Completeness

*For any* valid symbol, the aggregated endpoint (/all) SHALL return results for all four data types (ticker, open interest, funding rate, long/short ratio), SHALL include individual timing information for each data type, and SHALL include field mappings for all data types.

**Validates: Requirements 5.1, 5.2, 5.3, 8.5**

### Property 8: Graceful Partial Failure Handling

*For any* request to the aggregated endpoint where one or more data type requests fail, the Debug API SHALL include error information for failed requests in their respective data sections while successfully returning data for requests that succeed.

**Validates: Requirements 5.4**

### Property 9: Concurrent Execution Efficiency

*For any* request to the aggregated endpoint, the total response time SHALL be less than or equal to the maximum individual data type response time plus reasonable overhead (< 100ms), demonstrating concurrent rather than sequential execution.

**Validates: Requirements 5.5**

### Property 10: HTTP Status Code Mapping

*For any* error condition, the Debug API SHALL return appropriate HTTP status codes: 400 for invalid input (empty symbol, invalid characters, exceeds length), 401 for authentication failures (when auth is enabled), 503 for exchange connectivity issues (DNS errors, connection failures), and 504 for timeout errors.

**Validates: Requirements 2.5, 10.3, 10.4**

### Property 11: Security - No Secrets in Responses

*For any* response from any debug endpoint, the response SHALL NOT contain API keys, secrets, authentication tokens, or other sensitive credentials.

**Validates: Requirements 12.3**

### Property 12: Request Logging

*For any* request to any debug endpoint, the Debug API SHALL log the request with requester identity (when available) and timestamp.

**Validates: Requirements 12.4**

## Error Handling

### Error Categories

The Debug API handles errors in the following categories:

#### 1. Input Validation Errors (HTTP 400)

**Triggers**:
- Empty or whitespace-only symbol parameter
- Symbol contains non-alphanumeric characters
- Symbol exceeds 20 characters

**Response Structure**:
```python
{
    "success": false,
    "error": {
        "message": "Symbol parameter is required" | 
                   "Symbol must contain only alphanumeric characters" |
                   "Symbol parameter exceeds maximum length",
        "code": "INVALID_INPUT"
    },
    "metadata": {
        "request_timestamp": "2024-01-01T00:00:00.000Z",
        "response_timestamp": "2024-01-01T00:00:00.050Z",
        "response_time_ms": 50.0,
        "exchange": "binanceusdm"
    }
}
```

#### 2. Authentication Errors (HTTP 401)

**Triggers** (when authentication is enabled):
- Missing authentication credentials
- Invalid authentication credentials

**Response Structure**:
```python
{
    "success": false,
    "error": {
        "message": "Authentication required",
        "code": "UNAUTHORIZED"
    },
    "metadata": {...}
}
```

#### 3. Exchange Client Errors (HTTP 4xx from exchange)

**Triggers**:
- Invalid symbol not supported by exchange
- Rate limit exceeded by exchange
- Invalid request parameters

**Response Structure**:
```python
{
    "success": false,
    "error": {
        "message": "Exchange error: {original_error_message}",
        "code": "EXCHANGE_ERROR",
        "exchange_status": 400  # Original exchange status code
    },
    "data": {...},  # Original exchange error response preserved
    "metadata": {...}
}
```

#### 4. Exchange Server Errors (HTTP 5xx from exchange)

**Triggers**:
- Exchange API server errors
- Exchange maintenance mode

**Response Structure**:
```python
{
    "success": false,
    "error": {
        "message": "Exchange server error: {original_error_message}",
        "code": "EXCHANGE_SERVER_ERROR",
        "exchange_status": 500
    },
    "data": {...},  # Original exchange error response preserved
    "metadata": {...}
}
```

#### 5. Connectivity Errors (HTTP 503)

**Triggers**:
- DNS resolution failure
- Connection refused
- Network unreachable
- Exchange unavailable

**Response Structure**:
```python
{
    "success": false,
    "error": {
        "message": "Service unavailable: Cannot connect to exchange",
        "code": "SERVICE_UNAVAILABLE",
        "details": "DNS resolution failed" | "Connection refused" | ...
    },
    "metadata": {...}
}
```

#### 6. Timeout Errors (HTTP 504)

**Triggers**:
- Exchange request timeout (> 10 seconds)
- Network timeout

**Response Structure**:
```python
{
    "success": false,
    "error": {
        "message": "Gateway timeout: Exchange request timed out",
        "code": "GATEWAY_TIMEOUT",
        "timeout_duration_ms": 10000.0
    },
    "metadata": {...}
}
```

#### 7. Internal Server Errors (HTTP 500)

**Triggers**:
- Unexpected exceptions during request processing
- Programming errors
- Unhandled edge cases

**Response Structure**:
```python
{
    "success": false,
    "error": {
        "message": "Internal server error: An unexpected error occurred",
        "code": "INTERNAL_ERROR"
    },
    "metadata": {...}
}
```

**Logging**: Full stack trace logged server-side, sanitized message returned to client

### Error Handling Strategy

1. **Validation First**: Input validation occurs before any exchange requests
2. **Preserve Original Errors**: Exchange error responses are preserved in the data field
3. **Consistent Structure**: All error responses follow the same structure
4. **Detailed Logging**: All errors are logged with full context and stack traces
5. **Graceful Degradation**: In the aggregated endpoint, individual failures don't prevent other data from being returned
6. **Security**: Internal error details are sanitized before being sent to clients

### Exception Handling Flow

```python
try:
    # Validate input
    validate_symbol(symbol)
    
    # Measure timing
    start_time = datetime.now()
    
    # Make exchange request
    raw_data = await exchange.fetch_ticker(symbol)
    
    # Calculate timing
    end_time = datetime.now()
    response_time_ms = (end_time - start_time).total_seconds() * 1000
    
    # Build success response
    return DebugResponse(
        success=True,
        data=raw_data,
        metadata=RequestMetadata(...),
        fieldMapping=field_mappings['ticker']
    )
    
except ValidationError as e:
    # 400 - Input validation error
    return JSONResponse(
        status_code=400,
        content=DebugResponse(
            success=False,
            error=ErrorInfo(message=str(e), code="INVALID_INPUT"),
            metadata=RequestMetadata(...)
        ).dict()
    )
    
except ccxt.NetworkError as e:
    # 503 - Network/connectivity error
    logger.error(f"Network error: {e}", exc_info=True)
    return JSONResponse(
        status_code=503,
        content=DebugResponse(
            success=False,
            error=ErrorInfo(
                message=f"Service unavailable: {str(e)}",
                code="SERVICE_UNAVAILABLE"
            ),
            metadata=RequestMetadata(...)
        ).dict()
    )
    
except ccxt.RequestTimeout as e:
    # 504 - Timeout error
    logger.error(f"Request timeout: {e}", exc_info=True)
    return JSONResponse(
        status_code=504,
        content=DebugResponse(
            success=False,
            error=ErrorInfo(
                message="Gateway timeout: Exchange request timed out",
                code="GATEWAY_TIMEOUT"
            ),
            metadata=RequestMetadata(...)
        ).dict()
    )
    
except ccxt.ExchangeError as e:
    # Exchange-specific error (4xx or 5xx)
    status_code = 502  # Bad Gateway as default
    if hasattr(e, 'status_code'):
        status_code = e.status_code
    
    logger.error(f"Exchange error: {e}", exc_info=True)
    return JSONResponse(
        status_code=status_code,
        content=DebugResponse(
            success=False,
            error=ErrorInfo(
                message=f"Exchange error: {str(e)}",
                code="EXCHANGE_ERROR"
            ),
            data=getattr(e, 'response', None),
            metadata=RequestMetadata(...)
        ).dict()
    )
    
except Exception as e:
    # 500 - Unexpected internal error
    logger.error(f"Internal error: {e}", exc_info=True)
    return JSONResponse(
        status_code=500,
        content=DebugResponse(
            success=False,
            error=ErrorInfo(
                message="Internal server error: An unexpected error occurred",
                code="INTERNAL_ERROR"
            ),
            metadata=RequestMetadata(...)
        ).dict()
    )
```

## Testing Strategy

### Testing Approach

The Exchange Debug API will be tested using a dual testing approach:

1. **Property-Based Tests**: Verify universal properties across all inputs using Hypothesis
2. **Example-Based Unit Tests**: Test specific scenarios, edge cases, and error conditions
3. **Integration Tests**: Test authentication and rate limiting when configured

### Property-Based Testing

**Library**: Hypothesis (already in requirements.txt)

**Configuration**: Minimum 100 iterations per property test

**Test Tag Format**: Each property test will include a comment:
```python
# Feature: exchange-debug-api, Property {number}: {property_text}
```

**Property Test Coverage**:

1. **Property 1 - Raw Data Retrieval**: Generate random valid symbols, test all four data endpoints, verify raw data is returned
2. **Property 2 - Complete Metadata Structure**: Generate random requests, verify metadata structure and field types
3. **Property 3 - Field Mapping Documentation**: Generate random data endpoint requests, verify field mapping structure
4. **Property 4 - Error Response Structure**: Generate error conditions, verify error response structure
5. **Property 5 - Response Format Consistency**: Generate random endpoint requests, verify JSON format and structure
6. **Property 6 - Symbol Validation**: Generate invalid symbols (special chars, too long, empty), verify validation
7. **Property 7 - Aggregated Endpoint Completeness**: Generate random symbols, verify all four data types returned
8. **Property 8 - Graceful Partial Failure**: Simulate partial failures, verify other data types succeed
9. **Property 9 - Concurrent Execution Efficiency**: Measure timing, verify concurrent execution
10. **Property 10 - HTTP Status Code Mapping**: Generate various error conditions, verify correct status codes
11. **Property 11 - Security**: Generate random responses, verify no secrets present
12. **Property 12 - Request Logging**: Generate random requests, verify logging occurs

**Hypothesis Strategies**:

```python
from hypothesis import strategies as st

# Valid symbol strategy
valid_symbols = st.text(
    alphabet=st.characters(whitelist_categories=('Lu', 'Nd')),  # Uppercase + digits
    min_size=1,
    max_size=20
)

# Invalid symbol strategies
invalid_symbols_special_chars = st.text(
    alphabet=st.characters(blacklist_categories=('Lu', 'Ll', 'Nd')),
    min_size=1,
    max_size=20
)

invalid_symbols_too_long = st.text(
    alphabet=st.characters(whitelist_categories=('Lu', 'Nd')),
    min_size=21,
    max_size=50
)

invalid_symbols_empty = st.just("") | st.text(
    alphabet=st.just(" "),
    min_size=1,
    max_size=10
)

# Endpoint strategy
endpoints = st.sampled_from([
    'ticker',
    'open-interest',
    'funding-rate',
    'long-short-ratio'
])
```

### Example-Based Unit Tests

**Coverage**:

1. **Health Check Endpoint**: Test successful health check, test exchange unavailable scenario
2. **Empty Symbol Validation**: Test empty string, whitespace-only string
3. **Symbol Length Validation**: Test 21-character symbol, test 20-character symbol (boundary)
4. **Specific Error Messages**: Verify exact error messages for validation failures
5. **Timeout Handling**: Simulate timeout, verify 504 response
6. **DNS Error Handling**: Simulate DNS failure, verify 503 response
7. **Whitespace Trimming**: Test symbols with leading/trailing whitespace
8. **Case Conversion**: Test lowercase and mixed-case symbols

### Integration Tests

**Coverage** (when features are enabled):

1. **Authentication**: Test with valid credentials, test with invalid credentials, test without credentials
2. **Rate Limiting**: Test rapid requests, verify rate limit enforcement

### Mock Strategy

For unit and property tests:
- Mock CCXT exchange instance to avoid real API calls
- Mock responses with realistic exchange data structures
- Simulate various error conditions (timeouts, network errors, exchange errors)
- Control timing for concurrent execution tests

### Test Organization

```
tests/
├── unit/
│   ├── test_debug_api_routes.py          # Route handler tests
│   ├── test_debug_exchange_service.py    # Service layer tests
│   ├── test_symbol_validation.py         # Validation logic tests
│   └── test_field_mappings.py            # Field mapping tests
├── property/
│   ├── test_properties_raw_data.py       # Property 1
│   ├── test_properties_metadata.py       # Property 2
│   ├── test_properties_field_mapping.py  # Property 3
│   ├── test_properties_errors.py         # Properties 4, 10
│   ├── test_properties_format.py         # Property 5
│   ├── test_properties_validation.py     # Property 6
│   ├── test_properties_aggregated.py     # Properties 7, 8, 9
│   └── test_properties_security.py       # Properties 11, 12
└── integration/
    ├── test_authentication.py            # Auth integration tests
    └── test_rate_limiting.py             # Rate limit integration tests
```

### Test Execution

```bash
# Run all tests
pytest tests/

# Run only property-based tests
pytest tests/property/

# Run only unit tests
pytest tests/unit/

# Run with coverage
pytest --cov=src.api.debug --cov-report=html tests/

# Run property tests with verbose output
pytest tests/property/ -v --hypothesis-show-statistics
```

### Continuous Integration

Property-based tests will run in CI with:
- Minimum 100 iterations per property
- Hypothesis database enabled to track found failures
- Seed randomization for comprehensive coverage
- Failure reproduction via Hypothesis examples

## Implementation Notes

### File Structure

```
src/
├── api/
│   ├── debug/
│   │   ├── __init__.py
│   │   ├── routes.py              # Debug API route handlers
│   │   ├── models.py              # Pydantic models for debug responses
│   │   └── service.py             # DebugExchangeService
│   ├── app.py                     # Main FastAPI app (existing)
│   └── routes.py                  # Main routes (existing)
└── exchange/
    └── connector.py               # ExchangeConnector (existing)
```

### Dependencies

All required dependencies are already in `requirements.txt`:
- `fastapi>=0.104.0` - Web framework
- `pydantic>=2.5.0` - Data validation
- `ccxt==4.2.25` - Exchange connector
- `hypothesis>=6.92.0` - Property-based testing
- `pytest>=7.4.0` - Testing framework

### Configuration

No new configuration required. The debug API will use the existing:
- `ExchangeConnector` instance from application state
- Logging configuration from `src/config/logging_config.py`
- Settings from `src/config/settings.py`

### Security Considerations

1. **No Secrets in Responses**: All responses are sanitized to remove API keys and secrets
2. **Authentication Support**: When authentication is enabled, all debug endpoints require valid credentials
3. **Rate Limiting Support**: When rate limiting is configured, debug endpoints are rate-limited
4. **Logging**: All access is logged with requester identity and timestamp
5. **Error Sanitization**: Internal error details are sanitized before being sent to clients

### Performance Considerations

1. **Concurrent Execution**: The aggregated endpoint uses `asyncio.gather()` for concurrent requests
2. **Timeout Configuration**: All exchange requests have 10-second timeouts
3. **No Caching**: Debug endpoints always fetch fresh data (no caching layer)
4. **Minimal Overhead**: Response wrapping adds < 10ms overhead

### Deployment Considerations

1. **Backward Compatibility**: Debug endpoints are additive and don't affect existing API
2. **Feature Flag**: Consider adding a feature flag to enable/disable debug endpoints in production
3. **Access Control**: In production, restrict debug endpoint access to authorized users only
4. **Monitoring**: Monitor debug endpoint usage and response times
5. **Documentation**: Include debug endpoints in API documentation (OpenAPI/Swagger)

