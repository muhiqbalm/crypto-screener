"""Unit tests for src/trading/position_manager.py — PositionManager class.

Covers:
- _lock_key helper (determinism, range, collision resistance)
- check_and_lock for "open" action (happy path + duplicate rejection)
- check_and_lock for "close" action (happy path + no-position rejection)
- check_and_lock lock timeout handling
- open_position record creation
- close_position record update
"""

from __future__ import annotations

from unittest.mock import MagicMock, call, patch

import pytest

from src.trading.position_manager import (
    DuplicatePositionError,
    LockTimeoutError,
    NoPositionError,
    PositionManager,
    _lock_key,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def make_supabase(position_rows: list[dict] | None = None) -> MagicMock:
    """Build a minimal Supabase mock that returns the given position rows.

    The mock chains .table() → .select() / .update() / .insert() → .eq() →
    … → .execute() in the fluent Supabase style.  The ``rpc`` method also
    returns a chainable mock whose ``.execute()`` succeeds silently.

    Args:
        position_rows: List of position dicts to return from SELECT queries.
                       Defaults to [] (no open positions).
    """
    if position_rows is None:
        position_rows = []

    supabase = MagicMock()

    # rpc calls (.set_config, pg_advisory_xact_lock) succeed silently
    rpc_mock = MagicMock()
    rpc_mock.execute.return_value = MagicMock(data=None)
    supabase.rpc.return_value = rpc_mock

    # Build a chainable table mock whose final execute() returns position_rows.
    table_chain = MagicMock()
    table_chain.execute.return_value = MagicMock(data=position_rows)

    # Make every method in the chain return table_chain so .eq().eq()... works.
    table_chain.select.return_value = table_chain
    table_chain.insert.return_value = table_chain
    table_chain.update.return_value = table_chain
    table_chain.eq.return_value = table_chain
    table_chain.limit.return_value = table_chain
    table_chain.upsert.return_value = table_chain

    supabase.table.return_value = table_chain

    return supabase


def make_open_position(
    user_id: str = "user-1",
    symbol: str = "BTC/USDT:USDT",
    side: str = "long",
    entry_price: float = 50000.0,
    quantity: float = 0.002,
) -> dict:
    return {
        "id": "pos-abc123",
        "user_id": user_id,
        "symbol": symbol,
        "side": side,
        "entry_price": entry_price,
        "quantity": quantity,
        "status": "open",
        "opened_at": "2024-01-01T00:00:00+00:00",
    }


# ---------------------------------------------------------------------------
# _lock_key helper
# ---------------------------------------------------------------------------


class TestLockKey:
    def test_deterministic(self):
        """Same inputs always produce same key."""
        key1 = _lock_key("user-1", "BTC/USDT:USDT")
        key2 = _lock_key("user-1", "BTC/USDT:USDT")
        assert key1 == key2

    def test_different_users_differ(self):
        """Different user_ids produce different keys for the same symbol."""
        key1 = _lock_key("user-1", "BTC/USDT:USDT")
        key2 = _lock_key("user-2", "BTC/USDT:USDT")
        assert key1 != key2

    def test_different_symbols_differ(self):
        """Different symbols produce different keys for the same user."""
        key1 = _lock_key("user-1", "BTC/USDT:USDT")
        key2 = _lock_key("user-1", "ETH/USDT:USDT")
        assert key1 != key2

    def test_key_in_signed_32bit_range(self):
        """Result fits within signed 32-bit integer range [0, 2**31 - 1]."""
        key = _lock_key("user-xyz", "BTC/USDT:USDT")
        assert 0 <= key <= 0x7FFFFFFF

    def test_many_keys_in_range(self):
        """All generated keys are within the valid range."""
        pairs = [
            ("user-1", "BTC/USDT:USDT"),
            ("user-2", "ETH/USDT:USDT"),
            ("user-abc-def", "SOL/USDT:USDT"),
            ("", ""),
            ("a" * 100, "B" * 50),
        ]
        for uid, sym in pairs:
            key = _lock_key(uid, sym)
            assert 0 <= key <= 0x7FFFFFFF, f"Key out of range for ({uid!r}, {sym!r})"


# ---------------------------------------------------------------------------
# check_and_lock — "open" action
# ---------------------------------------------------------------------------


class TestCheckAndLockOpen:
    @pytest.mark.asyncio
    async def test_open_no_existing_position_returns_none(self):
        """With no existing open position, check_and_lock("open") returns None."""
        supabase = make_supabase(position_rows=[])
        pm = PositionManager(supabase)

        result = await pm.check_and_lock("user-1", "BTC/USDT:USDT", "open")

        assert result is None

    @pytest.mark.asyncio
    async def test_open_with_existing_position_raises_duplicate(self):
        """Existing open position → DuplicatePositionError (Req 6.2)."""
        existing = make_open_position()
        supabase = make_supabase(position_rows=[existing])
        pm = PositionManager(supabase)

        with pytest.raises(DuplicatePositionError):
            await pm.check_and_lock("user-1", "BTC/USDT:USDT", "open")

    @pytest.mark.asyncio
    async def test_open_acquires_advisory_lock(self):
        """pg_advisory_xact_lock RPC is called before the position query."""
        supabase = make_supabase(position_rows=[])
        pm = PositionManager(supabase)

        await pm.check_and_lock("user-1", "BTC/USDT:USDT", "open")

        # rpc should have been called for advisory lock
        lock_calls = [str(c) for c in supabase.rpc.call_args_list]
        assert any("pg_advisory_xact_lock" in c for c in lock_calls)

    @pytest.mark.asyncio
    async def test_open_sets_statement_timeout(self):
        """statement_timeout is set via set_config before lock acquisition."""
        supabase = make_supabase(position_rows=[])
        pm = PositionManager(supabase)

        await pm.check_and_lock("user-1", "BTC/USDT:USDT", "open")

        # First rpc call should be set_config for statement_timeout
        first_call = supabase.rpc.call_args_list[0]
        assert first_call[0][0] == "set_config"

    @pytest.mark.asyncio
    async def test_open_no_order_placed_on_duplicate(self):
        """DuplicatePositionError is raised before any exchange order (Req 6.2)."""
        existing = make_open_position()
        supabase = make_supabase(position_rows=[existing])
        pm = PositionManager(supabase)

        # Just verifying the exception is raised — no exchange interaction here
        with pytest.raises(DuplicatePositionError, match="already has an open position"):
            await pm.check_and_lock("user-1", "BTC/USDT:USDT", "open")


# ---------------------------------------------------------------------------
# check_and_lock — "close" action
# ---------------------------------------------------------------------------


class TestCheckAndLockClose:
    @pytest.mark.asyncio
    async def test_close_with_existing_position_returns_record(self):
        """Existing open position → returns position record (Req 6.3)."""
        existing = make_open_position()
        supabase = make_supabase(position_rows=[existing])
        pm = PositionManager(supabase)

        result = await pm.check_and_lock("user-1", "BTC/USDT:USDT", "close")

        assert result is not None
        assert result["id"] == "pos-abc123"
        assert result["side"] == "long"

    @pytest.mark.asyncio
    async def test_close_no_position_raises_no_position_error(self):
        """No open position → NoPositionError (Req 6.3)."""
        supabase = make_supabase(position_rows=[])
        pm = PositionManager(supabase)

        with pytest.raises(NoPositionError):
            await pm.check_and_lock("user-1", "BTC/USDT:USDT", "close")

    @pytest.mark.asyncio
    async def test_close_no_order_placed_on_missing_position(self):
        """NoPositionError raised before any exchange order (Req 6.3)."""
        supabase = make_supabase(position_rows=[])
        pm = PositionManager(supabase)

        with pytest.raises(NoPositionError, match="No open position"):
            await pm.check_and_lock("user-1", "BTC/USDT:USDT", "close")

    @pytest.mark.asyncio
    async def test_close_returns_full_position_record(self):
        """Returned position record contains expected fields."""
        existing = make_open_position(side="short", entry_price=3000.0, quantity=1.0)
        supabase = make_supabase(position_rows=[existing])
        pm = PositionManager(supabase)

        position = await pm.check_and_lock("user-1", "ETH/USDT:USDT", "close")

        assert position["side"] == "short"
        assert float(position["entry_price"]) == pytest.approx(3000.0)
        assert float(position["quantity"]) == pytest.approx(1.0)


# ---------------------------------------------------------------------------
# check_and_lock — lock timeout
# ---------------------------------------------------------------------------


class TestCheckAndLockTimeout:
    @pytest.mark.asyncio
    async def test_lock_timeout_raises_lock_timeout_error(self):
        """When advisory lock RPC raises a timeout-like error, LockTimeoutError is raised."""
        supabase = MagicMock()

        # set_config succeeds
        set_config_mock = MagicMock()
        set_config_mock.execute.return_value = MagicMock(data=None)

        # pg_advisory_xact_lock raises timeout error
        lock_mock = MagicMock()
        lock_mock.execute.side_effect = Exception(
            "ERROR: canceling statement due to statement timeout"
        )

        def rpc_side_effect(name, params=None):
            if name == "set_config":
                return set_config_mock
            return lock_mock

        supabase.rpc.side_effect = rpc_side_effect

        pm = PositionManager(supabase)

        with pytest.raises(LockTimeoutError):
            await pm.check_and_lock("user-1", "BTC/USDT:USDT", "open")

    @pytest.mark.asyncio
    async def test_lock_generic_error_raises_lock_timeout_error(self):
        """Any unexpected lock error is also wrapped in LockTimeoutError."""
        supabase = MagicMock()

        set_config_mock = MagicMock()
        set_config_mock.execute.return_value = MagicMock(data=None)

        lock_mock = MagicMock()
        lock_mock.execute.side_effect = Exception("Database connection lost")

        def rpc_side_effect(name, params=None):
            if name == "set_config":
                return set_config_mock
            return lock_mock

        supabase.rpc.side_effect = rpc_side_effect

        pm = PositionManager(supabase)

        with pytest.raises(LockTimeoutError):
            await pm.check_and_lock("user-1", "BTC/USDT:USDT", "close")


# ---------------------------------------------------------------------------
# open_position
# ---------------------------------------------------------------------------


class TestOpenPosition:
    @pytest.mark.asyncio
    async def test_creates_position_record(self):
        """open_position inserts a record and returns it."""
        new_position = make_open_position()
        supabase = make_supabase(position_rows=[new_position])
        pm = PositionManager(supabase)

        result = await pm.open_position(
            user_id="user-1",
            symbol="BTC/USDT:USDT",
            side="long",
            entry_price=50000.0,
            quantity=0.002,
        )

        assert result["id"] == "pos-abc123"
        assert result["status"] == "open"

    @pytest.mark.asyncio
    async def test_insert_called_with_correct_fields(self):
        """Verify the insert payload contains all required fields."""
        new_position = make_open_position()
        supabase = make_supabase(position_rows=[new_position])
        pm = PositionManager(supabase)

        await pm.open_position(
            user_id="user-1",
            symbol="BTC/USDT:USDT",
            side="long",
            entry_price=50000.0,
            quantity=0.002,
        )

        # Inspect what was passed to .insert()
        table_mock = supabase.table.return_value
        insert_call = table_mock.insert.call_args
        inserted_record = insert_call[0][0]

        assert inserted_record["user_id"] == "user-1"
        assert inserted_record["symbol"] == "BTC/USDT:USDT"
        assert inserted_record["side"] == "long"
        assert inserted_record["entry_price"] == pytest.approx(50000.0)
        assert inserted_record["quantity"] == pytest.approx(0.002)
        assert inserted_record["status"] == "open"

    @pytest.mark.asyncio
    async def test_partial_fill_quantity_recorded(self):
        """Partial fill: only the filled quantity is stored (Req 6.6)."""
        partial_qty = 0.001  # Only half filled
        partial_position = make_open_position(quantity=partial_qty)
        supabase = make_supabase(position_rows=[partial_position])
        pm = PositionManager(supabase)

        result = await pm.open_position(
            user_id="user-1",
            symbol="BTC/USDT:USDT",
            side="long",
            entry_price=50000.0,
            quantity=partial_qty,  # actual filled qty from exchange
        )

        table_mock = supabase.table.return_value
        insert_call = table_mock.insert.call_args
        inserted_record = insert_call[0][0]
        assert inserted_record["quantity"] == pytest.approx(partial_qty)

    @pytest.mark.asyncio
    async def test_open_position_returns_fallback_when_no_rows_returned(self):
        """When insert returns empty data, fallback dict is returned."""
        supabase = make_supabase(position_rows=[])
        pm = PositionManager(supabase)

        result = await pm.open_position(
            user_id="user-1",
            symbol="BTC/USDT:USDT",
            side="short",
            entry_price=3000.0,
            quantity=1.0,
        )

        # Should contain at minimum the fields we tried to insert
        assert result["user_id"] == "user-1"
        assert result["symbol"] == "BTC/USDT:USDT"
        assert result["side"] == "short"


# ---------------------------------------------------------------------------
# close_position
# ---------------------------------------------------------------------------


class TestClosePosition:
    @pytest.mark.asyncio
    async def test_marks_position_closed(self):
        """close_position updates status to 'closed' and sets exit_price."""
        closed_position = {
            **make_open_position(),
            "status": "closed",
            "exit_price": 55000.0,
            "closed_at": "2024-01-02T00:00:00+00:00",
        }
        supabase = make_supabase(position_rows=[closed_position])
        pm = PositionManager(supabase)

        result = await pm.close_position(
            user_id="user-1",
            symbol="BTC/USDT:USDT",
            exit_price=55000.0,
        )

        assert result["status"] == "closed"
        assert result["exit_price"] == pytest.approx(55000.0)

    @pytest.mark.asyncio
    async def test_update_called_with_correct_fields(self):
        """Verify the update payload contains status, exit_price, and closed_at."""
        closed_position = {
            **make_open_position(),
            "status": "closed",
            "exit_price": 55000.0,
            "closed_at": "2024-01-02T00:00:00+00:00",
        }
        supabase = make_supabase(position_rows=[closed_position])
        pm = PositionManager(supabase)

        await pm.close_position(
            user_id="user-1",
            symbol="BTC/USDT:USDT",
            exit_price=55000.0,
        )

        table_mock = supabase.table.return_value
        update_call = table_mock.update.call_args
        update_data = update_call[0][0]

        assert update_data["status"] == "closed"
        assert update_data["exit_price"] == pytest.approx(55000.0)
        assert "closed_at" in update_data
        # closed_at should be an ISO 8601 string
        assert "T" in update_data["closed_at"]

    @pytest.mark.asyncio
    async def test_update_filters_by_user_and_symbol_and_open_status(self):
        """Update is scoped to (user_id, symbol, status='open') only."""
        closed_position = {**make_open_position(), "status": "closed", "exit_price": 55000.0}
        supabase = make_supabase(position_rows=[closed_position])
        pm = PositionManager(supabase)

        await pm.close_position(
            user_id="user-1",
            symbol="BTC/USDT:USDT",
            exit_price=55000.0,
        )

        table_mock = supabase.table.return_value
        eq_calls = table_mock.eq.call_args_list

        # Should have filtered by user_id, symbol, and status="open"
        eq_args = {args[0][0]: args[0][1] for args in eq_calls}
        assert eq_args.get("user_id") == "user-1"
        assert eq_args.get("symbol") == "BTC/USDT:USDT"
        assert eq_args.get("status") == "open"

    @pytest.mark.asyncio
    async def test_close_position_returns_fallback_when_no_rows(self):
        """When update returns empty data, fallback dict is returned."""
        supabase = make_supabase(position_rows=[])
        pm = PositionManager(supabase)

        result = await pm.close_position(
            user_id="user-1",
            symbol="BTC/USDT:USDT",
            exit_price=45000.0,
        )

        assert result["user_id"] == "user-1"
        assert result["symbol"] == "BTC/USDT:USDT"
        assert result["status"] == "closed"
        assert result["exit_price"] == pytest.approx(45000.0)

    @pytest.mark.asyncio
    async def test_closed_at_is_utc_iso8601(self):
        """closed_at timestamp is stored as UTC ISO 8601 string."""
        closed_position = {
            **make_open_position(),
            "status": "closed",
            "exit_price": 60000.0,
            "closed_at": "2024-06-01T12:00:00+00:00",
        }
        supabase = make_supabase(position_rows=[closed_position])
        pm = PositionManager(supabase)

        await pm.close_position(
            user_id="user-1",
            symbol="BTC/USDT:USDT",
            exit_price=60000.0,
        )

        table_mock = supabase.table.return_value
        update_call = table_mock.update.call_args
        update_data = update_call[0][0]

        # Should contain UTC offset "+00:00"
        assert "+00:00" in update_data["closed_at"] or "Z" in update_data["closed_at"]
