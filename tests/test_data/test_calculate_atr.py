#!/usr/bin/env python3
"""
Unit tests for MarketDataFetcher.calculate_atr() method.

Tests cover:
- True Range calculation correctness
- 14-period SMA of True Range values
- ATR percentage calculation
- Volatility level classification
- Insufficient data handling
- Error handling for OHLCV fetch failures
"""

import pytest
from unittest.mock import Mock, patch
from src.data.fetcher import MarketDataFetcher


def _make_ohlcv(prices):
    """
    Helper to create OHLCV candle data from a list of (open, high, low, close) tuples.
    Format: [timestamp, open, high, low, close, volume]
    """
    candles = []
    for i, (o, h, l, c) in enumerate(prices):
        candles.append([1000000 + i * 86400000, o, h, l, c, 1000.0])
    return candles


class TestTrueRangeCalculation:
    """Tests specifically for the True Range formula: TR = max(High-Low, |High-PrevClose|, |Low-PrevClose|)."""

    def setup_method(self):
        """Set up test fixtures."""
        self.mock_exchange = Mock()
        self.fetcher = MarketDataFetcher(self.mock_exchange, ['BTC/USDT:USDT'])

    def test_true_range_high_minus_low_dominant(self):
        """Test TR when (High - Low) is the largest component (no gap)."""
        # Scenario: prev_close=100, high=120, low=80
        # TR = max(120-80, |120-100|, |80-100|) = max(40, 20, 20) = 40
        # The high-low range dominates when there's no gap
        candles = _make_ohlcv(
            [(100, 110, 90, 100)] +  # Candle 0: close=100 (prev_close for candle 1)
            [(100, 120, 80, 100)] * 14  # Candles 1-14: H=120, L=80, prev_close=100
        )

        self.mock_exchange.fetch_ohlcv.return_value = candles
        result = self.fetcher.calculate_atr('BTC/USDT:USDT')

        # All TRs = 40, ATR = 40
        assert result['atr_value'] == pytest.approx(40.0, rel=1e-6)

    def test_true_range_high_minus_prev_close_dominant(self):
        """Test TR when |High - PrevClose| is the largest component (gap up)."""
        # Scenario: prev_close=50, high=120, low=110
        # TR = max(120-110, |120-50|, |110-50|) = max(10, 70, 60) = 70
        # The |High - PrevClose| dominates during a gap up
        candles = _make_ohlcv(
            [(50, 60, 40, 50)] +  # Candle 0: close=50 (prev_close for candle 1)
            [(115, 120, 110, 115)] * 14  # Candles 1-14: gap up from 50 to 110-120 range
        )

        self.mock_exchange.fetch_ohlcv.return_value = candles
        result = self.fetcher.calculate_atr('BTC/USDT:USDT')

        # Candle 1: TR = max(10, |120-50|, |110-50|) = max(10, 70, 60) = 70
        # Candles 2-14: TR = max(10, |120-115|, |110-115|) = max(10, 5, 5) = 10
        expected_atr = (70 + 13 * 10) / 14
        assert result['atr_value'] == pytest.approx(expected_atr, rel=1e-6)

    def test_true_range_low_minus_prev_close_dominant(self):
        """Test TR when |Low - PrevClose| is the largest component (gap down)."""
        # Scenario: prev_close=200, high=110, low=100
        # TR = max(110-100, |110-200|, |100-200|) = max(10, 90, 100) = 100
        # The |Low - PrevClose| dominates during a gap down
        candles = _make_ohlcv(
            [(200, 210, 190, 200)] +  # Candle 0: close=200 (prev_close for candle 1)
            [(105, 110, 100, 105)] * 14  # Candles 1-14: gap down from 200 to 100-110 range
        )

        self.mock_exchange.fetch_ohlcv.return_value = candles
        result = self.fetcher.calculate_atr('BTC/USDT:USDT')

        # Candle 1: TR = max(10, |110-200|, |100-200|) = max(10, 90, 100) = 100
        # Candles 2-14: TR = max(10, |110-105|, |100-105|) = max(10, 5, 5) = 10
        expected_atr = (100 + 13 * 10) / 14
        assert result['atr_value'] == pytest.approx(expected_atr, rel=1e-6)

    def test_true_range_with_varied_known_values(self):
        """Test TR calculation with a sequence of varied candles where each TR is manually computed."""
        # Manually construct candles with different TR scenarios
        candles = _make_ohlcv([
            (100, 105, 95, 100),   # Candle 0: close=100 (only used as prev_close)
            (102, 108, 92, 104),   # TR = max(108-92, |108-100|, |92-100|) = max(16, 8, 8) = 16
            (104, 112, 98, 106),   # TR = max(112-98, |112-104|, |98-104|) = max(14, 8, 6) = 14
            (106, 130, 95, 110),   # TR = max(130-95, |130-106|, |95-106|) = max(35, 24, 11) = 35
            (110, 115, 85, 90),    # TR = max(115-85, |115-110|, |85-110|) = max(30, 5, 25) = 30
            (90, 92, 88, 91),      # TR = max(92-88, |92-90|, |88-90|) = max(4, 2, 2) = 4
            (91, 95, 89, 93),      # TR = max(95-89, |95-91|, |89-91|) = max(6, 4, 2) = 6
            (93, 100, 90, 98),     # TR = max(100-90, |100-93|, |90-93|) = max(10, 7, 3) = 10
            (98, 105, 95, 102),    # TR = max(105-95, |105-98|, |95-98|) = max(10, 7, 3) = 10
            (102, 110, 100, 108),  # TR = max(110-100, |110-102|, |100-102|) = max(10, 8, 2) = 10
            (108, 115, 105, 112),  # TR = max(115-105, |115-108|, |105-108|) = max(10, 7, 3) = 10
            (112, 120, 110, 118),  # TR = max(120-110, |120-112|, |110-112|) = max(10, 8, 2) = 10
            (118, 125, 115, 122),  # TR = max(125-115, |125-118|, |115-118|) = max(10, 7, 3) = 10
            (122, 130, 120, 128),  # TR = max(130-120, |130-122|, |120-122|) = max(10, 8, 2) = 10
            (128, 135, 125, 132),  # TR = max(135-125, |135-128|, |125-128|) = max(10, 7, 3) = 10
        ])

        self.mock_exchange.fetch_ohlcv.return_value = candles
        result = self.fetcher.calculate_atr('BTC/USDT:USDT')

        # True Ranges: [16, 14, 35, 30, 4, 6, 10, 10, 10, 10, 10, 10, 10, 10]
        expected_trs = [16, 14, 35, 30, 4, 6, 10, 10, 10, 10, 10, 10, 10, 10]
        expected_atr = sum(expected_trs) / 14
        assert result['atr_value'] == pytest.approx(expected_atr, rel=1e-6)

    def test_true_range_all_components_equal(self):
        """Test TR when all three components are equal."""
        # Scenario: prev_close=100, high=110, low=90
        # TR = max(110-90, |110-100|, |90-100|) = max(20, 10, 10) = 20
        # Note: High-Low is always >= the other two when prev_close is between high and low
        # To get all equal: prev_close must be outside the range
        # Actually, for all three to be equal:
        # H-L = |H-prevC| = |L-prevC|
        # This requires prevC = L (then H-L = H-prevC, and |L-prevC| = 0) - not all equal
        # Or: H-L = 2*(H-prevC) when prevC = (H+L)/2 - then |H-prevC| = |L-prevC| = (H-L)/2
        # So H-L > |H-prevC| = |L-prevC| when prevC is midpoint
        # Let's test the midpoint case: prev_close=100, H=110, L=90
        candles = _make_ohlcv(
            [(100, 110, 90, 100)] +  # Candle 0: close=100
            [(100, 110, 90, 100)] * 14  # Same pattern: prevC=100 is midpoint of [90,110]
        )

        self.mock_exchange.fetch_ohlcv.return_value = candles
        result = self.fetcher.calculate_atr('BTC/USDT:USDT')

        # TR = max(20, 10, 10) = 20 for all candles
        assert result['atr_value'] == pytest.approx(20.0, rel=1e-6)


class TestCalculateATR:
    """Tests for the calculate_atr method."""

    def setup_method(self):
        """Set up test fixtures."""
        self.mock_exchange = Mock()
        self.fetcher = MarketDataFetcher(self.mock_exchange, ['BTC/USDT:USDT'])

    def test_basic_atr_calculation(self):
        """Test ATR calculation with known values."""
        # Create 15 candles (period=14, need 15 for 14 True Range values)
        # Using simple data where True Range is easy to verify
        candles = _make_ohlcv([
            (100, 110, 90, 100),   # Candle 0 (used only for prev_close)
            (100, 112, 88, 105),   # TR = max(24, |112-100|, |88-100|) = max(24, 12, 12) = 24
            (105, 115, 95, 110),   # TR = max(20, |115-105|, |95-105|) = max(20, 10, 10) = 20
            (110, 120, 100, 115),  # TR = max(20, |120-110|, |100-110|) = max(20, 10, 10) = 20
            (115, 125, 105, 120),  # TR = max(20, |125-115|, |105-115|) = max(20, 10, 10) = 20
            (120, 130, 110, 125),  # TR = max(20, |130-120|, |110-120|) = max(20, 10, 10) = 20
            (125, 135, 115, 130),  # TR = max(20, |135-125|, |115-125|) = max(20, 10, 10) = 20
            (130, 140, 120, 135),  # TR = max(20, |140-130|, |120-130|) = max(20, 10, 10) = 20
            (135, 145, 125, 140),  # TR = max(20, |145-135|, |125-135|) = max(20, 10, 10) = 20
            (140, 150, 130, 145),  # TR = max(20, |150-140|, |130-140|) = max(20, 10, 10) = 20
            (145, 155, 135, 150),  # TR = max(20, |155-145|, |135-145|) = max(20, 10, 10) = 20
            (150, 160, 140, 155),  # TR = max(20, |160-150|, |140-150|) = max(20, 10, 10) = 20
            (155, 165, 145, 160),  # TR = max(20, |165-155|, |145-155|) = max(20, 10, 10) = 20
            (160, 170, 150, 165),  # TR = max(20, |170-160|, |150-160|) = max(20, 10, 10) = 20
            (165, 175, 155, 170),  # TR = max(20, |175-165|, |155-165|) = max(20, 10, 10) = 20
        ])

        self.mock_exchange.fetch_ohlcv.return_value = candles
        result = self.fetcher.calculate_atr('BTC/USDT:USDT')

        # First TR = 24, rest are 20. SMA of last 14 = (24 + 13*20) / 14 = (24+260)/14 = 284/14 ≈ 20.2857
        expected_atr = (24 + 13 * 20) / 14
        assert result['atr_value'] == pytest.approx(expected_atr, rel=1e-4)

        # ATR percent = (atr_value / current_price) * 100
        # current_price = 170 (last candle close)
        expected_percent = (expected_atr / 170) * 100
        assert result['atr_percent'] == pytest.approx(expected_percent, rel=1e-4)

    def test_volatility_level_low(self):
        """Test that ATR < 3% returns 'low' volatility level."""
        # Create candles with small True Range relative to price
        # Price ~1000, TR ~10 => ATR% = (10/1000)*100 = 1% (low)
        candles = _make_ohlcv(
            [(1000, 1005, 995, 1000)] +  # First candle
            [(1000, 1010, 990, 1000)] * 14  # 14 more candles, TR = 20 each
        )
        # TR for each = max(20, |1010-1000|, |990-1000|) = max(20, 10, 10) = 20
        # ATR = 20, price = 1000, ATR% = 2.0% (low)

        self.mock_exchange.fetch_ohlcv.return_value = candles
        result = self.fetcher.calculate_atr('BTC/USDT:USDT')

        assert result['volatility_level'] == 'low'
        assert result['atr_percent'] < 3.0

    def test_volatility_level_medium(self):
        """Test that 3% <= ATR <= 6% returns 'medium' volatility level."""
        # Price ~1000, TR ~40 => ATR% = (40/1000)*100 = 4% (medium)
        candles = _make_ohlcv(
            [(1000, 1020, 980, 1000)] +  # First candle
            [(1000, 1040, 960, 1000)] * 14  # TR = max(80, 40, 40) = 80... too high
        )
        # Let's be more precise: need ATR% between 3% and 6%
        # Price = 1000, need ATR between 30 and 60
        # TR = max(H-L, |H-prevC|, |L-prevC|)
        # If H=1020, L=980, prevC=1000: TR = max(40, 20, 20) = 40
        # ATR = 40, ATR% = 4% (medium)
        candles = _make_ohlcv(
            [(1000, 1020, 980, 1000)] +  # First candle (prev_close = 1000)
            [(1000, 1020, 980, 1000)] * 14  # TR = max(40, |1020-1000|, |980-1000|) = max(40, 20, 20) = 40
        )

        self.mock_exchange.fetch_ohlcv.return_value = candles
        result = self.fetcher.calculate_atr('BTC/USDT:USDT')

        assert result['volatility_level'] == 'medium'
        assert 3.0 <= result['atr_percent'] <= 6.0

    def test_volatility_level_high(self):
        """Test that ATR > 6% returns 'high' volatility level."""
        # Price ~1000, TR ~80 => ATR% = (80/1000)*100 = 8% (high)
        candles = _make_ohlcv(
            [(1000, 1040, 960, 1000)] +  # First candle
            [(1000, 1080, 920, 1000)] * 14  # TR = max(160, 80, 80) = 160
        )
        # TR = max(160, |1080-1000|, |920-1000|) = max(160, 80, 80) = 160
        # ATR = 160, ATR% = 16% (high)

        self.mock_exchange.fetch_ohlcv.return_value = candles
        result = self.fetcher.calculate_atr('BTC/USDT:USDT')

        assert result['volatility_level'] == 'high'
        assert result['atr_percent'] > 6.0

    def test_insufficient_data_returns_null(self):
        """Test that fewer than 15 candles returns null values."""
        # Only 10 candles (need 15 for period=14)
        candles = _make_ohlcv([(100, 110, 90, 100)] * 10)

        self.mock_exchange.fetch_ohlcv.return_value = candles
        result = self.fetcher.calculate_atr('BTC/USDT:USDT')

        assert result['atr_value'] is None
        assert result['atr_percent'] is None
        assert result['volatility_level'] is None

    def test_empty_ohlcv_returns_null(self):
        """Test that empty OHLCV data returns null values."""
        self.mock_exchange.fetch_ohlcv.return_value = []
        result = self.fetcher.calculate_atr('BTC/USDT:USDT')

        assert result['atr_value'] is None
        assert result['atr_percent'] is None
        assert result['volatility_level'] is None

    def test_ohlcv_fetch_exception_returns_null(self):
        """Test that OHLCV fetch failure returns null values."""
        self.mock_exchange.fetch_ohlcv.side_effect = Exception("Network error")
        result = self.fetcher.calculate_atr('BTC/USDT:USDT')

        assert result['atr_value'] is None
        assert result['atr_percent'] is None
        assert result['volatility_level'] is None

    def test_zero_price_returns_null(self):
        """Test that zero current price returns null values."""
        # 15 candles but last candle has close=0
        candles = _make_ohlcv(
            [(100, 110, 90, 100)] * 14 + [(0, 10, 0, 0)]
        )

        self.mock_exchange.fetch_ohlcv.return_value = candles
        result = self.fetcher.calculate_atr('BTC/USDT:USDT')

        assert result['atr_value'] is None
        assert result['atr_percent'] is None
        assert result['volatility_level'] is None

    def test_true_range_uses_prev_close_gap_up(self):
        """Test True Range correctly handles gap up (High - PrevClose > High - Low)."""
        # Gap up scenario: prev_close=100, current candle high=150, low=140, close=145
        # TR = max(150-140, |150-100|, |140-100|) = max(10, 50, 40) = 50
        candles = _make_ohlcv(
            [(100, 110, 90, 100)] +  # Candle 0: close=100
            [(145, 150, 140, 145)] * 14  # Gap up candles
        )
        # For candle 1: TR = max(10, |150-100|, |140-100|) = max(10, 50, 40) = 50
        # For candles 2-14: TR = max(10, |150-145|, |140-145|) = max(10, 5, 5) = 10

        self.mock_exchange.fetch_ohlcv.return_value = candles
        result = self.fetcher.calculate_atr('BTC/USDT:USDT')

        # ATR = (50 + 13*10) / 14 = (50 + 130) / 14 = 180/14 ≈ 12.857
        expected_atr = (50 + 13 * 10) / 14
        assert result['atr_value'] == pytest.approx(expected_atr, rel=1e-4)

    def test_true_range_uses_prev_close_gap_down(self):
        """Test True Range correctly handles gap down (|Low - PrevClose| > High - Low)."""
        # Gap down scenario: prev_close=200, current candle high=110, low=100, close=105
        # TR = max(110-100, |110-200|, |100-200|) = max(10, 90, 100) = 100
        candles = _make_ohlcv(
            [(200, 210, 190, 200)] +  # Candle 0: close=200
            [(105, 110, 100, 105)] * 14  # Gap down candles
        )
        # For candle 1: TR = max(10, |110-200|, |100-200|) = max(10, 90, 100) = 100
        # For candles 2-14: TR = max(10, |110-105|, |100-105|) = max(10, 5, 5) = 10

        self.mock_exchange.fetch_ohlcv.return_value = candles
        result = self.fetcher.calculate_atr('BTC/USDT:USDT')

        # ATR = (100 + 13*10) / 14 = (100 + 130) / 14 = 230/14 ≈ 16.4286
        expected_atr = (100 + 13 * 10) / 14
        assert result['atr_value'] == pytest.approx(expected_atr, rel=1e-4)

    def test_custom_period(self):
        """Test ATR calculation with a custom period (e.g., 7)."""
        # Need 8 candles for period=7
        candles = _make_ohlcv(
            [(100, 110, 90, 100)] +  # First candle
            [(100, 115, 85, 100)] * 7  # 7 more candles, TR = max(30, 15, 15) = 30
        )

        self.mock_exchange.fetch_ohlcv.return_value = candles
        result = self.fetcher.calculate_atr('BTC/USDT:USDT', period=7)

        # All TRs = 30 (first one: max(30, |115-100|, |85-100|) = max(30, 15, 15) = 30)
        expected_atr = 30.0
        assert result['atr_value'] == pytest.approx(expected_atr, rel=1e-4)
        # ATR% = (30/100)*100 = 30%
        assert result['atr_percent'] == pytest.approx(30.0, rel=1e-4)
        assert result['volatility_level'] == 'high'

    def test_exactly_15_candles(self):
        """Test ATR works with exactly 15 candles (minimum for period=14)."""
        candles = _make_ohlcv([(100, 110, 90, 100)] * 15)

        self.mock_exchange.fetch_ohlcv.return_value = candles
        result = self.fetcher.calculate_atr('BTC/USDT:USDT')

        # All TRs = max(20, 10, 10) = 20, ATR = 20, ATR% = (20/100)*100 = 20%
        assert result['atr_value'] == pytest.approx(20.0, rel=1e-4)
        assert result['atr_percent'] == pytest.approx(20.0, rel=1e-4)
        assert result['volatility_level'] == 'high'

    def test_boundary_3_percent(self):
        """Test volatility level at exactly 3% boundary (should be medium)."""
        # Need ATR% = exactly 3.0%
        # Price = 1000, ATR = 30 => ATR% = 3.0%
        # TR = 30 for all candles
        candles = _make_ohlcv(
            [(1000, 1015, 985, 1000)] +  # prev_close = 1000
            [(1000, 1030, 1000, 1000)] * 14  # TR = max(30, |1030-1000|, |1000-1000|) = max(30, 30, 0) = 30
        )

        self.mock_exchange.fetch_ohlcv.return_value = candles
        result = self.fetcher.calculate_atr('BTC/USDT:USDT')

        assert result['atr_percent'] == pytest.approx(3.0, rel=1e-4)
        assert result['volatility_level'] == 'medium'

    def test_boundary_6_percent(self):
        """Test volatility level at exactly 6% boundary (should be medium)."""
        # Need ATR% = exactly 6.0%
        # Price = 1000, ATR = 60 => ATR% = 6.0%
        # TR = 60 for all candles
        candles = _make_ohlcv(
            [(1000, 1030, 970, 1000)] +  # prev_close = 1000
            [(1000, 1060, 1000, 1000)] * 14  # TR = max(60, |1060-1000|, |1000-1000|) = max(60, 60, 0) = 60
        )

        self.mock_exchange.fetch_ohlcv.return_value = candles
        result = self.fetcher.calculate_atr('BTC/USDT:USDT')

        assert result['atr_percent'] == pytest.approx(6.0, rel=1e-4)
        assert result['volatility_level'] == 'medium'

    def test_return_dict_structure(self):
        """Test that the return dict has the correct keys."""
        candles = _make_ohlcv([(100, 110, 90, 100)] * 15)
        self.mock_exchange.fetch_ohlcv.return_value = candles

        result = self.fetcher.calculate_atr('BTC/USDT:USDT')

        assert 'atr_value' in result
        assert 'atr_percent' in result
        assert 'volatility_level' in result
        assert len(result) == 3
