"""Telegram notifier module for TradingView webhook trading.

Sends trade execution notifications to users via the Telegram Bot API.
Notifications are dispatched asynchronously as FastAPI BackgroundTasks
so they never block the webhook response.

Requirements: 7.1, 7.2, 7.3, 7.4, 7.5
"""

import logging

import httpx

logger = logging.getLogger(__name__)


def _calculate_pnl(position: dict, exit_price: float) -> float:
    """Calculate realized PnL for a closed position.

    For long:  PnL = (exit_price - entry_price) * quantity
    For short: PnL = (entry_price - exit_price) * quantity

    Requirement 7.2: The Notifier SHALL include realized PnL for close orders.

    Args:
        position: The position record containing side, entry_price, and quantity.
        exit_price: The fill price of the closing order.

    Returns:
        Realized PnL in quote currency units.
    """
    entry_price: float = float(position["entry_price"])
    quantity: float = float(position["quantity"])
    side: str = position["side"]

    if side == "long":
        return (exit_price - entry_price) * quantity
    else:  # short
        return (entry_price - exit_price) * quantity


def _format_notification_message(
    trade_result: dict,
    position: dict | None = None,
) -> str:
    """Format a human-readable Telegram message for a trade execution.

    Always includes: symbol, side, quantity, execution price, exchange name.
    For close orders (when position is provided): also includes realized PnL.

    Requirement 7.1: Message SHALL contain symbol, side, quantity, execution
    price, and exchange name.
    Requirement 7.2: Close orders SHALL include realized PnL.

    Args:
        trade_result: Dict with keys: symbol, side, filled_quantity,
                      fill_price, exchange, action.
        position: Open position record (provided only for close orders).

    Returns:
        Formatted notification message string.
    """
    symbol: str = trade_result["symbol"]
    side: str = trade_result["side"]
    quantity: float = float(trade_result["filled_quantity"])
    fill_price: float = float(trade_result["fill_price"])
    exchange: str = trade_result["exchange"]
    action: str = trade_result["action"]

    # Emoji indicators for readability
    action_emoji = "🟢" if action == "open" else "🔴"
    side_emoji = "📈" if side == "long" else "📉"

    lines = [
        f"{action_emoji} Trade Executed",
        f"",
        f"Exchange: {exchange.upper()}",
        f"Symbol:   {symbol}",
        f"Action:   {action.upper()} {side.upper()} {side_emoji}",
        f"Quantity: {quantity}",
        f"Price:    {fill_price}",
    ]

    # Requirement 7.2: include PnL for close orders
    if action == "close" and position is not None:
        pnl = _calculate_pnl(position, fill_price)
        pnl_emoji = "✅" if pnl >= 0 else "❌"
        lines.append(f"PnL:      {pnl:+.4f} {pnl_emoji}")

    return "\n".join(lines)


class TelegramNotifier:
    """Sends Telegram notifications on trade execution events.

    Uses httpx.AsyncClient with a 10-second timeout.
    Failures are logged silently and never propagate to the caller.
    Notifications are intended to be dispatched as FastAPI BackgroundTasks.

    Requirements: 7.1, 7.2, 7.3, 7.4, 7.5
    """

    # Timeout in seconds for Telegram API calls (Requirement 7.3)
    TIMEOUT_SECONDS: int = 10

    def __init__(self, bot_token: str) -> None:
        """Initialise the notifier with the Telegram bot token.

        Args:
            bot_token: Telegram Bot API token. When empty or blank, all
                       send calls are no-ops (log warning only).
        """
        self._bot_token = bot_token
        self._base_url = f"https://api.telegram.org/bot{bot_token}"

    async def send_trade_notification(
        self,
        chat_id: str | None,
        trade_result: dict,
        position: dict | None = None,
    ) -> None:
        """Send a trade execution notification to the user's Telegram chat.

        Requirement 7.1: Message includes symbol, side, quantity, execution
        price, and exchange name.
        Requirement 7.2: Close orders include realized PnL.
        Requirement 7.3: Timeout 10 seconds, no retry, log failures silently.
        Requirement 7.4: Called as a BackgroundTask — must not block caller.
        Requirement 7.5: Skip and log warning when chat_id is not configured.

        Args:
            chat_id: Telegram chat ID for the recipient user. None or empty
                     string causes the notification to be skipped.
            trade_result: Dict with trade details (symbol, side, filled_quantity,
                          fill_price, exchange, action).
            position: The open position record for close orders (provides entry
                      price and quantity for PnL calculation). None for open orders.
        """
        # Requirement 7.5: skip if no chat_id configured
        if not chat_id:
            logger.warning(
                "Telegram notification skipped: no chat_id configured "
                "(symbol=%s, action=%s)",
                trade_result.get("symbol"),
                trade_result.get("action"),
            )
            return

        if not self._bot_token:
            logger.warning(
                "Telegram notification skipped: bot_token is not configured "
                "(chat_id=%s)",
                chat_id,
            )
            return

        message = _format_notification_message(trade_result, position)
        url = f"{self._base_url}/sendMessage"
        payload = {
            "chat_id": chat_id,
            "text": message,
        }

        # Requirement 7.3: 10-second timeout, no retry, log failures silently
        try:
            async with httpx.AsyncClient(timeout=self.TIMEOUT_SECONDS) as client:
                response = await client.post(url, json=payload)
                if not response.is_success:
                    logger.error(
                        "Telegram API returned non-2xx status %d for chat_id=%s "
                        "(symbol=%s): %s",
                        response.status_code,
                        chat_id,
                        trade_result.get("symbol"),
                        response.text,
                    )
                else:
                    logger.info(
                        "Telegram notification sent: chat_id=%s symbol=%s action=%s",
                        chat_id,
                        trade_result.get("symbol"),
                        trade_result.get("action"),
                    )
        except httpx.TimeoutException:
            logger.error(
                "Telegram notification timed out after %ds: chat_id=%s symbol=%s",
                self.TIMEOUT_SECONDS,
                chat_id,
                trade_result.get("symbol"),
            )
        except httpx.HTTPError as exc:
            logger.error(
                "Telegram notification failed (HTTP error): chat_id=%s symbol=%s "
                "error=%s",
                chat_id,
                trade_result.get("symbol"),
                exc,
            )
