"""Unit tests for src/trading/credentials.py — encrypted credential store.

Tests cover:
- Fernet round-trip: encrypted value decrypts back to original (Requirement 3.1, 3.2)
- store_credentials writes encrypted data to DB (Requirement 3.1, 3.4, 3.6)
- get_credentials returns plaintext api_key and secret (Requirement 3.2)
- get_credentials includes passphrase only when present (Requirement 3.6)
- MissingCredentialsError raised when no row found (Requirement 3.3)
- DecryptionError raised when ciphertext is corrupt (Requirement 3.5)
- store_credentials with passphrase=None omits passphrase_encrypted field (Requirement 3.6)
"""

import logging
from unittest.mock import MagicMock

import pytest
from cryptography.fernet import Fernet

from src.trading.credentials import (
    CredentialStore,
    DecryptionError,
    MissingCredentialsError,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def fernet_key() -> str:
    """Generate a fresh Fernet key for each test."""
    return Fernet.generate_key().decode()


def _make_store(fernet_key: str, rows=None, raise_exc=None) -> CredentialStore:
    """Build a CredentialStore backed by a stubbed Supabase client."""
    execute_mock = MagicMock()
    if raise_exc is not None:
        execute_mock.side_effect = raise_exc
    else:
        result = MagicMock()
        result.data = rows if rows is not None else []
        execute_mock.return_value = result

    eq_mock2 = MagicMock()
    eq_mock2.execute = execute_mock

    eq_mock1 = MagicMock()
    eq_mock1.eq = MagicMock(return_value=eq_mock2)

    select_mock = MagicMock()
    select_mock.eq = MagicMock(return_value=eq_mock1)

    upsert_mock = MagicMock()
    upsert_mock.execute = execute_mock

    table_mock = MagicMock()
    table_mock.select = MagicMock(return_value=select_mock)
    table_mock.upsert = MagicMock(return_value=upsert_mock)

    supabase = MagicMock()
    supabase.table = MagicMock(return_value=table_mock)

    return CredentialStore(fernet_key, supabase)


def _make_row(store: CredentialStore, api_key: str, secret: str, passphrase: str | None = None) -> dict:
    """Produce an encrypted DB row dict using the store's internal Fernet instance."""
    row = {
        "api_key_encrypted": store._encrypt(api_key),
        "secret_encrypted": store._encrypt(secret),
        "passphrase_encrypted": store._encrypt(passphrase) if passphrase else None,
    }
    return row


# ---------------------------------------------------------------------------
# Tests: Fernet round-trip encryption
# ---------------------------------------------------------------------------


def test_encrypt_decrypt_round_trip(fernet_key):
    """Encrypting a value and then decrypting it returns the original string. (Req 3.1, 3.2)"""
    store = _make_store(fernet_key)
    plaintext = "my-super-secret-api-key-12345"
    ciphertext = store._encrypt(plaintext)
    assert store._decrypt(ciphertext) == plaintext


def test_encrypt_produces_different_output(fernet_key):
    """Fernet uses a random IV, so encrypting the same value twice gives different ciphertext."""
    store = _make_store(fernet_key)
    ct1 = store._encrypt("same-value")
    ct2 = store._encrypt("same-value")
    assert ct1 != ct2  # probabilistic; Fernet always includes a random IV


def test_ciphertext_does_not_contain_plaintext(fernet_key):
    """The ciphertext must not be the plaintext string (Req 3.1)."""
    store = _make_store(fernet_key)
    plaintext = "plaintext-secret"
    ciphertext = store._encrypt(plaintext)
    assert plaintext not in ciphertext


# ---------------------------------------------------------------------------
# Tests: get_credentials — happy path
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_credentials_returns_api_key_and_secret(fernet_key):
    """get_credentials returns decrypted api_key and secret (Requirement 3.2)."""
    store = _make_store(fernet_key)
    row = _make_row(store, api_key="TEST_API_KEY", secret="TEST_SECRET")
    store._supabase.table().select().eq().eq.return_value.execute.return_value.data = [row]

    creds = await store.get_credentials("user-123", "binance")

    assert creds["api_key"] == "TEST_API_KEY"
    assert creds["secret"] == "TEST_SECRET"
    assert "passphrase" not in creds


@pytest.mark.asyncio
async def test_get_credentials_includes_passphrase_when_present(fernet_key):
    """get_credentials includes passphrase in dict when stored record has one (Req 3.6)."""
    store = _make_store(fernet_key)
    row = _make_row(store, api_key="AK", secret="SK", passphrase="pp-okx")
    store._supabase.table().select().eq().eq.return_value.execute.return_value.data = [row]

    creds = await store.get_credentials("user-123", "okx")

    assert creds["passphrase"] == "pp-okx"


@pytest.mark.asyncio
async def test_get_credentials_no_passphrase_key_when_null(fernet_key):
    """passphrase key is absent from result when stored passphrase_encrypted is None (Req 3.6)."""
    store = _make_store(fernet_key)
    row = _make_row(store, api_key="AK", secret="SK", passphrase=None)
    store._supabase.table().select().eq().eq.return_value.execute.return_value.data = [row]

    creds = await store.get_credentials("user-xyz", "binance")

    assert "passphrase" not in creds


# ---------------------------------------------------------------------------
# Tests: get_credentials — missing credentials
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_credentials_raises_missing_when_no_row(fernet_key):
    """No DB record for user/exchange raises MissingCredentialsError (Requirement 3.3)."""
    store = _make_store(fernet_key, rows=[])

    with pytest.raises(MissingCredentialsError):
        await store.get_credentials("user-999", "binance")


@pytest.mark.asyncio
async def test_missing_credentials_error_message_contains_exchange(fernet_key):
    """MissingCredentialsError message identifies the exchange (Req 3.3)."""
    store = _make_store(fernet_key, rows=[])

    with pytest.raises(MissingCredentialsError) as exc_info:
        await store.get_credentials("user-abc", "okx")

    assert "okx" in str(exc_info.value)


# ---------------------------------------------------------------------------
# Tests: get_credentials — decryption failure
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_credentials_raises_decryption_error_on_corrupt_data(fernet_key):
    """Corrupt ciphertext raises DecryptionError (Requirement 3.5)."""
    store = _make_store(fernet_key)
    row = {
        "api_key_encrypted": "not-valid-ciphertext",
        "secret_encrypted": store._encrypt("SK"),
        "passphrase_encrypted": None,
    }
    store._supabase.table().select().eq().eq.return_value.execute.return_value.data = [row]

    with pytest.raises(DecryptionError):
        await store.get_credentials("user-123", "binance")


@pytest.mark.asyncio
async def test_get_credentials_raises_decryption_error_on_wrong_key(fernet_key):
    """Ciphertext encrypted with a different key raises DecryptionError (Requirement 3.5)."""
    # Encrypt using the store's key, then try to decrypt with a different key
    other_key = Fernet.generate_key().decode()
    original_store = _make_store(fernet_key)

    # Build a row encrypted with `fernet_key`
    row = _make_row(original_store, api_key="AK", secret="SK")

    # Attempt decryption with a different key
    wrong_key_store = _make_store(other_key)
    wrong_key_store._supabase.table().select().eq().eq.return_value.execute.return_value.data = [row]

    with pytest.raises(DecryptionError):
        await wrong_key_store.get_credentials("user-123", "binance")


# ---------------------------------------------------------------------------
# Tests: store_credentials
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_store_credentials_calls_upsert(fernet_key):
    """store_credentials calls supabase upsert on exchange_credentials table (Req 3.1, 3.4)."""
    store = _make_store(fernet_key)

    await store.store_credentials(
        user_id="user-001",
        exchange="binance",
        api_key="MY_KEY",
        secret="MY_SECRET",
    )

    store._supabase.table.assert_called_with("exchange_credentials")
    store._supabase.table().upsert.assert_called_once()


@pytest.mark.asyncio
async def test_store_credentials_encrypts_values(fernet_key):
    """Stored fields api_key_encrypted and secret_encrypted are not plaintext (Req 3.1)."""
    store = _make_store(fernet_key)

    await store.store_credentials(
        user_id="user-001",
        exchange="binance",
        api_key="PLAIN_KEY",
        secret="PLAIN_SECRET",
    )

    call_args = store._supabase.table().upsert.call_args
    record = call_args[0][0]  # first positional arg = the dict

    # Encrypted values must not equal the plaintext
    assert record["api_key_encrypted"] != "PLAIN_KEY"
    assert record["secret_encrypted"] != "PLAIN_SECRET"


@pytest.mark.asyncio
async def test_store_credentials_without_passphrase_omits_field(fernet_key):
    """passphrase_encrypted is absent from the upsert record when not supplied (Req 3.6)."""
    store = _make_store(fernet_key)

    await store.store_credentials(
        user_id="user-001",
        exchange="binance",
        api_key="K",
        secret="S",
        passphrase=None,
    )

    call_args = store._supabase.table().upsert.call_args
    record = call_args[0][0]
    assert "passphrase_encrypted" not in record


@pytest.mark.asyncio
async def test_store_credentials_with_passphrase_includes_encrypted_field(fernet_key):
    """passphrase_encrypted is present and encrypted when passphrase is supplied (Req 3.6)."""
    store = _make_store(fernet_key)

    await store.store_credentials(
        user_id="user-001",
        exchange="okx",
        api_key="K",
        secret="S",
        passphrase="OKX_PASS",
    )

    call_args = store._supabase.table().upsert.call_args
    record = call_args[0][0]
    assert "passphrase_encrypted" in record
    assert record["passphrase_encrypted"] != "OKX_PASS"
    # Verify round-trip
    assert store._decrypt(record["passphrase_encrypted"]) == "OKX_PASS"


@pytest.mark.asyncio
async def test_store_credentials_round_trip(fernet_key):
    """Values stored by store_credentials can be decrypted back to originals (Req 3.1, 3.2)."""
    store = _make_store(fernet_key)

    await store.store_credentials(
        user_id="user-001",
        exchange="binance",
        api_key="ROUND_TRIP_KEY",
        secret="ROUND_TRIP_SECRET",
    )

    call_args = store._supabase.table().upsert.call_args
    record = call_args[0][0]

    assert store._decrypt(record["api_key_encrypted"]) == "ROUND_TRIP_KEY"
    assert store._decrypt(record["secret_encrypted"]) == "ROUND_TRIP_SECRET"


# ---------------------------------------------------------------------------
# Tests: DecryptionError logging
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_decryption_error_is_logged(fernet_key, caplog):
    """DecryptionError must be logged at ERROR level (Requirement 3.5)."""
    store = _make_store(fernet_key)
    row = {
        "api_key_encrypted": "corrupt-data",
        "secret_encrypted": store._encrypt("SK"),
        "passphrase_encrypted": None,
    }
    store._supabase.table().select().eq().eq.return_value.execute.return_value.data = [row]

    with caplog.at_level(logging.ERROR, logger="src.trading.credentials"):
        with pytest.raises(DecryptionError):
            await store.get_credentials("user-123", "binance")

    assert any(
        "decrypt" in record.message.lower()
        for record in caplog.records
        if record.levelno >= logging.ERROR
    )
