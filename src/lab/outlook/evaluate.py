"""After-the-fact evaluation of one Outlook call (stdlib only).

A call made at a 4H close is read as the instruction the page gives:
  entry at that close, a resting stop at SL and a resting limit at TP, and
  "batal" (exit at the close) when the strategy closes or flips the position,
  or when the horizon runs out.
It is walked forward over the following 4H bars (OHLC):

  * gap      the bar opens beyond SL (or TP): filled at the open
  * both     SL and TP inside the same bar: counted as SL (conservative; the
             path inside a 4H bar is unknown) and flagged ``ambiguous``
  * batal    the strategy closed / flipped at the close of bar k: exit at that close
  * expired  horizon reached without SL/TP: exit at the close of the last bar
  * open     not enough bars yet (live calls only)

R = (exit - entry) x side / |entry - SL|; ``r_net`` also subtracts the round-trip
cost (commission + slippage, both sides) expressed in R. Funding is ignored.
The same function scores the live track record and the historical replay.
"""
from __future__ import annotations

from typing import Optional, Sequence

COST_ROUNDTRIP_PCT = 0.2          # 0.05% commission + 0.05% slippage, per side
STATUSES = ("tp", "sl", "batal", "expired", "open", "invalid")
STATUS_TEXT = {"tp": "kena TP dulu", "sl": "kena SL dulu", "batal": "dibatalkan (strategi keluar)",
               "expired": "habis waktu", "open": "masih berjalan", "invalid": "tidak valid"}

Bar = Sequence[float]             # (open, high, low, close)


def evaluate_call(side: str, entry: float, sl: Optional[float], tp: Optional[float], bars: Sequence[Bar],
                  horizon: int, invalid_at: Optional[int] = None,
                  cost_pct: float = COST_ROUNDTRIP_PCT) -> dict:
    """``bars`` are the bars AFTER the call bar, oldest first. ``invalid_at`` is the 1-based
    position in ``bars`` at whose close the call is cancelled (None = never)."""
    s = 1 if side == "long" else -1
    if sl is None or not entry or entry <= 0:
        return {"status": "invalid", "reason": "tanpa SL", "r_gross": None, "r_net": None}
    r_unit = (entry - sl) * s
    if r_unit <= 0:
        return {"status": "invalid", "reason": "harga sudah melewati SL", "r_gross": None, "r_net": None}
    if tp is not None and (tp - entry) * s <= 0:
        tp = None   # TP already behind the price: not a target any more
    cost_r = entry * cost_pct / 100.0 / r_unit
    mfe = mae = 0.0
    status, exit_px, k_end, ambiguous = "open", None, 0, False
    last_close = entry
    for k, b in enumerate(bars[:max(0, int(horizon))], start=1):
        o, h, lo, c = float(b[0]), float(b[1]), float(b[2]), float(b[3])
        fav, adv = (h, lo) if s > 0 else (lo, h)
        k_end, last_close = k, c
        # gap through a level at the open
        if (o - sl) * s <= 0:
            status, exit_px = "sl", o
            mae = min(mae, (o - entry) * s / r_unit)
            break
        if tp is not None and (o - tp) * s >= 0:
            status, exit_px = "tp", o
            mfe = max(mfe, (o - entry) * s / r_unit)
            break
        sl_hit = (adv - sl) * s <= 0
        tp_hit = tp is not None and (fav - tp) * s >= 0
        mfe = max(mfe, (fav - entry) * s / r_unit)
        mae = min(mae, (adv - entry) * s / r_unit)
        if sl_hit:
            status, exit_px, ambiguous = "sl", sl, tp_hit
            break
        if tp_hit:
            status, exit_px = "tp", tp
            break
        if invalid_at is not None and k >= invalid_at:
            status, exit_px = "batal", c
            break
        if k >= horizon:
            status, exit_px = "expired", c
            break
    mark = exit_px if exit_px is not None else last_close
    r_gross = (mark - entry) * s / r_unit
    return {
        "status": status, "exit_price": exit_px, "bars": k_end, "ambiguous": ambiguous,
        "r_gross": r_gross, "r_net": r_gross - cost_r, "cost_r": cost_r,
        "mfe_r": mfe, "mae_r": mae, "r_unit_pct": r_unit / entry * 100.0,
    }
