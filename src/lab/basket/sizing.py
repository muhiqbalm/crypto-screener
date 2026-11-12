"""Position size of a basket member's NEW entry on the basket's shared paper account
(08-praregistrasi-basket.md §5). Called by watch_eval._autopaper only for basket watches;
normal watches keep their own sizing untouched.

Modes (sizing_json.mode):
  risk         qty = balance x risk_pct% / |fill - strategy stop|   (basket A: 0.25% per trade)
  slot_engine  qty = balance / slots x engine notional multiple / price   (basket B: VT60, 28 slots)
  slot_fixed   qty = balance / slots x notional_x / price
then, in order: per-position cap (max_position_notional_x x balance), gross cap (all open
notional + this one <= gross_cap_x x balance; shrink to fit, skip below min_fill_frac), and the
kill switch (equity >= kill_dd_pct below its peak -> basket stops opening, for good).

Every skip / shrink is logged in lab_basket_events with the signal bar, so the
paper-vs-engine check can explain each engine entry that has no paper twin.
Stdlib only; never sends an order (it only returns a quantity).
"""
from __future__ import annotations

from typing import Optional

from .. import paper
from ..ledger.store import to_epoch
from . import store

TF_SECONDS = {"15m": 900, "30m": 1800, "1h": 3600, "4h": 14400, "1d": 86400}


def _open_positions(conn, account_id: int) -> list[dict]:
    return [dict(r) for r in conn.execute(
        "SELECT symbol, side, qty, entry_price, mark_price, fees, funding FROM paper_positions "
        "WHERE account_id=? AND status='open'", (account_id,))]


def equity_and_peak(conn, account: dict) -> tuple[float, float]:
    """(equity now, highest equity seen): realised balance + open PnL at the last marks, vs the
    peak of the starting balance, every realised balance and every hourly arena snapshot."""
    upnl = sum(paper.unrealized(p, p["mark_price"]) - (p["fees"] or 0) - (p["funding"] or 0)
               for p in _open_positions(conn, account["id"]))
    equity = float(account["balance"]) + upnl
    peak = max(float(account["starting_balance"]), equity)
    bal = float(account["starting_balance"])
    for r in conn.execute("SELECT pnl FROM journal_entries WHERE account_id=? ORDER BY exit_time, id",
                          (account["id"],)):
        bal += float(r["pnl"] or 0.0)
        peak = max(peak, bal)
    if conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='arena_equity_snapshots'").fetchone():
        snap = conn.execute("SELECT MAX(equity) FROM arena_equity_snapshots WHERE account_id=?",
                            (account["id"],)).fetchone()[0]
        if snap is not None:
            peak = max(peak, float(snap))
    return equity, peak


def entry_plan(conn, basket: dict, watch: dict, pos: dict, price: float) -> dict:
    """{"qty": float, "skip": None} to open, or {"qty": None, "skip": reason} to stay flat.
    Logs the decision when it is not a plain full-size entry."""
    bid, sym, bar = basket["id"], watch["symbol"], pos.get("entry_time")
    sz = basket["sizing"]

    def skip(reason: str, **detail) -> dict:
        store.log_event(conn, bid, "skip", reason, watch_id=watch["id"], symbol=sym, bar=bar, detail=detail or None)
        return {"qty": None, "skip": reason}

    if not basket["active"]:
        return skip("basket_berhenti")
    tf_s = TF_SECONDS.get(basket["timeframe"], 0)
    if bar and to_epoch(bar) + tf_s < to_epoch(basket["created_at"]):
        # the signal bar closed before the basket existed: a position the strategy already held at the start
        return skip("sebelum_mulai")
    account = paper.get_account(conn, basket["account_id"])
    bal = float(account["balance"])
    if bal <= 0:
        return skip("saldo_habis", balance=bal)

    equity, peak = equity_and_peak(conn, account)
    dd = (equity / peak - 1.0) * 100.0 if peak > 0 else 0.0
    if dd <= -float(sz["kill_dd_pct"]):
        store.set_active(conn, bid, False)
        store.log_event(conn, bid, "kill", "rem_darurat", watch_id=watch["id"], symbol=sym, bar=bar,
                        detail={"equity": equity, "peak": peak, "dd_pct": dd, "limit_pct": -float(sz["kill_dd_pct"])})
        from ..notify_events import basket_stopped
        basket_stopped(conn, basket, dd, -float(sz["kill_dd_pct"]))
        return {"qty": None, "skip": "rem_darurat"}

    px = float(price)
    mode = sz["mode"]
    if mode == "risk":
        slip = float((basket.get("costs") or {}).get("slippage_pct", paper.DEFAULT_SLIPPAGE_PCT))
        fill = paper._slip(px, pos["side"], "entry", slip)
        dist = abs(fill - float(pos["sl"])) if pos.get("sl") else 0.0
        if dist <= 0:
            return skip("stop_tidak_valid", sl=pos.get("sl"), fill=fill)
        qty = bal * float(sz["risk_pct"]) / 100.0 / dist
    elif mode == "slot_engine":
        nm = pos.get("notional_mult")
        if not nm or float(nm) <= 0:
            return skip("ukuran_engine_tidak_ada")
        qty = bal / int(sz["slots"]) * float(nm) / px
    else:  # slot_fixed
        qty = bal / int(sz["slots"]) * float(sz["notional_x"]) / px
    want = qty

    cap_qty = bal * float(sz["max_position_notional_x"]) / px
    if qty > cap_qty:
        qty = cap_qty
        store.log_event(conn, bid, "shrink", "cap_posisi", watch_id=watch["id"], symbol=sym, bar=bar,
                        detail={"want_notional": want * px, "notional": qty * px})

    open_notional = sum(abs(p["qty"]) * float(p["mark_price"] or p["entry_price"])
                        for p in _open_positions(conn, account["id"]))
    room = bal * float(sz["gross_cap_x"]) - open_notional
    if qty * px > room:
        if room > 0 and room >= float(sz.get("min_fill_frac", 0.1)) * want * px:
            store.log_event(conn, bid, "shrink", "cap_total", watch_id=watch["id"], symbol=sym, bar=bar,
                            detail={"want_notional": want * px, "notional": room, "open_notional": open_notional})
            qty = room / px
        else:
            return skip("cap_total", want_notional=want * px, room=room, open_notional=open_notional)
    return {"qty": qty, "skip": None}
