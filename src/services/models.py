"""Internal data structures for the API backend services."""

from dataclasses import dataclass, field
from datetime import datetime

import pandas as pd


@dataclass
class ProcessedResult:
    """Output of DataProcessor.process_all().

    Contains the processed screener results along with any per-symbol errors
    that occurred during data fetching/processing.
    """

    data: pd.DataFrame
    errors: list[dict] = field(default_factory=list)
    processed_at: datetime = field(default_factory=datetime.utcnow)


@dataclass
class CacheEntry:
    """Stored cache item with expiration metadata.

    Wraps a ProcessedResult with timing information to support
    TTL-based cache invalidation.
    """

    result: ProcessedResult
    cached_at: datetime
    ttl: int

    @property
    def is_expired(self) -> bool:
        """Return True if current time exceeds cached_at + ttl."""
        age = (datetime.utcnow() - self.cached_at).total_seconds()
        return age > self.ttl

    @property
    def age_seconds(self) -> float:
        """Return seconds elapsed since this entry was cached."""
        return (datetime.utcnow() - self.cached_at).total_seconds()
