"""Trading module for TradingView webhook-driven automated trading.

This module is architecturally separate from the existing screener module
under src/exchange/. It provides webhook-based trade execution on Binance
and OKX via the CCXT library.
"""

from .auth import authenticate_by_passphrase
from .config import TradingSettings, get_trading_settings
from .executor import InsufficientBalanceError, OrderExecutionError, TradeExecutor
from .models import TradeErrorResponse, TradeSuccessResponse, WebhookPayload
from .notifier import TelegramNotifier
from .position_manager import (
    DuplicatePositionError,
    LockTimeoutError,
    NoPositionError,
    PositionManager,
)
from .router import router as trading_router

__all__ = [
    "TradingSettings",
    "get_trading_settings",
    "WebhookPayload",
    "TradeSuccessResponse",
    "TradeErrorResponse",
    "authenticate_by_passphrase",
    "TradeExecutor",
    "InsufficientBalanceError",
    "OrderExecutionError",
    "PositionManager",
    "DuplicatePositionError",
    "NoPositionError",
    "LockTimeoutError",
    "TelegramNotifier",
    "trading_router",
]
