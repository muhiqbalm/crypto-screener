"""Webhook router for TradingView trading alerts.

Receives POST /webhook/tradingview requests and orchestrates the full
trade processing pipeline:
  1. Content-Type and body-size validation
  2. Pydantic payload parsing
  3. Passphrase authentication
  4. Credential retrieval
  5. Exchange creation
  6. Position check + advisory lock
  7. Order execution
  8. Position record open/close
  9. Trade audit logging
  10. Telegram notification (background task)
  11. Return TradeSuccessResponse

Requirements: 1.1, 1.11, 5.7, 9.1, 9.3, 11.5, 11.6
"""

from __future__ import annotations

import json
import logging
from typing import Annotated, Any

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import ValidationError

from .auth import authenticate_by_passphrase
from .config import TradingSettings, get_trading_settings
from .connector import AuthenticationError, LeverageSetError, TradingConnector
from .credentials import CredentialStore, DecryptionError, MissingCredentialsError
from .executor import InsufficientBalanceError, OrderExecutionError, TradeExecutor
from .models import TradeErrorResponse, TradeSuccessResponse, WebhookPayload
from .notifier import TelegramNotifier
from .position_manager import (
    DuplicatePositionError,
    LockTimeoutError,
    NoPositionError,
    PositionManager,
)
from .trade_logger import TradeLogger

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/webhook", tags=["Trading Webhook"])


# ---------------------------------------------------------------------------
# Dependency injection helpers
# ---------------------------------------------------------------------------


def get_settings() -> TradingSettings:
    """FastAPI dependency that provides TradingSettings."""
    return get_trading_settings()


def get_supabase_client(
    settings: Annotated[TradingSettings, Depends(get_settings)],
) -> Any:
    """FastAPI dependency that creates and returns a Supabase client.

    Returns None when the Supabase URL or key is not configured (e.g. during
    tests where individual components are mocked).
    """
    if not settings.supabase_url or not settings.supabase_key:
        logger.warning(
            "Supabase credentials not configured — returning None client. "
            "Ensure TRADING_SUPABASE_URL and TRADING_SUPABASE_KEY are set."
        )
        return None

    try:
        from supabase import create_client

        return create_client(settings.supabase_url, settings.supabase_key)
    except Exception as exc:
        logger.error("Failed to create Supabase client: %s", exc, exc_info=True)
        return None


# ---------------------------------------------------------------------------
# POST /webhook/tradingview
# ---------------------------------------------------------------------------


@router.post(
    "/tradingview",
    status_code=200,
    response_model=TradeSuccessResponse,
    responses={
        400: {"model": TradeErrorResponse, "description": "Bad request"},
        401: {"model": TradeErrorResponse, "description": "Unauthorized"},
        404: {"model": TradeErrorResponse, "description": "No open position found"},
        409: {"model": TradeErrorResponse, "description": "Conflict"},
        413: {"model": TradeErrorResponse, "description": "Payload too large"},
        422: {"model": TradeErrorResponse, "description": "Validation error"},
        500: {"model": TradeErrorResponse, "description": "Internal server error"},
        502: {"model": TradeErrorResponse, "description": "Exchange error"},
        503: {"model": TradeErrorResponse, "description": "Service unavailable"},
    },
    summary="Receive a TradingView strategy alert and execute the trade",
)
async def receive_tradingview_alert(
    request: Request,
    background_tasks: BackgroundTasks,
    settings: Annotated[TradingSettings, Depends(get_settings)],
    supabase: Annotated[Any, Depends(get_supabase_client)],
) -> JSONResponse:
    """Process a TradingView webhook alert through the full trading pipeline.

    Requirements: 1.1, 1.11, 5.7, 9.1, 9.3, 11.5, 11.6
    """

    # ------------------------------------------------------------------
    # Step 1: Validate Content-Type and body size
    # ------------------------------------------------------------------

    # Requirement 11.5: reject non-JSON Content-Type with 422
    content_type = request.headers.get("content-type", "")
    if not content_type.startswith("application/json"):
        return JSONResponse(
            status_code=422,
            content=TradeErrorResponse(
                error="Validation error",
                detail="Content-Type must be application/json",
            ).model_dump(),
        )

    # Requirement 11.6: reject body > max_payload_size with 413
    body = await request.body()
    if len(body) > settings.max_payload_size:
        return JSONResponse(
            status_code=413,
            content=TradeErrorResponse(
                error="Payload too large",
                detail=f"Request body must not exceed {settings.max_payload_size} bytes",
            ).model_dump(),
        )

    # ------------------------------------------------------------------
    # Step 2: Parse body into WebhookPayload
    # ------------------------------------------------------------------

    # Attempt JSON decode first so we give a 400 for malformed JSON rather
    # than letting Pydantic produce an unhelpful 422.
    try:
        raw_data = json.loads(body)
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        return JSONResponse(
            status_code=400,
            content=TradeErrorResponse(
                error="Malformed payload",
                detail=str(exc),
            ).model_dump(),
        )

    # Pydantic validation — produces 422 with field-level details on failure.
    try:
        payload = WebhookPayload.model_validate(raw_data)
    except ValidationError as exc:
        return JSONResponse(
            status_code=422,
            content=TradeErrorResponse(
                error="Validation error",
                detail=exc.json(),
            ).model_dump(),
        )

    # Variables for the audit log (populated as we progress)
    user_id: str | None = None
    order_id: str | None = None
    fill_price: float | None = None
    filled_quantity: float | None = None
    log_status: str = "failed"
    error_details: str | None = None

    # Instantiate services (use supabase from DI)
    trade_logger = TradeLogger(supabase)
    position_manager = PositionManager(supabase)
    credential_store = CredentialStore(settings.encryption_key, supabase)
    trading_connector = TradingConnector()
    executor = TradeExecutor()
    notifier = TelegramNotifier(settings.telegram_bot_token)

    # ------------------------------------------------------------------
    # Step 3: Authenticate by passphrase
    # ------------------------------------------------------------------

    try:
        auth_result = await authenticate_by_passphrase(payload.passphrase, supabase)
        user_id = auth_result["user_id"]
        config = auth_result["config"]
    except HTTPException:
        # 401 or 503 — re-raise directly (auth.py already builds the response)
        raise

    # Requirement 5.7: verify the resolved user has is_active = true
    try:
        user_response = (
            supabase.table("users")
            .select("is_active")
            .eq("id", user_id)
            .single()
            .execute()
        )
    except Exception as exc:
        logger.error(
            "Database error checking is_active for user=%s: %s",
            user_id,
            exc,
            exc_info=True,
        )
        raise HTTPException(status_code=503, detail="Service unavailable") from exc

    if not user_response.data or not user_response.data.get("is_active"):
        raise HTTPException(status_code=401, detail="Unauthorized")

    # ------------------------------------------------------------------
    # Step 4: Retrieve exchange credentials
    # ------------------------------------------------------------------

    try:
        credentials = await credential_store.get_credentials(user_id, payload.exchange)
    except MissingCredentialsError as exc:
        error_details = str(exc)
        await _log_failure(
            trade_logger, user_id, payload, log_status, error_details
        )
        return JSONResponse(
            status_code=400,
            content=TradeErrorResponse(
                error=f"No credentials for {payload.exchange}",
                detail=error_details,
            ).model_dump(),
        )
    except DecryptionError as exc:
        error_details = str(exc)
        logger.error(
            "Credential decryption failure for user=%s exchange=%s: %s",
            user_id,
            payload.exchange,
            exc,
        )
        await _log_failure(
            trade_logger, user_id, payload, "failed", error_details
        )
        return JSONResponse(
            status_code=500,
            content=TradeErrorResponse(
                error="Internal error",
                detail="Credential decryption failed",
            ).model_dump(),
        )

    # ------------------------------------------------------------------
    # Step 5: Create exchange instance
    # ------------------------------------------------------------------

    exchange = None
    try:
        exchange = await trading_connector.create_exchange(
            exchange_name=payload.exchange,
            credentials=credentials,
            symbol=payload.symbol,
            leverage=payload.leverage,
        )
    except AuthenticationError as exc:
        error_details = str(exc)
        await _log_failure(
            trade_logger, user_id, payload, "failed", error_details
        )
        return JSONResponse(
            status_code=400,
            content=TradeErrorResponse(
                error="Exchange authentication failed",
                detail=error_details,
            ).model_dump(),
        )
    except LeverageSetError as exc:
        error_details = str(exc)
        await _log_failure(
            trade_logger, user_id, payload, "failed", error_details
        )
        return JSONResponse(
            status_code=400,
            content=TradeErrorResponse(
                error="Failed to set leverage",
                detail=error_details,
            ).model_dump(),
        )

    # ------------------------------------------------------------------
    # Step 6: Position check and advisory lock
    # ------------------------------------------------------------------

    position: dict | None = None
    try:
        position = await position_manager.check_and_lock(
            user_id=user_id,
            symbol=payload.symbol,
            action=payload.action,
            exchange=exchange,
        )
    except DuplicatePositionError as exc:
        error_details = str(exc)
        await _log_failure(
            trade_logger, user_id, payload, "rejected", error_details
        )
        await _close_exchange_safe(exchange)
        return JSONResponse(
            status_code=409,
            content=TradeErrorResponse(
                error="Position already open",
                detail=error_details,
            ).model_dump(),
        )
    except NoPositionError as exc:
        error_details = str(exc)
        await _log_failure(
            trade_logger, user_id, payload, "rejected", error_details
        )
        await _close_exchange_safe(exchange)
        return JSONResponse(
            status_code=404,
            content=TradeErrorResponse(
                error="No open position found",
                detail=error_details,
            ).model_dump(),
        )
    except LockTimeoutError as exc:
        error_details = str(exc)
        logger.warning(
            "Lock timeout for user=%s symbol=%s: %s", user_id, payload.symbol, exc
        )
        await _log_failure(
            trade_logger, user_id, payload, "rejected", error_details
        )
        await _close_exchange_safe(exchange)
        return JSONResponse(
            status_code=409,
            content=TradeErrorResponse(
                error="Symbol currently being processed",
                detail=error_details,
            ).model_dump(),
        )

    # ------------------------------------------------------------------
    # Step 7: Execute trade
    # ------------------------------------------------------------------

    try:
        order = await executor.execute_trade(
            exchange=exchange,
            payload=payload,
            position=position,
        )
    except InsufficientBalanceError as exc:
        error_details = str(exc)
        await _log_failure(
            trade_logger, user_id, payload, "failed", error_details
        )
        await _close_exchange_safe(exchange)
        return JSONResponse(
            status_code=400,
            content=TradeErrorResponse(
                error="Insufficient balance",
                detail=error_details,
            ).model_dump(),
        )
    except OrderExecutionError as exc:
        error_details = str(exc)
        logger.error(
            "Order execution failed for user=%s symbol=%s: %s",
            user_id,
            payload.symbol,
            exc,
        )
        await _log_failure(
            trade_logger, user_id, payload, "failed", error_details
        )
        await _close_exchange_safe(exchange)
        return JSONResponse(
            status_code=502,
            content=TradeErrorResponse(
                error="Order execution failed",
                detail=error_details,
            ).model_dump(),
        )

    # Extract fill details from the CCXT order response
    order_id = str(order.get("id", ""))
    fill_price = float(order.get("average") or order.get("price") or 0.0)
    filled_quantity = float(order.get("filled") or order.get("amount") or 0.0)

    # ------------------------------------------------------------------
    # Step 8: Update position record
    # ------------------------------------------------------------------

    if payload.action == "open":
        updated_position = await position_manager.open_position(
            user_id=user_id,
            symbol=payload.symbol,
            side=payload.side,
            entry_price=fill_price,
            quantity=filled_quantity,
            exchange=payload.exchange,
        )
    else:  # "close"
        updated_position = await position_manager.close_position(
            user_id=user_id,
            symbol=payload.symbol,
            exit_price=fill_price,
        )

    # ------------------------------------------------------------------
    # Step 9: Log trade (required before response — 500 on failure)
    # ------------------------------------------------------------------

    log_status = "success"
    try:
        await trade_logger.log_trade(
            user_id=user_id,
            symbol=payload.symbol,
            action=payload.action,
            side=payload.side,
            exchange=payload.exchange,
            size_value=payload.size_value,
            status=log_status,
            order_id=order_id,
            fill_price=fill_price,
            filled_quantity=filled_quantity,
        )
    except Exception as exc:
        logger.error(
            "Trade log write failed after retry for user=%s symbol=%s: %s",
            user_id,
            payload.symbol,
            exc,
            exc_info=True,
        )
        await _close_exchange_safe(exchange)
        return JSONResponse(
            status_code=500,
            content=TradeErrorResponse(
                error="Trade executed but log failed",
                detail=str(exc),
            ).model_dump(),
        )

    # ------------------------------------------------------------------
    # Step 10: Dispatch Telegram notification (non-blocking background task)
    # ------------------------------------------------------------------

    trade_result_for_notifier = {
        "symbol": payload.symbol,
        "side": payload.side,
        "filled_quantity": filled_quantity,
        "fill_price": fill_price,
        "exchange": payload.exchange,
        "action": payload.action,
    }

    # Retrieve chat_id from user config (if available)
    chat_id: str | None = config.get("telegram_chat_id") if config else None

    background_tasks.add_task(
        notifier.send_trade_notification,
        chat_id,
        trade_result_for_notifier,
        # Pass position record for PnL calculation on close orders
        position if payload.action == "close" else None,
    )

    # Close the exchange session (clean up)
    await _close_exchange_safe(exchange)

    # ------------------------------------------------------------------
    # Step 11: Return TradeSuccessResponse
    # ------------------------------------------------------------------

    return JSONResponse(
        status_code=200,
        content=TradeSuccessResponse(
            order_id=order_id,
            symbol=payload.symbol,
            action=payload.action,
            side=payload.side,
            fill_price=fill_price,
            filled_quantity=filled_quantity,
        ).model_dump(),
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _log_failure(
    trade_logger: TradeLogger,
    user_id: str | None,
    payload: WebhookPayload,
    status: str,
    error_details: str | None,
) -> None:
    """Best-effort trade log write on failure paths.

    Swallows exceptions so that a logging failure does not mask the original
    error response.
    """
    if user_id is None:
        return
    try:
        await trade_logger.log_trade(
            user_id=user_id,
            symbol=payload.symbol,
            action=payload.action,
            side=payload.side,
            exchange=payload.exchange,
            size_value=payload.size_value,
            status=status,
            error_details=error_details,
        )
    except Exception as exc:
        logger.warning(
            "Best-effort trade log write failed for user=%s symbol=%s: %s",
            user_id,
            payload.symbol,
            exc,
        )


async def _close_exchange_safe(exchange: Any) -> None:
    """Close a CCXT exchange instance without raising."""
    if exchange is None:
        return
    try:
        await exchange.close()
    except Exception:
        pass
