#!/usr/bin/env python3
"""
Unit tests for MarketDataFetcher.calculate_distance_to_ma50() method.

Tests cover:
- 50-day SMA calculation from closing prices
- Distance percentage calculation (positive and negative)
- Position classification ('above'/'below')
- Insufficient data handling (< 50 candles)
- Error handling for OHLCV fetch failures
"""

import pytest
from unittest.mock import Mock
from src.data.fetcher import MarketDataFetcher


def _make_ohlcv(close_prices):
    """
    Helper to create OHLCV candle data from a list of closing prices.
    Format: [timestamp, open, high, low, close, volume]
    """
    candles = []
    for i, close in enumerate(close_prices):
        # Use close as open, close+5 as high, close-5 as low
        candles.append([1000000 + i * 86400000, close, close + 5, close - 5, close, 1000.0])
    return candles


class TestCalculateMA50SMA:
    """Tests specifically for the 50-day SMA calculation from closing prices."""

    def setup_method(self):
        """Set up test fixtures."""
        self.mock_exchange = Mock()
        self.fetcher = MarketDataFetcher(self.mock_exchange, ['BTC/USDT:USDT'])

    def test_sma_calculation_with_uniform_prices(self):
        """Test SMA calculation when all closing prices are the same."""
        # All 50 candles have close=100
        candles = _make_ohlcv([100.0] * 50)
        self.mock_exchange.fetch_ohlcv.return_value = candles

        result = self.fetcher.calculate_distance_to_ma50('BTC/USDT:USDT')

        # SMA of 50 identical values = that value
        assert result['ma50'] == pytest.approx(100.0, rel=1e-6)

    def test_sma_calculation_with_known_values(self):
        """Test SMA calculation with a known set of closing prices."""
        # Create 50 prices: 1, 2, 3, ..., 50
        close_prices = list(range(1, 51))
        candles = _make_ohlcv([float(p) for p in close_prices])
        self.mock_exchange.fetch_ohlcv.return_value = candles

        result = self.fetcher.calculate_distance_to_ma50('BTC/USDT:USDT')

        # SMA = sum(1..50) / 50 = 1275 / 50 = 25.5
        expected_ma50 = sum(range(1, 51)) / 50
        assert result['ma50'] == pytest.approx(expected_ma50, rel=1e-6)
        assert result['ma50'] == pytest.approx(25.5, rel=1e-6)

    def test_sma_uses_all_50_closing_prices(self):
        """Test that SMA uses exactly all 50 closing prices."""
        # 49 candles at 100, last candle at 200
        close_prices = [100.0] * 49 + [200.0]
        candles = _make_ohlcv(close_prices)
        self.mock_exchange.fetch_ohlcv.return_value = candles

        result = self.fetcher.calculate_distance_to_ma50('BTC/USDT:USDT')

        # SMA = (49*100 + 200) / 50 = (4900 + 200) / 50 = 5100 / 50 = 102.0
        expected_ma50 = (49 * 100.0 + 200.0) / 50
        assert result['ma50'] == pytest.approx(expected_ma50, rel=1e-6)
        assert result['ma50'] == pytest.approx(102.0, rel=1e-6)

    def test_sma_with_decreasing_prices(self):
        """Test SMA calculation with decreasing price series."""
        # Prices from 100 down to 51
        close_prices = list(range(100, 50, -1))  # [100, 99, ..., 51]
        candles = _make_ohlcv([float(p) for p in close_prices])
        self.mock_exchange.fetch_ohlcv.return_value = candles

        result = self.fetcher.calculate_distance_to_ma50('BTC/USDT:USDT')

        # SMA = sum(51..100) / 50 = (sum(1..100) - sum(1..50)) / 50 = (5050 - 1275) / 50 = 3775 / 50 = 75.5
        expected_ma50 = sum(range(51, 101)) / 50
        assert result['ma50'] == pytest.approx(expected_ma50, rel=1e-6)
        assert result['ma50'] == pytest.approx(75.5, rel=1e-6)

    def test_sma_extracts_close_price_from_index_4(self):
        """Test that SMA correctly extracts closing price from OHLCV index 4."""
        # Create candles where open, high, low differ from close
        # This verifies we're using index 4 (close), not other indices
        candles = []
        for i in range(50):
            # [timestamp, open=50, high=200, low=10, close=100, volume=1000]
            candles.append([1000000 + i * 86400000, 50.0, 200.0, 10.0, 100.0, 1000.0])
        self.mock_exchange.fetch_ohlcv.return_value = candles

        result = self.fetcher.calculate_distance_to_ma50('BTC/USDT:USDT')

        # SMA should be 100 (using close prices), not 50 (open) or 200 (high) or 10 (low)
        assert result['ma50'] == pytest.approx(100.0, rel=1e-6)

    def test_sma_with_fractional_prices(self):
        """Test SMA calculation with fractional/decimal prices."""
        # Use prices like 0.5, 1.5, 2.5, ..., 49.5
        close_prices = [i + 0.5 for i in range(50)]
        candles = _make_ohlcv(close_prices)
        self.mock_exchange.fetch_ohlcv.return_value = candles

        result = self.fetcher.calculate_distance_to_ma50('BTC/USDT:USDT')

        # SMA = sum(0.5, 1.5, ..., 49.5) / 50 = (sum(0..49) + 50*0.5) / 50 = (1225 + 25) / 50 = 25.0
        expected_ma50 = sum(close_prices) / 50
        assert result['ma50'] == pytest.approx(expected_ma50, rel=1e-6)
        assert result['ma50'] == pytest.approx(25.0, rel=1e-6)


class TestCalculateDistanceToMA50:
    """Tests for the full calculate_distance_to_ma50 method."""

    def setup_method(self):
        """Set up test fixtures."""
        self.mock_exchange = Mock()
        self.fetcher = MarketDataFetcher(self.mock_exchange, ['BTC/USDT:USDT'])

    def test_positive_distance_price_above_ma50(self):
        """Test distance calculation when current price is above MA50."""
        # 49 candles at 100, last candle at 150
        # MA50 = (49*100 + 150) / 50 = 5050/50 = 101.0
        # Current price = 150 (last candle close)
        # Distance = ((150 - 101) / 101) * 100 ≈ 48.51%
        close_prices = [100.0] * 49 + [150.0]
        candles = _make_ohlcv(close_prices)
        self.mock_exchange.fetch_ohlcv.return_value = candles

        result = self.fetcher.calculate_distance_to_ma50('BTC/USDT:USDT')

        expected_ma50 = (49 * 100.0 + 150.0) / 50
        expected_distance = ((150.0 - expected_ma50) / expected_ma50) * 100

        assert result['distance_percent'] == pytest.approx(expected_distance, rel=1e-4)
        assert result['distance_percent'] > 0
        assert result['position'] == 'above'

    def test_negative_distance_price_below_ma50(self):
        """Test distance calculation when current price is below MA50."""
        # 49 candles at 100, last candle at 50
        # MA50 = (49*100 + 50) / 50 = 4950/50 = 99.0
        # Current price = 50 (last candle close)
        # Distance = ((50 - 99) / 99) * 100 ≈ -49.49%
        close_prices = [100.0] * 49 + [50.0]
        candles = _make_ohlcv(close_prices)
        self.mock_exchange.fetch_ohlcv.return_value = candles

        result = self.fetcher.calculate_distance_to_ma50('BTC/USDT:USDT')

        expected_ma50 = (49 * 100.0 + 50.0) / 50
        expected_distance = ((50.0 - expected_ma50) / expected_ma50) * 100

        assert result['distance_percent'] == pytest.approx(expected_distance, rel=1e-4)
        assert result['distance_percent'] < 0
        assert result['position'] == 'below'

    def test_zero_distance_price_at_ma50(self):
        """Test distance calculation when current price equals MA50."""
        # All 50 candles at 100 => MA50 = 100, current = 100
        close_prices = [100.0] * 50
        candles = _make_ohlcv(close_prices)
        self.mock_exchange.fetch_ohlcv.return_value = candles

        result = self.fetcher.calculate_distance_to_ma50('BTC/USDT:USDT')

        assert result['distance_percent'] == pytest.approx(0.0, abs=1e-6)
        assert result['position'] == 'above'  # >= ma50 is 'above'

    def test_insufficient_data_returns_null(self):
        """Test that fewer than 50 candles returns null values."""
        # Only 30 candles
        candles = _make_ohlcv([100.0] * 30)
        self.mock_exchange.fetch_ohlcv.return_value = candles

        result = self.fetcher.calculate_distance_to_ma50('BTC/USDT:USDT')

        assert result['ma50'] is None
        assert result['current_price'] is None
        assert result['distance_percent'] is None
        assert result['position'] is None

    def test_empty_ohlcv_returns_null(self):
        """Test that empty OHLCV data returns null values."""
        self.mock_exchange.fetch_ohlcv.return_value = []

        result = self.fetcher.calculate_distance_to_ma50('BTC/USDT:USDT')

        assert result['ma50'] is None
        assert result['current_price'] is None
        assert result['distance_percent'] is None
        assert result['position'] is None

    def test_ohlcv_fetch_exception_returns_null(self):
        """Test that OHLCV fetch failure returns null values."""
        self.mock_exchange.fetch_ohlcv.side_effect = Exception("Network error")

        result = self.fetcher.calculate_distance_to_ma50('BTC/USDT:USDT')

        assert result['ma50'] is None
        assert result['current_price'] is None
        assert result['distance_percent'] is None
        assert result['position'] is None

    def test_return_dict_structure(self):
        """Test that the return dict has the correct keys."""
        candles = _make_ohlcv([100.0] * 50)
        self.mock_exchange.fetch_ohlcv.return_value = candles

        result = self.fetcher.calculate_distance_to_ma50('BTC/USDT:USDT')

        assert 'ma50' in result
        assert 'current_price' in result
        assert 'distance_percent' in result
        assert 'position' in result
        assert len(result) == 4

    def test_fetches_50_daily_candles(self):
        """Test that fetch_ohlcv is called with correct parameters."""
        candles = _make_ohlcv([100.0] * 50)
        self.mock_exchange.fetch_ohlcv.return_value = candles

        self.fetcher.calculate_distance_to_ma50('BTC/USDT:USDT')

        self.mock_exchange.fetch_ohlcv.assert_called_once_with(
            'BTC/USDT:USDT', '1d', limit=50
        )

    def test_ma50_zero_returns_null(self):
        """Test that MA50 of zero returns null values (division by zero protection)."""
        # All 50 candles with close=0
        candles = _make_ohlcv([0.0] * 50)
        self.mock_exchange.fetch_ohlcv.return_value = candles

        result = self.fetcher.calculate_distance_to_ma50('BTC/USDT:USDT')

        assert result['ma50'] is None
        assert result['distance_percent'] is None
