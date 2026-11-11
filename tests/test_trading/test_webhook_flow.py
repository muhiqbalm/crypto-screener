"""End-to-end webhook tests against a database with the original schema."""

import asyncio
import sqlite3
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.trading import position_manager, router as router_module, webhook_jobs
from src.trading.executor import TradeExecutor
from src.trading.local_db import LocalDatabaseClient
from src.trading.models import WebhookPayload
from src.trading.notifier import _calculate_pnl
from src.trading.position_manager import DuplicatePositionError, PositionManager

PASSPHRASE = "test-passphrase"
OLD_SCHEMA = """
CREATE TABLE positions (id TEXT PRIMARY KEY, user_id TEXT NOT NULL, symbol TEXT NOT NULL,
  side TEXT NOT NULL, size REAL, entry_price REAL, status TEXT NOT NULL,
  exchange TEXT NOT NULL DEFAULT 'binance', created_at TEXT NOT NULL, closed_at TEXT);
CREATE TABLE trade_logs (id TEXT PRIMARY KEY, user_id TEXT, symbol TEXT NOT NULL,
  action TEXT NOT NULL, side TEXT NOT NULL, exchange TEXT NOT NULL, size_value REAL,
  status TEXT NOT NULL, order_id TEXT, fill_price REAL, filled_quantity REAL,
  created_at TEXT NOT NULL);
"""


def fake_exchange(positions=None):
    exchange = MagicMock()
    exchange.id = "binanceusdm"
    exchange.fetch_positions = AsyncMock(return_value=positions or [])
    exchange.fetch_balance = AsyncMock(return_value={"free": {"USDT": 1000.0}})
    exchange.fetch_ticker = AsyncMock(return_value={"last": 2000.0})
    exchange.market = MagicMock(return_value={"limits": {}})
    exchange.amount_to_precision = MagicMock(side_effect=lambda _s, q: str(q))
    exchange.create_order = AsyncMock(
        return_value={"id": "order-1", "average": 2000.0, "filled": 1.0}
    )
    exchange.close = AsyncMock()
    return exchange


@pytest.fixture
def flow(tmp_path, monkeypatch):
    position_manager._position_locks.clear()
    webhook_jobs.reset()
    path = str(tmp_path / "old.db")
    conn = sqlite3.connect(path)
    conn.executescript(OLD_SCHEMA)
    conn.close()

    db = LocalDatabaseClient(path)
    db.table("users").insert(
        {"id": "u1", "email": "a@b.c", "name": "Tester", "is_active": True}
    ).execute()
    db.table("webhook_configs").insert(
        {"id": "w1", "user_id": "u1", "passphrase": PASSPHRASE, "is_active": True}
    ).execute()

    exchange = fake_exchange()
    settings = SimpleNamespace(
        max_payload_size=1_048_576,
        encryption_key="key",
        testnet_enabled=False,
        ccxt_verbose=False,
        telegram_bot_token="token",
        telegram_default_chat_id="-100",
        halt_file=str(tmp_path / "HALT"),
        max_leverage=0,
        max_notional_usdt=0.0,
    )
    monkeypatch.setattr(router_module, "CredentialStore", MagicMock(return_value=MagicMock(
        get_credentials=AsyncMock(return_value={"api_key": "k", "secret": "s"})
    )))
    connector = MagicMock(
        create_exchange=AsyncMock(return_value=exchange), apply_leverage=AsyncMock()
    )
    monkeypatch.setattr(router_module, "TradingConnector", MagicMock(return_value=connector))
    notifier = MagicMock(send_alert=AsyncMock(), send_trade_notification=AsyncMock())
    monkeypatch.setattr(router_module, "TelegramNotifier", MagicMock(return_value=notifier))

    app = FastAPI()
    app.include_router(router_module.router)
    app.dependency_overrides[router_module.get_settings] = lambda: settings
    app.dependency_overrides[router_module.get_supabase_client] = lambda: db
    # Keep one event loop for the whole test so background jobs can finish.
    with TestClient(app) as client:
        yield SimpleNamespace(
            client=client, db=db, exchange=exchange, notifier=notifier,
            settings=settings, connector=connector,
        )
    webhook_jobs.reset()


def bot_position(flow, side="long", quantity=1.0):
    flow.db.table("positions").insert({
        "user_id": "u1", "symbol": "ETH/USDT:USDT", "side": side, "entry_price": 1900.0,
        "quantity": quantity, "status": "open", "exchange": "binance",
    }).execute()


def send(flow, **overrides):
    body = {
        "action": "open", "symbol": "ETHUSDT.P", "side": "long", "size_type": "percent",
        "size_value": 50, "leverage": 4, "exchange": "binance", "passphrase": PASSPHRASE,
    }
    response = flow.client.post("/webhook/tradingview", json={**body, **overrides})
    flow.client.portal.call(wait_for_jobs)
    return response


async def wait_for_jobs():
    """Wait until every acknowledged alert has finished executing."""
    tasks = list(webhook_jobs._jobs)
    if tasks:
        await asyncio.wait(tasks, timeout=5)
    assert not webhook_jobs._jobs, "webhook job did not finish"


def last_log(flow):
    return flow.db.table("trade_logs").select("*").execute().data[-1]


def test_open_succeeds_and_is_recorded_on_old_database(flow):
    response = send(flow)

    assert response.status_code == 202
    log = flow.db.table("trade_logs").select("*").execute().data[0]
    assert (log["status"], log["order_id"]) == ("success", "order-1")
    position = flow.db.table("positions").select("*").execute().data[0]
    assert (position["status"], position["quantity"]) == ("open", 1.0)


def test_notification_goes_to_default_chat_with_account_name(flow):
    send(flow)

    args = flow.notifier.send_trade_notification.call_args.args
    assert args[0] == "-100"
    assert args[1]["account"] == "Tester"


def test_failed_trade_log_keeps_success_response_and_alerts(flow, monkeypatch):
    monkeypatch.setattr(
        router_module.TradeLogger, "log_trade", AsyncMock(side_effect=RuntimeError("db down"))
    )

    response = send(flow)

    assert response.status_code == 202
    flow.notifier.send_alert.assert_awaited_once()
    flow.notifier.send_trade_notification.assert_awaited_once()


def test_halt_rejects_open_without_touching_exchange(flow):
    open(flow.settings.halt_file, "w").close()

    response = send(flow)

    assert response.status_code == 403
    flow.exchange.create_order.assert_not_awaited()
    assert flow.db.table("trade_logs").select("*").execute().data[0]["status"] == "rejected"


def test_halt_still_allows_close(flow):
    open(flow.settings.halt_file, "w").close()
    bot_position(flow)
    flow.exchange.fetch_positions.return_value = [
        {"contracts": 1.0, "side": "long", "entryPrice": 1900.0}
    ]

    response = send(flow, action="close")

    assert response.status_code == 202
    assert flow.exchange.create_order.call_args.kwargs["params"] == {"reduceOnly": True}


def test_leverage_limit_rejects_open(flow):
    flow.settings.max_leverage = 3

    assert send(flow).status_code == 403
    flow.exchange.create_order.assert_not_awaited()


def test_position_check_failure_is_logged_and_alerted(flow):
    flow.exchange.fetch_positions.side_effect = RuntimeError("binance down")

    assert send(flow).status_code == 202
    flow.notifier.send_alert.assert_awaited_once()
    flow.exchange.close.assert_awaited()
    log = last_log(flow)
    assert log["status"] == "failed"


def test_lock_is_free_after_order_failure(flow):
    flow.exchange.fetch_ticker.side_effect = RuntimeError("boom")

    assert send(flow).status_code == 202
    assert not position_manager._position_locks["u1:ETH/USDT:USDT"].locked()
    assert last_log(flow)["status"] == "failed"
    assert "boom" in flow.notifier.send_alert.call_args.args[1]


@pytest.mark.asyncio
async def test_concurrent_opens_place_one_order():
    position_manager._position_locks.clear()
    positions: list[dict] = []
    exchange = fake_exchange()
    exchange.fetch_positions = AsyncMock(side_effect=lambda _s: list(positions))
    manager = PositionManager(MagicMock())
    orders = 0

    async def open_once():
        nonlocal orders
        await manager.check_and_lock("u", "ETH/USDT:USDT", "open", exchange=exchange)
        try:
            await asyncio.sleep(0.01)
            orders += 1
            positions.append({"contracts": 1.0})
        finally:
            manager.release_lock("u", "ETH/USDT:USDT")

    results = await asyncio.gather(open_once(), open_once(), return_exceptions=True)

    assert orders == 1
    assert sum(isinstance(r, DuplicatePositionError) for r in results) == 1


@pytest.mark.asyncio
async def test_notional_cap_limits_order_size():
    exchange = fake_exchange()
    payload = WebhookPayload(
        action="open", symbol="ETHUSDT", side="long", size_type="percent",
        size_value=50, leverage=4, exchange="binance", passphrase="x",
    )

    await TradeExecutor(max_notional=500.0).execute_trade(exchange, payload)

    assert exchange.create_order.call_args.kwargs["amount"] == 0.25


@pytest.mark.parametrize(
    "symbol, expected",
    [
        ("BTCUSDT.P", "BTC/USDT:USDT"),
        ("BINANCE:ETHUSDT.P", "ETH/USDT:USDT"),
        ("1000PEPEUSDT.P", "1000PEPE/USDT:USDT"),
        ("BTCUSDT", "BTC/USDT:USDT"),
    ],
)
def test_tradingview_symbols_are_normalized(symbol, expected):
    payload = WebhookPayload(
        action="open", symbol=symbol, side="long", size_type="percent",
        size_value=1, exchange="binance", passphrase="x",
    )
    assert payload.symbol == expected


def test_pnl_accepts_exchange_position_keys():
    position = {"entryPrice": "100", "contracts": 2.0, "side": "short"}
    assert _calculate_pnl(position, 90.0) == 20.0


def test_duplicate_open_does_not_touch_leverage_and_alerts(flow):
    flow.exchange.fetch_positions.return_value = [{"contracts": 3.0, "side": "long"}]

    assert send(flow).status_code == 202
    flow.connector.apply_leverage.assert_not_awaited()
    flow.notifier.send_alert.assert_awaited_once()
    flow.exchange.create_order.assert_not_awaited()
    assert last_log(flow)["status"] == "rejected"


def test_open_sets_leverage_after_position_check(flow):
    assert send(flow).status_code == 202
    flow.connector.apply_leverage.assert_awaited_once_with(
        flow.exchange, "binance", 4, "ETH/USDT:USDT"
    )
    assert flow.connector.create_exchange.call_args.kwargs["leverage"] is None


def test_close_leaves_manual_position_untouched(flow):
    flow.exchange.fetch_positions.return_value = [{"contracts": 3.0, "side": "long"}]

    response = send(flow, action="close")

    assert response.status_code == 202
    flow.exchange.create_order.assert_not_awaited()
    flow.notifier.send_alert.assert_awaited_once()
    assert not position_manager._position_locks["u1:ETH/USDT:USDT"].locked()


def test_close_only_sells_bot_quantity(flow):
    bot_position(flow, quantity=1.0)
    flow.exchange.fetch_positions.return_value = [
        {"contracts": 3.0, "side": "long", "entryPrice": 2100.0}
    ]

    assert send(flow, action="close").status_code == 202
    kwargs = flow.exchange.create_order.call_args.kwargs
    assert (kwargs["side"], kwargs["amount"]) == ("sell", 1.0)
    position = flow.db.table("positions").select("*").execute().data[0]
    assert position["status"] == "closed"
    pnl_position = flow.notifier.send_trade_notification.call_args.args[2]
    assert pnl_position["entryPrice"] == 1900.0


def test_close_rejects_side_mismatch(flow):
    bot_position(flow, side="short")
    flow.exchange.fetch_positions.return_value = [{"contracts": 1.0, "side": "long"}]

    assert send(flow, action="close").status_code == 202
    flow.exchange.create_order.assert_not_awaited()
    assert last_log(flow)["status"] == "rejected"


def test_close_without_exchange_position_marks_record_missing(flow):
    bot_position(flow)

    assert send(flow, action="close").status_code == 202
    flow.notifier.send_alert.assert_awaited_once()
    position = flow.db.table("positions").select("*").execute().data[0]
    assert position["status"] == "missing"
