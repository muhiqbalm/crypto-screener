"""Trading connector module for authenticated CCXT exchange instances.

This module is completely separate from src/exchange/connector.py (the read-only
screener connector). It uses ccxt.async_support and always operates in testnet mode.
"""

import logging
from typing import Optional

import ccxt.async_support as ccxt_async

logger = logging.getLogger(__name__)


class AuthenticationError(Exception):
    """Raised when exchange authentication fails during instance creation."""


class LeverageSetError(Exception):
    """Raised when setting leverage on the exchange fails."""


class TradingConnector:
    """
    Creates authenticated CCXT exchange instances for trading on testnet.

    Completely separate from the screener's ExchangeConnector — does not inherit
    from it, does not share class hierarchy, and does not share exchange instances.

    Requirements: 4.1, 4.2, 4.3, 4.4, 4.5, 4.6
    """

    SUPPORTED_EXCHANGES: dict[str, type] = {
        "binance": ccxt_async.binance,
        "okx": ccxt_async.okx,
    }

    async def create_exchange(
        self,
        exchange_name: str,
        credentials: dict,
        symbol: str,
        leverage: Optional[int] = None,
    ) -> ccxt_async.Exchange:
        """Create an authenticated CCXT exchange instance configured for testnet.

        Optionally sets leverage for the symbol before returning the instance.

        Args:
            exchange_name: One of "binance" or "okx".
            credentials: Dict with at minimum "api_key" and "secret" keys.
                         May also include "passphrase" for OKX.
            symbol: CCXT unified symbol (e.g., "BTC/USDT:USDT"). Used when
                    setting leverage.
            leverage: Optional integer in [1, 125]. When provided, set_leverage
                      is called on the exchange for the given symbol.

        Returns:
            An authenticated, testnet-enabled ccxt.async_support.Exchange instance.

        Raises:
            ValueError: If exchange_name is not supported.
            AuthenticationError: If exchange authentication fails (Req 4.5).
            LeverageSetError: If setting leverage on the exchange fails (Req 4.6).
        """
        exchange_name_lower = exchange_name.lower()
        if exchange_name_lower not in self.SUPPORTED_EXCHANGES:
            raise ValueError(
                f"Exchange '{exchange_name}' is not supported. "
                f"Supported exchanges: {list(self.SUPPORTED_EXCHANGES.keys())}"
            )

        exchange_class = self.SUPPORTED_EXCHANGES[exchange_name_lower]

        # Build constructor config — testnet always enabled (Req 4.2)
        config: dict = {
            "apiKey": credentials.get("api_key", ""),
            "secret": credentials.get("secret", ""),
            "sandbox": True,  # testnet mode (Req 4.2)
            "options": {
                "defaultType": "future",  # perpetual futures for leverage trading
            },
        }

        # OKX additionally requires a passphrase (Req 3.6)
        if exchange_name_lower == "okx" and credentials.get("passphrase"):
            config["password"] = credentials["passphrase"]

        exchange: ccxt_async.Exchange = exchange_class(config)

        # Attempt authentication by loading markets — this validates credentials
        # (Req 4.1, 4.5)
        try:
            await exchange.load_markets()
        except ccxt_async.AuthenticationError as exc:
            await self._close_exchange(exchange)
            error_msg = (
                f"Exchange authentication failed for '{exchange_name}': "
                "invalid or expired credentials."
            )
            logger.error("%s Original error: %s", error_msg, exc)
            raise AuthenticationError(error_msg) from exc
        except ccxt_async.NetworkError as exc:
            await self._close_exchange(exchange)
            error_msg = (
                f"Network error while authenticating with '{exchange_name}': {exc}"
            )
            logger.error(error_msg)
            raise AuthenticationError(error_msg) from exc
        except Exception as exc:
            await self._close_exchange(exchange)
            error_msg = (
                f"Unexpected error during exchange authentication for "
                f"'{exchange_name}': {exc}"
            )
            logger.error(error_msg)
            raise AuthenticationError(error_msg) from exc

        # Set leverage when provided (Req 4.4, 4.6)
        if leverage is not None:
            try:
                await exchange.set_leverage(leverage, symbol)
                logger.info(
                    "Leverage set to %d for symbol '%s' on '%s'",
                    leverage,
                    symbol,
                    exchange_name,
                )
            except ccxt_async.ExchangeError as exc:
                await self._close_exchange(exchange)
                error_msg = (
                    f"Failed to set leverage {leverage} for symbol '{symbol}' "
                    f"on '{exchange_name}': {exc}"
                )
                logger.error(error_msg)
                raise LeverageSetError(error_msg) from exc
            except Exception as exc:
                await self._close_exchange(exchange)
                error_msg = (
                    f"Unexpected error setting leverage {leverage} for symbol "
                    f"'{symbol}' on '{exchange_name}': {exc}"
                )
                logger.error(error_msg)
                raise LeverageSetError(error_msg) from exc

        logger.info(
            "Trading connector created for exchange '%s', symbol '%s', testnet=True",
            exchange_name,
            symbol,
        )
        return exchange

    async def create_exchange_for_monitoring(
        self,
        exchange_name: str,
        credentials: dict,
    ) -> ccxt_async.Exchange:
        """Create an authenticated CCXT exchange instance for read-only monitoring.

        Unlike ``create_exchange``, this method does not set leverage and is
        intended for fetching positions, balances, and other account data.

        Args:
            exchange_name: One of "binance" or "okx".
            credentials:   Dict with at minimum "api_key" and "secret" keys.
                           May also include "passphrase" for OKX.

        Returns:
            An authenticated, testnet-enabled ccxt.async_support.Exchange instance.

        Raises:
            ValueError:           If exchange_name is not supported.
            AuthenticationError:  If exchange authentication fails.
        """
        exchange_name_lower = exchange_name.lower()
        if exchange_name_lower not in self.SUPPORTED_EXCHANGES:
            raise ValueError(
                f"Exchange '{exchange_name}' is not supported. "
                f"Supported exchanges: {list(self.SUPPORTED_EXCHANGES.keys())}"
            )

        exchange_class = self.SUPPORTED_EXCHANGES[exchange_name_lower]

        config: dict = {
            "apiKey": credentials.get("api_key", ""),
            "secret": credentials.get("secret", ""),
            "sandbox": True,
            "options": {
                "defaultType": "future",
            },
        }

        if exchange_name_lower == "okx" and credentials.get("passphrase"):
            config["password"] = credentials["passphrase"]

        exchange: ccxt_async.Exchange = exchange_class(config)

        try:
            await exchange.load_markets()
        except ccxt_async.AuthenticationError as exc:
            await self._close_exchange(exchange)
            error_msg = (
                f"Exchange authentication failed for '{exchange_name}': "
                "invalid or expired credentials."
            )
            logger.error("%s Original error: %s", error_msg, exc)
            raise AuthenticationError(error_msg) from exc
        except Exception as exc:
            await self._close_exchange(exchange)
            error_msg = (
                f"Unexpected error during exchange authentication for "
                f"'{exchange_name}': {exc}"
            )
            logger.error(error_msg)
            raise AuthenticationError(error_msg) from exc

        logger.info(
            "Monitoring connector created for exchange '%s', testnet=True",
            exchange_name,
        )
        return exchange

    @staticmethod
    async def _close_exchange(exchange: ccxt_async.Exchange) -> None:
        """Safely close an exchange instance, suppressing any errors."""
        try:
            await exchange.close()
        except Exception:
            pass  # Ignore close errors during error handling
