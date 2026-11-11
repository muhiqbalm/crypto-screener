"""``arena_snapshot`` job: one mark-to-market equity row per paper account per hour.

Marks come from paper_positions.mark_price, which the scheduler's paper check
refreshes every minute from closed 1m candles; this job does no network I/O.
Idempotent: a second run in the same hour overwrites that hour's row.
"""
from __future__ import annotations

import time
from typing import Optional

from ..db import utcnow
from ..ledger.store import iso
from .store import ensure_schema


def snapshot(conn, now: Optional[float] = None) -> int:
    ensure_schema(conn)
    now = now or time.time()
    hour = iso(now - now % 3600)
    n = 0
    for a in conn.execute("SELECT id, balance FROM paper_accounts").fetchall():
        upnl, n_open = 0.0, 0
        for p in conn.execute("SELECT side, qty, entry_price, mark_price, fees, funding FROM paper_positions "
                              "WHERE account_id=? AND status='open'", (a["id"],)):
            n_open += 1
            if p["mark_price"]:
                d = 1.0 if p["side"] == "long" else -1.0
                upnl += (p["mark_price"] - p["entry_price"]) * p["qty"] * d - (p["fees"] or 0) - (p["funding"] or 0)
        conn.execute(
            "INSERT INTO arena_equity_snapshots (account_id, ts, balance, equity, upnl, n_open, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?) ON CONFLICT(account_id, ts) DO UPDATE SET balance=excluded.balance, "
            "equity=excluded.equity, upnl=excluded.upnl, n_open=excluded.n_open, created_at=excluded.created_at",
            (a["id"], hour, a["balance"], a["balance"] + upnl, upnl, n_open, utcnow()))
        n += 1
    conn.commit()
    return n


def execute(conn, job: dict) -> None:
    snapshot(conn)
