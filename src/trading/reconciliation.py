"""Compares open positions on the exchange with the audit table.

A difference usually means a webhook was lost, for example a missed close
alert, so it is reported on Telegram. Each difference is reported once.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from .config import TradingSettings
from .connector import TradingConnector
from .credentials import CredentialStore
from .notifier import TelegramNotifier

logger = logging.getLogger(__name__)


def find_differences(exchange_symbols: set[str], audit_symbols: set[str]) -> list[str]:
    """Return a description of each symbol open on only one side."""
    missing_audit = [f"{s} open on exchange, not in audit" for s in exchange_symbols - audit_symbols]
    missing_exchange = [f"{s} open in audit, not on exchange" for s in audit_symbols - exchange_symbols]
    return sorted(missing_audit + missing_exchange)


async def _check_credential(row: dict, db: Any, settings: TradingSettings) -> list[str]:
    user_id, exchange_name = row["user_id"], row["exchange"]
    credentials = await CredentialStore(settings.encryption_key, db).get_credentials(
        user_id, exchange_name
    )
    connector = TradingConnector(testnet_enabled=settings.testnet_enabled)
    exchange = await connector.create_exchange_for_monitoring(exchange_name, credentials)
    try:
        positions = await exchange.fetch_positions()
    finally:
        await exchange.close()

    exchange_symbols = {p["symbol"] for p in positions if float(p.get("contracts") or 0) > 0}
    audit_rows = (
        db.table("positions").select("symbol").eq("user_id", user_id).eq("status", "open").execute()
    )
    audit_symbols = {r["symbol"] for r in audit_rows.data or []}
    return [f"{user_id}: {d}" for d in find_differences(exchange_symbols, audit_symbols)]


async def run_reconciliation(db: Any, settings: TradingSettings) -> None:
    """Check every stored credential forever; started only when enabled."""
    notifier = TelegramNotifier(settings.telegram_bot_token)
    reported: set[str] = set()
    while True:
        rows = db.table("exchange_credentials").select("user_id, exchange").execute().data or []
        current: set[str] = set()
        for row in rows:
            try:
                current.update(await _check_credential(row, db, settings))
            except Exception as exc:
                logger.error("Reconciliation failed for %s: %s", row["user_id"], exc)
        for difference in sorted(current - reported):
            await notifier.send_alert(
                settings.telegram_default_chat_id, f"⚠️ Position mismatch: {difference}"
            )
        reported = current
        await asyncio.sleep(settings.reconcile_interval_seconds)
