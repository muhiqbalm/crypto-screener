"""Pydantic models for debug API responses.

Defines all request/response schemas used by the debug endpoints.
These models provide structured responses for raw exchange data inspection,
including metadata, field mappings, and error information.
"""

from datetime import datetime
from typing import Any, Dict, Optional

from pydantic import BaseModel, ConfigDict, Field


class RequestMetadata(BaseModel):
    """Metadata included in debug API responses.
    
    Contains timing information and exchange details for diagnostic purposes.
    """

    model_config = ConfigDict(
        from_attributes=True,
        json_schema_extra={
            "example": {
                "request_timestamp": "2024-01-15T10:30:00.000Z",
                "response_timestamp": "2024-01-15T10:30:00.250Z",
                "response_time_ms": 250.45,
                "http_status": 200,
                "exchange": "binanceusdm"
            }
        }
    )

    request_timestamp: datetime = Field(
        ...,
        description="ISO 8601 timestamp when the request was initiated",
        examples=["2024-01-15T10:30:00.000Z"]
    )
    response_timestamp: datetime = Field(
        ...,
        description="ISO 8601 timestamp when the response was received",
        examples=["2024-01-15T10:30:00.250Z"]
    )
    response_time_ms: float = Field(
        ...,
        description="Response time in milliseconds with at least 2 decimal places precision",
        ge=0.0,
        examples=[250.45]
    )
    http_status: Optional[int] = Field(
        None,
        description="HTTP status code from the exchange API",
        examples=[200]
    )
    exchange: str = Field(
        default="binanceusdm",
        description="Exchange identifier",
        examples=["binanceusdm"]
    )


class FieldMappingInfo(BaseModel):
    """Information about how an exchange field maps to application fields.
    
    Documents the relationship between raw exchange data and application data models.
    """

    model_config = ConfigDict(
        from_attributes=True,
        json_schema_extra={
            "example": {
                "app_field": "price",
                "required": True,
                "data_type": "float",
                "description": "Most recent trade price",
                "transformation": None
            }
        }
    )

    app_field: str = Field(
        ...,
        description="Application field name that uses this exchange field",
        examples=["price", "volume_24h", "funding_rate"]
    )
    required: bool = Field(
        ...,
        description="Whether this field is required for the application to function",
        examples=[True, False]
    )
    data_type: str = Field(
        ...,
        description="Expected data type (float, int, str, bool)",
        examples=["float", "int", "str", "bool"]
    )
    description: str = Field(
        ...,
        description="Human-readable description of the field's purpose",
        examples=["Most recent trade price", "24-hour trading volume in USDT"]
    )
    transformation: Optional[str] = Field(
        None,
        description="Description of any transformation applied to the field",
        examples=["Multiply by 100 to convert to percentage", None]
    )


class ErrorInfo(BaseModel):
    """Error information for failed requests.
    
    Provides structured error details for debugging and diagnostics.
    """

    model_config = ConfigDict(
        from_attributes=True,
        json_schema_extra={
            "example": {
                "message": "Symbol parameter is required",
                "code": "INVALID_INPUT",
                "timeout_duration_ms": None,
                "details": None
            }
        }
    )

    message: str = Field(
        ...,
        description="Human-readable error message",
        examples=["Symbol parameter is required", "Exchange error: Invalid symbol"]
    )
    code: str = Field(
        ...,
        description="Machine-readable error code",
        examples=["INVALID_INPUT", "EXCHANGE_ERROR", "SERVICE_UNAVAILABLE", "GATEWAY_TIMEOUT"]
    )
    timeout_duration_ms: Optional[float] = Field(
        None,
        description="Timeout duration in milliseconds (only present for timeout errors)",
        examples=[10000.0]
    )
    details: Optional[str] = Field(
        None,
        description="Additional error details (e.g., 'DNS resolution failed', 'Connection refused')",
        examples=["DNS resolution failed", "Connection refused"]
    )


class DebugResponse(BaseModel):
    """Standard debug response for individual data type endpoints.
    
    Contains raw exchange data, metadata, field mappings, and error information.
    """

    model_config = ConfigDict(
        from_attributes=True,
        json_schema_extra={
            "example": {
                "success": True,
                "data": {
                    "symbol": "BTC/USDT:USDT",
                    "last": 45000.50,
                    "percentage": 2.5,
                    "quoteVolume": 1500000000.0,
                    "baseVolume": 33333.33
                },
                "error": None,
                "metadata": {
                    "request_timestamp": "2024-01-15T10:30:00.000Z",
                    "response_timestamp": "2024-01-15T10:30:00.250Z",
                    "response_time_ms": 250.45,
                    "http_status": 200,
                    "exchange": "binanceusdm"
                },
                "fieldMapping": {
                    "last": {
                        "app_field": "price",
                        "required": True,
                        "data_type": "float",
                        "description": "Most recent trade price"
                    },
                    "percentage": {
                        "app_field": "change_24h",
                        "required": True,
                        "data_type": "float",
                        "description": "24-hour percentage change"
                    }
                }
            }
        }
    )

    success: bool = Field(
        ...,
        description="Whether the request was successful",
        examples=[True, False]
    )
    data: Optional[Dict[str, Any]] = Field(
        None,
        description="Raw exchange response data (null on error)"
    )
    error: Optional[ErrorInfo] = Field(
        None,
        description="Error information (null on success)"
    )
    metadata: RequestMetadata = Field(
        ...,
        description="Request timing and exchange metadata"
    )
    fieldMapping: Optional[Dict[str, FieldMappingInfo]] = Field(
        None,
        description="Mapping of exchange fields to application fields"
    )


class DataTypeResult(BaseModel):
    """Result for a single data type in the aggregated endpoint.
    
    Used within AggregatedDebugResponse to represent individual data type results.
    """

    model_config = ConfigDict(
        from_attributes=True,
        json_schema_extra={
            "example": {
                "success": True,
                "data": {
                    "symbol": "BTC/USDT:USDT",
                    "last": 45000.50,
                    "percentage": 2.5
                },
                "error": None
            }
        }
    )

    success: bool = Field(
        ...,
        description="Whether this specific data type request was successful",
        examples=[True, False]
    )
    data: Optional[Dict[str, Any]] = Field(
        None,
        description="Raw exchange response data for this data type (null on error)"
    )
    error: Optional[ErrorInfo] = Field(
        None,
        description="Error information for this data type (null on success)"
    )


class AggregatedDebugResponse(BaseModel):
    """Response for the aggregated debug endpoint (/all).
    
    Contains results for all four data types (ticker, open interest, funding rate,
    long/short ratio) with individual timing information and field mappings.
    """

    model_config = ConfigDict(
        from_attributes=True,
        json_schema_extra={
            "example": {
                "success": True,
                "data": {
                    "ticker": {
                        "success": True,
                        "data": {"symbol": "BTC/USDT:USDT", "last": 45000.50},
                        "error": None
                    },
                    "openInterest": {
                        "success": True,
                        "data": {"openInterestAmount": 1000000.0},
                        "error": None
                    },
                    "fundingRate": {
                        "success": True,
                        "data": {"fundingRate": 0.0001},
                        "error": None
                    },
                    "longShortRatio": {
                        "success": True,
                        "data": {"longShortRatio": 1.5},
                        "error": None
                    }
                },
                "metadata": {
                    "request_timestamp": "2024-01-15T10:30:00.000Z",
                    "response_timestamp": "2024-01-15T10:30:00.500Z",
                    "total_response_time_ms": 500.0,
                    "individual_timings": {
                        "ticker_ms": 250.0,
                        "open_interest_ms": 300.0,
                        "funding_rate_ms": 280.0,
                        "long_short_ratio_ms": 320.0
                    }
                },
                "fieldMapping": {
                    "ticker": {
                        "last": {
                            "app_field": "price",
                            "required": True,
                            "data_type": "float",
                            "description": "Most recent trade price"
                        }
                    }
                }
            }
        }
    )

    success: bool = Field(
        ...,
        description="Whether the overall request was successful (true if any data type succeeded)",
        examples=[True, False]
    )
    data: Dict[str, DataTypeResult] = Field(
        ...,
        description="Results for each data type (ticker, openInterest, fundingRate, longShortRatio)"
    )
    metadata: Dict[str, Any] = Field(
        ...,
        description="Request metadata including individual timings for each data type"
    )
    fieldMapping: Dict[str, Dict[str, FieldMappingInfo]] = Field(
        ...,
        description="Field mappings for all data types"
    )


class HealthCheckResponse(BaseModel):
    """Response for the exchange health check endpoint.
    
    Provides connection status and available endpoint information.
    """

    model_config = ConfigDict(
        from_attributes=True,
        json_schema_extra={
            "example": {
                "success": True,
                "data": {
                    "status": "connected",
                    "exchange": "binanceusdm",
                    "base_url": "https://fapi.binance.com",
                    "server_timestamp": 1705315800000,
                    "available_endpoints": [
                        "/api/v1/debug/exchange/ticker/{symbol}",
                        "/api/v1/debug/exchange/open-interest/{symbol}",
                        "/api/v1/debug/exchange/funding-rate/{symbol}",
                        "/api/v1/debug/exchange/long-short-ratio/{symbol}",
                        "/api/v1/debug/exchange/all/{symbol}"
                    ]
                },
                "metadata": {
                    "request_timestamp": "2024-01-15T10:30:00.000Z",
                    "response_timestamp": "2024-01-15T10:30:00.150Z",
                    "response_time_ms": 150.0,
                    "http_status": 200,
                    "exchange": "binanceusdm"
                }
            }
        }
    )

    success: bool = Field(
        ...,
        description="Whether the health check was successful",
        examples=[True, False]
    )
    data: Dict[str, Any] = Field(
        ...,
        description="Health check data including status, exchange info, and available endpoints"
    )
    metadata: RequestMetadata = Field(
        ...,
        description="Request timing metadata"
    )
