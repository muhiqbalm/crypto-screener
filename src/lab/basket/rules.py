"""Pre-registered basket rules (08-praregistrasi-basket.md §6-§9, locked 2026-11-12, commit 52dccca).

Changing any number here is a NEW pre-registration, never an edit:
tests/test_lab/test_basket.py checks every value against
docs/research/basket/prereg-basket-2026-11-12.json. Pure functions, stdlib only.
"""
from __future__ import annotations

import math
from datetime import datetime, timedelta, timezone
from typing import Optional, Sequence

PREREG_ID = "basket-2026-11-12"
PREREG_DOC = "docs/riset-2026-11-12/08-praregistrasi-basket.md"
PREREG_JSON = "docs/research/basket/prereg-basket-2026-11-12.json"
PREREG_COMMIT = "52dccca"

REVIEW_MIN_TRADES = 30
CHECKPOINTS: dict[int, dict[str, int]] = {
    1: {"min_trades": 30, "min_days": 28, "min_coins": 8, "min_entry_days": 10},
    2: {"min_trades": 60, "min_days": 56, "min_coins": 0, "min_entry_days": 0},
}
DEADLINE_DAYS = 84                    # checkpoint 1 conditions must be met within 84 days of the start
PF_FAIL = {1: 1.0, 2: 1.2}            # PF below this at the checkpoint -> GAGAL
PF_PASS = 1.2                         # PF at least this (and DD + fidelity ok) -> LULUS
DD_LIMIT_FLOOR_PCT = -5.0             # DD limit = the looser of -5% and -1.5 x |reference max DD|
DD_LIMIT_MULT = 1.5
KILL_DD_PCT = 15.0                    # equity >= 15% below its peak at any time -> no new entries, GAGAL
FIDELITY_COVERAGE_MIN = 0.90
FIDELITY_MAX_MEDIAN_ABS_DIFF_PP = 0.30
ENTRY_WINDOW_S = (-5 * 60, 2 * 3600)  # paper entry time vs the signal bar's close

BELUM, LANJUT, LULUS, GAGAL, TIDAK_SAH, TIDAK_CUKUP_DATA = (
    "BELUM", "LANJUT", "LULUS", "GAGAL", "TIDAK_SAH", "TIDAK_CUKUP_DATA")
OUTCOMES = (BELUM, LANJUT, LULUS, GAGAL, TIDAK_SAH, TIDAK_CUKUP_DATA)

DAY_S = 86400


def profit_factor(pnls: Sequence[float]) -> Optional[float]:
    """sum(wins) / |sum(losses)|; inf without a loss; None without trades."""
    if not pnls:
        return None
    win = sum(p for p in pnls if p > 0)
    loss = -sum(p for p in pnls if p < 0)
    if loss == 0:
        return math.inf if win > 0 else None
    return win / loss


def pf_decision(pf: Optional[float], checkpoint: int) -> Optional[str]:
    """GAGAL / LANJUT / LULUS from the profit factor alone (None without trades)."""
    if pf is None:
        return None
    if pf < PF_FAIL[checkpoint]:
        return GAGAL
    if pf >= PF_PASS:
        return LULUS
    return LANJUT                     # only reachable at checkpoint 1 (PF_FAIL[2] == PF_PASS)


def dd_limit_pct(reference_max_dd_pct: Optional[float]) -> Optional[float]:
    """Deepest allowed drawdown in % (negative). None without a reference backtest."""
    if reference_max_dd_pct is None:
        return None
    return min(DD_LIMIT_FLOOR_PCT, -DD_LIMIT_MULT * abs(float(reference_max_dd_pct)))


def next_monday(epoch_s: float) -> float:
    """Monday 00:00 UTC on/after epoch_s (the weekly report day)."""
    d = datetime.fromtimestamp(epoch_s, tz=timezone.utc)
    midnight = d.replace(hour=0, minute=0, second=0, microsecond=0)
    if d.weekday() == 0 and d == midnight:
        return epoch_s
    days = (7 - d.weekday()) % 7 or 7
    return (midnight + timedelta(days=days)).timestamp()


def checkpoint_due(trades: Sequence[dict], start_s: float, checkpoint: int) -> Optional[dict]:
    """When checkpoint `checkpoint` falls, from closed trades ({exit_s, entry_s, symbol}).

    Walks the trades in exit order and stops at the first trade after which every
    condition holds: >= min_trades closed, from >= min_coins coins, opened on >=
    min_entry_days distinct UTC days. The conditions are met at max(that exit,
    start + min_days); the checkpoint is the Monday 00:00 UTC on/after that moment.
    Returns {met_s, due_s, n_at_met} or None while the conditions are not met yet."""
    need = CHECKPOINTS[checkpoint]
    coins: set = set()
    days: set = set()
    for n, t in enumerate(sorted(trades, key=lambda x: (x["exit_s"], x.get("id", 0))), start=1):
        coins.add(t["symbol"])
        days.add(int(t["entry_s"] // DAY_S))
        if n >= need["min_trades"] and len(coins) >= need["min_coins"] and len(days) >= need["min_entry_days"]:
            met = max(float(t["exit_s"]), start_s + need["min_days"] * DAY_S)
            return {"met_s": met, "due_s": next_monday(met), "n_at_met": n}
    return None
