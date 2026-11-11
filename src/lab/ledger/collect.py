"""Collectors for non-screener sources (stdlib only). Idempotent: every run rescans
its source and relies on ``ledger_signals.dedupe_key`` to skip what is already there.
"""
from __future__ import annotations

import logging
import sqlite3
from pathlib import Path
from typing import Optional

from ..db import loads
from .store import ensure_schema, insert_signal, iso, norm_symbol, to_epoch

log = logging.getLogger("lab.ledger.collect")

WEBHOOK_MERGE_S = 600          # one TradingView alert fans out to N users: merge same symbol+side within 10 min


def _dir(side: Optional[str]) -> int:
    s = (side or "").lower()
    return 1 if s in ("long", "buy") else -1 if s in ("short", "sell") else 0


def collect_lab_watches(conn) -> int:
    """Entries of every Lab watch that happened at/after the watch was created.

    watch_state holds the engine's re-computation over ~1000 bars before creation as well;
    those earlier trades are a backtest, not a recorded live signal, so they are skipped.
    """
    n = 0
    rows = conn.execute(
        "SELECT w.id, w.template_id, w.symbol, w.timeframe, w.created_at, s.recent_trades_json, s.position_json "
        "FROM watches w JOIN watch_state s ON s.watch_id = w.id").fetchall()
    for r in rows:
        created = to_epoch(r["created_at"])
        stype = f"{r['template_id']}_{r['timeframe']}"
        entries = []
        for t in loads(r["recent_trades_json"], []) or []:
            entries.append((t.get("entry_time"), t.get("side"), t.get("entry_price"),
                            {"exit_time": t.get("exit_time"), "exit_reason": t.get("exit_reason"),
                             "engine_pnl_pct": t.get("pnl_pct")}))
        pos = loads(r["position_json"])
        if pos:
            entries.append((pos.get("entry_time"), pos.get("side"), pos.get("entry_price"),
                            {"open": True, "sl": pos.get("sl"), "tp": pos.get("tp")}))
        for et, side, px, meta in entries:
            d = _dir(side)
            if not et or not d:
                continue
            # entry_time = open of the fill bar (= close of the signal bar). Anything before the
            # watch existed was never observed live.
            if to_epoch(et) < created:
                continue
            ok = insert_signal(conn, source="lab_watch", signal_type=stype, symbol=r["symbol"], direction=d,
                               ts=iso(to_epoch(et)), ref=f"watch:{r['id']}", price=px,
                               meta={"watch_id": r["id"], "timeframe": r["timeframe"], **meta},
                               dedupe_key=f"lab_watch|{r['id']}|{iso(to_epoch(et))}|{d}")
            n += int(ok)
    conn.commit()
    return n


def collect_universal(conn) -> int:
    """A coin entering a Universal watch's target book, or flipping side, at a rebalance."""
    n = 0
    prev: dict[int, dict[str, int]] = {}
    for r in conn.execute("SELECT id, watch_id, bar, targets_json FROM universal_rebalances ORDER BY watch_id, id"):
        targets = {norm_symbol(t["symbol"]): (1 if t["weight_pct"] > 0 else -1)
                   for t in loads(r["targets_json"], []) or [] if t.get("weight_pct")}
        before = prev.get(r["watch_id"], {})
        weights = {norm_symbol(t["symbol"]): t.get("weight_pct") for t in loads(r["targets_json"], []) or []}
        for sym, d in targets.items():
            if before.get(sym) == d:
                continue
            ok = insert_signal(conn, source="universal", signal_type="universal_v0", symbol=sym, direction=d,
                               ts=iso(to_epoch(r["bar"])), ref=f"universal:{r['watch_id']}",
                               meta={"watch_id": r["watch_id"], "weight_pct": weights.get(sym),
                                     "flip": sym in before, "rebalance_id": r["id"]},
                               dedupe_key=f"universal|{r['watch_id']}|{r['bar']}|{sym}|{d}")
            n += int(ok)
        prev[r["watch_id"]] = targets
    conn.commit()
    return n


def collect_webhook(conn, trading_db_path: str) -> int:
    """TradingView 'open' alerts from bmtm_trading.db trade_logs (read-only, short query).

    Every alert is a signal whatever happened to the order (success / failed / rejected);
    the statuses are kept in meta. Rows for several users within 10 minutes with the same
    symbol + side are one alert. 'close' alerts are not directional predictions: skipped.
    """
    if not trading_db_path or not Path(trading_db_path).exists():
        return 0
    since = conn.execute("SELECT value FROM lab_kv WHERE key='ledger_webhook_since'").fetchone()
    since = since[0] if since else ""
    src = sqlite3.connect(f"file:{trading_db_path}?mode=ro", uri=True, timeout=2.0)
    try:
        src.execute("PRAGMA query_only=1")
        cols = {r[1] for r in src.execute("PRAGMA table_info(trade_logs)")}
        if not cols:
            return 0
        rows = src.execute(
            "SELECT id, user_id, symbol, action, side, status, fill_price, created_at FROM trade_logs "
            "WHERE created_at > ? ORDER BY created_at LIMIT 5000", (since,)).fetchall()
    finally:
        src.close()
    n = 0
    groups: list[dict] = []
    for _id, uid, sym, action, side, status, fill, created in rows:
        if (action or "").lower() != "open" or not _dir(side):
            continue
        t = to_epoch(created)
        key = (norm_symbol(sym), _dir(side))
        g = next((g for g in groups if g["key"] == key and t - g["t0"] <= WEBHOOK_MERGE_S), None)
        if g is None:
            g = {"key": key, "t0": t, "statuses": [], "users": set(), "price": None}
            groups.append(g)
        g["statuses"].append(status)
        g["users"].add(str(uid or "")[:8])
        if fill and g["price"] is None:
            g["price"] = float(fill)
    for g in groups:
        sym, d = g["key"]
        # bucket the dedupe key to the merge window so a later re-scan maps onto the same alert
        bucket = int(g["t0"] // WEBHOOK_MERGE_S)
        prev = conn.execute("SELECT 1 FROM ledger_signals WHERE source='webhook' AND symbol=? AND direction=? AND "
                            "dedupe_key IN (?, ?)",
                            (sym, d, f"webhook|{sym}|{d}|{bucket}", f"webhook|{sym}|{d}|{bucket - 1}")).fetchone()
        if prev:
            continue
        ok = insert_signal(conn, source="webhook", signal_type="tv_open", symbol=sym, direction=d,
                           ts=iso(g["t0"]), ref="tradingview", price=g["price"],
                           meta={"users": len(g["users"]), "statuses": sorted(set(g["statuses"])),
                                 "rows": len(g["statuses"])},
                           dedupe_key=f"webhook|{sym}|{d}|{bucket}")
        n += int(ok)
    if rows:
        last = max(r[7] for r in rows)
        conn.execute("INSERT INTO lab_kv (key, value) VALUES ('ledger_webhook_since', ?) "
                     "ON CONFLICT(key) DO UPDATE SET value=excluded.value", (last,))
    conn.commit()
    return n


def collect_all(conn, trading_db_path: str) -> dict:
    ensure_schema(conn)
    out = {}
    for name, fn in (("lab_watch", lambda: collect_lab_watches(conn)), ("universal", lambda: collect_universal(conn)),
                     ("webhook", lambda: collect_webhook(conn, trading_db_path))):
        try:
            out[name] = fn()
        except Exception as e:  # noqa: BLE001
            log.exception("ledger collect %s failed", name)
            out[name] = f"error: {type(e).__name__}: {e}"
    return out
