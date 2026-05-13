"""Property-based tests for CacheManager service.

Uses Hypothesis to verify universal correctness properties across
randomly generated inputs.

Feature: api-backend-transformation
"""

import time
from datetime import datetime, timedelta
from unittest.mock import patch

import pandas as pd
import pytest
from hypothesis import given, strategies as st, settings

from src.services.cache_manager import CacheManager
from src.services.models import ProcessedResult


def _make_result() -> ProcessedResult:
    """Create a minimal ProcessedResult for testing."""
    df = pd.DataFrame({"symbol": ["BTC/USDT:USDT"], "price": [50000.0]})
    return ProcessedResult(data=df, errors=[])


class TestProperty5CacheTTLCorrectness:
    """Property 5: Cache TTL Correctness
    
    **Validates: Requirements 5.1, 5.2, 5.3**
    
    For any stored cache entry, retrieving it before TTL seconds have elapsed
    SHALL return the cached data (cache_hit=true), and retrieving it after TTL
    seconds have elapsed SHALL trigger a fresh data fetch (cache_hit=false).
    """

    @given(
        ttl=st.integers(min_value=1, max_value=300),
        time_offset=st.floats(min_value=0.0, max_value=0.99, allow_nan=False, allow_infinity=False)
    )
    @settings(max_examples=30, deadline=None)
    def test_cache_returns_data_before_ttl_expiry(self, ttl, time_offset):
        """Cache should return data when accessed before TTL expires.
        
        This test verifies that:
        - Data is stored with a specific TTL
        - When accessed before TTL expires, get() returns the cached entry
        - The returned entry contains the original data
        """
        cm = CacheManager(ttl=ttl)
        result = _make_result()
        
        # Store the result
        cm.set(result)
        
        # Calculate time to wait (less than TTL)
        wait_time = ttl * time_offset
        
        # Mock datetime to simulate time passing without actual sleep
        original_time = datetime.utcnow()
        future_time = original_time + timedelta(seconds=wait_time)
        
        with patch('src.services.models.datetime') as mock_datetime:
            mock_datetime.utcnow.return_value = future_time
            
            # Get should return the cached entry
            entry = cm.get()
            
            # Verify cache hit
            assert entry is not None, \
                f"Cache should return data after {wait_time:.2f}s (TTL={ttl}s)"
            assert entry.result is result, \
                "Cached entry should contain the original result"
            assert entry.ttl == ttl, \
                f"Cached entry should preserve TTL value: expected {ttl}, got {entry.ttl}"

    @given(
        ttl=st.integers(min_value=1, max_value=300),
        time_offset=st.floats(min_value=1.01, max_value=2.0, allow_nan=False, allow_infinity=False)
    )
    @settings(max_examples=30, deadline=None)
    def test_cache_returns_none_after_ttl_expiry(self, ttl, time_offset):
        """Cache should return None when accessed after TTL expires.
        
        This test verifies that:
        - Data is stored with a specific TTL
        - When accessed after TTL expires, get() returns None
        - This indicates a cache miss, requiring fresh data fetch
        """
        cm = CacheManager(ttl=ttl)
        result = _make_result()
        
        # Store the result
        cm.set(result)
        
        # Calculate time to wait (more than TTL)
        wait_time = ttl * time_offset
        
        # Mock datetime to simulate time passing
        original_time = datetime.utcnow()
        future_time = original_time + timedelta(seconds=wait_time)
        
        with patch('src.services.models.datetime') as mock_datetime:
            mock_datetime.utcnow.return_value = future_time
            
            # Get should return None (cache miss)
            entry = cm.get()
            
            # Verify cache miss
            assert entry is None, \
                f"Cache should return None after {wait_time:.2f}s (TTL={ttl}s)"

    @given(
        ttl=st.integers(min_value=1, max_value=300)
    )
    @settings(max_examples=30, deadline=None)
    def test_cache_boundary_at_exact_ttl(self, ttl):
        """Cache should expire at exactly TTL seconds.
        
        This test verifies the boundary condition:
        - At exactly TTL seconds, the cache should be expired
        - This ensures strict TTL enforcement
        """
        cm = CacheManager(ttl=ttl)
        result = _make_result()
        
        # Store the result
        cm.set(result)
        
        # Mock datetime to simulate exactly TTL seconds passing
        original_time = datetime.utcnow()
        exact_expiry_time = original_time + timedelta(seconds=ttl + 0.001)
        
        with patch('src.services.models.datetime') as mock_datetime:
            mock_datetime.utcnow.return_value = exact_expiry_time
            
            # Get should return None at exact TTL boundary
            entry = cm.get()
            
            # Verify cache is expired
            assert entry is None, \
                f"Cache should be expired at exactly TTL={ttl}s"

    @given(
        ttl=st.integers(min_value=1, max_value=300),
        num_accesses=st.integers(min_value=1, max_value=10)
    )
    @settings(max_examples=30, deadline=None)
    def test_multiple_cache_hits_before_expiry(self, ttl, num_accesses):
        """Cache should consistently return data on multiple accesses before TTL.
        
        This test verifies that:
        - Multiple get() calls before TTL all return the same cached data
        - Cache state remains consistent across multiple reads
        """
        cm = CacheManager(ttl=ttl)
        result = _make_result()
        
        # Store the result
        cm.set(result)
        
        # Access cache multiple times before TTL
        time_offset = 0.5  # Access at 50% of TTL
        wait_time = ttl * time_offset
        
        original_time = datetime.utcnow()
        future_time = original_time + timedelta(seconds=wait_time)
        
        with patch('src.services.models.datetime') as mock_datetime:
            mock_datetime.utcnow.return_value = future_time
            
            # Multiple accesses should all return the cached entry
            for i in range(num_accesses):
                entry = cm.get()
                assert entry is not None, \
                    f"Cache access {i+1}/{num_accesses} should return data"
                assert entry.result is result, \
                    f"Cache access {i+1}/{num_accesses} should return same result"

    @given(
        ttl=st.integers(min_value=1, max_value=300)
    )
    @settings(max_examples=30, deadline=None)
    def test_data_age_increases_over_time(self, ttl):
        """Data age should increase as time passes.
        
        This test verifies that:
        - data_age_seconds property accurately tracks elapsed time
        - Age increases monotonically
        """
        cm = CacheManager(ttl=ttl)
        result = _make_result()
        
        # Store the result
        original_time = datetime.utcnow()
        with patch('src.services.models.datetime') as mock_datetime:
            mock_datetime.utcnow.return_value = original_time
            cm.set(result)
        
        # Check age at different time points
        time_points = [0.25, 0.5, 0.75]
        previous_age = 0.0
        
        for time_fraction in time_points:
            wait_time = ttl * time_fraction
            future_time = original_time + timedelta(seconds=wait_time)
            
            with patch('src.services.models.datetime') as mock_datetime:
                mock_datetime.utcnow.return_value = future_time
                
                age = cm.data_age_seconds
                assert age is not None, "data_age_seconds should not be None"
                assert age >= previous_age, \
                    f"Age should increase: {age} should be >= {previous_age}"
                assert abs(age - wait_time) < 0.1, \
                    f"Age should be approximately {wait_time}s, got {age}s"
                
                previous_age = age

    @given(
        ttl=st.integers(min_value=1, max_value=300)
    )
    @settings(max_examples=30, deadline=None)
    def test_is_stale_property_reflects_ttl_state(self, ttl):
        """is_stale property should correctly reflect cache expiration state.
        
        This test verifies that:
        - is_stale is False before TTL expires
        - is_stale is True after TTL expires
        """
        cm = CacheManager(ttl=ttl)
        result = _make_result()
        
        original_time = datetime.utcnow()
        
        # Store the result
        with patch('src.services.models.datetime') as mock_datetime:
            mock_datetime.utcnow.return_value = original_time
            cm.set(result)
        
        # Check is_stale before expiry (at 50% of TTL)
        before_expiry_time = original_time + timedelta(seconds=ttl * 0.5)
        with patch('src.services.models.datetime') as mock_datetime:
            mock_datetime.utcnow.return_value = before_expiry_time
            assert cm.is_stale is False, \
                f"Cache should not be stale at {ttl * 0.5}s (TTL={ttl}s)"
        
        # Check is_stale after expiry (at 150% of TTL)
        after_expiry_time = original_time + timedelta(seconds=ttl * 1.5)
        with patch('src.services.models.datetime') as mock_datetime:
            mock_datetime.utcnow.return_value = after_expiry_time
            assert cm.is_stale is True, \
                f"Cache should be stale at {ttl * 1.5}s (TTL={ttl}s)"

    @given(
        ttl=st.integers(min_value=1, max_value=300)
    )
    @settings(max_examples=30, deadline=None)
    def test_next_refresh_at_is_accurate(self, ttl):
        """next_refresh_at should accurately predict cache expiration time.
        
        This test verifies that:
        - next_refresh_at returns cached_at + TTL
        - The predicted expiration time is accurate
        """
        cm = CacheManager(ttl=ttl)
        result = _make_result()
        
        # Store the result
        cm.set(result)
        
        # Get the predicted refresh time
        next_refresh = cm.next_refresh_at
        assert next_refresh is not None, "next_refresh_at should not be None"
        
        # Get the actual cached_at time
        entry = cm.get()
        assert entry is not None, "Cache should have an entry"
        
        # Verify next_refresh_at = cached_at + TTL
        expected_refresh = entry.cached_at + timedelta(seconds=ttl)
        assert next_refresh == expected_refresh, \
            f"next_refresh_at should be {expected_refresh}, got {next_refresh}"

    @given(
        ttl1=st.integers(min_value=1, max_value=300),
        ttl2=st.integers(min_value=1, max_value=300)
    )
    @settings(max_examples=30, deadline=None)
    def test_cache_overwrites_with_new_ttl(self, ttl1, ttl2):
        """Setting new data should overwrite cache with new TTL.
        
        This test verifies that:
        - Calling set() again overwrites the previous entry
        - The new entry uses the current TTL value
        """
        cm = CacheManager(ttl=ttl1)
        result1 = _make_result()
        result2 = _make_result()
        
        # Store first result
        cm.set(result1)
        entry1 = cm.get()
        assert entry1 is not None
        assert entry1.ttl == ttl1
        
        # Change TTL and store second result
        cm._ttl = ttl2
        cm.set(result2)
        entry2 = cm.get()
        assert entry2 is not None
        assert entry2.ttl == ttl2
        assert entry2.result is result2
        assert entry2.result is not result1
