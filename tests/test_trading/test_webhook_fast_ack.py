"""The webhook acknowledges fast and runs the order in a tracked background job.

The exchange, credential store and Telegram notifier are always mocked here.
"""

import asyncio
import os
import signal
import socket
import subprocess
import sys
import textwrap
import time
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest
from fastapi import FastAPI

from src.trading import position_manager, router as router_module, webhook_jobs
from src.trading.executor import OrderExecutionError
from src.trading.local_db import LocalDatabaseClient

PASSPHRASE = "test-passphrase"
REPO_ROOT = Path(__file__).resolve().parents[2]


def fake_exchange(order_delay: float = 0.0):
    exchange = MagicMock()
    exchange.id = "binanceusdm"
    exchange.positions = []
    exchange.fetch_positions = AsyncMock(side_effect=lambda _s: list(exchange.positions))
    exchange.fetch_balance = AsyncMock(return_value={"free": {"USDT": 1000.0}})
    exchange.fetch_ticker = AsyncMock(return_value={"last": 2000.0})
    exchange.market = MagicMock(return_value={"limits": {}})
    exchange.amount_to_precision = MagicMock(side_effect=lambda _s, q: str(q))
    exchange.order_started = asyncio.Event()

    async def create_order(**kwargs):
        exchange.order_started.set()
        await asyncio.sleep(order_delay)
        exchange.positions.append({"contracts": 1.0, "side": "long", "entryPrice": 2000.0})
        return {"id": f"order-{exchange.create_order.await_count}", "average": 2000.0, "filled": 1.0}

    exchange.create_order = AsyncMock(side_effect=create_order)
    exchange.close = AsyncMock()
    return exchange


@pytest.fixture
def ctx(tmp_path, monkeypatch):
    position_manager._position_locks.clear()
    webhook_jobs.reset()
    db = LocalDatabaseClient(str(tmp_path / "trading.db"))
    db.table("users").insert(
        {"id": "u1", "email": "a@b.c", "name": "Tester", "is_active": True}
    ).execute()
    db.table("webhook_configs").insert(
        {"id": "w1", "user_id": "u1", "passphrase": PASSPHRASE, "is_active": True}
    ).execute()

    settings = SimpleNamespace(
        max_payload_size=1_048_576, encryption_key="key", testnet_enabled=False,
        ccxt_verbose=False, telegram_bot_token="token", telegram_default_chat_id="-100",
        halt_file=str(tmp_path / "HALT"), max_leverage=0, max_notional_usdt=0.0,
    )
    exchange = fake_exchange()
    connector = MagicMock(create_exchange=AsyncMock(return_value=exchange), apply_leverage=AsyncMock())
    notifier = MagicMock(send_alert=AsyncMock(), send_trade_notification=AsyncMock())
    monkeypatch.setattr(router_module, "CredentialStore", MagicMock(return_value=MagicMock(
        get_credentials=AsyncMock(return_value={"api_key": "k", "secret": "s"})
    )))
    monkeypatch.setattr(router_module, "TradingConnector", MagicMock(return_value=connector))
    monkeypatch.setattr(router_module, "TelegramNotifier", MagicMock(return_value=notifier))

    app = FastAPI()
    app.include_router(router_module.router)
    app.dependency_overrides[router_module.get_settings] = lambda: settings
    app.dependency_overrides[router_module.get_supabase_client] = lambda: db
    yield SimpleNamespace(
        app=app, db=db, exchange=exchange, connector=connector, notifier=notifier,
        settings=settings,
    )
    webhook_jobs.reset()


def body(**overrides):
    return {
        "action": "open", "symbol": "ETHUSDT.P", "side": "long", "size_type": "percent",
        "size_value": 50, "leverage": 4, "exchange": "binance", "passphrase": PASSPHRASE,
        **overrides,
    }


def client_for(app):
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")


async def wait_for_jobs(timeout=10):
    tasks = list(webhook_jobs._jobs)
    if tasks:
        await asyncio.wait(tasks, timeout=timeout)
    assert not webhook_jobs._jobs


def logs(ctx):
    return ctx.db.table("trade_logs").select("*").execute().data


# ---------------------------------------------------------------------------
# Fast acknowledgement
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_ack_returns_before_slow_exchange_order_finishes(ctx):
    slow = fake_exchange(order_delay=2.0)
    ctx.connector.create_exchange.return_value = slow

    async with client_for(ctx.app) as client:
        started = time.perf_counter()
        response = await client.post("/webhook/tradingview", json=body())
        elapsed = time.perf_counter() - started

        assert response.status_code == 202
        assert response.json()["status"] == "accepted"
        assert response.json()["symbol"] == "ETH/USDT:USDT"
        assert elapsed < 0.3
        slow.create_order.assert_not_awaited()  # nothing touched the exchange yet
        await asyncio.wait_for(slow.order_started.wait(), 1)
        assert webhook_jobs.pending_jobs() == ["Tester open long ETH/USDT:USDT"]
        await wait_for_jobs()

    assert slow.create_order.await_count == 1
    assert [row["status"] for row in logs(ctx)] == ["success"]


@pytest.mark.asyncio
async def test_ack_latency_p99_under_300ms_with_slow_exchange(ctx):
    slow = fake_exchange(order_delay=1.5)
    ctx.connector.create_exchange.return_value = slow

    async def slow_positions(_symbols):
        await asyncio.sleep(1.0)
        return []

    slow.fetch_positions = AsyncMock(side_effect=slow_positions)
    latencies = []
    async with client_for(ctx.app) as client:
        for i in range(100):
            # Distinct symbols so no request is a duplicate of another.
            started = time.perf_counter()
            response = await client.post("/webhook/tradingview", json=body(symbol=f"C{i}USDT.P"))
            latencies.append(time.perf_counter() - started)
            assert response.status_code == 202
        await wait_for_jobs()

    latencies.sort()
    p50, p99 = latencies[49], latencies[98]
    print(f"\nwebhook ack latency over 100 requests: p50={p50*1000:.1f}ms "
          f"p99={p99*1000:.1f}ms max={latencies[-1]*1000:.1f}ms")
    assert p99 < 0.3
    assert slow.create_order.await_count == 100
    assert len([row for row in logs(ctx) if row["status"] == "success"]) == 100


# ---------------------------------------------------------------------------
# Background outcomes reach trade_logs and Telegram
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_background_success_logs_and_notifies(ctx):
    async with client_for(ctx.app) as client:
        assert (await client.post("/webhook/tradingview", json=body())).status_code == 202
        await wait_for_jobs()

    log = logs(ctx)[0]
    assert (log["status"], log["order_id"], log["fill_price"]) == ("success", "order-1", 2000.0)
    chat_id, trade, position = ctx.notifier.send_trade_notification.call_args.args
    assert (chat_id, trade["account"], trade["action"], position) == ("-100", "Tester", "open", None)
    ctx.notifier.send_alert.assert_not_awaited()
    ctx.connector.apply_leverage.assert_awaited_once_with(ctx.exchange, "binance", 4, "ETH/USDT:USDT")
    assert ctx.db.table("positions").select("*").execute().data[0]["status"] == "open"
    ctx.exchange.close.assert_awaited()


@pytest.mark.asyncio
async def test_background_order_failure_logs_and_alerts(ctx, monkeypatch):
    monkeypatch.setattr(
        router_module.TradeExecutor, "execute_trade",
        AsyncMock(side_effect=OrderExecutionError("binance rejected the order")),
    )
    async with client_for(ctx.app) as client:
        assert (await client.post("/webhook/tradingview", json=body())).status_code == 202
        await wait_for_jobs()

    log = logs(ctx)[0]
    assert log["status"] == "failed"
    assert "binance rejected the order" in log["error_details"]
    chat_id, text = ctx.notifier.send_alert.call_args.args
    assert chat_id == "-100"
    assert text.startswith("⚠️ Tester OPEN ETH/USDT:USDT") and "binance rejected the order" in text
    ctx.notifier.send_trade_notification.assert_not_awaited()
    assert not position_manager._position_locks["u1:ETH/USDT:USDT"].locked()


@pytest.mark.asyncio
async def test_background_unexpected_error_is_not_swallowed(ctx, caplog):
    ctx.exchange.fetch_ticker.side_effect = RuntimeError("ticker exploded")

    async with client_for(ctx.app) as client:
        assert (await client.post("/webhook/tradingview", json=body())).status_code == 202
        await wait_for_jobs()

    log = logs(ctx)[0]
    assert log["status"] == "failed"
    assert "Unexpected error" in log["error_details"]
    assert "Unexpected error" in ctx.notifier.send_alert.call_args.args[1]
    assert "Webhook job failed" in caplog.text
    assert not position_manager._position_locks["u1:ETH/USDT:USDT"].locked()
    ctx.exchange.close.assert_awaited()


@pytest.mark.asyncio
async def test_exchange_auth_failure_is_logged_and_alerted(ctx):
    ctx.connector.create_exchange.side_effect = router_module.AuthenticationError("bad key")

    async with client_for(ctx.app) as client:
        assert (await client.post("/webhook/tradingview", json=body())).status_code == 202
        await wait_for_jobs()

    assert logs(ctx)[0]["status"] == "failed"
    assert "bad key" in ctx.notifier.send_alert.call_args.args[1]


@pytest.mark.asyncio
async def test_failing_notifier_does_not_break_the_job(ctx, caplog):
    ctx.notifier.send_trade_notification.side_effect = RuntimeError("telegram down")

    async with client_for(ctx.app) as client:
        assert (await client.post("/webhook/tradingview", json=body())).status_code == 202
        await wait_for_jobs()

    assert logs(ctx)[0]["status"] == "success"
    assert "telegram down" in caplog.text


@pytest.mark.asyncio
async def test_slow_telegram_does_not_hold_the_symbol_lock(ctx):
    released = asyncio.Event()

    async def slow_alert(*_args):
        assert not position_manager._position_locks["u1:ETH/USDT:USDT"].locked()
        released.set()

    ctx.notifier.send_alert.side_effect = slow_alert
    ctx.exchange.positions.append({"contracts": 3.0, "side": "long"})  # manual position

    async with client_for(ctx.app) as client:
        assert (await client.post("/webhook/tradingview", json=body())).status_code == 202
        await wait_for_jobs()

    assert released.is_set()


# ---------------------------------------------------------------------------
# Idempotency
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_duplicate_delivery_while_in_flight_is_refused_fast(ctx):
    slow = fake_exchange(order_delay=1.0)
    ctx.connector.create_exchange.return_value = slow

    async with client_for(ctx.app) as client:
        first = await client.post("/webhook/tradingview", json=body())
        started = time.perf_counter()
        second = await client.post("/webhook/tradingview", json=body())
        elapsed = time.perf_counter() - started
        await wait_for_jobs()

    assert first.status_code == 202
    assert second.status_code == 409
    assert second.json()["error"] == "Duplicate alert"
    assert elapsed < 0.3
    assert slow.create_order.await_count == 1
    assert sorted(row["status"] for row in logs(ctx)) == ["rejected", "success"]
    assert "duplicate alert skipped" in ctx.notifier.send_alert.call_args.args[1]


@pytest.mark.asyncio
async def test_redelivery_after_completion_opens_no_second_position(ctx):
    async with client_for(ctx.app) as client:
        assert (await client.post("/webhook/tradingview", json=body())).status_code == 202
        await wait_for_jobs()
        assert (await client.post("/webhook/tradingview", json=body())).status_code == 202
        await wait_for_jobs()

    assert ctx.exchange.create_order.await_count == 1
    assert [row["status"] for row in logs(ctx)] == ["success", "rejected"]
    assert len(ctx.db.table("positions").select("*").execute().data) == 1


@pytest.mark.asyncio
async def test_close_and_reverse_open_both_run(ctx):
    """A close and an opposite open on one bar are different alerts."""
    ctx.db.table("positions").insert({
        "user_id": "u1", "symbol": "ETH/USDT:USDT", "side": "long", "entry_price": 1900.0,
        "quantity": 1.0, "status": "open", "exchange": "binance",
    }).execute()
    ctx.exchange.positions.append({"contracts": 1.0, "side": "long", "entryPrice": 1900.0})

    async def create_order(**kwargs):
        await asyncio.sleep(0.2)
        if kwargs.get("params") == {"reduceOnly": True}:
            ctx.exchange.positions.clear()
        else:
            ctx.exchange.positions.append({"contracts": 1.0, "side": "short"})
        return {"id": f"order-{ctx.exchange.create_order.await_count}", "average": 2000.0, "filled": 1.0}

    ctx.exchange.create_order.side_effect = create_order
    async with client_for(ctx.app) as client:
        close = await client.post("/webhook/tradingview", json=body(action="close"))
        reverse = await client.post("/webhook/tradingview", json=body(side="short"))
        await wait_for_jobs()

    assert (close.status_code, reverse.status_code) == (202, 202)
    calls = [c.kwargs for c in ctx.exchange.create_order.call_args_list]
    assert calls[0]["params"] == {"reduceOnly": True} and calls[0]["side"] == "sell"
    assert calls[1]["side"] == "sell" and calls[1].get("params") != {"reduceOnly": True}
    assert [row["status"] for row in logs(ctx)] == ["success", "success"]


# ---------------------------------------------------------------------------
# Synchronous rejections keep their status codes
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_bad_passphrase_is_401_and_starts_no_job(ctx):
    async with client_for(ctx.app) as client:
        started = time.perf_counter()
        response = await client.post("/webhook/tradingview", json=body(passphrase="wrong"))
        elapsed = time.perf_counter() - started

    assert response.status_code == 401
    assert elapsed < 0.3
    assert webhook_jobs.pending_jobs() == []
    ctx.connector.create_exchange.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("bad", [
    {"action": "buy"},
    {"size_value": 0},
    {"symbol": "not a symbol"},
    {"leverage": 500},
])
async def test_invalid_payload_is_422_and_starts_no_job(ctx, bad):
    async with client_for(ctx.app) as client:
        response = await client.post("/webhook/tradingview", json=body(**bad))

    assert response.status_code == 422
    assert webhook_jobs.pending_jobs() == []
    ctx.connector.create_exchange.assert_not_awaited()


@pytest.mark.asyncio
async def test_halt_is_still_403_without_a_job(ctx):
    open(ctx.settings.halt_file, "w").close()
    async with client_for(ctx.app) as client:
        response = await client.post("/webhook/tradingview", json=body())

    assert response.status_code == 403
    assert webhook_jobs.pending_jobs() == []


# ---------------------------------------------------------------------------
# Shutdown draining
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_drain_waits_for_in_flight_order(ctx, caplog):
    slow = fake_exchange(order_delay=0.5)
    ctx.connector.create_exchange.return_value = slow

    async with client_for(ctx.app) as client:
        assert (await client.post("/webhook/tradingview", json=body())).status_code == 202
        left = await webhook_jobs.drain(timeout=5)

        assert left == []
        assert slow.create_order.await_count == 1
        assert logs(ctx)[0]["status"] == "success"
        assert "Waiting for 1 in-flight webhook job(s)" in caplog.text

        # After the drain the endpoint refuses new work instead of losing it.
        response = await client.post("/webhook/tradingview", json=body(symbol="BTCUSDT.P"))
    assert response.status_code == 503
    assert logs(ctx)[-1]["status"] == "rejected"


@pytest.mark.asyncio
async def test_drain_timeout_reports_jobs_still_running(ctx, caplog):
    slow = fake_exchange(order_delay=1.0)
    ctx.connector.create_exchange.return_value = slow

    async with client_for(ctx.app) as client:
        await client.post("/webhook/tradingview", json=body())
        left = await webhook_jobs.drain(timeout=0.1)

        assert left == ["Tester open long ETH/USDT:USDT"]
        assert "still running" in caplog.text
        await wait_for_jobs()  # not cancelled: it still completes
    assert slow.create_order.await_count == 1


# ---------------------------------------------------------------------------
# Real server: the job survives the client hanging up, and SIGINT drains it
# ---------------------------------------------------------------------------


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


SERVER_SCRIPT = textwrap.dedent('''
    import asyncio, sys
    from unittest.mock import AsyncMock, MagicMock

    import uvicorn
    import src.api.app as app_module
    import src.exchange.connector as exchange_connector
    import src.trading.config as trading_config
    from src.trading import webhook_jobs

    # No network: fake screener, fake debug exchange, trading settings absent.
    app_module.DataProcessor = MagicMock(return_value=MagicMock(process_all=AsyncMock()))
    exchange_connector.ExchangeConnector = MagicMock()
    def no_trading():
        raise RuntimeError("trading not configured in this test")
    trading_config.get_trading_settings = no_trading

    port, marker = int(sys.argv[1]), sys.argv[2]
    app = app_module.create_app()

    async def slow_order():
        await asyncio.sleep(1.5)
        open(marker, "w").write("order done")

    @app.post("/test/job")
    async def start_job():
        webhook_jobs.submit(slow_order(), key="k", description="test open long ETH")
        return {"status": "accepted"}

    uvicorn.run(app, host="127.0.0.1", port=port, log_level="info")
''')


def _start_server(tmp_path):
    port = _free_port()
    marker = tmp_path / "marker"
    script = tmp_path / "server.py"
    script.write_text(SERVER_SCRIPT)
    env = {**os.environ, "PYTHONPATH": str(REPO_ROOT), "SCREENER_LOG_LEVEL": "INFO"}
    proc = subprocess.Popen(
        [sys.executable, str(script), str(port), str(marker)],
        cwd=str(tmp_path), env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
    )
    deadline = time.time() + 20
    while time.time() < deadline:
        try:
            httpx.get(f"http://127.0.0.1:{port}/api/v1/health", timeout=0.5)
            return proc, port, marker
        except httpx.HTTPError:
            if proc.poll() is not None:
                break
            time.sleep(0.2)
    proc.kill()
    pytest.fail("test server did not start:\n" + (proc.stdout.read() if proc.stdout else ""))


def test_sigint_drains_in_flight_job_before_exit(tmp_path):
    proc, port, marker = _start_server(tmp_path)
    try:
        response = httpx.post(f"http://127.0.0.1:{port}/test/job", timeout=2)
        assert response.status_code == 200
        proc.send_signal(signal.SIGINT)  # what PM2 sends on restart
        proc.wait(timeout=15)
    finally:
        if proc.poll() is None:
            proc.kill()
    output = proc.stdout.read()
    assert marker.read_text() == "order done", output
    assert "Waiting for 1 in-flight webhook job(s)" in output, output
    assert "All 1 in-flight webhook job(s) finished before shutdown" in output, output
    assert "Application shutdown complete" in output, output


@pytest.mark.asyncio
async def test_job_survives_client_disconnect_behind_middleware(ctx, tmp_path):
    """TradingView hanging up must not cancel an acknowledged order."""
    import uvicorn
    from starlette.middleware.base import BaseHTTPMiddleware

    slow = fake_exchange(order_delay=1.0)
    ctx.connector.create_exchange.return_value = slow

    class PassThrough(BaseHTTPMiddleware):  # production stacks BaseHTTPMiddleware
        async def dispatch(self, request, call_next):
            return await call_next(request)

    ctx.app.add_middleware(PassThrough)
    port = _free_port()
    server = uvicorn.Server(uvicorn.Config(ctx.app, host="127.0.0.1", port=port, log_level="warning"))
    server_task = asyncio.create_task(server.serve())
    try:
        while not server.started:
            await asyncio.sleep(0.05)
        async with httpx.AsyncClient() as client:
            response = await client.post(f"http://127.0.0.1:{port}/webhook/tradingview", json=body())
        assert response.status_code == 202
        # Client connection is closed now; the order must still complete.
        await wait_for_jobs()

        # Ack latency over real HTTP, each with a fresh connection like TradingView.
        slow.fetch_positions = AsyncMock(return_value=[])  # every symbol is flat
        latencies = []
        for i in range(50):
            async with httpx.AsyncClient() as client:
                started = time.perf_counter()
                response = await client.post(
                    f"http://127.0.0.1:{port}/webhook/tradingview", json=body(symbol=f"H{i}USDT.P")
                )
                latencies.append(time.perf_counter() - started)
            assert response.status_code == 202
        await wait_for_jobs()
    finally:
        server.should_exit = True
        await server_task

    latencies.sort()
    print(f"\nwebhook ack latency over real HTTP (50 requests, order takes 1s): "
          f"p50={latencies[24]*1000:.1f}ms p99={latencies[48]*1000:.1f}ms max={latencies[-1]*1000:.1f}ms")
    assert latencies[48] < 0.3
    assert slow.create_order.await_count == 51
    assert [row["status"] for row in logs(ctx)] == ["success"] * 51
    assert ctx.notifier.send_trade_notification.await_count == 51
