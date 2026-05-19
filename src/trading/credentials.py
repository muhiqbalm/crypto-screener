"""Encrypted credential store for exchange API keys.

Uses Fernet symmetric encryption (AES-128-CBC + HMAC-SHA256) from the
``cryptography`` library to protect API keys and secrets at rest.

The encryption key is read from the environment variable
``TRADING_ENCRYPTION_KEY`` and never stored in the database.

Requirements: 3.1, 3.2, 3.3, 3.4, 3.5, 3.6
"""

from __future__ import annotations

import logging
from typing import Optional

from cryptography.fernet import Fernet, InvalidToken

logger = logging.getLogger(__name__)


class CredentialError(Exception):
    """Base error for CredentialStore failures."""


class MissingCredentialsError(CredentialError):
    """Raised when no credentials are found for the requested user/exchange.

    Requirement 3.3
    """


class DecryptionError(CredentialError):
    """Raised when decryption of stored credentials fails.

    Requirement 3.5
    """


class CredentialStore:
    """Encrypt and decrypt exchange API credentials stored in Supabase.

    Each credential field (api_key, secret, passphrase) is encrypted
    independently using Fernet symmetric encryption.  The encryption key
    is supplied at construction time — typically loaded from the
    ``TRADING_ENCRYPTION_KEY`` environment variable — and is never written
    to the database.

    Requirements:
        3.1  Credentials are stored as ciphertext; plaintext is never written
             to the database.
        3.2  Decrypted credentials are returned within 2 seconds.
        3.3  Missing credentials raise MissingCredentialsError.
        3.4  Credentials are stored per user per exchange (composite unique
             key in the DB schema).
        3.5  Decryption failures raise DecryptionError.
        3.6  At minimum api_key + secret are stored; passphrase is optional
             and stored only when provided.
    """

    def __init__(self, encryption_key: str, supabase) -> None:
        """Initialise the store.

        Args:
            encryption_key: A URL-safe base64-encoded 32-byte Fernet key.
                            Typically read from ``TRADING_ENCRYPTION_KEY``.
            supabase:       An async (or sync) Supabase client instance.
        """
        self._fernet = Fernet(encryption_key.encode())
        self._supabase = supabase

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _encrypt(self, value: str) -> str:
        """Encrypt *value* and return a UTF-8 string of the ciphertext.

        The ciphertext is URL-safe base64 encoded, so it is safe to store
        in a TEXT column.
        """
        return self._fernet.encrypt(value.encode()).decode()

    def _decrypt(self, ciphertext: str) -> str:
        """Decrypt *ciphertext* and return the original plaintext string.

        Raises:
            DecryptionError: if the token is invalid or tampered with.
        """
        try:
            return self._fernet.decrypt(ciphertext.encode()).decode()
        except (InvalidToken, Exception) as exc:
            logger.error("Credential decryption failed: %s", exc)
            raise DecryptionError("Credential decryption failed") from exc

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    async def store_credentials(
        self,
        user_id: str,
        exchange: str,
        api_key: str,
        secret: str,
        passphrase: Optional[str] = None,
    ) -> None:
        """Encrypt and persist credentials for *user_id* on *exchange*.

        Each field is encrypted independently before being sent to the
        database.  If a record for (user_id, exchange) already exists it
        is replaced via an upsert.

        Args:
            user_id:    UUID string of the owning user.
            exchange:   Exchange identifier, e.g. ``"binance"`` or ``"okx"``.
            api_key:    Plaintext API key.
            secret:     Plaintext API secret.
            passphrase: Optional plaintext API passphrase (required for OKX).

        Requirement 3.1, 3.4, 3.6
        """
        record: dict = {
            "user_id": user_id,
            "exchange": exchange,
            "api_key_encrypted": self._encrypt(api_key),
            "secret_encrypted": self._encrypt(secret),
        }
        if passphrase is not None:
            record["passphrase_encrypted"] = self._encrypt(passphrase)

        # Upsert on the composite unique key (user_id, exchange)
        (
            self._supabase.table("exchange_credentials")
            .upsert(record, on_conflict="user_id,exchange")
            .execute()
        )

        logger.info(
            "Stored %s credentials for user %s", exchange, user_id
        )

    async def get_credentials(self, user_id: str, exchange: str) -> dict:
        """Retrieve and decrypt credentials for *user_id* on *exchange*.

        Returns a dict with keys ``api_key``, ``secret``, and optionally
        ``passphrase`` (only present if the stored record has a non-null
        ``passphrase_encrypted`` column).

        Args:
            user_id:  UUID string of the owning user.
            exchange: Exchange identifier, e.g. ``"binance"`` or ``"okx"``.

        Returns:
            ``{"api_key": str, "secret": str}`` or
            ``{"api_key": str, "secret": str, "passphrase": str}``

        Raises:
            MissingCredentialsError: if no record exists for the pair.
            DecryptionError:         if any stored ciphertext is invalid.

        Requirements 3.2, 3.3, 3.5
        """
        response = (
            self._supabase.table("exchange_credentials")
            .select("api_key_encrypted, secret_encrypted, passphrase_encrypted")
            .eq("user_id", user_id)
            .eq("exchange", exchange)
            .execute()
        )

        rows = response.data if response.data else []
        if not rows:
            logger.warning(
                "No %s credentials found for user %s", exchange, user_id
            )
            raise MissingCredentialsError(
                f"No credentials configured for exchange '{exchange}' "
                f"and user '{user_id}'"
            )

        row = rows[0]

        # Decrypt each field independently — a failure in any one raises
        # DecryptionError (requirement 3.5).
        credentials: dict = {
            "api_key": self._decrypt(row["api_key_encrypted"]),
            "secret": self._decrypt(row["secret_encrypted"]),
        }

        passphrase_cipher = row.get("passphrase_encrypted")
        if passphrase_cipher:
            credentials["passphrase"] = self._decrypt(passphrase_cipher)

        return credentials
