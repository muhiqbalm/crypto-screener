"""TTL-based in-memory cache manager for processed screener results.

Provides thread-safe caching with configurable TTL to prevent
exchange rate limit violations while maintaining data freshness.
"""

import threading
from datetime import datetime, timedelta
from typing import Optional

from src.services.models import CacheEntry, ProcessedResult


class CacheManager:
    """Manages a single cached ProcessedResult with TTL-based expiration.

    The cache stores one entry (the full screener result for all symbols)
    and uses a threading lock for safe concurrent access.
    """

    def __init__(self, ttl: int = 60) -> None:
        """Initialize the cache manager.

        Args:
            ttl: Time-to-live in seconds for cached entries. Defaults to 60.
        """
        self._ttl = ttl
        self._entry: Optional[CacheEntry] = None
        self._lock = threading.Lock()

    def get(self) -> Optional[CacheEntry]:
        """Return the cached entry if it exists and is not expired.

        Returns:
            The CacheEntry if valid, or None if the cache is empty or expired.
        """
        with self._lock:
            if self._entry is None:
                return None
            if self._entry.is_expired:
                return None
            return self._entry

    def set(self, result: ProcessedResult) -> None:
        """Store a processed result in the cache with the current timestamp.

        Args:
            result: The ProcessedResult to cache.
        """
        with self._lock:
            self._entry = CacheEntry(
                result=result,
                cached_at=datetime.utcnow(),
                ttl=self._ttl,
            )

    @property
    def data_age_seconds(self) -> Optional[float]:
        """Return seconds since the last cache write, or None if cache is empty."""
        with self._lock:
            if self._entry is None:
                return None
            return self._entry.age_seconds

    @property
    def is_stale(self) -> bool:
        """Return True if the cache is empty or the entry has expired."""
        with self._lock:
            if self._entry is None:
                return True
            return self._entry.is_expired

    @property
    def next_refresh_at(self) -> Optional[datetime]:
        """Return the datetime when the current cache entry will expire.

        Returns:
            cached_at + ttl as a datetime, or None if cache is empty.
        """
        with self._lock:
            if self._entry is None:
                return None
            return self._entry.cached_at + timedelta(seconds=self._ttl)
