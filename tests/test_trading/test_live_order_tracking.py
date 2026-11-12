"""Audit 2026-11-13 fixes in the live order path: K1, K2, K3, P7.

Everything runs against a fake exchange and a temp SQLite file. No network,
no keys, and the Telegram notifier is a mock.
"""

import asyncio
import time
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import ccxt.async_support as ccxt_async
import httpx
import pytest
from fastapi import FastAPI

from src.trading import position_manager as pm_module
from src.trading import router as router_module
from src.trading import webhook_jobs
from src.trading.executor import OrderExecutionError, TradeExecutor
from src.trading.local_db import LocalDatabaseClient
from src.trading.models import WebhookPayload
from src.trading.position_manager import PositionManager
from src.trading.trade_logger import TradeLogger

SYMBOL = "ETH/USDT:USDT"


class FakeExchange:
    """A futures account with one symbol. ``answer`` decides how create_order replies."""

    def __init__(self, exchange_id="binanceusdm", answer="ok", contract_size=1.0,
                 balance=1000.0, price=100.0):
        self.id = exchange_id
        self.answer = answer          # "ok" | "hang" | "network" | "reject"
        self.accepts = True           # False: the order never reaches the exchange
        self.market_data = {"limits": {"amount": {"min": 0.001}}, "contractSize": contract_size}
        self.balance, self.price = balance, price
        self.contracts, self.side = 0.0, None
        self.orders: list[dict] = []
        self.position_calls = 0
        self.position_error: Exception | None = None
        self.closed = False

    async def fetch_positions(self, _symbols):
        self.position_calls += 1
        # The first call is the pre-order check; only later checks can be made to fail.
        if self.position_error is not None and self.position_calls > 1:
            raise self.position_error
        if not self.contracts:
            return []
        return [{"contracts": self.contracts, "side": self.side, "entryPrice": self.price}]

    async def fetch_balance(self):
        return {"free": {"USDT": self.balance}}

    async def fetch_ticker(self, _symbol):
        return {"last": self.price}

    def market(self, _symbol):
        return self.market_data

    def amount_to_precision(self, _symbol, quantity):
        return f"{quantity:.3f}"

    async def set_margin_mode(self, *_args):
        return None

    async def create_order(self, symbol, type, side, amount, params):
        self.orders.append({"symbol": symbol, "type": type, "side": side,
                            "amount": amount, "params": params})
        if self.answer == "reject":
            raise ccxt_async.InsufficientFunds("margin is insufficient")
        if self.accepts:
            if params.get("reduceOnly"):
                self.contracts = 0.0
            else:
                self.contracts, self.side = amount, "long" if side == "buy" else "short"
        if self.answer == "hang":
            await asyncio.sleep(30)
        if self.answer == "network":
            raise ccxt_async.RequestTimeout("connection reset")
        return {"id": f"order-{len(self.orders)}", "average": self.price, "filled": amount}

    async def close(self):
        self.closed = True


@pytest.fixture
def env(tmp_path, monkeypatch):
    pm_module._position_locks.clear()
    webhook_jobs.reset()
    monkeypatch.setattr(TradeExecutor, "ORDER_TIMEOUT_SECONDS", 0.05)
    monkeypatch.setattr(PositionManager, "OPEN_CONFIRM_DELAYS_SECONDS", (0.01, 0.01, 0.01))
    monkeypatch.setattr(PositionManager, "OPEN_CONFIRM_CALL_TIMEOUT_SECONDS", 0.2)
    monkeypatch.setattr(PositionManager, "RECORD_RETRY_DELAY_SECONDS", 0.0)
    db = LocalDatabaseClient(str(tmp_path / "trading.db"))
    notifier = MagicMock(send_alert=AsyncMock(), send_trade_notification=AsyncMock())
    yield SimpleNamespace(db=db, notifier=notifier, tmp_path=tmp_path)
    webhook_jobs.reset()


def payload(**overrides) -> WebhookPayload:
    return WebhookPayload(**{
        "action": "open", "symbol": "ETHUSDT", "side": "long", "size_type": "percent",
        "size_value": 10, "leverage": 2, "exchange": "binance", "passphrase": "x" * 8,
        **overrides,
    })


async def run_job(env, exchange, db=None, **overrides):
    db = db or env.db
    p = payload(**overrides)
    connector = MagicMock(
        create_exchange=AsyncMock(return_value=exchange), apply_leverage=AsyncMock()
    )
    await router_module._execute_trade_job(
        payload=p, user_id="u1", account_name="Tester", chat_id="-100",
        alert_prefix=f"ALERT Tester {p.action.upper()} {p.symbol}", credentials={},
        trade_logger=TradeLogger(db), position_manager=PositionManager(db),
        trading_connector=connector, executor=TradeExecutor(), notifier=env.notifier,
        started_at=time.perf_counter(),
    )


def positions(env):
    return env.db.table("positions").select("*").execute().data


def logs(env):
    return env.db.table("trade_logs").select("*").execute().data


def alerts(env):
    return [call.args[1] for call in env.notifier.send_alert.await_args_list]


def lock_is_free():
    lock = pm_module._position_locks.get(f"u1:{SYMBOL}")
    return lock is None or not lock.locked()


# ---------------------------------------------------------------------------
# K1: an open order that got no answer is looked up before it is called failed
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize("answer", ["hang", "network"])
async def test_unanswered_open_that_filled_is_recorded_like_a_normal_open(env, answer):
    exchange = FakeExchange(answer=answer)

    await run_job(env, exchange)

    assert len(exchange.orders) == 1  # never re-sent
    [row] = positions(env)
    assert (row["status"], row["side"], row["symbol"], row["exchange"]) == (
        "open", "long", SYMBOL, "binance")
    assert (row["quantity"], row["entry_price"]) == (exchange.orders[0]["amount"], 100.0)
    [log] = logs(env)
    assert (log["status"], log["action"], log["fill_price"], log["filled_quantity"]) == (
        "success", "open", 100.0, exchange.orders[0]["amount"])
    env.notifier.send_trade_notification.assert_awaited_once()
    [text] = alerts(env)
    assert "recorded as opened" in text and "not re-sent" in text
    assert lock_is_free() and exchange.closed


@pytest.mark.asyncio
async def test_position_recovered_after_timeout_is_closed_by_the_close_alert(env):
    """The audit's case A end to end: the orphan no longer happens."""
    exchange = FakeExchange(answer="hang")
    await run_job(env, exchange)
    exchange.answer = "ok"

    await run_job(env, exchange, action="close")

    assert exchange.contracts == 0.0
    assert [o["side"] for o in exchange.orders] == ["buy", "sell"]
    assert exchange.orders[1]["params"] == {"reduceOnly": True}
    assert positions(env)[0]["status"] == "closed"


@pytest.mark.asyncio
async def test_unanswered_open_that_never_arrived_fails_after_checking(env):
    exchange = FakeExchange(answer="hang")
    exchange.accepts = False

    await run_job(env, exchange)

    assert len(exchange.orders) == 1
    assert exchange.position_calls == 1 + 3  # pre-order check + every confirmation
    assert positions(env) == []
    [log] = logs(env)
    assert log["status"] == "failed"
    assert "timed out" in log["error_details"]
    assert "no position was opened" in log["error_details"]
    assert "UNKNOWN" not in alerts(env)[0]
    env.notifier.send_trade_notification.assert_not_awaited()
    assert lock_is_free()


@pytest.mark.asyncio
async def test_unanswered_open_with_unreadable_exchange_alerts_the_human(env):
    exchange = FakeExchange(answer="hang")
    exchange.position_error = ccxt_async.ExchangeNotAvailable("502 bad gateway")

    await run_job(env, exchange)

    assert len(exchange.orders) == 1  # bounded checks, never a second order
    assert exchange.position_calls == 1 + 3
    assert positions(env) == []
    [text] = alerts(env)
    assert "ORDER OUTCOME UNKNOWN" in text
    assert "LONG" in text and SYMBOL in text
    assert "Check the exchange now" in text and "not re-sent" in text
    assert logs(env)[0]["status"] == "failed"
    assert lock_is_free() and exchange.closed


@pytest.mark.asyncio
async def test_slow_position_check_counts_as_unknown_not_as_flat(env):
    exchange = FakeExchange(answer="hang")
    real = exchange.fetch_positions

    async def slow_after_first(symbols):
        if exchange.position_calls >= 1:
            exchange.position_calls += 1
            await asyncio.sleep(5)
        return await real(symbols)

    exchange.fetch_positions = slow_after_first

    await run_job(env, exchange)

    assert "ORDER OUTCOME UNKNOWN" in alerts(env)[0]
    assert positions(env) == []


@pytest.mark.asyncio
async def test_opposite_side_position_after_timeout_is_not_adopted(env):
    exchange = FakeExchange(answer="hang")
    exchange.accepts = False
    real = exchange.fetch_positions

    async def short_appears(symbols):
        if exchange.position_calls >= 1:
            exchange.contracts, exchange.side = 2.0, "short"
        return await real(symbols)

    exchange.fetch_positions = short_appears

    await run_job(env, exchange)

    assert positions(env) == []
    assert "ORDER OUTCOME UNKNOWN" in alerts(env)[0]
    assert "shows a short position" in alerts(env)[0]


@pytest.mark.asyncio
async def test_fill_seen_on_a_later_check_is_still_recorded(env):
    exchange = FakeExchange(answer="hang")
    exchange.accepts = False
    real = exchange.fetch_positions

    async def fills_late(symbols):
        if exchange.position_calls == 2:  # flat on the first confirmation
            exchange.contracts, exchange.side = 2.0, "long"
        return await real(symbols)

    exchange.fetch_positions = fills_late

    await run_job(env, exchange)

    assert positions(env)[0]["quantity"] == 2.0
    assert logs(env)[0]["status"] == "success"


@pytest.mark.asyncio
async def test_exchange_rejection_is_a_plain_failure_without_lookup(env):
    exchange = FakeExchange(answer="reject")

    await run_job(env, exchange)

    assert exchange.position_calls == 1  # only the pre-order check
    assert positions(env) == []
    assert logs(env)[0]["status"] == "failed"
    assert "margin is insufficient" in alerts(env)[0]
    assert "UNKNOWN" not in alerts(env)[0]


@pytest.mark.asyncio
async def test_unanswered_close_keeps_the_old_behaviour(env):
    exchange = FakeExchange()
    await run_job(env, exchange)
    exchange.answer = "hang"
    exchange.position_calls = 0

    await run_job(env, exchange, action="close")

    assert exchange.position_calls == 1  # no confirmation loop for closes
    assert logs(env)[-1]["status"] == "failed"
    assert "timed out" in alerts(env)[-1]
    assert positions(env)[0]["status"] == "open"  # the record is not touched


@pytest.mark.asyncio
async def test_lock_is_held_while_the_exchange_is_asked(env, monkeypatch):
    exchange = FakeExchange(answer="hang")
    seen = []
    real = exchange.fetch_positions

    async def spy(symbols):
        seen.append(lock_is_free())
        return await real(symbols)

    exchange.fetch_positions = spy

    await run_job(env, exchange)

    assert seen == [False, False]  # pre-order check, then the confirmation that found it
    assert lock_is_free()


@pytest.mark.asyncio
async def test_webhook_acks_fast_while_confirmation_runs_in_the_background(env, monkeypatch):
    """The lookup and its waits happen after the 202, never before it."""
    monkeypatch.setattr(PositionManager, "OPEN_CONFIRM_DELAYS_SECONDS", (0.3, 0.3, 0.3))
    env.db.table("users").insert(
        {"id": "u1", "email": "a@b.c", "name": "Tester", "is_active": True}
    ).execute()
    env.db.table("webhook_configs").insert(
        {"id": "w1", "user_id": "u1", "passphrase": "test-passphrase", "is_active": True}
    ).execute()
    exchange = FakeExchange(answer="hang")
    settings = SimpleNamespace(
        max_payload_size=1_048_576, encryption_key="key", testnet_enabled=False,
        ccxt_verbose=False, telegram_bot_token="token", telegram_default_chat_id="-100",
        halt_file=str(env.tmp_path / "HALT"), max_leverage=0, max_notional_usdt=0.0,
    )
    monkeypatch.setattr(router_module, "CredentialStore", MagicMock(return_value=MagicMock(
        get_credentials=AsyncMock(return_value={"api_key": "k", "secret": "s"})
    )))
    monkeypatch.setattr(router_module, "TradingConnector", MagicMock(return_value=MagicMock(
        create_exchange=AsyncMock(return_value=exchange), apply_leverage=AsyncMock()
    )))
    monkeypatch.setattr(router_module, "TelegramNotifier", MagicMock(return_value=env.notifier))
    app = FastAPI()
    app.include_router(router_module.router)
    app.dependency_overrides[router_module.get_settings] = lambda: settings
    app.dependency_overrides[router_module.get_supabase_client] = lambda: env.db

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        started = time.perf_counter()
        response = await client.post("/webhook/tradingview", json={
            "action": "open", "symbol": "ETHUSDT.P", "side": "long", "size_type": "percent",
            "size_value": 10, "leverage": 2, "exchange": "binance",
            "passphrase": "test-passphrase",
        })
        elapsed = time.perf_counter() - started
        assert response.status_code == 202
        assert elapsed < 0.3
        assert positions(env) == []  # nothing decided yet
        await asyncio.wait(list(webhook_jobs._jobs), timeout=10)

    assert positions(env)[0]["status"] == "open"
    assert len(exchange.orders) == 1


# ---------------------------------------------------------------------------
# K2: a position-record write that fails is retried, then alerted
# ---------------------------------------------------------------------------


class FlakyDb:
    """Wraps the database; the next ``failures`` position writes raise."""

    def __init__(self, db, failures, on="insert"):
        self.db, self.failures, self.on = db, failures, on
        self.attempts = 0

    def table(self, name):
        query = self.db.table(name)
        if name != "positions":
            return query
        real = getattr(query, self.on)

        def write(*args, **kwargs):
            self.attempts += 1
            if self.failures > 0:
                self.failures -= 1
                raise RuntimeError("database is locked")
            return real(*args, **kwargs)

        setattr(query, self.on, write)
        return query


@pytest.mark.asyncio
async def test_record_write_is_retried_and_succeeds_silently(env):
    exchange = FakeExchange()
    db = FlakyDb(env.db, failures=1)

    await run_job(env, exchange, db=db)

    assert db.attempts == 2
    assert positions(env)[0]["status"] == "open"
    assert alerts(env) == []
    env.notifier.send_trade_notification.assert_awaited_once()


@pytest.mark.asyncio
async def test_record_write_that_keeps_failing_alerts_about_the_real_position(env):
    exchange = FakeExchange()
    db = FlakyDb(env.db, failures=99)

    await run_job(env, exchange, db=db)

    assert db.attempts == PositionManager.RECORD_WRITE_ATTEMPTS
    assert exchange.contracts > 0 and positions(env) == []
    [text] = alerts(env)
    assert "REAL POSITION WITHOUT A RECORD" in text
    assert "long" in text and SYMBOL in text and "order-1" in text
    assert "database is locked" in text
    # The order is live, so the trade is still logged and announced as before.
    assert logs(env)[0]["status"] == "success"
    env.notifier.send_trade_notification.assert_awaited_once()
    assert lock_is_free()


@pytest.mark.asyncio
async def test_close_is_still_refused_when_the_record_is_missing(env):
    """No fallback to the exchange position: see the report for why."""
    exchange = FakeExchange()
    await run_job(env, exchange, db=FlakyDb(env.db, failures=99))

    await run_job(env, exchange, action="close")

    assert len(exchange.orders) == 1 and exchange.contracts > 0
    assert "not opened by the bot" in alerts(env)[-1]


@pytest.mark.asyncio
async def test_failed_close_record_update_is_alerted(env):
    exchange = FakeExchange()
    await run_job(env, exchange)
    db = FlakyDb(env.db, failures=99, on="update")

    await run_job(env, exchange, db=db, action="close")

    assert exchange.contracts == 0.0
    assert db.attempts == PositionManager.RECORD_WRITE_ATTEMPTS
    assert "record still says open" in alerts(env)[-1]
    assert logs(env)[-1]["status"] == "success"


# ---------------------------------------------------------------------------
# P7: a close must name the side the bot holds
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_close_with_the_wrong_side_is_refused_and_alerted(env):
    exchange = FakeExchange()
    await run_job(env, exchange)  # bot opens long

    await run_job(env, exchange, action="close", side="short")

    assert len(exchange.orders) == 1 and exchange.contracts > 0
    assert positions(env)[0]["status"] == "open"
    assert logs(env)[-1]["status"] == "rejected"
    text = alerts(env)[-1]
    assert "close skipped" in text and "close short" in text and "is long" in text
    assert lock_is_free()


@pytest.mark.asyncio
@pytest.mark.parametrize("side", ["long", "short"])
async def test_close_with_the_matching_side_still_closes(env, side):
    exchange = FakeExchange()
    await run_job(env, exchange, side=side)

    await run_job(env, exchange, action="close", side=side)

    assert exchange.contracts == 0.0
    assert positions(env)[0]["status"] == "closed"
    assert alerts(env) == []


# ---------------------------------------------------------------------------
# K3: OKX orders are sent in contracts; Binance is untouched
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "contract_size, expected_contracts",
    [(100.0, 0.02), (0.01, 200.0), (1.0, 2.0)],
)
async def test_okx_percent_size_is_converted_to_contracts(contract_size, expected_contracts):
    # 1000 USDT x 10% x 2 = 200 USDT notional = 2 coins at 100.
    exchange = FakeExchange("okx", contract_size=contract_size)

    _order, info = await TradeExecutor().execute_trade(exchange, payload(exchange="okx"))

    assert exchange.orders[0]["amount"] == pytest.approx(expected_contracts)
    assert exchange.orders[0]["amount"] * contract_size * 100.0 == pytest.approx(200.0)
    assert info["order_quantity"] == pytest.approx(expected_contracts)
    assert info["order_notional"] == pytest.approx(200.0)
    assert info["margin_required"] == pytest.approx(100.0)


@pytest.mark.asyncio
async def test_okx_fixed_size_in_coins_is_converted_to_contracts():
    exchange = FakeExchange("okx", contract_size=10.0)

    await TradeExecutor().execute_trade(
        exchange, payload(exchange="okx", size_type="fixed", size_value=5, leverage=10)
    )

    assert exchange.orders[0]["amount"] == pytest.approx(0.5)


@pytest.mark.asyncio
async def test_okx_notional_cap_is_applied_in_coins():
    exchange = FakeExchange("okx", contract_size=100.0)

    _order, info = await TradeExecutor(max_notional=150.0).execute_trade(
        exchange, payload(exchange="okx")
    )

    assert exchange.orders[0]["amount"] * 100.0 * 100.0 == pytest.approx(150.0)
    assert info["order_notional"] == pytest.approx(150.0)


@pytest.mark.asyncio
async def test_okx_order_below_one_lot_is_refused_not_rounded_up():
    exchange = FakeExchange("okx", contract_size=100.0)
    exchange.market_data["limits"]["amount"]["min"] = 1.0

    with pytest.raises(Exception, match="below the minimum"):
        await TradeExecutor().execute_trade(exchange, payload(exchange="okx"))
    assert exchange.orders == []


@pytest.mark.asyncio
@pytest.mark.parametrize("bad", [None, 0, -1, "abc", float("nan")])
async def test_okx_without_a_usable_contract_size_sends_no_order(bad):
    exchange = FakeExchange("okx")
    exchange.market_data["contractSize"] = bad

    with pytest.raises(OrderExecutionError, match="Contract size"):
        await TradeExecutor().execute_trade(exchange, payload(exchange="okx"))
    assert exchange.orders == []


def _amount_before_fix(exchange, p, max_notional):
    """The open-order amount exactly as the executor computed it before K3."""
    free_balance, price, leverage = exchange.balance, exchange.price, p.leverage or 1
    if p.size_type == "percent":
        margin_used = free_balance * p.size_value / 100
        quantity = margin_used * max(leverage, 1) / price
    else:
        quantity = p.size_value
    if max_notional and quantity * price > max_notional:
        quantity = max_notional / price
    return float(exchange.amount_to_precision(p.symbol, quantity))


@pytest.mark.asyncio
@pytest.mark.parametrize("market_contract_size", [1.0, 100.0, None])
@pytest.mark.parametrize("max_notional", [0.0, 333.33])
@pytest.mark.parametrize("size_type, size_value", [
    ("percent", 10), ("percent", 33.3), ("percent", 100), ("fixed", 0.137),
])
@pytest.mark.parametrize("balance, price, leverage", [
    (1000.0, 100.0, 2), (873.4519, 3127.61, 4), (51.07, 0.4312, 20), (25000.0, 97123.4, 1),
])
async def test_binance_order_is_bit_identical_to_before(
    market_contract_size, max_notional, size_type, size_value, balance, price, leverage
):
    exchange = FakeExchange("binanceusdm", balance=balance, price=price)
    # Even a market that reports a contract size must not change a Binance order.
    exchange.market_data["contractSize"] = market_contract_size
    exchange.amount_to_precision = lambda _s, q: f"{q:.6f}"
    p = payload(size_type=size_type, size_value=size_value, leverage=leverage)
    expected = _amount_before_fix(exchange, p, max_notional)

    try:
        _order, info = await TradeExecutor(max_notional=max_notional).execute_trade(exchange, p)
    except Exception as exc:  # insufficient margin: must be refused as before
        assert "Insufficient margin" in str(exc)
        assert exchange.orders == []
        assert round(expected * price / leverage, 6) > balance
        return

    order = exchange.orders[0]
    assert order["amount"].hex() == expected.hex()  # same bits, not just close
    assert order == {"symbol": SYMBOL, "type": "market", "side": "buy",
                     "amount": expected, "params": {}}
    assert info["order_quantity"].hex() == expected.hex()
    assert info["order_notional"] == round(expected * price, 6)
    assert info["margin_required"] == round((expected * price) / leverage, 6)
