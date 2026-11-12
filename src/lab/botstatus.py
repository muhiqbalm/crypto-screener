"""Status bot (/bot page): read-only summary of the live webhook path, for admins.

Answers two questions the reconciliation (``livecheck``) cannot: "is the webhook of the
account(s) the live bot trades on switched on?" and "when did the bot last process an
alert, and what happened to it?".

Source: bmtm_trading.db through a separate read-only connection (``mode=ro`` plus
``PRAGMA query_only``), short queries, selecting only:

  users                 id, name, email, is_active   (email only to build a masked label)
  webhook_configs       user_id, is_active, created_at   (never the passphrase)
  exchange_credentials  user_id, exchange                (never keys, secrets or passphrases)
  trade_logs            user_id, symbol, action, side, status, created_at
                        (never order ids, sizes or error text)

User ids are only used to join the tables; they never leave this module. Accounts are
labelled by display name (or a masked e-mail). Nothing here imports the trading package,
calls an exchange, posts to the webhook, notifies anyone or writes anywhere.
"""
from __future__ import annotations

import sqlite3
import time
from pathlib import Path
from typing import Any, Optional

from .ledger.store import iso, norm_symbol, to_epoch

WINDOW_DAYS = 7
ROWS_PER_ACCOUNT = 500          # newest trade_logs rows read per account (counts stop at the window)
STATUSES = ("success", "failed", "rejected")


def _connect(path: str) -> sqlite3.Connection:
    src = sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=2.0)
    src.execute("PRAGMA query_only=1")
    return src


def _cols(src: sqlite3.Connection, table: str) -> set:
    return {r[1] for r in src.execute(f"PRAGMA table_info({table})")}


def _epoch(v: Any) -> Optional[float]:
    if v in (None, ""):
        return None
    try:
        return to_epoch(str(v))
    except ValueError:
        return None


def _iso(v: Any) -> Optional[str]:
    t = _epoch(v)
    return iso(t) if t is not None else None


def mask_email(email: Optional[str]) -> Optional[str]:
    """"rosyade@bmtm.io" -> "ro•••@bmtm.io"; None when there is nothing usable."""
    if not email or "@" not in str(email):
        return None
    local, _, domain = str(email).partition("@")
    return f"{local[:2]}•••@{domain}" if local and domain else None


def _label(name: Optional[str], email: Optional[str]) -> str:
    n = (name or "").strip()
    return n or mask_email(email) or "Akun tanpa nama"


def _unavailable(reason: str, now: float, days: int) -> dict:
    return {"generated_at": iso(now), "window_days": days, "available": False, "reason": reason,
            "active_accounts": 0, "accounts": [], "last_alert": None}


def build(trading_db_path: str, now: Optional[float] = None, days: int = WINDOW_DAYS) -> dict:
    """Per account that has a webhook config: is it active, which exchanges have a key, the
    last alert the bot processed and how many alerts (and failures) in the last ``days``."""
    now = time.time() if now is None else now
    if not trading_db_path or not Path(trading_db_path).exists():
        return _unavailable("database bot tidak ditemukan", now, days)
    try:
        src = _connect(trading_db_path)
    except sqlite3.Error:
        return _unavailable("database bot tidak bisa dibuka", now, days)
    try:
        return _collect(src, now, days)
    except sqlite3.Error:
        return _unavailable("database bot sedang sibuk atau tidak terbaca", now, days)
    finally:
        src.close()


def _collect(src: sqlite3.Connection, now: float, days: int) -> dict:
    wh_cols = _cols(src, "webhook_configs")
    if not {"user_id", "is_active"} <= wh_cols:
        return _unavailable("tabel webhook tidak ada", now, days)
    created = "created_at" if "created_at" in wh_cols else "NULL"
    configs: dict[str, dict] = {}
    for uid, active, created_at in src.execute(
            f"SELECT user_id, is_active, {created} FROM webhook_configs ORDER BY {created} DESC"):
        if uid is None:
            continue
        c = configs.setdefault(str(uid), {"active": False, "since": None})
        if active and not c["active"]:
            c["active"], c["since"] = True, _iso(created_at)

    users: dict[str, dict] = {}
    u_cols = _cols(src, "users")
    if "id" in u_cols:
        sel = ["id"] + [c if c in u_cols else "NULL" for c in ("name", "email", "is_active")]
        for uid, name, email, active in src.execute(f"SELECT {', '.join(sel)} FROM users"):
            users[str(uid)] = {"label": _label(name, email), "active": active is None or bool(active)}

    exchanges: dict[str, set] = {}
    if {"user_id", "exchange"} <= _cols(src, "exchange_credentials"):
        for uid, ex in src.execute("SELECT user_id, exchange FROM exchange_credentials"):
            if uid is not None and ex:
                exchanges.setdefault(str(uid), set()).add(str(ex).lower())

    tl_cols = _cols(src, "trade_logs")
    has_logs = {"user_id", "symbol", "action", "side", "created_at"} <= tl_cols
    status_col = "status" if "status" in tl_cols else "NULL"
    cutoff = now - days * 86400

    accounts = []
    for uid, cfg in configs.items():
        user = users.get(uid, {"label": "Akun tanpa nama", "active": True})
        last, n_window, failed, rejected = None, 0, 0, 0
        if has_logs:
            rows = src.execute(
                f"SELECT symbol, action, side, {status_col}, created_at FROM trade_logs WHERE user_id=? "
                "ORDER BY created_at DESC LIMIT ?", (uid, ROWS_PER_ACCOUNT)).fetchall()
            for symbol, action, side, status, created_at in rows:
                t = _epoch(created_at)
                if t is None:
                    continue
                st = (status or "").lower() or None
                if last is None:
                    last = {"at": iso(t), "symbol": norm_symbol(symbol), "action": (action or "").lower() or None,
                            "side": (side or "").lower() or None, "status": st}
                if t >= cutoff:
                    n_window += 1
                    failed += st == "failed"
                    rejected += st == "rejected"
        accounts.append({
            "label": user["label"],
            "account_active": user["active"],
            "webhook_active": cfg["active"],
            "webhook_since": cfg["since"],
            "exchanges": sorted(exchanges.get(uid, set())),
            "last_alert": last,
            "alerts_window": n_window,
            "failed_window": failed,
            "rejected_window": rejected,
        })

    # Live accounts first, then the most recent activity.
    accounts.sort(key=lambda a: (not (a["webhook_active"] and a["account_active"]),
                                 -(_epoch(a["last_alert"]["at"]) or 0) if a["last_alert"] else 0, a["label"]))
    latest = max((a for a in accounts if a["last_alert"]), key=lambda a: a["last_alert"]["at"], default=None)
    return {
        "generated_at": iso(now),
        "window_days": days,
        "available": True,
        "reason": None if has_logs else "tabel trade_logs tidak ada",
        "active_accounts": sum(1 for a in accounts if a["webhook_active"] and a["account_active"]),
        "accounts": accounts,
        "last_alert": {**latest["last_alert"], "label": latest["label"]} if latest else None,
    }
