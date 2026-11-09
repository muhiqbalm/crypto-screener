"""Scheduler hooks run inside the lab worker's main loop (never in the API).

  * watches: enqueue a watch_eval job ~LAB_WATCH_DELAY_S after every candle close
  * paper:   every minute, check open paper positions against closed 1m candles
             (SL/TP, engine intrabar rule), charge funding settlements, refresh marks
  * bot:     every LAB_BOT_IMPORT_INTERVAL_S, import the live bot's CLOSED trades from
             bmtm_trading.db (opened read-only, mode=ro, short queries) into the journal
"""
from __future__ import annotations

import logging
import sqlite3
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from . import paper
from . import queue as q
from .db import dumps, utcnow
from .settings import LabSettings

log = logging.getLogger("lab.scheduler")

TF_SECONDS = {"1h": 3600, "4h": 14400, "1d": 86400}
PAPER_TF = "1m"


def _iso(epoch: float) -> str:
    return datetime.fromtimestamp(epoch, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def last_closed_bar_open(tf: str, now: float, delay_s: int) -> Optional[str]:
    """Open time of the newest bar that closed at least delay_s ago."""
    step = TF_SECONDS[tf]
    t = now - delay_s
    last_close = t - t % step            # most recent bar boundary <= t
    return _iso(last_close - step)


def schedule_watches(conn, s: LabSettings, now: Optional[float] = None) -> list[int]:
    now = now or time.time()
    queued = []
    for w in conn.execute("SELECT * FROM watches WHERE active=1").fetchall():
        bar = last_closed_bar_open(w["timeframe"], now, s.watch_delay_s)
        if w["last_bar_scheduled"] == bar:
            continue
        busy = conn.execute("SELECT 1 FROM lab_jobs WHERE kind='watch_eval' AND ref_id=? AND status IN "
                            "('queued','running')", (w["id"],)).fetchone()
        if busy:
            continue
        jid = q.enqueue(conn, "watch_eval", w["id"], {"bar": bar}, priority=10)
        conn.execute("UPDATE watches SET last_bar_scheduled=? WHERE id=?", (bar, w["id"]))
        conn.commit()
        queued.append(jid)
    return queued


def check_paper(conn, s: LabSettings, market=None) -> int:
    """SL/TP + funding for every open paper position. Returns positions closed."""
    if market is None:
        from . import market as market  # noqa: PLW0127
    rows = [dict(r) for r in conn.execute("SELECT * FROM paper_positions WHERE status='open'")]
    closed = 0
    by_symbol: dict[str, list[dict]] = {}
    for r in rows:
        by_symbol.setdefault(r["symbol"], []).append(r)
    for sym, positions in by_symbol.items():
        try:
            start = min((p["last_checked_bar"] or p["entry_time"]) for p in positions)
            since_ms = int(datetime.fromisoformat(start[:19]).replace(tzinfo=timezone.utc).timestamp() * 1000)
            candles = market.closed_klines(sym, PAPER_TF, since_ms)
            fund_since = min((p["last_funding_at"] or p["entry_time"]) for p in positions)
            f_ms = int(datetime.fromisoformat(fund_since[:19]).replace(tzinfo=timezone.utc).timestamp() * 1000)
            events = [{**e, "t": _iso(e["ts"] / 1000)} for e in market.funding_history(sym, f_ms + 1)]
        except Exception as e:  # noqa: BLE001
            log.warning("paper check: market data for %s failed: %s", sym, e)
            continue
        for p in positions:
            try:
                paper.apply_funding(conn, p["id"], [e for e in events if e["ts"] <= time.time() * 1000])
                if paper.check_candles(conn, p["id"], candles) is not None:
                    closed += 1
            except Exception:  # noqa: BLE001
                log.exception("paper check failed for position %s", p["id"])
    return closed


def import_bot_trades(conn, s: LabSettings) -> int:
    """Copy CLOSED live-bot positions into journal_entries (source='bot'). Read-only."""
    path = s.trading_db_path
    if not path or not Path(path).exists():
        return 0
    last = conn.execute("SELECT value FROM lab_kv WHERE key='bot_import_closed_at'").fetchone()
    since = last["value"] if last else ""
    src = sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=2.0)
    try:
        src.execute("PRAGMA query_only=1")
        cols = {r[1] for r in src.execute("PRAGMA table_info(positions)")}
        qty_col = "COALESCE(quantity, size)" if "quantity" in cols else "size"
        exit_col = "exit_price" if "exit_price" in cols else "NULL"
        rows = src.execute(
            f"SELECT id, user_id, symbol, side, {qty_col}, entry_price, {exit_col}, created_at, closed_at "
            "FROM positions WHERE status='closed' AND closed_at IS NOT NULL AND closed_at > ? "
            "ORDER BY closed_at LIMIT 500", (since,)).fetchall()
    finally:
        src.close()
    n = 0
    for pid, uid, sym, side, qty, entry, exit_, opened, closed in rows:
        side = (side or "").lower()
        side = "long" if side in ("long", "buy") else "short" if side in ("short", "sell") else side
        pnl = None
        if qty and entry and exit_:
            pnl = (float(exit_) - float(entry)) * float(qty) * (1 if side == "long" else -1)
        cur = conn.execute(
            "INSERT OR IGNORE INTO journal_entries (account_id, source, external_id, symbol, side, entry_time, "
            "entry_price, exit_time, exit_price, qty, pnl, r_multiple, exit_reason, tags, created_at) "
            "VALUES (NULL, 'bot', ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, 'bot_close', ?, ?)",
            (str(pid), str(sym).replace("/", "").split(":")[0], side, opened, entry, closed, exit_, qty, pnl,
             dumps([f"user:{str(uid)[:8]}"]), utcnow()))
        n += cur.rowcount
        since = max(since, closed)
    if rows:
        conn.execute("INSERT INTO lab_kv (key, value) VALUES ('bot_import_closed_at', ?) "
                     "ON CONFLICT(key) DO UPDATE SET value=excluded.value", (since,))
    conn.commit()
    return n


class Scheduler:
    def __init__(self, settings: LabSettings):
        self.s = settings
        self._last_paper = 0.0
        self._last_bot = 0.0

    def tick(self, conn) -> None:
        now = time.time()
        schedule_watches(conn, self.s, now)
        if now - self._last_paper >= 60:
            self._last_paper = now
            try:
                check_paper(conn, self.s)
            except Exception:  # noqa: BLE001
                log.exception("paper check failed")
        if now - self._last_bot >= self.s.bot_import_interval_s:
            self._last_bot = now
            try:
                n = import_bot_trades(conn, self.s)
                if n:
                    log.info("imported %d bot trades into the journal", n)
            except Exception:  # noqa: BLE001
                log.exception("bot trade import failed")
