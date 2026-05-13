"""Unit tests for CacheManager."""

import time
from datetime import datetime, timedelta
from unittest.mock import patch

import pandas as pd
import pytest

from src.services.cache_manager import CacheManager
from src.services.models import ProcessedResult


def _make_result() -> ProcessedResult:
    """Create a minimal ProcessedResult for testing."""
    df = pd.DataFrame({"symbol": ["BTC/USDT:USDT"], "price": [50000.0]})
    return ProcessedResult(data=df, errors=[])


class TestCacheManagerGet:
    """Tests for CacheManager.get() method."""

    def test_get_returns_none_when_empty(self):
        cm = CacheManager(ttl=60)
        assert cm.get() is None

    def test_get_returns_entry_when_valid(self):
        cm = CacheManager(ttl=60)
        result = _make_result()
        cm.set(result)

        entry = cm.get()
        assert entry is not None
        assert entry.result is result

    def test_get_returns_none_when_expired(self):
        cm = CacheManager(ttl=1)
        cm.set(_make_result())
        time.sleep(1.1)

        assert cm.get() is None


class TestCacheManagerSet:
    """Tests for CacheManager.set() method."""

    def test_set_stores_result(self):
        cm = CacheManager(ttl=60)
        result = _make_result()
        cm.set(result)

        entry = cm.get()
        assert entry is not None
        assert entry.result is result
        assert entry.ttl == 60

    def test_set_overwrites_previous_entry(self):
        cm = CacheManager(ttl=60)
        result1 = _make_result()
        result2 = _make_result()

        cm.set(result1)
        cm.set(result2)

        entry = cm.get()
        assert entry is not None
        assert entry.result is result2

    def test_set_records_cached_at_timestamp(self):
        cm = CacheManager(ttl=60)
        before = datetime.utcnow()
        cm.set(_make_result())
        after = datetime.utcnow()

        entry = cm.get()
        assert entry is not None
        assert before <= entry.cached_at <= after


class TestCacheManagerProperties:
    """Tests for CacheManager properties."""

    def test_data_age_seconds_none_when_empty(self):
        cm = CacheManager(ttl=60)
        assert cm.data_age_seconds is None

    def test_data_age_seconds_returns_elapsed_time(self):
        cm = CacheManager(ttl=60)
        cm.set(_make_result())
        time.sleep(0.1)

        age = cm.data_age_seconds
        assert age is not None
        assert age >= 0.1

    def test_is_stale_true_when_empty(self):
        cm = CacheManager(ttl=60)
        assert cm.is_stale is True

    def test_is_stale_false_when_fresh(self):
        cm = CacheManager(ttl=60)
        cm.set(_make_result())
        assert cm.is_stale is False

    def test_is_stale_true_when_expired(self):
        cm = CacheManager(ttl=1)
        cm.set(_make_result())
        time.sleep(1.1)
        assert cm.is_stale is True

    def test_next_refresh_at_none_when_empty(self):
        cm = CacheManager(ttl=60)
        assert cm.next_refresh_at is None

    def test_next_refresh_at_returns_expiry_time(self):
        cm = CacheManager(ttl=60)
        cm.set(_make_result())

        entry = cm.get()
        assert entry is not None
        expected = entry.cached_at + timedelta(seconds=60)
        assert cm.next_refresh_at == expected


class TestCacheManagerThreadSafety:
    """Tests for thread-safe concurrent access."""

    def test_concurrent_set_and_get(self):
        import threading

        cm = CacheManager(ttl=60)
        errors = []

        def writer():
            for _ in range(100):
                try:
                    cm.set(_make_result())
                except Exception as e:
                    errors.append(e)

        def reader():
            for _ in range(100):
                try:
                    cm.get()
                except Exception as e:
                    errors.append(e)

        threads = [
            threading.Thread(target=writer),
            threading.Thread(target=reader),
            threading.Thread(target=reader),
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert errors == []
