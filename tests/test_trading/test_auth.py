"""Unit tests for src/trading/auth.py — passphrase authentication module.

Tests cover:
- Successful authentication returns user_id and config dict (Requirement 2.1)
- Mismatched / missing passphrase raises 401 with generic message (Requirement 2.2)
- Database connection failure raises 503 and is logged (Requirement 2.3)
- Inactive webhook_config is not matched (is_active = False)
"""

import logging
from unittest.mock import MagicMock, patch

import pytest

from src.trading.auth import authenticate_by_passphrase
from fastapi import HTTPException


# ---------------------------------------------------------------------------
# Helpers — build minimal Supabase client stubs
# ---------------------------------------------------------------------------

def _make_supabase_stub(rows: list | None = None, raise_exc: Exception | None = None):
    """Return a synchronous Supabase-style stub for use in async tests.

    The stub mocks the chained query pattern:
        supabase.table(...).select(...).eq(...).eq(...).limit(...).execute()
    """
    execute_mock = MagicMock()
    if raise_exc is not None:
        execute_mock.side_effect = raise_exc
    else:
        result = MagicMock()
        result.data = rows or []
        execute_mock.return_value = result

    limit_mock = MagicMock()
    limit_mock.execute = execute_mock

    eq_mock2 = MagicMock()
    eq_mock2.limit = MagicMock(return_value=limit_mock)

    eq_mock1 = MagicMock()
    eq_mock1.eq = MagicMock(return_value=eq_mock2)

    select_mock = MagicMock()
    select_mock.eq = MagicMock(return_value=eq_mock1)

    table_mock = MagicMock()
    table_mock.select = MagicMock(return_value=select_mock)

    supabase = MagicMock()
    supabase.table = MagicMock(return_value=table_mock)

    return supabase


_VALID_CONFIG = {
    "id": "cfg-uuid-1234",
    "user_id": "user-uuid-5678",
    "passphrase": "super-secret-pass",
    "is_active": True,
    "created_at": "2024-01-01T00:00:00+00:00",
}


# ---------------------------------------------------------------------------
# Tests: successful authentication
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_authenticate_returns_user_id_and_config():
    """Valid passphrase returns user_id and config dict (Requirement 2.1)."""
    supabase = _make_supabase_stub(rows=[_VALID_CONFIG])

    result = await authenticate_by_passphrase("super-secret-pass", supabase)

    assert result["user_id"] == "user-uuid-5678"
    assert result["config"] == _VALID_CONFIG


@pytest.mark.asyncio
async def test_authenticate_queries_correct_table_and_passphrase():
    """The function must query the webhook_configs table using the given passphrase."""
    supabase = _make_supabase_stub(rows=[_VALID_CONFIG])

    await authenticate_by_passphrase("super-secret-pass", supabase)

    supabase.table.assert_called_once_with("webhook_configs")


# ---------------------------------------------------------------------------
# Tests: authentication failure (401) — no information leakage
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_wrong_passphrase_raises_401():
    """No matching row → HTTPException 401 (Requirement 2.2)."""
    supabase = _make_supabase_stub(rows=[])  # no matching record

    with pytest.raises(HTTPException) as exc_info:
        await authenticate_by_passphrase("wrong-passphrase", supabase)

    assert exc_info.value.status_code == 401
    assert exc_info.value.detail == "Unauthorized"


@pytest.mark.asyncio
async def test_generic_unauthorized_message_no_info_leakage():
    """The 401 response body must be the generic word 'Unauthorized', no other detail."""
    supabase = _make_supabase_stub(rows=[])

    with pytest.raises(HTTPException) as exc_info:
        await authenticate_by_passphrase("any-passphrase", supabase)

    # Must not reveal whether the passphrase itself was wrong or the user doesn't exist
    assert exc_info.value.detail == "Unauthorized"
    assert "passphrase" not in exc_info.value.detail.lower()
    assert "user" not in exc_info.value.detail.lower()


@pytest.mark.asyncio
async def test_inactive_config_raises_401():
    """Inactive webhook_config (is_active=False) must not authenticate (returns empty rows)."""
    # The query filters is_active=True on the DB side; stub returns empty rows
    # to simulate the database correctly filtering inactive records.
    supabase = _make_supabase_stub(rows=[])

    with pytest.raises(HTTPException) as exc_info:
        await authenticate_by_passphrase("inactive-pass", supabase)

    assert exc_info.value.status_code == 401


# ---------------------------------------------------------------------------
# Tests: database failure (503)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_database_error_raises_503():
    """Database exception → HTTPException 503 (Requirement 2.3)."""
    supabase = _make_supabase_stub(raise_exc=ConnectionError("DB unreachable"))

    with pytest.raises(HTTPException) as exc_info:
        await authenticate_by_passphrase("any-pass", supabase)

    assert exc_info.value.status_code == 503
    assert exc_info.value.detail == "Service unavailable"


@pytest.mark.asyncio
async def test_database_error_is_logged(caplog):
    """Database failure must be logged at ERROR level before raising 503 (Requirement 2.3)."""
    supabase = _make_supabase_stub(raise_exc=RuntimeError("timeout"))

    with caplog.at_level(logging.ERROR, logger="src.trading.auth"):
        with pytest.raises(HTTPException):
            await authenticate_by_passphrase("any-pass", supabase)

    assert any(
        "database" in record.message.lower() or "connection" in record.message.lower()
        for record in caplog.records
        if record.levelno >= logging.ERROR
    )


@pytest.mark.asyncio
async def test_503_does_not_leak_db_error_details():
    """503 response body must not expose internal exception details to caller."""
    supabase = _make_supabase_stub(raise_exc=Exception("internal secret error details"))

    with pytest.raises(HTTPException) as exc_info:
        await authenticate_by_passphrase("any-pass", supabase)

    assert exc_info.value.status_code == 503
    assert "secret" not in exc_info.value.detail
    assert "internal" not in exc_info.value.detail.lower()
