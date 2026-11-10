"""Intel endpoints are public: refreshes must be single-flight and a failed
refresh must not be retried on every request (Binance weight is shared with
the live-trading IP)."""

import asyncio

import src.services.intel_service as mod
from src.services.intel_service import IntelService


class _Resp:
    def __init__(self, status, payload=None):
        self.status_code = status
        self._payload = payload
        self.text = ""

    def json(self):
        return self._payload


def test_failed_news_refresh_is_backed_off():
    svc = IntelService()
    calls = {"n": 0}

    async def fail(*a, **k):
        calls["n"] += 1
        return _Resp(503)

    svc._client.get = fail

    async def run():
        first = await svc.get_news_data()
        n_after_first = calls["n"]
        for _ in range(5):
            again = await svc.get_news_data()
            assert again["status"] == "unavailable"
        return first, n_after_first

    first, n_after_first = asyncio.run(run())
    assert first["status"] == "unavailable"
    assert calls["n"] == n_after_first  # no upstream calls during backoff
    assert svc._news_cache is None      # failures never become the "good" cache


def test_failed_refresh_retried_after_backoff(monkeypatch):
    svc = IntelService()
    calls = {"n": 0}

    async def fail(*a, **k):
        calls["n"] += 1
        return _Resp(503)

    svc._client.get = fail
    clock = {"t": 1_000.0}
    monkeypatch.setattr(mod.time, "time", lambda: clock["t"])
    asyncio.run(svc.get_whales_data())
    n1 = calls["n"]
    clock["t"] += mod.FAILURE_RETRY_SECONDS + 1
    asyncio.run(svc.get_whales_data())
    assert calls["n"] > n1


def test_concurrent_requests_share_one_refresh():
    svc = IntelService()
    calls = {"n": 0}

    async def slow_fail(*a, **k):
        calls["n"] += 1
        await asyncio.sleep(0.01)
        return _Resp(503)

    svc._client.get = slow_fail

    async def run():
        await asyncio.gather(*[svc.get_whales_data() for _ in range(10)])

    asyncio.run(run())
    single = calls["n"]

    svc2 = IntelService()
    calls["n"] = 0
    svc2._client.get = slow_fail
    asyncio.run(svc2.get_whales_data())
    assert single == calls["n"]  # 10 concurrent callers cost one refresh
