"""Rate limiting middleware for debug API endpoints.

Provides configurable rate limiting to prevent abuse of debug endpoints.
Uses a sliding window algorithm with in-memory storage of request timestamps.
"""

import logging
import time
from collections import defaultdict, deque
from typing import Deque, Dict, Iterable, Optional

from fastapi import Request
from starlette.types import ASGIApp, Receive, Scope, Send
from starlette.responses import JSONResponse

logger = logging.getLogger(__name__)


class RateLimitMiddleware:
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
        path_prefixes: Iterable[str] = ("/api/v1/debug",),
        methods: Optional[Iterable[str]] = None,
    ):
        """Initialize rate limiting middleware.
        
        Args:
            app: FastAPI application instance
            max_requests: Maximum number of requests allowed in the time window
            window_seconds: Time window in seconds for rate limiting
        """
        self.app = app
        self.max_requests = max_requests
        self.window_seconds = window_seconds
        self.path_prefixes = tuple(path_prefixes)
        self.methods = frozenset(m.upper() for m in methods) if methods else None
        # Dictionary mapping client IP to deque of request timestamps
        self.request_history: Dict[str, Deque[float]] = defaultdict(deque)
        
        # Cleanup configuration
        self._request_count = 0
        self._cleanup_threshold = 100
        
        logger.info(
            f"Rate limiting enabled: {max_requests} requests per {window_seconds} seconds"
        )

    @property
    def active_clients(self) -> int:
        """Return the number of clients currently tracked in memory."""
        return len(self.request_history)

    def _cleanup_inactive_clients(self) -> None:
        """Remove clients that haven't made any requests in the cleanup window."""
        current_time = time.time()
        # Inactive if no requests in 2x window_seconds
        inactive_threshold = current_time - (self.window_seconds * 2)
        
        # Collect keys to remove to avoid modifying dict during iteration
        to_remove = []
        for client_id, history in self.request_history.items():
            # If history is empty or the most recent request is older than threshold
            if not history or history[-1] < inactive_threshold:
                to_remove.append(client_id)
                
        for client_id in to_remove:
            del self.request_history[client_id]
            
        if to_remove:
            logger.debug(f"Cleaned up {len(to_remove)} inactive rate limit entries")

    def _get_client_identifier(self, request: Request) -> str:
        """Get the client IP as observed by the reverse proxy.

        The app only listens on 127.0.0.1 behind nginx, which *overwrites*
        ``X-Real-IP`` with ``$remote_addr`` and *appends* ``$remote_addr`` to
        ``X-Forwarded-For``.  The first XFF hop is client-controlled (anyone
        can send ``X-Forwarded-For: 1.2.3.4`` to get a fresh bucket), so we
        use X-Real-IP, then the last XFF hop, then the socket peer.
        """
        real_ip = request.headers.get("X-Real-IP")
        if real_ip and real_ip.strip():
            return real_ip.strip()

        forwarded_for = request.headers.get("X-Forwarded-For")
        if forwarded_for:
            hops = [h.strip() for h in forwarded_for.split(",") if h.strip()]
            if hops:
                return hops[-1]

        if request.client:
            return request.client.host

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
        
        Applied only to paths under ``path_prefixes`` (default: /api/v1/debug)
        and, when ``methods`` is set, only to those HTTP methods.
        
        Args:
            request: FastAPI request object
            
        Returns:
            True if rate limiting should be applied, False otherwise
        """
        if self.methods is not None and request.method.upper() not in self.methods:
            return False
        return request.url.path.startswith(self.path_prefixes)

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        """Pure ASGI entry point: non-matching requests pass straight through.

        Implemented as plain ASGI (not BaseHTTPMiddleware) so unrelated routes
        — notably the latency-sensitive TradingView webhook — pay no extra
        request/response wrapping cost.
        """
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        request = Request(scope)
        if not self._should_apply_rate_limit(request):
            await self.app(scope, receive, send)
            return

        client_id = self._get_client_identifier(request)

        if self._is_rate_limited(client_id):
            logger.warning(
                f"Rate limit exceeded for client {client_id}",
                extra={
                    "client_id": client_id,
                    "endpoint": request.url.path,
                    "method": request.method,
                },
            )
            response = JSONResponse(
                status_code=429,
                content={
                    "success": False,
                    "error": {
                        "message": f"Rate limit exceeded. Maximum {self.max_requests} requests per {self.window_seconds} seconds.",
                        "code": "RATE_LIMIT_EXCEEDED",
                    },
                },
                headers={"Retry-After": str(self.window_seconds)},
            )
            await response(scope, receive, send)
            return

        self._request_count += 1
        if self._request_count >= self._cleanup_threshold:
            self._cleanup_inactive_clients()
            self._request_count = 0

        await self.app(scope, receive, send)


class AuthRateLimitMiddleware(RateLimitMiddleware):
    """Per-IP limiter for the public auth endpoints (login/refresh/register).

    Separate class so it can be registered alongside the debug limiter and
    identified independently in ``app.user_middleware``.
    """
