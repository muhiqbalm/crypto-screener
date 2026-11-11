"""bmtm_trading.db readers for the live check (stdlib, read-only).

Separate ``mode=ro`` connection with ``PRAGMA query_only``. Only the columns needed
here are selected: never user ids, passphrases, keys or order ids. Error details are
sanitised before they leave this module.
"""
from __future__ import annotations

import sqlite3
from pathlib import Path

from ..ledger.store import norm_symbol, to_epoch
from .logs import sanitize


def _epoch(v):
    if v in (None, ""):
        return None
    try:
        return to_epoch(str(v))
    except ValueError:
        return None


def _connect(path: str):
    src = sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=2.0)
    src.execute("PRAGMA query_only=1")
    return src


def _cols(src, table: str) -> set:
    return {r[1] for r in src.execute(f"PRAGMA table_info({table})")}


def read_trade_logs(path: str, symbol: str, limit: int = 20000) -> list[dict]:
    """trade_logs rows of one symbol: {ts, action, side, status, fill_price, fill_qty, reason}."""
    if not path or not Path(path).exists():
        return []
    src = _connect(path)
    try:
        cols = _cols(src, "trade_logs")
        if not {"symbol", "action", "side", "created_at"} <= cols:
            return []
        opt = [c for c in ("status", "fill_price", "filled_quantity", "error_details") if c in cols]
        rows = src.execute(f"SELECT symbol, action, side, created_at{''.join(', ' + c for c in opt)} "
                           "FROM trade_logs ORDER BY created_at LIMIT ?", (limit,))
        names = [d[0] for d in rows.description]
        out = []
        for r in rows.fetchall():
            d = dict(zip(names, r))
            if norm_symbol(d["symbol"]) != symbol:
                continue
            ts = _epoch(d["created_at"])
            if ts is None:
                continue
            try:
                px = float(d.get("fill_price")) if d.get("fill_price") not in (None, "") else None
            except (TypeError, ValueError):
                px = None
            try:
                qty = float(d.get("filled_quantity")) if d.get("filled_quantity") not in (None, "") else None
            except (TypeError, ValueError):
                qty = None
            out.append({"ts": ts, "action": (d["action"] or "").lower(), "side": (d["side"] or "").lower(),
                        "status": (d.get("status") or "").lower(), "fill_price": px or None, "fill_qty": qty,
                        "reason": sanitize(d.get("error_details"))})
        return out
    finally:
        src.close()


def read_bot_positions(path: str, symbol: str, limit: int = 5000) -> list[dict]:
    """Positions the BOT opened (the bot only records its own; manual positions on the
    exchange are never in this table): {side, status, entry_price, exit_price, opened, closed}."""
    if not path or not Path(path).exists():
        return []
    src = _connect(path)
    try:
        cols = _cols(src, "positions")
        if not {"symbol", "side", "created_at"} <= cols:
            return []
        opt = [c for c in ("status", "entry_price", "exit_price", "closed_at") if c in cols]
        rows = src.execute(f"SELECT symbol, side, created_at{''.join(', ' + c for c in opt)} FROM positions "
                           "ORDER BY created_at LIMIT ?", (limit,))
        names = [d[0] for d in rows.description]
        out = []
        for r in rows.fetchall():
            d = dict(zip(names, r))
            if norm_symbol(d["symbol"]) != symbol:
                continue
            out.append({"side": (d["side"] or "").lower(), "status": (d.get("status") or "").lower(),
                        "entry_price": d.get("entry_price"), "exit_price": d.get("exit_price"),
                        "opened": _epoch(d["created_at"]), "closed": _epoch(d.get("closed_at"))})
        return out
    finally:
        src.close()
