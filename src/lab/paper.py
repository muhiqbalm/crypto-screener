"""Paper (simulated) trading. No real orders, no API keys.

Stdlib only. Prices come from callers (src.lab.market). Accounting:
  * fill = price +/- slippage (adverse), commission 0.05% per side on notional
  * balance changes only when a position closes: pnl = gross - fees - funding
  * SL/TP checked on closed candles with the engine's intrabar rule
    (bmtm-v2 strategy/order_manager.py): trigger on high/low, fill at the level
    or at the open on a gap; if both hit, the level nearer the open wins
  * funding charged at each settlement (00/08/16 UTC): qty * mark * rate,
    long pays positive rates
Every closed position is written to journal_entries.
"""
from __future__ import annotations

import sqlite3
from typing import Optional

from .db import dumps, utcnow

COMMISSION_PCT = 0.05
DEFAULT_SLIPPAGE_PCT = 0.05


class PaperError(ValueError):
    pass


def _slip(price: float, side: str, action: str, slippage_pct: float) -> float:
    buying = (side == "long") == (action == "entry")
    s = slippage_pct / 100.0
    return price * (1 + s) if buying else price * (1 - s)


def create_account(conn: sqlite3.Connection, name: str, starting_balance: float = 10000.0,
                   risk_pct: float = 0.5, leverage_max: float = 5.0) -> int:
    cur = conn.execute(
        "INSERT INTO paper_accounts (name, starting_balance, balance, risk_pct, leverage_max, realized_pnl, "
        "created_at) VALUES (?, ?, ?, ?, ?, 0, ?)",
        (name, starting_balance, starting_balance, risk_pct, leverage_max, utcnow()))
    conn.commit()
    return int(cur.lastrowid)


def get_account(conn, account_id: int) -> dict:
    row = conn.execute("SELECT * FROM paper_accounts WHERE id=?", (account_id,)).fetchone()
    if row is None:
        raise PaperError("paper account not found")
    return dict(row)


def unrealized(pos: dict, price: Optional[float]) -> float:
    if price is None:
        return 0.0
    d = 1.0 if pos["side"] == "long" else -1.0
    return (price - pos["entry_price"]) * pos["qty"] * d


def account_summary(conn, account_id: int) -> dict:
    a = get_account(conn, account_id)
    pos = [dict(r) for r in conn.execute(
        "SELECT * FROM paper_positions WHERE account_id=? AND status='open' ORDER BY id", (account_id,))]
    upnl = sum(unrealized(p, p["mark_price"]) - p["fees"] - p["funding"] for p in pos)
    return {
        "id": a["id"], "name": a["name"], "balance": a["balance"], "equity": a["balance"] + upnl,
        "starting_balance": a["starting_balance"], "realized_pnl": a["realized_pnl"],
        "risk_pct": a["risk_pct"], "leverage_max": a["leverage_max"], "created_at": a["created_at"],
        "open_positions": [position_out(p) for p in pos],
    }


def position_out(p: dict) -> dict:
    return {"id": p["id"], "account_id": p["account_id"], "symbol": p["symbol"], "side": p["side"],
            "entry_price": p["entry_price"], "qty": p["qty"], "sl": p["sl"], "tp": p["tp"],
            "entry_time": p["entry_time"], "watch_id": p["watch_id"], "source": p["source"],
            "fees": p["fees"], "funding": p["funding"], "risk_amount": p["risk_amount"],
            "mark_price": p["mark_price"], "unrealized_pnl": unrealized(p, p["mark_price"]) if p["mark_price"]
            else None, "note": p["note"], "status": p["status"]}


def open_position(conn, *, account_id: int, symbol: str, side: str, price: float, sl: float,
                  tp: Optional[float] = None, qty: Optional[float] = None, note: Optional[str] = None,
                  watch_id: Optional[int] = None, source: str = "paper_manual",
                  slippage_pct: float = DEFAULT_SLIPPAGE_PCT, when: Optional[str] = None) -> dict:
    if side not in ("long", "short"):
        raise PaperError("side must be long or short")
    a = get_account(conn, account_id)
    fill = _slip(float(price), side, "entry", slippage_pct)
    if side == "long" and not sl < fill:
        raise PaperError(f"long SL {sl} must be below the fill {fill:.6g}")
    if side == "short" and not sl > fill:
        raise PaperError(f"short SL {sl} must be above the fill {fill:.6g}")
    if tp is not None and ((side == "long" and tp <= fill) or (side == "short" and tp >= fill)):
        raise PaperError(f"TP {tp} is on the wrong side of the fill {fill:.6g}")
    dist = abs(fill - sl)
    if qty is None:
        risk_budget = a["balance"] * a["risk_pct"] / 100.0
        qty = risk_budget / dist
    max_qty = a["balance"] * a["leverage_max"] / fill
    if qty > max_qty:
        qty = max_qty  # capped by leverage_max
    if qty <= 0:
        raise PaperError("quantity must be positive")
    fee = qty * fill * COMMISSION_PCT / 100.0
    now = when or utcnow()
    cur = conn.execute(
        "INSERT INTO paper_positions (account_id, symbol, side, qty, entry_price, entry_time, sl, tp, fees, "
        "funding, risk_amount, source, watch_id, note, status, mark_price, mark_time, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 0, ?, ?, ?, ?, 'open', ?, ?, ?)",
        (account_id, symbol, side, qty, fill, now, sl, tp, fee, qty * dist, source, watch_id, note, fill, now,
         utcnow()))
    conn.commit()
    return dict(conn.execute("SELECT * FROM paper_positions WHERE id=?", (cur.lastrowid,)).fetchone())


def close_position(conn, position_id: int, price: float, reason: str, *, when: Optional[str] = None,
                   slippage_pct: float = DEFAULT_SLIPPAGE_PCT, slipped: bool = False) -> dict:
    p = conn.execute("SELECT * FROM paper_positions WHERE id=?", (position_id,)).fetchone()
    if p is None:
        raise PaperError("position not found")
    p = dict(p)
    if p["status"] != "open":
        raise PaperError("position already closed")
    exit_px = float(price) if slipped else _slip(float(price), p["side"], "exit", slippage_pct)
    gross = unrealized(p, exit_px)
    exit_fee = p["qty"] * exit_px * COMMISSION_PCT / 100.0
    fees = p["fees"] + exit_fee
    pnl = gross - fees - p["funding"]
    now = when or utcnow()
    r_mult = pnl / p["risk_amount"] if p["risk_amount"] else None
    # one transaction: position close + balance + journal
    conn.execute(
        "UPDATE paper_positions SET status='closed', exit_price=?, exit_time=?, exit_reason=?, pnl=?, fees=? "
        "WHERE id=? AND status='open'", (exit_px, now, reason, pnl, fees, position_id))
    conn.execute("UPDATE paper_accounts SET balance=balance+?, realized_pnl=realized_pnl+? WHERE id=?",
                 (pnl, pnl, p["account_id"]))
    jid = conn.execute(
        "INSERT INTO journal_entries (account_id, source, watch_id, symbol, side, entry_time, entry_price, "
        "exit_time, exit_price, qty, fees, funding, sl, tp, risk_amount, pnl, r_multiple, exit_reason, notes, "
        "tags, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (p["account_id"], p["source"], p["watch_id"], p["symbol"], p["side"], p["entry_time"], p["entry_price"],
         now, exit_px, p["qty"], fees, p["funding"], p["sl"], p["tp"], p["risk_amount"], pnl, r_mult, reason,
         p["note"], dumps([]), utcnow())).lastrowid
    conn.execute("UPDATE paper_positions SET journal_id=? WHERE id=?", (jid, position_id))
    conn.commit()
    return dict(conn.execute("SELECT * FROM paper_positions WHERE id=?", (position_id,)).fetchone())


# ── intrabar rule (mirrors bmtm-v2 order_manager) ─────────────────────────

def candle_exit(side: str, sl: Optional[float], tp: Optional[float], o: float, h: float, l: float
                ) -> Optional[tuple[float, str]]:
    if side == "long":
        sl_hit = sl is not None and l <= sl
        tp_hit = tp is not None and h >= tp
    else:
        sl_hit = sl is not None and h >= sl
        tp_hit = tp is not None and l <= tp
    if not sl_hit and not tp_hit:
        return None
    if sl_hit and tp_hit:
        near_low = abs(o - l) < abs(o - h)
        sl_first = near_low if side == "long" else not near_low
        if not sl_first:
            sl_hit = False
    if sl_hit:
        if side == "long":
            return (min(o, sl) if o <= sl else sl), "hard_sl"
        return (max(o, sl) if o >= sl else sl), "hard_sl"
    if side == "long":
        return (max(o, tp) if o >= tp else tp), "hard_tp"
    return (min(o, tp) if o <= tp else tp), "hard_tp"


def check_candles(conn, position_id: int, candles: list[dict],
                  slippage_pct: float = DEFAULT_SLIPPAGE_PCT) -> Optional[dict]:
    """Apply closed candles (dicts with t, ts, o, h, l, c) in order. Only candles
    opening at/after the entry are used (an entry mid-candle cannot be stopped by
    that candle's earlier extremes)."""
    p = dict(conn.execute("SELECT * FROM paper_positions WHERE id=?", (position_id,)).fetchone())
    if p["status"] != "open":
        return None
    last = p["last_checked_bar"]
    for c in candles:
        if c["t"] < p["entry_time"][:19] + "Z":
            continue
        if last and c["t"] <= last:
            continue
        hit = candle_exit(p["side"], p["sl"], p["tp"], c["o"], c["h"], c["l"])
        conn.execute("UPDATE paper_positions SET last_checked_bar=?, mark_price=?, mark_time=? WHERE id=?",
                     (c["t"], c["c"], c["t"], position_id))
        conn.commit()
        if hit:
            px, reason = hit
            return close_position(conn, position_id, _slip(px, p["side"], "exit", slippage_pct), reason,
                                  when=c["t"], slipped=True)
        last = c["t"]
    return None


def apply_funding(conn, position_id: int, events: list[dict]) -> float:
    """events: [{ts (ms), t (ISO), rate, mark}] settlements; charges those after
    the entry and after the last one already charged. Returns amount charged."""
    p = dict(conn.execute("SELECT * FROM paper_positions WHERE id=?", (position_id,)).fetchone())
    if p["status"] != "open":
        return 0.0
    since = p["last_funding_at"] or p["entry_time"]
    total, last = 0.0, p["last_funding_at"]
    sign = 1.0 if p["side"] == "long" else -1.0
    for e in sorted(events, key=lambda x: x["t"]):
        if e["t"] <= since:
            continue
        mark = e.get("mark") or p["mark_price"] or p["entry_price"]
        total += p["qty"] * mark * e["rate"] * sign
        last = e["t"]
    if last != p["last_funding_at"]:
        conn.execute("UPDATE paper_positions SET funding=funding+?, last_funding_at=? WHERE id=?",
                     (total, last, position_id))
        conn.commit()
    return total


def update_stops(conn, position_id: int, sl: Optional[float], tp: Optional[float]) -> None:
    conn.execute("UPDATE paper_positions SET sl=COALESCE(?, sl), tp=? WHERE id=? AND status='open'",
                 (sl, tp, position_id))
    conn.commit()
