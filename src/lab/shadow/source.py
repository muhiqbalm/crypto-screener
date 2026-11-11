"""Live webhook signals from bmtm_trading.db ``trade_logs`` (read-only, stdlib).

Separate ``mode=ro`` connection with ``PRAGMA query_only``; only the columns needed
here are selected (never passphrases, keys or e-mails; user ids are only counted).

Written defensively against both the current schema (one row per user, written
AFTER the order attempt, so ``created_at`` is an upper bound for the arrival time)
and a future one that may add explicit timing columns or write a row on receipt
and update it later (non-final statuses keep the signal open for re-reading).
"""
from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Optional

from ..ledger.store import iso, norm_symbol, to_epoch

TF_S = {"15m": 900, "1h": 3600, "4h": 14400, "1d": 86400}

# Optional columns, first present wins. created_at is always there.
ARRIVAL_COLS = ("received_at", "webhook_received_at", "alert_received_at", "request_received_at", "signal_received_at")
FILL_TS_COLS = ("filled_at", "executed_at", "order_filled_at", "fill_time", "completed_at")
FILL_PX_COLS = ("fill_price", "avg_fill_price", "avg_price", "executed_price")
FILL_QTY_COLS = ("filled_quantity", "filled_qty", "executed_qty")
FILLED_STATUSES = {"success", "filled", "ok", "done", "executed"}
NONFINAL_STATUSES = {"pending", "queued", "accepted", "processing", "received", "submitted", "running"}


def trade_dir(action: str, side: str) -> int:
    """+1 = the order buys, -1 = it sells. Open long / close short buy; open short / close long sell."""
    a, s = (action or "").lower(), (side or "").lower()
    base = 1 if s in ("long", "buy") else -1 if s in ("short", "sell") else 0
    if a == "close":
        return -base
    return base if a == "open" else 0


def _first(cols: set[str], names: tuple) -> Optional[str]:
    return next((c for c in names if c in cols), None)


def read_trade_logs(trading_db_path: str, limit: int = 20000) -> list[dict]:
    """Rows as dicts with normalised keys; [] when the DB / table is missing."""
    if not trading_db_path or not Path(trading_db_path).exists():
        return []
    src = sqlite3.connect(f"file:{trading_db_path}?mode=ro", uri=True, timeout=2.0)
    try:
        src.execute("PRAGMA query_only=1")
        cols = {r[1] for r in src.execute("PRAGMA table_info(trade_logs)")}
        if not {"symbol", "action", "side", "created_at"} <= cols:
            return []
        pick = {
            "user_id": "user_id" if "user_id" in cols else None,
            "status": "status" if "status" in cols else None,
            "arrival": _first(cols, ARRIVAL_COLS),
            "fill_ts": _first(cols, FILL_TS_COLS),
            "fill_px": _first(cols, FILL_PX_COLS),
            "fill_qty": _first(cols, FILL_QTY_COLS),
        }
        sel = ["symbol", "action", "side", "created_at"] + [f"{c} AS {k}" for k, c in pick.items() if c]
        rows = src.execute(f"SELECT {', '.join(sel)} FROM trade_logs ORDER BY created_at LIMIT ?", (limit,))
        names = [d[0] for d in rows.description]
        out = []
        for r in rows.fetchall():
            d = dict(zip(names, r))
            d["_arrival_col"] = pick["arrival"]
            d["_fill_ts_col"] = pick["fill_ts"]
            out.append(d)
        return out
    finally:
        src.close()


def _epoch(v) -> Optional[float]:
    if v in (None, ""):
        return None
    if isinstance(v, (int, float)):
        return float(v) / (1000.0 if v > 1e11 else 1.0)
    try:
        return to_epoch(str(v))
    except ValueError:
        return None


def group_signals(rows: list[dict], tf: str = "4h", off_close_s: int = 1800) -> list[dict]:
    """One signal per (symbol, action, side, signal bar). The bar is the one whose close is the
    latest boundary at/before the arrival; alerts fan out to every user within seconds."""
    step = TF_S[tf]
    groups: dict[str, dict] = {}
    for r in rows:
        d = trade_dir(r.get("action"), r.get("side"))
        created = _epoch(r.get("created_at"))
        if not d or created is None:
            continue
        arr = _epoch(r.get("arrival")) if r.get("arrival") is not None else None
        t = min(x for x in (arr, created) if x is not None)
        bar_close = t - t % step
        sym = norm_symbol(r.get("symbol"))
        key = f"{sym}|{r['action'].lower()}|{r['side'].lower()}|{iso(bar_close)}"
        g = groups.setdefault(key, {
            "key": key, "symbol": sym, "action": r["action"].lower(), "side": r["side"].lower(), "trade_dir": d,
            "tf": tf, "bar_close_s": bar_close, "arrival_s": t,
            "arrival_basis": r["_arrival_col"] if arr is not None and arr <= created else "created_at",
            "log_s": created, "statuses": [], "users": set(), "fills": [], "fill_ts": [],
            "fill_ts_basis": r.get("_fill_ts_col"),
        })
        if t < g["arrival_s"]:
            g["arrival_s"] = t
            g["arrival_basis"] = r["_arrival_col"] if arr is not None and arr <= created else "created_at"
        g["log_s"] = min(g["log_s"], created)
        status = (r.get("status") or "").lower()
        g["statuses"].append(status)
        if r.get("user_id") is not None:
            g["users"].add(str(r["user_id"]))
        px = r.get("fill_px")
        try:
            px = float(px) if px not in (None, "") else None
        except (TypeError, ValueError):
            px = None
        if px and px > 0 and (status in FILLED_STATUSES or not status):
            try:
                qty = float(r.get("fill_qty") or 0) or 1.0
            except (TypeError, ValueError):
                qty = 1.0
            g["fills"].append((px, qty))
            ft = _epoch(r.get("fill_ts"))
            if ft is not None:
                g["fill_ts"].append(ft)
    out = []
    for g in groups.values():
        qty = sum(q for _, q in g["fills"])
        fill_px = sum(p * q for p, q in g["fills"]) / qty if qty else None
        out.append({
            "key": g["key"], "symbol": g["symbol"], "action": g["action"], "side": g["side"],
            "trade_dir": g["trade_dir"], "tf": tf, "bar_close_s": g["bar_close_s"], "arrival_s": g["arrival_s"],
            "arrival_basis": g["arrival_basis"], "log_s": g["log_s"],
            "off_close": int(g["arrival_s"] - g["bar_close_s"] > off_close_s),
            "n_rows": len(g["statuses"]), "n_users": len(g["users"]) or None,
            "statuses": sorted(set(s for s in g["statuses"] if s)),
            "final": not any(s in NONFINAL_STATUSES for s in g["statuses"]),
            "fill_price": fill_px, "fill_qty": qty if g["fills"] else None,
            "fill_s": min(g["fill_ts"]) if g["fill_ts"] else None,
            "fill_ts_basis": g["fill_ts_basis"] if g["fill_ts"] else None,
        })
    out.sort(key=lambda s: s["arrival_s"])
    return out
