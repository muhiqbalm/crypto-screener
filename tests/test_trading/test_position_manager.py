"""Unit tests for src/trading/position_manager.py.

The exchange is the source of truth for whether a position exists; the
``positions`` table records what the bot itself opened.
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.trading import position_manager
from src.trading.local_db import LocalDatabaseClient
from src.trading.position_manager import (
    DuplicatePositionError,
    LockTimeoutError,
    NoPositionError,
    PositionManager,
)

SYMBOL = "ETH/USDT:USDT"


@pytest.fixture(autouse=True)
def clear_locks():
    position_manager._position_locks.clear()
    yield
    position_manager._position_locks.clear()


@pytest.fixture
def manager(tmp_path):
    return PositionManager(LocalDatabaseClient(str(tmp_path / "pm.db")))


def exchange_with(positions):
    exchange = MagicMock()
    exchange.fetch_positions = AsyncMock(return_value=positions)
    return exchange


def is_locked(user="u"):
    lock = position_manager._position_locks.get(f"{user}:{SYMBOL}")
    return lock is not None and lock.locked()


@pytest.mark.asyncio
async def test_open_without_position_returns_none_and_holds_lock(manager):
    result = await manager.check_and_lock("u", SYMBOL, "open", exchange_with([]))

    assert result is None
    assert is_locked()
    manager.release_lock("u", SYMBOL)
    assert not is_locked()


@pytest.mark.asyncio
async def test_open_with_existing_position_is_duplicate_and_releases(manager):
    with pytest.raises(DuplicatePositionError):
        await manager.check_and_lock("u", SYMBOL, "open", exchange_with([{"contracts": 1}]))
    assert not is_locked()


@pytest.mark.asyncio
async def test_zero_contract_positions_count_as_flat(manager):
    exchange = exchange_with([{"contracts": 0}, {"contracts": None}])

    assert await manager.check_and_lock("u", SYMBOL, "open", exchange) is None


@pytest.mark.asyncio
async def test_close_returns_exchange_position(manager):
    pos = {"contracts": 2.0, "side": "short"}

    assert await manager.check_and_lock("u", SYMBOL, "close", exchange_with([pos])) == pos


@pytest.mark.asyncio
async def test_close_without_position_raises_and_releases(manager):
    with pytest.raises(NoPositionError):
        await manager.check_and_lock("u", SYMBOL, "close", exchange_with([]))
    assert not is_locked()


@pytest.mark.asyncio
async def test_exchange_error_releases_lock(manager):
    exchange = MagicMock(fetch_positions=AsyncMock(side_effect=RuntimeError("down")))

    with pytest.raises(RuntimeError):
        await manager.check_and_lock("u", SYMBOL, "open", exchange)
    assert not is_locked()


@pytest.mark.asyncio
async def test_lock_timeout_when_symbol_busy(manager, monkeypatch):
    monkeypatch.setattr(PositionManager, "LOCK_TIMEOUT_SECONDS", 0.05)
    await manager.check_and_lock("u", SYMBOL, "open", exchange_with([]))

    with pytest.raises(LockTimeoutError):
        await manager.check_and_lock("u", SYMBOL, "open", exchange_with([]))


@pytest.mark.asyncio
async def test_locks_are_per_user(manager):
    await manager.check_and_lock("a", SYMBOL, "open", exchange_with([]))

    assert await asyncio.wait_for(
        manager.check_and_lock("b", SYMBOL, "open", exchange_with([])), timeout=1
    ) is None


@pytest.mark.asyncio
async def test_open_then_close_record_lifecycle(manager):
    await manager.open_position("u", SYMBOL, "long", 2000.0, 1.5, exchange="binance")

    record = manager.get_open_record("u", SYMBOL)
    assert (record["side"], record["quantity"], record["entry_price"]) == ("long", 1.5, 2000.0)

    await manager.close_position("u", SYMBOL, exit_price=2100.0)
    assert manager.get_open_record("u", SYMBOL) is None


def test_get_open_record_ignores_other_users(manager):
    assert manager.get_open_record("u", SYMBOL) is None


@pytest.mark.asyncio
async def test_mark_missing_closes_stale_record(manager):
    await manager.open_position("u", SYMBOL, "short", 2000.0, 1.0)

    manager.mark_missing("u", SYMBOL)

    assert manager.get_open_record("u", SYMBOL) is None
    rows = manager._supabase.table("positions").select("*").execute().data
    assert rows[0]["status"] == "missing"
