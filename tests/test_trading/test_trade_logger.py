"""Unit tests for src/trading/trade_logger.py — TradeLogger class.

Covers:
- Successful trade log insertion returns the inserted record (Requirement 8.1)
- ISO 8601 UTC timestamp is recorded in every log record (Requirement 8.1)
- error_details truncated to 1024 characters (Requirement 8.2)
- fill_price and filled_quantity recorded on success (Requirement 8.3)
- log_trade is awaitable (persisted before webhook response, Requirement 8.4)
- Retry once on database write failure; propagates on second failure (Requirement 8.5)
- Successful first attempt does not trigger retry (Requirement 8.5)
"""

import logging
import re
from unittest.mock import MagicMock, call

import pytest

from src.trading.trade_logger import TradeLogger, _ERROR_DETAILS_MAX_LEN


# ---------------------------------------------------------------------------
# Helpers — build minimal Supabase client stubs
# ---------------------------------------------------------------------------

def _make_supabase_stub(rows: list | None = None, raise_exc: Exception | None = None):
    """Return a synchronous Supabase-style stub that mocks:
        supabase.table(...).insert(...).execute()
    """
    execute_mock = MagicMock()
    if raise_exc is not None:
        execute_mock.side_effect = raise_exc
    else:
        result = MagicMock()
        result.data = rows if rows is not None else []
        execute_mock.return_value = result

    insert_mock = MagicMock()
    insert_mock.execute = execute_mock

    table_mock = MagicMock()
    table_mock.insert = MagicMock(return_value=insert_mock)

    supabase = MagicMock()
    supabase.table = MagicMock(return_value=table_mock)

    return supabase


def _make_supabase_stub_fail_then_succeed(success_rows: list):
    """Return a stub that raises on the first call and succeeds on the second."""
    call_count = {"n": 0}

    def execute_side_effect():
        call_count["n"] += 1
        if call_count["n"] == 1:
            raise RuntimeError("Transient DB failure")
        result = MagicMock()
        result.data = success_rows
        return result

    execute_mock = MagicMock(side_effect=execute_side_effect)

    insert_mock = MagicMock()
    insert_mock.execute = execute_mock

    table_mock = MagicMock()
    table_mock.insert = MagicMock(return_value=insert_mock)

    supabase = MagicMock()
    supabase.table = MagicMock(return_value=table_mock)

    return supabase


_INSERTED_ROW = {
    "id": "log-uuid-001",
    "user_id": "user-uuid-abc",
    "symbol": "BTC/USDT:USDT",
    "action": "open",
    "side": "long",
    "exchange": "binance",
    "size_value": 10.0,
    "status": "success",
    "order_id": "order-123",
    "fill_price": 50000.0,
    "filled_quantity": 0.002,
    "error_details": None,
    "created_at": "2024-01-01T12:00:00+00:00",
}


# ---------------------------------------------------------------------------
# Tests: successful log insertion (Requirement 8.1, 8.3)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_log_trade_returns_inserted_row():
    """log_trade returns the row dict returned by the Supabase client (Req 8.1)."""
    supabase = _make_supabase_stub(rows=[_INSERTED_ROW])
    logger_obj = TradeLogger(supabase)

    result = await logger_obj.log_trade(
        user_id="user-uuid-abc",
        symbol="BTC/USDT:USDT",
        action="open",
        side="long",
        exchange="binance",
        size_value=10.0,
        status="success",
        order_id="order-123",
        fill_price=50000.0,
        filled_quantity=0.002,
    )

    assert result["id"] == "log-uuid-001"
    assert result["status"] == "success"


@pytest.mark.asyncio
async def test_log_trade_inserts_into_trade_logs_table():
    """log_trade must call supabase.table('trade_logs')."""
    supabase = _make_supabase_stub(rows=[_INSERTED_ROW])
    logger_obj = TradeLogger(supabase)

    await logger_obj.log_trade(
        user_id="u1",
        symbol="ETH/USDT:USDT",
        action="close",
        side="short",
        exchange="okx",
        size_value=5.0,
        status="success",
    )

    supabase.table.assert_called_once_with("trade_logs")


@pytest.mark.asyncio
async def test_log_trade_record_contains_required_fields():
    """The record passed to insert must contain all required fields (Req 8.1)."""
    captured_records = []

    execute_mock = MagicMock()
    result = MagicMock()
    result.data = [_INSERTED_ROW]
    execute_mock.return_value = result

    insert_mock = MagicMock()
    insert_mock.execute = execute_mock

    table_mock = MagicMock()
    def capture_insert(record):
        captured_records.append(record)
        return insert_mock
    table_mock.insert = capture_insert

    supabase = MagicMock()
    supabase.table = MagicMock(return_value=table_mock)

    logger_obj = TradeLogger(supabase)
    await logger_obj.log_trade(
        user_id="user-1",
        symbol="BTC/USDT:USDT",
        action="open",
        side="long",
        exchange="binance",
        size_value=100.0,
        status="success",
        order_id="ord-99",
        fill_price=42000.0,
        filled_quantity=0.01,
    )

    assert len(captured_records) == 1
    record = captured_records[0]

    # Requirement 8.1: all these fields must be present and non-null
    for field in ("user_id", "symbol", "action", "side", "exchange", "size_value", "status", "created_at"):
        assert field in record, f"Missing field: {field}"
        assert record[field] is not None, f"Null field: {field}"

    # Optional fields should be present but may be None
    assert "order_id" in record
    assert "fill_price" in record
    assert "filled_quantity" in record
    assert "error_details" in record


@pytest.mark.asyncio
async def test_log_trade_records_fill_price_and_filled_quantity():
    """On success, fill_price and filled_quantity are included in the record (Req 8.3)."""
    captured_records = []

    execute_mock = MagicMock()
    result = MagicMock()
    result.data = [_INSERTED_ROW]
    execute_mock.return_value = result

    insert_mock = MagicMock()
    insert_mock.execute = execute_mock

    table_mock = MagicMock()
    def capture_insert(record):
        captured_records.append(record)
        return insert_mock
    table_mock.insert = capture_insert

    supabase = MagicMock()
    supabase.table = MagicMock(return_value=table_mock)

    logger_obj = TradeLogger(supabase)
    await logger_obj.log_trade(
        user_id="u1",
        symbol="ETH/USDT:USDT",
        action="open",
        side="long",
        exchange="binance",
        size_value=10.0,
        status="success",
        fill_price=3000.0,
        filled_quantity=0.333,
    )

    record = captured_records[0]
    assert record["fill_price"] == 3000.0
    assert record["filled_quantity"] == pytest.approx(0.333)


# ---------------------------------------------------------------------------
# Tests: ISO 8601 UTC timestamp (Requirement 8.1)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_log_trade_records_iso8601_utc_timestamp():
    """created_at must be an ISO 8601 UTC timestamp string (Req 8.1)."""
    captured_records = []

    execute_mock = MagicMock()
    result = MagicMock()
    result.data = [_INSERTED_ROW]
    execute_mock.return_value = result

    insert_mock = MagicMock()
    insert_mock.execute = execute_mock

    table_mock = MagicMock()
    def capture_insert(record):
        captured_records.append(record)
        return insert_mock
    table_mock.insert = capture_insert

    supabase = MagicMock()
    supabase.table = MagicMock(return_value=table_mock)

    logger_obj = TradeLogger(supabase)
    await logger_obj.log_trade(
        user_id="u1",
        symbol="BTC/USDT:USDT",
        action="open",
        side="long",
        exchange="binance",
        size_value=5.0,
        status="success",
    )

    record = captured_records[0]
    created_at = record["created_at"]

    # Must be a string
    assert isinstance(created_at, str)

    # Must include UTC offset indicator (+00:00 or Z) — ISO 8601 UTC
    assert "+00:00" in created_at or created_at.endswith("Z"), (
        f"created_at '{created_at}' is not a UTC ISO 8601 timestamp"
    )

    # Must parse as a valid datetime string with a date component
    assert re.match(r"\d{4}-\d{2}-\d{2}T", created_at), (
        f"created_at '{created_at}' does not look like an ISO 8601 timestamp"
    )


# ---------------------------------------------------------------------------
# Tests: error_details truncation (Requirement 8.2)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_error_details_truncated_to_1024_characters():
    """error_details longer than 1024 chars must be silently truncated (Req 8.2)."""
    captured_records = []

    execute_mock = MagicMock()
    result = MagicMock()
    result.data = [_INSERTED_ROW]
    execute_mock.return_value = result

    insert_mock = MagicMock()
    insert_mock.execute = execute_mock

    table_mock = MagicMock()
    def capture_insert(record):
        captured_records.append(record)
        return insert_mock
    table_mock.insert = capture_insert

    supabase = MagicMock()
    supabase.table = MagicMock(return_value=table_mock)

    long_error = "E" * 2000  # 2000-character error string

    logger_obj = TradeLogger(supabase)
    await logger_obj.log_trade(
        user_id="u1",
        symbol="BTC/USDT:USDT",
        action="open",
        side="long",
        exchange="binance",
        size_value=10.0,
        status="failed",
        error_details=long_error,
    )

    record = captured_records[0]
    assert len(record["error_details"]) == _ERROR_DETAILS_MAX_LEN
    assert record["error_details"] == "E" * _ERROR_DETAILS_MAX_LEN


@pytest.mark.asyncio
async def test_error_details_at_exactly_1024_not_truncated():
    """error_details of exactly 1024 chars should NOT be truncated (Req 8.2)."""
    captured_records = []

    execute_mock = MagicMock()
    result = MagicMock()
    result.data = [_INSERTED_ROW]
    execute_mock.return_value = result

    insert_mock = MagicMock()
    insert_mock.execute = execute_mock

    table_mock = MagicMock()
    def capture_insert(record):
        captured_records.append(record)
        return insert_mock
    table_mock.insert = capture_insert

    supabase = MagicMock()
    supabase.table = MagicMock(return_value=table_mock)

    exact_error = "X" * 1024

    logger_obj = TradeLogger(supabase)
    await logger_obj.log_trade(
        user_id="u1",
        symbol="BTC/USDT:USDT",
        action="open",
        side="long",
        exchange="binance",
        size_value=10.0,
        status="failed",
        error_details=exact_error,
    )

    record = captured_records[0]
    assert len(record["error_details"]) == 1024
    assert record["error_details"] == exact_error


@pytest.mark.asyncio
async def test_error_details_none_stored_as_none():
    """When error_details is None, it should be stored as None."""
    captured_records = []

    execute_mock = MagicMock()
    result = MagicMock()
    result.data = [_INSERTED_ROW]
    execute_mock.return_value = result

    insert_mock = MagicMock()
    insert_mock.execute = execute_mock

    table_mock = MagicMock()
    def capture_insert(record):
        captured_records.append(record)
        return insert_mock
    table_mock.insert = capture_insert

    supabase = MagicMock()
    supabase.table = MagicMock(return_value=table_mock)

    logger_obj = TradeLogger(supabase)
    await logger_obj.log_trade(
        user_id="u1",
        symbol="BTC/USDT:USDT",
        action="open",
        side="long",
        exchange="binance",
        size_value=10.0,
        status="success",
        error_details=None,
    )

    record = captured_records[0]
    assert record["error_details"] is None


@pytest.mark.asyncio
async def test_error_details_short_string_not_truncated():
    """error_details shorter than 1024 chars is stored unchanged."""
    captured_records = []

    execute_mock = MagicMock()
    result = MagicMock()
    result.data = [_INSERTED_ROW]
    execute_mock.return_value = result

    insert_mock = MagicMock()
    insert_mock.execute = execute_mock

    table_mock = MagicMock()
    def capture_insert(record):
        captured_records.append(record)
        return insert_mock
    table_mock.insert = capture_insert

    supabase = MagicMock()
    supabase.table = MagicMock(return_value=table_mock)

    short_error = "Insufficient balance: need 500 USDT, have 100 USDT"

    logger_obj = TradeLogger(supabase)
    await logger_obj.log_trade(
        user_id="u1",
        symbol="BTC/USDT:USDT",
        action="open",
        side="long",
        exchange="binance",
        size_value=10.0,
        status="rejected",
        error_details=short_error,
    )

    record = captured_records[0]
    assert record["error_details"] == short_error


# ---------------------------------------------------------------------------
# Tests: retry on database write failure (Requirement 8.5)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_retry_once_on_db_failure_then_succeeds():
    """Single transient DB error → retry succeeds, result is returned (Req 8.5)."""
    supabase = _make_supabase_stub_fail_then_succeed([_INSERTED_ROW])
    logger_obj = TradeLogger(supabase)

    result = await logger_obj.log_trade(
        user_id="u1",
        symbol="BTC/USDT:USDT",
        action="open",
        side="long",
        exchange="binance",
        size_value=10.0,
        status="success",
    )

    # Should have returned successfully after retry
    assert result is not None


@pytest.mark.asyncio
async def test_raises_after_two_consecutive_failures():
    """Two consecutive DB failures → exception propagates (causes HTTP 500) (Req 8.5)."""
    supabase = _make_supabase_stub(raise_exc=RuntimeError("Persistent DB error"))
    logger_obj = TradeLogger(supabase)

    with pytest.raises(RuntimeError, match="Persistent DB error"):
        await logger_obj.log_trade(
            user_id="u1",
            symbol="BTC/USDT:USDT",
            action="open",
            side="long",
            exchange="binance",
            size_value=10.0,
            status="failed",
            error_details="Exchange rejected the order",
        )


@pytest.mark.asyncio
async def test_insert_called_twice_on_first_failure():
    """insert().execute() must be called exactly twice on a single failure (Req 8.5)."""
    call_count = {"n": 0}

    def execute_side_effect():
        call_count["n"] += 1
        raise RuntimeError("Always fails")

    execute_mock = MagicMock(side_effect=execute_side_effect)
    insert_mock = MagicMock()
    insert_mock.execute = execute_mock

    table_mock = MagicMock()
    table_mock.insert = MagicMock(return_value=insert_mock)

    supabase = MagicMock()
    supabase.table = MagicMock(return_value=table_mock)

    logger_obj = TradeLogger(supabase)

    with pytest.raises(RuntimeError):
        await logger_obj.log_trade(
            user_id="u1",
            symbol="BTC/USDT:USDT",
            action="open",
            side="long",
            exchange="binance",
            size_value=10.0,
            status="failed",
        )

    assert call_count["n"] == 2, f"Expected 2 calls (initial + 1 retry), got {call_count['n']}"


@pytest.mark.asyncio
async def test_no_retry_on_success():
    """On first-attempt success, insert().execute() is called exactly once."""
    supabase = _make_supabase_stub(rows=[_INSERTED_ROW])
    logger_obj = TradeLogger(supabase)

    await logger_obj.log_trade(
        user_id="u1",
        symbol="BTC/USDT:USDT",
        action="open",
        side="long",
        exchange="binance",
        size_value=10.0,
        status="success",
    )

    # table().insert().execute() called exactly once
    insert_mock = supabase.table.return_value.insert.return_value
    assert insert_mock.execute.call_count == 1


@pytest.mark.asyncio
async def test_retry_logged_as_warning(caplog):
    """A first-attempt failure must be logged at WARNING level (Req 8.5)."""
    supabase = _make_supabase_stub_fail_then_succeed([_INSERTED_ROW])
    logger_obj = TradeLogger(supabase)

    with caplog.at_level(logging.WARNING, logger="src.trading.trade_logger"):
        await logger_obj.log_trade(
            user_id="u1",
            symbol="BTC/USDT:USDT",
            action="open",
            side="long",
            exchange="binance",
            size_value=10.0,
            status="success",
        )

    assert any(record.levelno >= logging.WARNING for record in caplog.records), (
        "Expected a WARNING log entry on first-attempt failure"
    )


@pytest.mark.asyncio
async def test_second_failure_logged_as_error(caplog):
    """Both attempts failing must produce an ERROR-level log entry (Req 8.5)."""
    supabase = _make_supabase_stub(raise_exc=RuntimeError("DB down"))
    logger_obj = TradeLogger(supabase)

    with caplog.at_level(logging.ERROR, logger="src.trading.trade_logger"):
        with pytest.raises(RuntimeError):
            await logger_obj.log_trade(
                user_id="u1",
                symbol="BTC/USDT:USDT",
                action="open",
                side="long",
                exchange="binance",
                size_value=10.0,
                status="failed",
            )

    assert any(record.levelno >= logging.ERROR for record in caplog.records), (
        "Expected an ERROR log entry after second attempt failure"
    )


# ---------------------------------------------------------------------------
# Tests: fallback when Supabase returns empty data list
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_fallback_when_insert_returns_empty_data():
    """When response.data is empty, log_trade returns the record dict itself."""
    supabase = _make_supabase_stub(rows=[])  # Supabase returns empty data list
    logger_obj = TradeLogger(supabase)

    result = await logger_obj.log_trade(
        user_id="fallback-user",
        symbol="LTC/USDT:USDT",
        action="close",
        side="short",
        exchange="okx",
        size_value=25.0,
        status="success",
    )

    # Should return the attempted record, not raise
    assert result is not None
    assert result["user_id"] == "fallback-user"
    assert result["symbol"] == "LTC/USDT:USDT"
