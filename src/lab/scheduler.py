"""Scheduler hooks run inside the lab worker's main loop (never in the API).

  * watches: ~LAB_WATCH_DELAY_S after every candle close of a watch's own timeframe
             (15m/30m/1h/4h/1d), ONE batched watch_eval job per (timeframe, bar) for
             all due watches (chunks of WATCH_BATCH_MAX); a watch whose previous job
             is still queued/running is skipped and picked up on the next tick
  * paper:   every minute, check open paper positions against closed 1m candles
             (SL/TP, engine intrabar rule), charge funding settlements, refresh marks
  * universe: one universe_refresh job per closed 4H bar (Koin Terkuat + Universal watches)
  * outlook: one outlook_refresh job per closed 4H bar, after that bar's universe_refresh (Outlook Koin)
  * alerts:  every 30 s, deliver pending Telegram alerts (rate-limited, see universal/alerts.py)
  * ledger:  one ledger_cycle job per closed hour + a one-off ledger_backfill (Catatan Sinyal)
  * shadow:  shadow_cycle when trade_logs changes / a signal is due / hourly (Kualitas eksekusi)
  * arena:   one arena_snapshot job per hour (paper equity snapshots for Arena Paper)
  * live check: livecheck_cycle after every 4H close + hourly (Cek bot live vs strategi)
  * weekly:  Laporan Mingguan snapshot each Monday 00:30 UTC + deploy-log notifications (weekly/schedule.py)
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
from .data_cache import TF_SECONDS
from .db import dumps, loads, utcnow
from .settings import LabSettings

log = logging.getLogger("lab.scheduler")

PAPER_TF = "1m"
WATCH_BATCH_MAX = 25   # watches per watch_eval job (one engine child, one data refresh per symbol)


def _iso(epoch: float) -> str:
    return datetime.fromtimestamp(epoch, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def last_closed_bar_open(tf: str, now: float, delay_s: int) -> Optional[str]:
    """Open time of the newest bar that closed at least delay_s ago."""
    step = TF_SECONDS[tf]
    t = now - delay_s
    last_close = t - t % step            # most recent bar boundary <= t
    return _iso(last_close - step)


def _busy_watch_ids(conn) -> set[int]:
    """Watches covered by a queued/running watch_eval job (single or batched)."""
    busy: set[int] = set()
    for j in conn.execute("SELECT ref_id, payload_json FROM lab_jobs WHERE kind='watch_eval' "
                          "AND status IN ('queued','running')"):
        ids = (loads(j["payload_json"], {}) or {}).get("watch_ids")
        if ids:
            busy.update(int(i) for i in ids)
        else:
            busy.add(j["ref_id"])
    return busy


def schedule_watches(conn, s: LabSettings, now: Optional[float] = None) -> list[int]:
    now = now or time.time()
    busy = _busy_watch_ids(conn)
    due: dict[tuple[str, str], list[int]] = {}
    for w in conn.execute("SELECT id, timeframe, last_bar_scheduled FROM watches WHERE active=1 ORDER BY id"):
        if w["timeframe"] not in TF_SECONDS:
            continue
        bar = last_closed_bar_open(w["timeframe"], now, s.watch_delay_s)
        if w["last_bar_scheduled"] == bar or w["id"] in busy:
            continue
        due.setdefault((w["timeframe"], bar), []).append(w["id"])
    queued = []
    for (tf, bar), ids in due.items():
        for k in range(0, len(ids), WATCH_BATCH_MAX):
            chunk = ids[k:k + WATCH_BATCH_MAX]
            jid = q.enqueue(conn, "watch_eval", chunk[0], {"bar": bar, "timeframe": tf, "watch_ids": chunk},
                            priority=10)
            conn.executemany("UPDATE watches SET last_bar_scheduled=? WHERE id=?", [(bar, i) for i in chunk])
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


def schedule_universe(conn, s: LabSettings, now: Optional[float] = None) -> Optional[int]:
    """One universe_refresh job per closed 4H bar (Koin Terkuat + Universal watches)."""
    now = now or time.time()
    has_watch = conn.execute("SELECT 1 FROM universal_watches WHERE active=1 LIMIT 1").fetchone()
    if not (s.strength_refresh or has_watch):
        return None
    bar = last_closed_bar_open("4h", now, s.watch_delay_s)
    row = conn.execute("SELECT value FROM lab_kv WHERE key='universe_refresh_bar'").fetchone()
    if row and row["value"] == bar:
        return None
    busy = conn.execute("SELECT 1 FROM lab_jobs WHERE kind='universe_refresh' AND status IN ('queued','running')"
                        ).fetchone()
    if busy:
        return None
    jid = q.enqueue(conn, "universe_refresh", None, {"bar": bar}, priority=10)
    conn.execute("INSERT INTO lab_kv (key, value) VALUES ('universe_refresh_bar', ?) "
                 "ON CONFLICT(key) DO UPDATE SET value=excluded.value", (bar,))
    conn.commit()
    return jid


class Scheduler:
    def __init__(self, settings: LabSettings):
        self.s = settings
        self._last_paper = 0.0
        self._last_bot = 0.0
        self._last_alerts = 0.0
        self._last_ledger = 0.0

    def tick(self, conn) -> None:
        now = time.time()
        schedule_watches(conn, self.s, now)
        try:
            schedule_universe(conn, self.s, now)
        except Exception:  # noqa: BLE001
            log.exception("universe refresh scheduling failed")
        try:
            from .outlook.schedule import tick as outlook_tick
            outlook_tick(conn, self.s, now)
        except Exception:  # noqa: BLE001
            log.exception("outlook scheduling failed")
        if now - self._last_ledger >= 30:
            self._last_ledger = now
            try:
                from .ledger.schedule import tick as ledger_tick
                ledger_tick(conn, self.s, now)
            except Exception:  # noqa: BLE001
                log.exception("signal ledger scheduling failed")
            try:
                from .shadow.schedule import tick as shadow_tick
                shadow_tick(conn, self.s, now)
            except Exception:  # noqa: BLE001
                log.exception("shadow execution scheduling failed")
            try:
                from .arena.schedule import tick as arena_tick
                arena_tick(conn, self.s, now)
            except Exception:  # noqa: BLE001
                log.exception("arena snapshot scheduling failed")
            try:
                from .livecheck.schedule import tick as livecheck_tick
                livecheck_tick(conn, self.s, now)
            except Exception:  # noqa: BLE001
                log.exception("live check scheduling failed")
        if now - self._last_alerts >= 30:
            self._last_alerts = now
            try:
                from .universal.alerts import send_pending
                send_pending(conn, self.s)
            except Exception:  # noqa: BLE001
                log.exception("alert delivery failed")
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
        if now - getattr(self, "_last_weekly", 0.0) >= 60:
            self._last_weekly = now
            try:  # Laporan Mingguan snapshot (Mon 00:30 UTC) + deploy-log notifications
                from .weekly.schedule import tick as weekly_tick
                weekly_tick(conn, self.s, now)
            except Exception:  # noqa: BLE001
                log.exception("weekly report hook failed")
