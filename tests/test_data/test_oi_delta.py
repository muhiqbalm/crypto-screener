"""
Unit tests for Open Interest Delta calculation (MarketDataFetcher.calculate_oi_delta).

calculate_oi_delta() reads current OI from Binance ``/fapi/v1/openInterest`` and
historical OI from ``/futures/data/openInterestHist`` via ``requests.get``, so the
tests mock ``requests.get`` and ``fetch_ticker_data`` (used for the price leg of
the interpretation matrix).

Tests cover:
- OI delta calculation with known values
- Interpretation matrix (all 4 combinations + neutral)
- Zero / missing OI handling
- API error handling
- Symbol conversion to the Binance id for both requests
"""

from unittest.mock import Mock, patch

import pytest

from src.data.fetcher import MarketDataFetcher

CURRENT_OI_URL = 'https://fapi.binance.com/fapi/v1/openInterest'
HIST_OI_URL = 'https://fapi.binance.com/futures/data/openInterestHist'


def _response(payload):
    resp = Mock()
    resp.json.return_value = payload
    resp.raise_for_status.return_value = None
    return resp


def _fake_get(current=None, history=None, current_exc=None, history_exc=None):
    """Build a requests.get replacement that answers both OI endpoints."""

    def fake_get(url, params=None, timeout=None):
        if url == CURRENT_OI_URL:
            if current_exc:
                raise current_exc
            return _response(current)
        if url == HIST_OI_URL:
            if history_exc:
                raise history_exc
            return _response(history)
        raise AssertionError(f"unexpected URL {url}")

    return Mock(side_effect=fake_get)


def _history(value):
    # One data point; calculate_oi_delta picks the point closest to now-24h.
    return [{'sumOpenInterest': str(value), 'timestamp': 1_000_000}]


class TestOIDeltaCalculation:
    """Test suite for calculate_oi_delta() method."""

    @pytest.fixture
    def mock_exchange(self):
        exchange = Mock()
        exchange.market.return_value = {'id': 'BTCUSDT'}
        return exchange

    @pytest.fixture
    def fetcher(self, mock_exchange):
        f = MarketDataFetcher(exchange=mock_exchange, symbols=['BTC/USDT:USDT'])
        return f

    def _run(self, fetcher, get_mock, change_24h=0.0):
        with patch('requests.get', get_mock), \
             patch.object(fetcher, 'fetch_ticker_data',
                          return_value={'price': 50000, 'change_24h': change_24h}):
            return fetcher.calculate_oi_delta('BTC/USDT:USDT')

    def test_oi_delta_calculation_positive(self, fetcher):
        get = _fake_get(current={'openInterest': '120000'}, history=_history(100000))
        result = self._run(fetcher, get)

        assert set(result) == {'current_oi', 'oi_24h_ago', 'oi_delta_percent', 'interpretation'}
        assert result['current_oi'] == 120000
        assert result['oi_24h_ago'] == 100000
        # ((120000 - 100000) / 100000) * 100 = 20%
        assert result['oi_delta_percent'] == pytest.approx(20.0)

    def test_oi_delta_calculation_negative(self, fetcher):
        get = _fake_get(current={'openInterest': '80000'}, history=_history(100000))
        result = self._run(fetcher, get)
        assert result['oi_delta_percent'] == pytest.approx(-20.0)

    def test_interpretation_oi_up_price_up(self, fetcher):
        get = _fake_get(current={'openInterest': '120000'}, history=_history(100000))
        result = self._run(fetcher, get, change_24h=10.0)
        assert result['interpretation'] == 'New longs opening (bullish)'

    def test_interpretation_oi_up_price_down(self, fetcher):
        get = _fake_get(current={'openInterest': '120000'}, history=_history(100000))
        result = self._run(fetcher, get, change_24h=-10.0)
        assert result['interpretation'] == 'New shorts opening (bearish)'

    def test_interpretation_oi_down_price_down(self, fetcher):
        get = _fake_get(current={'openInterest': '80000'}, history=_history(100000))
        result = self._run(fetcher, get, change_24h=-10.0)
        assert result['interpretation'] == 'Longs closing (liquidation)'

    def test_interpretation_oi_down_price_up(self, fetcher):
        get = _fake_get(current={'openInterest': '80000'}, history=_history(100000))
        result = self._run(fetcher, get, change_24h=10.0)
        assert result['interpretation'] == 'Shorts closing (squeeze)'

    def test_interpretation_neutral(self, fetcher):
        # |delta| <= 1% is treated as stable OI regardless of price.
        get = _fake_get(current={'openInterest': '100500'}, history=_history(100000))
        result = self._run(fetcher, get, change_24h=0.3)
        assert result['oi_delta_percent'] == pytest.approx(0.5)
        assert result['interpretation'] == 'Neutral (OI stable)'

    def test_ticker_failure_treats_price_change_as_zero(self, fetcher):
        get = _fake_get(current={'openInterest': '120000'}, history=_history(100000))
        with patch('requests.get', get), \
             patch.object(fetcher, 'fetch_ticker_data', side_effect=Exception('boom')):
            result = fetcher.calculate_oi_delta('BTC/USDT:USDT')
        assert result['interpretation'] == 'New shorts opening (bearish)'

    def test_zero_oi_24h_ago_handling(self, fetcher):
        get = _fake_get(current={'openInterest': '120000'}, history=_history(0))
        result = self._run(fetcher, get)
        assert result == {
            'current_oi': None, 'oi_24h_ago': None,
            'oi_delta_percent': None, 'interpretation': None,
        }

    def test_current_oi_api_error(self, fetcher):
        get = _fake_get(current_exc=Exception('rate limit exceeded'), history=_history(100000))
        result = self._run(fetcher, get)
        assert result == {
            'current_oi': None, 'oi_24h_ago': None,
            'oi_delta_percent': None, 'interpretation': None,
        }

    def test_historical_oi_api_error(self, fetcher):
        get = _fake_get(current={'openInterest': '120000'},
                        history_exc=Exception('historical data not available'))
        result = self._run(fetcher, get)
        assert result['oi_24h_ago'] is None
        assert result['oi_delta_percent'] is None
        assert result['interpretation'] is None

    def test_empty_historical_oi_response(self, fetcher):
        get = _fake_get(current={'openInterest': '120000'}, history=[])
        result = self._run(fetcher, get)
        assert result['oi_24h_ago'] is None
        assert result['oi_delta_percent'] is None
        assert result['interpretation'] is None

    def test_malformed_historical_oi_response(self, fetcher):
        # Missing sumOpenInterest -> unknown (None), never a fake 0 -> nulls.
        get = _fake_get(current={'openInterest': '120000'}, history=[{'timestamp': 1_000_000}])
        result = self._run(fetcher, get)
        assert result['oi_delta_percent'] is None
        assert result['interpretation'] is None

    def test_very_large_oi_delta(self, fetcher):
        get = _fake_get(current={'openInterest': '200000'}, history=_history(100000))
        result = self._run(fetcher, get)
        assert result['oi_delta_percent'] == pytest.approx(100.0)

    def test_symbol_format_conversion(self, fetcher, mock_exchange):
        get = _fake_get(current={'openInterest': '120000'}, history=_history(100000))
        self._run(fetcher, get)

        mock_exchange.market.assert_called_with('BTC/USDT:USDT')
        calls = {c.args[0]: c.kwargs['params'] for c in get.call_args_list}
        assert calls[CURRENT_OI_URL] == {'symbol': 'BTCUSDT'}
        assert calls[HIST_OI_URL]['symbol'] == 'BTCUSDT'
        assert calls[HIST_OI_URL]['period'] == '1h'
        assert calls[HIST_OI_URL]['limit'] == 25

    def test_missing_current_oi_is_unknown_not_zero(self, fetcher):
        # A response without openInterest used to become 0.0 -> a fake -100%
        # OI delta ("Longs closing"). It must now be reported as unknown.
        get = _fake_get(current={'symbol': 'BTCUSDT'}, history=_history(100000))
        result = self._run(fetcher, get)
        assert result['current_oi'] is None
        assert result['oi_delta_percent'] is None
        assert result['interpretation'] is None

    @pytest.mark.parametrize('bad', [None, '', 'abc', {'code': -1121}])
    def test_non_numeric_current_oi_is_unknown(self, fetcher, bad):
        payload = bad if isinstance(bad, dict) else {'openInterest': bad}
        get = _fake_get(current=payload, history=_history(100000))
        result = self._run(fetcher, get)
        assert result['oi_delta_percent'] is None

    def test_current_oi_is_memoized_when_enabled(self, mock_exchange):
        f = MarketDataFetcher(exchange=mock_exchange, symbols=['BTC/USDT:USDT'], memoize=True)
        get = _fake_get(current={'openInterest': '120000'}, history=_history(100000))
        with patch('requests.get', get):
            assert f._fetch_current_oi('BTC/USDT:USDT') == 120000.0
            assert f._fetch_current_oi('BTC/USDT:USDT') == 120000.0
        assert sum(1 for c in get.call_args_list if c.args[0] == CURRENT_OI_URL) == 1
