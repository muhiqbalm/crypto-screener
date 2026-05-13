"""Rate limiting middleware for debug API endpoints.

Provides configurable rate limiting to prevent abuse of debug endpoints.
Uses a sliding window algorithm with in-memory storage of request timestamps.
"""

import logging
import time
from collections import defaultdict, deque
from typing import Deque, Dict

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.responses import JSONResponse

logger = logging.getLogger(__name__)


class RateLimitMiddleware(BaseHTTPMiddleware):
    """Middleware that enforces rate limits on debug API endpoints.
    
    Uses a sliding window algorithm to track requests per client IP address.
    When rate limit is exceeded, returns 429 Too Many Requests.
    
    Attributes:
        max_requests: Maximum number of requests allowed in the time window
        window_seconds: Time window in seconds for rate limiting
        request_history: Dictionary mapping client IPs to deques of request timestamps
    """

    def __init__(
        self,
        app,
        max_requests: int = 10,
        window_seconds: int = 60,
    ):
        """Initialize rate limiting middleware.
        
        Args:
            app: FastAPI application instance
            max_requests: Maximum number of requests allowed in the time window
            window_seconds: Time window in seconds for rate limiting
        """
        super().__init__(app)
        self.max_requests = max_requests
        self.window_seconds = window_seconds
        # Dictionary mapping client IP to deque of request timestamps
        self.request_history: Dict[str, Deque[float]] = defaultdict(deque)
        logger.info(
            f"Rate limiting enabled: {max_requests} requests per {window_seconds} seconds"
        )

    def _get_client_identifier(self, request: Request) -> str:
        """Get unique identifier for the client.
        
        Uses X-Forwarded-For header if available (for proxied requests),
        otherwise falls back to client IP address.
        
        Args:
            request: FastAPI request object
            
        Returns:
            Client identifier (IP address)
        """
        # Check for X-Forwarded-For header (for proxied requests)
        forwarded_for = request.headers.get("X-Forwarded-For")
        if forwarded_for:
            # X-Forwarded-For can contain multiple IPs, use the first one
            return forwarded_for.split(",")[0].strip()
        
        # Fall back to direct client IP
        if request.client:
            return request.client.host
        
        # Fallback if client info is not available
        return "unknown"

    def _is_rate_limited(self, client_id: str) -> bool:
        """Check if client has exceeded rate limit.
        
        Uses sliding window algorithm: removes timestamps older than the window,
        then checks if remaining request count exceeds the limit.
        
        Args:
            client_id: Client identifier (IP address)
            
        Returns:
            True if client is rate limited, False otherwise
        """
        current_time = time.time()
        window_start = current_time - self.window_seconds
        
        # Get request history for this client
        history = self.request_history[client_id]
        
        # Remove timestamps outside the current window
        while history and history[0] < window_start:
            history.popleft()
        
        # Check if client has exceeded rate limit
        if len(history) >= self.max_requests:
            return True
        
        # Add current request timestamp
        history.append(current_time)
        return False

    def _should_apply_rate_limit(self, request: Request) -> bool:
        """Determine if rate limiting should be applied to this request.
        
        Rate limiting is only applied to debug API endpoints (paths starting with /api/v1/debug).
        
        Args:
            request: FastAPI request object
            
        Returns:
            True if rate limiting should be applied, False otherwise
        """
        return request.url.path.startswith("/api/v1/debug")

    async def dispatch(
        self, request: Request, call_next: RequestResponseEndpoint
    ) -> Response:
        """Process request and enforce rate limiting.
        
        Args:
            request: FastAPI request object
            call_next: Next middleware or route handler
            
        Returns:
            Response from next handler, or 429 error if rate limited
        """
        # Only apply rate limiting to debug endpoints
        if not self._should_apply_rate_limit(request):
            return await call_next(request)
        
        # Get client identifier
        client_id = self._get_client_identifier(request)
        
        # Check if client is rate limited
        if self._is_rate_limited(client_id):
            logger.warning(
                f"Rate limit exceeded for client {client_id}",
                extra={
                    "client_id": client_id,
                    "endpoint": request.url.path,
                    "method": request.method,
                },
            )
            return JSONResponse(
                status_code=429,
                content={
                    "success": False,
                    "error": {
                        "message": f"Rate limit exceeded. Maximum {self.max_requests} requests per {self.window_seconds} seconds.",
                        "code": "RATE_LIMIT_EXCEEDED",
                    },
                },
            )
        
        # Process request normally
        return await call_next(request)
