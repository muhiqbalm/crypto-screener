"""Forward-return scoring of ledger signals (stdlib only).

Price path = Binance USD-M 15m klines. For a signal at time ``ts``:

  * entry  = open of the first 15m bar opening at/after ``ts - ENTRY_TOLERANCE_S``
             (90 s tolerance so a signal computed seconds after a bar boundary uses that
             bar's open; anything later waits for the next bar — no look-back fills)
  * exit_H = close of the 15m bar that ends exactly at entry_open + H
  * ret    = exit / entry - 1; dir_ret = direction * ret; hit = dir_ret > 0
  * BTC    = BTC's return over the identical window; rel_btc = direction * (ret - btc_ret)
  * MFE / MAE = best / worst excursion (direction-aware) of 15m highs/lows inside the window

No fees, funding or slippage are deducted (this measures the signal, not a strategy).
"""
from __future__ import annotations

import bisect
import logging
import time
from typing import Callable, Optional

from ..db import utcnow
from . import HORIZONS
from .store import ensure_schema, iso, to_epoch

log = logging.getLogger("lab.ledger.scoring")

BAR_S = 900
ENTRY_TOLERANCE_S = 90
GIVE_UP_S = 2 * 86400          # mark a horizon no_data when its bar is still missing this long after it closed
BTC = "BTCUSDT"

Candles = list[dict]           # [{"ts": open_ms, "o","h","l","c"}] sorted by ts
FetchFn = Callable[[str, int, int], Candles]   # (symbol, start_ms, end_ms) -> candles (closed bars only)


class Path:
    """Index over a candle list: open-time lookup + sorted opens for bisect."""

    def __init__(self, candles: Candles):
        self.rows = sorted(candles, key=lambda c: c["ts"])
        self.opens = [c["ts"] // 1000 for c in self.rows]
        self.by_open = {o: i for i, o in enumerate(self.opens)}

    def first_at_or_after(self, t_s: float) -> Optional[int]:
        i = bisect.bisect_left(self.opens, t_s)
        return i if i < len(self.opens) else None

    def last_at_or_before(self, t_s: float) -> Optional[int]:
        i = bisect.bisect_right(self.opens, t_s) - 1
        return i if i >= 0 else None


def _pct(a: float, b: float) -> float:
    return (a / b - 1.0) * 100.0


def outcome(direction: int, path: Path, i_entry: int, horizon_s: int, now_s: float,
            btc: Optional[Path] = None, is_btc: bool = False) -> Optional[dict]:
    """Outcome for one horizon. None = not available yet; {'ret_pct': None,...} = gave up (no data)."""
    e_open = path.opens[i_entry]
    target_open = e_open + horizon_s - BAR_S        # bar whose close is entry + H
    if e_open + horizon_s > now_s:
        return None
    j = path.by_open.get(target_open)
    if j is None:
        # gap in the data (exchange outage / delisting): accept a bar up to 1 h earlier
        k = path.last_at_or_before(target_open)
        if k is not None and k >= i_entry and target_open - path.opens[k] <= 3600:
            j = k
    if j is None:
        if now_s - (e_open + horizon_s) > GIVE_UP_S:
            return {"exit_ts": None, "exit_price": None, "ret_pct": None, "dir_ret_pct": None, "btc_ret_pct": None,
                    "rel_btc_pct": None, "mfe_pct": None, "mae_pct": None, "hit": None}
        return None
    entry = path.rows[i_entry]["o"]
    exit_px = path.rows[j]["c"]
    window = path.rows[i_entry: j + 1]
    hi = max(c["h"] for c in window)
    lo = min(c["l"] for c in window)
    ret = _pct(exit_px, entry)
    if direction > 0:
        mfe, mae = _pct(hi, entry), _pct(lo, entry)
    else:
        mfe, mae = -_pct(lo, entry), -_pct(hi, entry)
    btc_ret = None
    if is_btc:
        btc_ret = ret
    elif btc is not None:
        a, b = btc.by_open.get(e_open), btc.by_open.get(path.opens[j])
        if a is not None and b is not None:
            btc_ret = _pct(btc.rows[b]["c"], btc.rows[a]["o"])
    dir_ret = direction * ret
    return {
        "exit_ts": iso(path.opens[j] + BAR_S), "exit_price": exit_px, "ret_pct": ret, "dir_ret_pct": dir_ret,
        "btc_ret_pct": btc_ret, "rel_btc_pct": None if btc_ret is None else direction * (ret - btc_ret),
        "mfe_pct": max(0.0, mfe), "mae_pct": min(0.0, mae), "hit": 1 if dir_ret > 0 else 0,
    }


def score_signal(sig: dict, path: Path, btc: Optional[Path], now_s: float, done_h: set[str]) -> dict:
    """Returns {"entry": (ts, price) | None, "outcomes": {h: dict}, "complete": bool, "no_data": bool}."""
    ts = to_epoch(sig["ts"])
    i = path.first_at_or_after(ts - ENTRY_TOLERANCE_S)
    if i is None or path.opens[i] - ts > 86400:
        stale = now_s - ts > GIVE_UP_S
        return {"entry": None, "outcomes": {}, "complete": stale, "no_data": stale}
    out = {}
    for h, sec in HORIZONS.items():
        if h in done_h:
            continue
        o = outcome(sig["direction"], path, i, sec, now_s, btc, is_btc=sig["symbol"] == BTC)
        if o is not None:
            out[h] = o
    complete = len(done_h) + len(out) == len(HORIZONS)
    return {"entry": (iso(path.opens[i]), path.rows[i]["o"]), "outcomes": out, "complete": complete,
            "no_data": False}


def _write(conn, sig_id: int, res: dict) -> None:
    now = utcnow()
    for h, o in res["outcomes"].items():
        conn.execute(
            "INSERT OR REPLACE INTO ledger_outcomes (signal_id, horizon, exit_ts, exit_price, ret_pct, dir_ret_pct, "
            "btc_ret_pct, rel_btc_pct, mfe_pct, mae_pct, hit, computed_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            (sig_id, h, o["exit_ts"], o["exit_price"], o["ret_pct"], o["dir_ret_pct"], o["btc_ret_pct"],
             o["rel_btc_pct"], o["mfe_pct"], o["mae_pct"], o["hit"], now))
    if res["entry"]:
        conn.execute("UPDATE ledger_signals SET entry_ts=?, entry_price=? WHERE id=?", (*res["entry"], sig_id))
    if res["complete"]:
        conn.execute("UPDATE ledger_signals SET status=? WHERE id=?", ("no_data" if res["no_data"] else "done", sig_id))


def score_pending(conn, fetch: FetchFn, now_s: Optional[float] = None, limit: int = 20000,
                  sleep_s: float = 0.0) -> dict:
    """Fill outcomes for every pending signal whose horizons have closed. Returns counters."""
    ensure_schema(conn)
    now_s = now_s or time.time()
    rows = [dict(r) for r in conn.execute(
        "SELECT id, symbol, direction, ts FROM ledger_signals WHERE status='pending' ORDER BY symbol, ts LIMIT ?",
        (limit,))]
    if not rows:
        return {"pending": 0, "scored": 0, "completed": 0, "errors": 0}
    done: dict[int, set[str]] = {}
    ids = [r["id"] for r in rows]
    for k in range(0, len(ids), 500):
        chunk = ids[k:k + 500]
        for sid, h in conn.execute(
                f"SELECT signal_id, horizon FROM ledger_outcomes WHERE signal_id IN ({','.join('?' * len(chunk))})",
                chunk):
            done.setdefault(sid, set()).add(h)
    max_h = max(HORIZONS.values())
    by_sym: dict[str, list[dict]] = {}
    for r in rows:
        by_sym.setdefault(r["symbol"], []).append(r)

    def span(sigs: list[dict]) -> tuple[int, int]:
        lo = min(to_epoch(s["ts"]) for s in sigs) - 3600
        hi = min(now_s, max(to_epoch(s["ts"]) for s in sigs) + max_h + 3600)
        return int(lo * 1000), int(hi * 1000)

    btc_path = None
    try:
        a, b = span(rows)
        btc_path = Path(fetch(BTC, a, b))
    except Exception as e:  # noqa: BLE001
        log.warning("ledger scoring: BTC candles failed: %s", e)
    scored = completed = errors = 0
    for sym, sigs in by_sym.items():
        try:
            if sym == BTC and btc_path is not None:
                path = btc_path
            else:
                a, b = span(sigs)
                path = Path(fetch(sym, a, b))
                if sleep_s:
                    time.sleep(sleep_s)
        except Exception as e:  # noqa: BLE001
            errors += 1
            unknown = getattr(e, "unknown_symbol", False)
            log.warning("ledger scoring: candles for %s failed: %s", sym, e)
            if unknown:
                for s in sigs:
                    conn.execute("UPDATE ledger_signals SET status='no_data' WHERE id=?", (s["id"],))
                conn.commit()
            continue
        for s in sigs:
            res = score_signal(s, path, btc_path, now_s, done.get(s["id"], set()))
            if res["outcomes"] or res["entry"] or res["complete"]:
                _write(conn, s["id"], res)
            scored += len(res["outcomes"])
            completed += int(res["complete"])
        conn.commit()
    return {"pending": len(rows), "scored": scored, "completed": completed, "errors": errors}


def outcome_rows(conn, signal_ids: list[int]) -> dict[int, dict]:
    out: dict[int, dict] = {}
    for k in range(0, len(signal_ids), 500):
        chunk = signal_ids[k:k + 500]
        if not chunk:
            continue
        for r in conn.execute(
                f"SELECT * FROM ledger_outcomes WHERE signal_id IN ({','.join('?' * len(chunk))})", chunk):
            d = dict(r)
            sid = d.pop("signal_id")
            h = d.pop("horizon")
            d.pop("computed_at", None)
            out.setdefault(sid, {})[h] = d
    return out

