"""Expected 4H-ETH-Basic signals from the Lab template + engine (engine child process).

How the live Pine script turns into webhook alerts (Rosyade_Terbaru.pine):
  * ``process_orders_on_close=true``: ``strategy.entry`` and every ``strategy.close``
    (TP check, ATR trailing, OB / structure / EMA / RSI / DCB exits) fill at the CLOSE
    of the bar that triggered them, so the alert fires right after the 4H close.
  * ``strategy.exit(stop=, limit=)`` (hard SL / TP) is a resting order; on a live
    chart TradingView fills it - and sends the alert - the moment price touches the
    level, i.e. somewhere INSIDE the 4H bar.
  * entries only when flat (``strategy.position_size == 0``): no reversals.

The engine mirrors this: bar-close exits carry the reason of the waterfall step;
``hard_sl`` / ``hard_tp`` / ``liquidation`` / ``sl_ltf`` are intrabar.

Three variants are computed (see docs/lab/live-check.md):
  utama    whole cached history, zero commission / slippage / funding = the Pine
           ``strategy()`` defaults (the script sets no commission). The reference.
  pendek   history starting ``short_history_days`` before ``since``: a signal that
           disappears here depends on the path long before the window (warm-up).
  biaya    whole history with the preset's costs: daily-loss and cooldown filters use
           realised PnL, so a signal that disappears here is cost-sensitive.
"""
from __future__ import annotations

from typing import Optional

INTRABAR_REASONS = {"hard_sl", "hard_tp", "liquidation", "sl_ltf"}
ZERO_COSTS = {"commission_pct": 0.0, "slippage_pct": 0.0, "funding": False}


def _epoch(ts) -> float:
    import pandas as pd
    t = pd.Timestamp(ts)
    if t.tzinfo is None:
        t = t.tz_localize("UTC")
    return t.timestamp()


def events_from_result(res, df, step: int, since_s: float) -> list[dict]:
    """Engine trades (+ the open position) -> alert events at or after ``since_s``."""
    closes = {_epoch(t): float(c) for t, c in zip(df["timestamp"], df["close"])}
    out: list[dict] = []

    def add(action: str, side: str, bar_open: float, reason: Optional[str], raw_px: Optional[float]) -> None:
        if bar_open + step < since_s:
            return
        intrabar = action == "close" and reason in INTRABAR_REASONS
        px = raw_px if intrabar else closes.get(bar_open, raw_px)
        out.append({"key": f"{action}|{side}|{int(bar_open)}", "action": action, "side": side,
                    "bar_open": bar_open, "alert": "intrabar" if intrabar else "close",
                    "price": float(px) if px is not None else None, "reason": reason})

    for t in res.trades:
        add("open", t.direction, _epoch(t.entry_timestamp), None, None)
        add("close", t.direction, _epoch(t.exit_timestamp), t.exit_reason, float(t.exit_price))
    op = res.open_position
    if op:
        add("open", op["direction"], _epoch(op["entry_timestamp"]), None, None)
    out.sort(key=lambda e: (e["bar_open"], 0 if e["action"] == "close" else 1))
    return out


def compute(params: dict, preset_costs: dict, symbol: str, tf: str, since: str, short_history_days: int,
            offline: bool = False, data=None) -> dict:
    """{"variants": {name: [event]}, "data_first_bar", "data_last_bar", "engine_commit"}.
    ``data`` = (ohlcv, funding) for tests; otherwise the Lab cache is refreshed first."""
    import pandas as pd

    from .. import data_cache as dc
    from .. import engine_adapter as ea

    ohlcv, fund = data if data is not None else dc.ensure(symbol, tf, funding=True, offline=offline)
    step = ea.TF_SECONDS[tf]
    since_ts = pd.Timestamp(since, tz="UTC")
    short_start = (since_ts - pd.Timedelta(days=short_history_days)).strftime("%Y-%m-%d %H:%M:%S")
    costs_b = {"commission_pct": float(preset_costs.get("commission_pct", 0.05)),
               "slippage_pct": float(preset_costs.get("slippage_pct", 0.05)),
               "funding": bool(preset_costs.get("funding", True))}
    plan = {"utama": (None, ZERO_COSTS), "pendek": (short_start, ZERO_COSTS), "biaya": (None, costs_b)}
    variants: dict[str, list[dict]] = {}
    for name, (start, costs) in plan.items():
        cfg, ecfg = ea.build_configs(params, tf, costs)
        df, _, _, _ = ea.prepare_frame(ohlcv, fund, tf, start, None, ecfg.warmup_period, bool(costs["funding"]))
        res, _ = ea.run(df, cfg, ecfg)
        variants[name] = events_from_result(res, df, step, since_ts.timestamp())
    try:
        commit = ea.engine_commit()
    except Exception:  # noqa: BLE001
        commit = None
    return {
        "variants": variants,
        "data_first_bar": _epoch(ohlcv["timestamp"].iloc[0]),
        "data_last_bar": _epoch(ohlcv["timestamp"].iloc[-1]),
        "engine_commit": commit,
    }
