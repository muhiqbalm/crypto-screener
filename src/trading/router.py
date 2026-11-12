"""Webhook router for TradingView trading alerts.

Receives POST /webhook/tradingview requests. TradingView drops a request
after about 3 seconds and never retries it, so the work is split in two.

Before the response (fast, no exchange calls):
  1. Content-Type and body-size validation
  2. Pydantic payload parsing (422)
  3. Passphrase authentication and is_active check (401)
  3b. Trading halt and leverage limit (403)
  4. Credential retrieval (400 / 500)
  4b. Duplicate delivery check against in-flight jobs (409)
  -> 202 Accepted

In a tracked background job (``webhook_jobs``), with the same behaviour the
endpoint had when it ran everything before responding:
  5. Exchange creation
  6. Position check + per user/symbol lock
  6b. Bot-owned close checks; leverage set only after the position check
  7. Order execution
  8. Position record open/close
  9. Trade audit logging
  10. Telegram notifications (sent once the job's work is done)

Requirements: 1.1, 1.11, 5.7, 9.1, 9.3, 11.5, 11.6
"""

from __future__ import annotations

import logging
import os
import time
from typing import Annotated, Any, Awaitable, Callable

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request
from fastapi.responses import JSONResponse

from . import webhook_jobs
from .auth import authenticate_by_passphrase
from .config import TradingSettings, get_trading_settings
from .connector import AuthenticationError, LeverageSetError, TradingConnector
from .credentials import CredentialStore, DecryptionError, MissingCredentialsError
from .executor import (
    InsufficientBalanceError,
    OrderExecutionError,
    OrderOutcomeUnknownError,
    TradeExecutor,
)
from .models import TradeAcceptedResponse, TradeErrorResponse, WebhookPayload
from .notifier import TelegramNotifier
from .position_manager import (
    DuplicatePositionError,
    LockTimeoutError,
    NoPositionError,
    PositionManager,
    PositionRecordError,
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
    """FastAPI dependency that creates and returns a database client.

    Uses LocalDatabaseClient (SQLite on VPS) when TRADING_USE_LOCAL_DB is enabled,
    or when Supabase URL is not configured / points to an expired cloud domain.
    This guarantees 100% self-hosted, zero-latency persistence directly on the VPS.
    """
    import os
    from .local_db import LocalDatabaseClient

    use_local = (
        os.environ.get("TRADING_USE_LOCAL_DB", "true").lower() in ("1", "true", "yes")
        or not settings.supabase_url
        or "supabase.co" in (settings.supabase_url or "")
    )
    if use_local:
        return LocalDatabaseClient()

    try:
        from supabase import create_client

        return create_client(settings.supabase_url, settings.supabase_key)
    except Exception as exc:
        logger.warning(
            "Failed to create Supabase client (%s) — falling back to LocalDatabaseClient", exc
        )
        return LocalDatabaseClient()


# ---------------------------------------------------------------------------
# POST /webhook/tradingview
# ---------------------------------------------------------------------------


@router.post(
    "/tradingview",
    status_code=202,
    response_model=TradeAcceptedResponse,
    responses={
        400: {"model": TradeErrorResponse, "description": "Bad request"},
        401: {"model": TradeErrorResponse, "description": "Unauthorized"},
        403: {"model": TradeErrorResponse, "description": "Order rejected"},
        409: {"model": TradeErrorResponse, "description": "Duplicate alert in progress"},
        413: {"model": TradeErrorResponse, "description": "Payload too large"},
        422: {"model": TradeErrorResponse, "description": "Validation error"},
        500: {"model": TradeErrorResponse, "description": "Internal server error"},
        503: {"model": TradeErrorResponse, "description": "Service unavailable"},
    },
    summary="Receive a TradingView strategy alert and execute the trade in the background",
)
async def receive_tradingview_alert(
    request: Request,
    body: WebhookPayload,
    background_tasks: BackgroundTasks,
    settings: Annotated[TradingSettings, Depends(get_settings)],
    supabase: Annotated[Any, Depends(get_supabase_client)],
) -> JSONResponse:
    """Validate a TradingView alert, acknowledge it, and execute it in the background.

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
    raw_body = await request.body()
    if len(raw_body) > settings.max_payload_size:
        return JSONResponse(
            status_code=413,
            content=TradeErrorResponse(
                error="Payload too large",
                detail=f"Request body must not exceed {settings.max_payload_size} bytes",
            ).model_dump(),
        )

    # ------------------------------------------------------------------
    # Step 2: Payload already parsed and validated by FastAPI via `body: WebhookPayload`
    # ------------------------------------------------------------------
    payload = body

    # Variables for the audit log (populated as we progress)
    user_id: str | None = None
    log_status: str = "failed"
    error_details: str | None = None

    # Instantiate services (use supabase from DI)
    trade_logger = TradeLogger(supabase)
    position_manager = PositionManager(supabase)
    credential_store = CredentialStore(settings.encryption_key, supabase)
    trading_connector = TradingConnector(
        testnet_enabled=settings.testnet_enabled,
        verbose=settings.ccxt_verbose,
    )
    executor = TradeExecutor(max_notional=settings.max_notional_usdt)
    notifier = TelegramNotifier(settings.telegram_bot_token)

    # ------------------------------------------------------------------
    # Step 3: Authenticate by passphrase
    # ------------------------------------------------------------------

    try:
        auth_result = await authenticate_by_passphrase(payload.passphrase, supabase)
        user_id = auth_result["user_id"]
    except HTTPException:
        # 401 or 503 — re-raise directly (auth.py already builds the response)
        raise

    # Requirement 5.7: verify the resolved user has is_active = true
    try:
        user_response = (
            supabase.table("users")
            .select("is_active, name, telegram_chat_id")
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

    account_name: str | None = user_response.data.get("name")
    chat_id: str | None = (
        user_response.data.get("telegram_chat_id") or settings.telegram_default_chat_id
    )
    alert_prefix = f"⚠️ {account_name or user_id} {payload.action.upper()} {payload.symbol}"

    def alert(reason: str) -> None:
        background_tasks.add_task(notifier.send_alert, chat_id, f"{alert_prefix}: {reason}")

    # ------------------------------------------------------------------
    # Step 3b: Trading halt and risk limits (closing is always allowed)
    # ------------------------------------------------------------------

    rejection: str | None = None
    if payload.action == "open":
        if os.path.exists(settings.halt_file):
            rejection = "Trading is halted"
        elif settings.max_leverage and (payload.leverage or 1) > settings.max_leverage:
            rejection = f"Leverage above limit of {settings.max_leverage}"

    if rejection:
        await _log_failure(trade_logger, user_id, payload, "rejected", rejection)
        alert(rejection)
        return JSONResponse(
            status_code=403,
            content=TradeErrorResponse(error="Order rejected", detail=rejection).model_dump(),
        )

    started_at = time.perf_counter()

    # ------------------------------------------------------------------
    # Step 4: Retrieve exchange credentials (database + local decryption)
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
    # Step 4b: Refuse a second delivery while the same alert is executing.
    # No await between this check and submit(), so two requests cannot both
    # pass it.
    # ------------------------------------------------------------------

    job_key = _job_key(user_id, payload)
    if webhook_jobs.is_inflight(job_key):
        rejection = (
            "duplicate alert skipped: the same signal for this symbol is still "
            "being executed"
        )
        logger.warning("Duplicate webhook delivery rejected: %s", job_key)
        await _log_failure(trade_logger, user_id, payload, "rejected", rejection)
        alert(rejection)
        return JSONResponse(
            status_code=409,
            content=TradeErrorResponse(error="Duplicate alert", detail=rejection).model_dump(),
        )

    job_description = (
        f"{account_name or user_id} {payload.action} {payload.side} {payload.symbol}"
    )
    try:
        webhook_jobs.submit(
            _execute_trade_job(
                payload=payload,
                user_id=user_id,
                account_name=account_name,
                chat_id=chat_id,
                alert_prefix=alert_prefix,
                credentials=credentials,
                trade_logger=trade_logger,
                position_manager=position_manager,
                trading_connector=trading_connector,
                executor=executor,
                notifier=notifier,
                started_at=started_at,
            ),
            key=job_key,
            description=job_description,
        )
    except webhook_jobs.NotAcceptingJobsError as exc:
        error_details = str(exc)
        await _log_failure(trade_logger, user_id, payload, "rejected", error_details)
        alert(error_details)
        return JSONResponse(
            status_code=503,
            content=TradeErrorResponse(
                error="Service unavailable", detail=error_details
            ).model_dump(),
        )

    # ------------------------------------------------------------------
    # Acknowledge. The outcome goes to trade_logs and Telegram.
    # ------------------------------------------------------------------

    return JSONResponse(
        status_code=202,
        content=TradeAcceptedResponse(
            symbol=payload.symbol,
            action=payload.action,
            side=payload.side,
        ).model_dump(),
    )


# ---------------------------------------------------------------------------
# Background trade job
# ---------------------------------------------------------------------------


def _job_key(user_id: str, payload: WebhookPayload) -> str:
    """Identity of an alert for duplicate-delivery detection.

    A second open (or close) of the same side on the same symbol while the
    first is still executing would be rejected by the exchange position check
    anyway; refusing it up front does not depend on the exchange having
    already reflected the first order.
    """
    return f"{user_id}|{payload.exchange}|{payload.symbol}|{payload.action}|{payload.side}"


async def _execute_trade_job(
    *,
    payload: WebhookPayload,
    user_id: str,
    account_name: str | None,
    chat_id: str | None,
    alert_prefix: str,
    credentials: dict,
    trade_logger: TradeLogger,
    position_manager: PositionManager,
    trading_connector: TradingConnector,
    executor: TradeExecutor,
    notifier: TelegramNotifier,
    started_at: float,
) -> None:
    """Run the exchange part of a webhook alert after it was acknowledged.

    Every failure is logged, written to trade_logs and alerted on Telegram.
    Notifications are queued while the job runs and sent at the end, so a slow
    Telegram call never holds the position lock.
    """
    notifications: list[tuple[Callable[..., Awaitable[None]], tuple]] = []

    def alert(reason: str) -> None:
        notifications.append((notifier.send_alert, (chat_id, f"{alert_prefix}: {reason}")))

    state: dict[str, Any] = {"exchange": None, "order_id": None}
    try:
        await _run_trade(
            payload=payload,
            user_id=user_id,
            account_name=account_name,
            chat_id=chat_id,
            credentials=credentials,
            trade_logger=trade_logger,
            position_manager=position_manager,
            trading_connector=trading_connector,
            executor=executor,
            notifier=notifier,
            started_at=started_at,
            alert=alert,
            notifications=notifications,
            state=state,
        )
    except Exception as exc:
        if state["order_id"] is not None:
            error_details = (
                f"Unexpected error after order {state['order_id']} was placed: {exc}"
            )
        else:
            error_details = f"Unexpected error during trade execution: {exc}"
        logger.error(
            "Webhook job failed for user=%s symbol=%s: %s",
            user_id,
            payload.symbol,
            error_details,
            exc_info=True,
        )
        await _log_failure(trade_logger, user_id, payload, "failed", error_details)
        alert(error_details)
        await _close_exchange_safe(state["exchange"])
    finally:
        for send, args in notifications:
            try:
                await send(*args)
            except Exception as exc:
                logger.error(
                    "Telegram notification failed for user=%s symbol=%s: %s",
                    user_id,
                    payload.symbol,
                    exc,
                    exc_info=True,
                )


async def _run_trade(
    *,
    payload: WebhookPayload,
    user_id: str,
    account_name: str | None,
    chat_id: str | None,
    credentials: dict,
    trade_logger: TradeLogger,
    position_manager: PositionManager,
    trading_connector: TradingConnector,
    executor: TradeExecutor,
    notifier: TelegramNotifier,
    started_at: float,
    alert: Callable[[str], None],
    notifications: list,
    state: dict,
) -> None:
    """Steps 5–10 of the webhook pipeline, unchanged apart from reporting.

    Each outcome that used to be an HTTP error response is now logged,
    written to trade_logs and alerted instead.
    """
    order_id: str | None = None
    fill_price: float | None = None
    filled_quantity: float | None = None
    error_details: str | None = None

    # ------------------------------------------------------------------
    # Step 5: Create exchange instance
    # ------------------------------------------------------------------

    exchange = None
    try:
        exchange = await trading_connector.create_exchange(
            exchange_name=payload.exchange,
            credentials=credentials,
            symbol=payload.symbol,
            # Leverage is applied only after the position check passes, so a
            # rejected signal never changes leverage on an existing position.
            leverage=None,
        )
    except AuthenticationError as exc:
        error_details = str(exc)
        await _log_failure(
            trade_logger, user_id, payload, "failed", error_details
        )
        alert(error_details)
        return
    except LeverageSetError as exc:
        error_details = str(exc)
        await _log_failure(
            trade_logger, user_id, payload, "failed", error_details
        )
        alert(error_details)
        return
    state["exchange"] = exchange

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
        alert(
            "signal skipped because the account already holds a position on this "
            "symbol (not opened by this signal). Check it on the exchange."
        )
        await _close_exchange_safe(exchange)
        return
    except NoPositionError as exc:
        error_details = str(exc)
        await _log_failure(
            trade_logger, user_id, payload, "rejected", error_details
        )
        position_manager.mark_missing(user_id, payload.symbol)
        alert("close signal but no position is open on the exchange (closed elsewhere?)")
        await _close_exchange_safe(exchange)
        return
    except LockTimeoutError as exc:
        error_details = str(exc)
        logger.warning(
            "Lock timeout for user=%s symbol=%s: %s", user_id, payload.symbol, exc
        )
        await _log_failure(
            trade_logger, user_id, payload, "rejected", error_details
        )
        alert(error_details)
        await _close_exchange_safe(exchange)
        return
    except Exception as exc:
        error_details = f"Position check failed: {exc}"
        logger.error(
            "Position check failed for user=%s symbol=%s: %s", user_id, payload.symbol, exc
        )
        await _log_failure(trade_logger, user_id, payload, "failed", error_details)
        alert(error_details)
        await _close_exchange_safe(exchange)
        return

    # ------------------------------------------------------------------
    # Step 6b: Close only what the bot opened; set leverage only for opens
    # ------------------------------------------------------------------

    rejection = None
    try:
        if payload.action == "close":
            record = position_manager.get_open_record(user_id, payload.symbol)
            exchange_side = str(position.get("side") or "").lower()
            if record is None:
                rejection = (
                    "close skipped: the open position on the exchange was not opened "
                    "by the bot, so it was left untouched"
                )
            elif exchange_side and exchange_side != str(record.get("side")).lower():
                rejection = (
                    f"close skipped: exchange position is {exchange_side} but the bot "
                    f"opened {record.get('side')}"
                )
            elif payload.side != str(record.get("side")).lower():
                rejection = (
                    f"close skipped: the alert says close {payload.side} but the bot's "
                    f"open position is {record.get('side')}; position left untouched"
                )
            else:
                contracts = float(position.get("contracts") or 0.0)
                recorded = float(record.get("quantity") or 0.0)
                position = {
                    **position,
                    "contracts": min(contracts, recorded) if recorded > 0 else contracts,
                    "entryPrice": record.get("entry_price") or position.get("entryPrice"),
                }
        elif payload.leverage is not None:
            await trading_connector.apply_leverage(
                exchange, payload.exchange, payload.leverage, payload.symbol
            )
    except LeverageSetError as exc:
        position_manager.release_lock(user_id, payload.symbol)
        error_details = str(exc)
        await _log_failure(trade_logger, user_id, payload, "failed", error_details)
        alert(error_details)
        await _close_exchange_safe(exchange)
        return
    except Exception as exc:
        position_manager.release_lock(user_id, payload.symbol)
        error_details = f"Position record lookup failed: {exc}"
        logger.error(error_details, exc_info=True)
        await _log_failure(trade_logger, user_id, payload, "failed", error_details)
        alert(error_details)
        await _close_exchange_safe(exchange)
        return

    if rejection:
        position_manager.release_lock(user_id, payload.symbol)
        await _log_failure(trade_logger, user_id, payload, "rejected", rejection)
        alert(rejection)
        await _close_exchange_safe(exchange)
        return

    ready_at = time.perf_counter()

    # ------------------------------------------------------------------
    # Step 7: Execute trade
    # ------------------------------------------------------------------

    try:
        try:
            order, _balance_info = await executor.execute_trade(
                exchange=exchange,
                payload=payload,
                position=position,
            )
        except InsufficientBalanceError as exc:
            error_details = str(exc)
            await _log_failure(
                trade_logger, user_id, payload, "failed", error_details
            )
            alert(error_details)
            await _close_exchange_safe(exchange)
            return
        except OrderExecutionError as exc:
            error_details = str(exc)
            logger.error(
                "Order execution failed for user=%s symbol=%s: %s",
                user_id,
                payload.symbol,
                exc,
            )
            # An open order that got no answer may still have been filled.
            # Ask the exchange (the lock is still held) before calling it failed.
            outcome, found = "failed", None
            if isinstance(exc, OrderOutcomeUnknownError) and payload.action == "open":
                outcome, found, note = await position_manager.confirm_unanswered_open(
                    exchange, payload.symbol, payload.side
                )
                logger.warning(
                    "Unanswered open for user=%s symbol=%s side=%s resolved as %s %s",
                    user_id,
                    payload.symbol,
                    payload.side,
                    outcome,
                    note,
                )
                if outcome == "flat":
                    error_details += (
                        ". Checked the exchange: no position was opened, nothing recorded"
                    )
                elif outcome == "unknown":
                    error_details = (
                        f"ORDER OUTCOME UNKNOWN for {payload.side.upper()} {payload.symbol}: "
                        f"{error_details}; {note}. A real {payload.side} position may be "
                        "open with no bot record, and the bot will not close it. "
                        "Check the exchange now. The order was not re-sent."
                    )
            if outcome != "filled":
                await _log_failure(
                    trade_logger, user_id, payload, "failed", error_details
                )
                alert(error_details)
                await _close_exchange_safe(exchange)
                return
            # Filled: carry on exactly as if the exchange had answered.
            order = {
                "id": "",
                "average": found.get("entryPrice"),
                "filled": found.get("contracts") or found.get("size"),
            }
            alert(
                f"{error_details}, but the exchange shows the {payload.side} position "
                "is open, so it was recorded as opened (order not re-sent)"
            )

        # Extract fill details from the CCXT order response
        order_id = str(order.get("id", ""))
        state["order_id"] = order_id
        fill_price = float(order.get("average") or order.get("price") or 0.0)
        filled_quantity = float(order.get("filled") or order.get("amount") or 0.0)

        # ------------------------------------------------------------------
        # Step 8: Update position record
        # ------------------------------------------------------------------

        try:
            if payload.action == "open":
                await position_manager.open_position(
                    user_id=user_id,
                    symbol=payload.symbol,
                    side=payload.side,
                    entry_price=fill_price,
                    quantity=filled_quantity,
                    exchange=payload.exchange,
                )
            else:  # "close"
                await position_manager.close_position(
                    user_id=user_id,
                    symbol=payload.symbol,
                    exit_price=fill_price,
                )
        except PositionRecordError as exc:
            # The order is already filled, so carry on, but a human must know.
            logger.error(
                "Position record write failed for user=%s symbol=%s order=%s: %s",
                user_id,
                payload.symbol,
                order_id,
                exc,
                exc_info=True,
            )
            if payload.action == "open":
                alert(
                    f"REAL POSITION WITHOUT A RECORD: {payload.side} {filled_quantity} "
                    f"{payload.symbol} at {fill_price} (order {order_id}) is open on the "
                    f"exchange, but the bot {exc}. The bot will NOT close it on a close "
                    "signal. Close it by hand on the exchange."
                )
            else:
                alert(
                    f"position closed on the exchange (order {order_id}), but the bot "
                    f"{exc}. The record still says open; tell the admin before opening "
                    "this symbol by hand"
                )
    finally:
        position_manager.release_lock(user_id, payload.symbol)

    # ------------------------------------------------------------------
    # Step 9: Log trade. The order is already live, so a log failure is
    # alerted but must not turn the outcome into an error.
    # ------------------------------------------------------------------

    try:
        await trade_logger.log_trade(
            user_id=user_id,
            symbol=payload.symbol,
            action=payload.action,
            side=payload.side,
            exchange=payload.exchange,
            size_value=payload.size_value,
            status="success",
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
        alert(f"order {order_id} executed but its log entry failed: {exc}")

    # ------------------------------------------------------------------
    # Step 10: Queue the Telegram trade notification (sent when the job ends)
    # ------------------------------------------------------------------

    trade_result_for_notifier = {
        "symbol": payload.symbol,
        "side": payload.side,
        "filled_quantity": filled_quantity,
        "fill_price": fill_price,
        "exchange": payload.exchange,
        "action": payload.action,
        "account": account_name,
    }

    notifications.append((
        notifier.send_trade_notification,
        (
            chat_id,
            trade_result_for_notifier,
            # Pass position record for PnL calculation on close orders
            position if payload.action == "close" else None,
        ),
    ))

    # Close the exchange session (clean up)
    await _close_exchange_safe(exchange)

    logger.info(
        "Webhook timing for %s: setup=%.2fs order=%.2fs order_id=%s",
        payload.symbol,
        ready_at - started_at,
        time.perf_counter() - ready_at,
        order_id,
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
