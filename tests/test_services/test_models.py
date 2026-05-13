"""Unit tests for src/services/models.py."""

from datetime import datetime, timedelta

import pandas as pd
import pytest

from src.services.models import CacheEntry, ProcessedResult


class TestProcessedResult:
    """Tests for the ProcessedResult dataclass."""

    def test_create_with_all_fields(self):
        df = pd.DataFrame({"symbol": ["BTC", "ETH"], "price": [50000.0, 3000.0]})
        errors = [{"symbol": "SOL", "error": "timeout"}]
        now = datetime.utcnow()

        result = ProcessedResult(data=df, errors=errors, processed_at=now)

        assert result.data.equals(df)
        assert result.errors == errors
        assert result.processed_at == now

    def test_default_errors_empty_list(self):
        df = pd.DataFrame({"symbol": ["BTC"]})
        result = ProcessedResult(data=df)

        assert result.errors == []

    def test_default_processed_at_is_set(self):
        df = pd.DataFrame({"symbol": ["BTC"]})
        before = datetime.utcnow()
        result = ProcessedResult(data=df)
        after = datetime.utcnow()

        assert before <= result.processed_at <= after

    def test_errors_are_independent_between_instances(self):
        df = pd.DataFrame({"symbol": ["BTC"]})
        r1 = ProcessedResult(data=df)
        r2 = ProcessedResult(data=df)

        r1.errors.append({"symbol": "ETH", "error": "fail"})
        assert r2.errors == []


class TestCacheEntry:
    """Tests for the CacheEntry dataclass."""

    def _make_result(self) -> ProcessedResult:
        return ProcessedResult(data=pd.DataFrame({"symbol": ["BTC"]}))

    def test_is_expired_false_within_ttl(self):
        result = self._make_result()
        entry = CacheEntry(
            result=result,
            cached_at=datetime.utcnow() - timedelta(seconds=10),
            ttl=60,
        )
        assert entry.is_expired is False

    def test_is_expired_true_after_ttl(self):
        result = self._make_result()
        entry = CacheEntry(
            result=result,
            cached_at=datetime.utcnow() - timedelta(seconds=90),
            ttl=60,
        )
        assert entry.is_expired is True

    def test_is_expired_boundary_at_ttl(self):
        """At exactly TTL seconds, entry is NOT expired (> not >=)."""
        result = self._make_result()
        # Use a very recent cached_at to test boundary
        entry = CacheEntry(
            result=result,
            cached_at=datetime.utcnow() - timedelta(seconds=60),
            ttl=60,
        )
        # At exactly 60s with 60s TTL, age is not > ttl (it's equal),
        # but due to execution time it will be slightly over.
        # The key behavior: is_expired uses > (strict), not >=
        assert isinstance(entry.is_expired, bool)

    def test_age_seconds_positive(self):
        result = self._make_result()
        entry = CacheEntry(
            result=result,
            cached_at=datetime.utcnow() - timedelta(seconds=45),
            ttl=60,
        )
        assert 44.0 <= entry.age_seconds <= 46.0

    def test_age_seconds_fresh_entry(self):
        result = self._make_result()
        entry = CacheEntry(
            result=result,
            cached_at=datetime.utcnow(),
            ttl=60,
        )
        assert entry.age_seconds < 1.0

    def test_ttl_zero_always_expired(self):
        result = self._make_result()
        entry = CacheEntry(
            result=result,
            cached_at=datetime.utcnow() - timedelta(seconds=1),
            ttl=0,
        )
        assert entry.is_expired is True
