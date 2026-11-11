"""Rosyade family template.

Same logic as the live ETH 4H "ROSYADE TERBARU" strategy (bmtm-v2
StrategyConfig / eth_4h_rosyade.yaml), with every parameter adjustable and
any Binance USD-M perp / timeframe. Defaults == the live ETH 4H preset.

The live Pine strategy on TradingView is NOT touched by anything here.
"""
from __future__ import annotations

from typing import Any

TEMPLATE_ID = "rosyade_family"
NAME = "Rosyade family"
DESCRIPTION = (
    "Breakout of swing structure with volume / HTF-EMA / RSI / ADX / MACD / BB / "
    "anti-chop filters; exits by TP1/TP2/TP, SL, ATR regime trailing, structure break, "
    "order-block trail, EMA cross, RSI extreme and breakeven lock. Defaults equal the "
    "live ETH 4H Rosyade preset; every parameter is adjustable."
)
TIMEFRAMES = ["15m", "30m", "1h", "4h", "1d"]

# HTF choices: "same" = the run's own timeframe (live preset: 4H EMA on a 4H chart).
# A choice at or below the run's timeframe falls back to "same". A true higher
# timeframe (e.g. 4h on a 15m run) is an EMA over CLOSED higher-timeframe bars.
HTF_CHOICES = ["same", "1h", "4h", "1d", "1w"]


def _p(key, label, type_, default, min_=None, max_=None, step=None, group="General",
       choices=None, tunable=False) -> dict:
    d = {"key": key, "label": label, "type": type_, "default": default,
         "min": min_, "max": max_, "step": step, "group": group, "tunable": tunable}
    if choices is not None:
        d["choices"] = choices
    return d


def _b(key, label, default, group):
    return _p(key, label, "bool", default, group=group)


def _i(key, label, default, lo, hi, group, step=1, tunable=False):
    return _p(key, label, "int", default, lo, hi, step, group, tunable=tunable)


def _f(key, label, default, lo, hi, step, group, tunable=False):
    return _p(key, label, "float", default, lo, hi, step, group, tunable=tunable)


G_DIR, G_TPSL, G_TPC, G_EXIT, G_TRAIL, G_REGIME = (
    "Direction", "TP / SL", "TP check", "Exits", "ATR trailing", "Regime")
G_ENTRY, G_CHOP, G_SHORT, G_BE, G_OB, G_RISK, G_ENGINE = (
    "Entry filters", "Anti-sideways", "Short filters", "Breakeven lock",
    "Order blocks", "Risk & sizing", "Engine")
G_MTF = "Entry timing (MTF)"

# MTF entry timing (research only). "bar_close" = the live behaviour: fill at the
# close of the signal bar. Other modes keep the signal / trend / exits on the run's
# timeframe and time the entry on a LOWER timeframe (see engine strategy/mtf_entry.py).
ENTRY_MODES = ["bar_close", "ltf_close", "ltf_pullback", "ltf_limit"]
ENTRY_TFS = ["15m", "30m", "1h"]

PARAMS: list[dict] = [
    _b("enable_long", "Enable long", True, G_DIR),
    _b("enable_short", "Enable short", True, G_DIR),
    _i("swing_len", "Swing length", 2, 1, 20, G_DIR, tunable=True),

    _f("long_sl_pct", "Long SL %", 13.0, 0.5, 30.0, 0.5, G_TPSL, tunable=True),
    _f("long_tp_pct", "Long TP %", 62.5, 1.0, 150.0, 0.5, G_TPSL),
    _b("use_long_tp1", "Long TP1", True, G_TPSL),
    _f("long_tp1_pct", "Long TP1 %", 10.0, 0.5, 50.0, 0.5, G_TPSL),
    _b("use_long_tp2", "Long TP2", True, G_TPSL),
    _f("long_tp2_pct", "Long TP2 %", 25.0, 0.5, 100.0, 0.5, G_TPSL),
    _f("short_sl_pct", "Short SL %", 3.0, 0.5, 30.0, 0.5, G_TPSL, tunable=True),
    _f("short_tp_pct", "Short TP %", 12.5, 1.0, 100.0, 0.5, G_TPSL),
    _b("use_short_tp1", "Short TP1", True, G_TPSL),
    _f("short_tp1_pct", "Short TP1 %", 10.0, 0.5, 50.0, 0.5, G_TPSL),
    _b("use_short_tp2", "Short TP2", True, G_TPSL),
    _f("short_tp2_pct", "Short TP2 %", 12.5, 0.5, 100.0, 0.5, G_TPSL),

    _b("use_tp_check", "TP check (exhaustion)", True, G_TPC),
    _i("tp_chk_vol_period", "TP check vol period", 50, 5, 200, G_TPC),
    _f("tp_chk_vol_mult", "TP check vol mult", 1.3, 0.5, 5.0, 0.1, G_TPC),
    _i("tp_chk_body_lookback", "TP check body lookback", 11, 2, 50, G_TPC),
    _f("tp_chk_body_mult", "TP check body mult", 0.05, 0.0, 1.0, 0.01, G_TPC),
    _f("tp_chk_atr_decay", "TP check ATR decay", 0.2, 0.0, 1.0, 0.05, G_TPC),

    _b("use_ema_exit", "EMA cross exit", True, G_EXIT),
    _i("ema_exit_len", "EMA exit length", 24, 5, 200, G_EXIT, tunable=True),
    _b("use_adaptive_exit", "Adaptive exit", True, G_EXIT),
    _b("use_structure_exit_long", "Structure exit (long)", True, G_EXIT),
    _b("use_structure_exit_short", "Structure exit (short)", True, G_EXIT),
    _i("structure_pivot_len", "Structure pivot length", 5, 1, 30, G_EXIT, tunable=True),
    _b("use_exit_rsi", "RSI extreme exit", True, G_EXIT),
    _i("exit_rsi_ob", "Exit RSI overbought", 91, 60, 100, G_EXIT),
    _i("exit_rsi_os", "Exit RSI oversold", 10, 0, 40, G_EXIT),

    _b("use_atr_trailing_long", "ATR trailing (long)", True, G_TRAIL),
    _i("atr_trailing_len_long", "ATR length (long)", 26, 2, 100, G_TRAIL),
    _i("atr_lookback_long", "HH lookback (long)", 13, 2, 100, G_TRAIL),
    _f("atr_mult_strong_long", "ATR mult strong (long)", 3.5, 0.5, 10.0, 0.1, G_TRAIL),
    _f("atr_mult_medium_long", "ATR mult medium (long)", 1.9, 0.5, 10.0, 0.1, G_TRAIL, tunable=True),
    _f("atr_mult_weak_long", "ATR mult weak (long)", 2.0, 0.5, 10.0, 0.1, G_TRAIL),
    _b("use_atr_trailing_short", "ATR trailing (short)", True, G_TRAIL),
    _i("atr_trailing_len_short", "ATR length (short)", 26, 2, 100, G_TRAIL),
    _i("atr_lookback_short", "LL lookback (short)", 13, 2, 100, G_TRAIL),
    _f("atr_mult_strong_short", "ATR mult strong (short)", 3.5, 0.5, 10.0, 0.1, G_TRAIL),
    _f("atr_mult_medium_short", "ATR mult medium (short)", 1.9, 0.5, 10.0, 0.1, G_TRAIL, tunable=True),
    _f("atr_mult_weak_short", "ATR mult weak (short)", 2.0, 0.5, 10.0, 0.1, G_TRAIL),

    _i("adx_strong_threshold", "ADX strong threshold", 25, 10, 60, G_REGIME, tunable=True),
    _i("adx_weak_threshold", "ADX weak threshold", 15, 5, 40, G_REGIME),
    _p("dcb_htf_input", "DCB HTF", "choice", "same", group=G_REGIME, choices=HTF_CHOICES),
    _b("use_dcb_entry", "DCB entry", False, G_REGIME),
    _b("use_dcb_reverse", "DCB reverse exit", True, G_REGIME),
    _f("dcb_vol_thresh", "DCB volume threshold", 4.4, 1.0, 10.0, 0.1, G_REGIME),
    _b("use_dcb_htf_exit", "DCB HTF exit", False, G_REGIME),
    _b("use_dcb_close", "DCB close", False, G_REGIME),

    _b("use_entry_volume", "Volume filter", True, G_ENTRY),
    _i("entry_vol_period", "Volume period", 50, 5, 200, G_ENTRY),
    _f("entry_vol_mult", "Volume mult", 1.6, 0.5, 5.0, 0.1, G_ENTRY, tunable=True),
    _b("use_ema_htf", "HTF EMA trend filter", True, G_ENTRY),
    _i("ema_htf_len", "HTF EMA length", 194, 10, 400, G_ENTRY, tunable=True),
    _p("ema_htf_tf", "HTF EMA timeframe", "choice", "same", group=G_ENTRY, choices=HTF_CHOICES),
    _b("use_entry_rsi", "RSI filter", True, G_ENTRY),
    _i("entry_rsi_len", "RSI length", 14, 2, 50, G_ENTRY),
    _i("entry_rsi_ob", "RSI overbought", 78, 50, 100, G_ENTRY),
    _i("entry_rsi_os", "RSI oversold", 16, 0, 50, G_ENTRY),
    _b("use_entry_adx", "ADX filter", True, G_ENTRY),
    _i("entry_adx_threshold", "ADX entry threshold", 11, 0, 50, G_ENTRY),
    _b("use_entry_macd", "MACD filter", True, G_ENTRY),
    _i("macd_fast_len", "MACD fast", 13, 2, 50, G_ENTRY),
    _i("macd_slow_len", "MACD slow", 28, 5, 100, G_ENTRY),
    _i("macd_sig_len", "MACD signal", 9, 2, 50, G_ENTRY),
    _b("use_entry_bb", "Bollinger filter", True, G_ENTRY),
    _i("bb_len", "BB length", 14, 5, 100, G_ENTRY),
    _f("bb_mult", "BB mult", 1.0, 0.5, 4.0, 0.1, G_ENTRY),
    _b("use_candle", "Candle body filter", True, G_ENTRY),
    _f("body_pct", "Min body %", 20.0, 0.0, 100.0, 1.0, G_ENTRY),
    _b("use_atr_filter", "ATR % filter", False, G_ENTRY),
    _i("atr_len_filter", "ATR filter length", 26, 2, 100, G_ENTRY),
    _f("atr_min_pct", "ATR min %", 1.5, 0.0, 10.0, 0.1, G_ENTRY),

    _b("use_chop", "Choppiness filter", True, G_CHOP),
    _i("chop_len", "Choppiness length", 15, 5, 100, G_CHOP),
    _f("chop_limit", "Choppiness limit", 65.0, 30.0, 100.0, 1.0, G_CHOP, tunable=True),
    _b("use_slope", "EMA slope filter", True, G_CHOP),
    _i("slope_len", "Slope EMA length", 12, 2, 100, G_CHOP),
    _f("slope_th", "Slope threshold %", 0.1, 0.0, 5.0, 0.01, G_CHOP),
    _b("use_sqz", "Squeeze filter", True, G_CHOP),
    _f("sqz_bb_mult", "Squeeze BB mult", 2.0, 0.5, 4.0, 0.1, G_CHOP),
    _f("sqz_kc_mult", "Squeeze KC mult", 1.0, 0.5, 4.0, 0.1, G_CHOP),
    _b("use_rvol", "Relative volume filter", True, G_CHOP),
    _f("rvol_thresh", "RVOL threshold", 1.3, 0.5, 5.0, 0.1, G_CHOP),
    _i("rvol_len", "RVOL length", 20, 5, 200, G_CHOP),

    _b("use_short_oversold", "Short: block oversold", False, G_SHORT),
    _i("short_rsi_min", "Short: min RSI", 30, 0, 60, G_SHORT),
    _b("use_short_drop_filter", "Short: drop filter", True, G_SHORT),
    _i("short_drop_lookback", "Short: drop lookback", 11, 2, 100, G_SHORT),
    _f("short_max_drop_pct", "Short: max drop %", 22.0, 1.0, 80.0, 0.5, G_SHORT),

    _b("use_be_lock", "Breakeven lock", True, G_BE),
    _f("be_lock_long_pct", "BE lock trigger long %", 12.0, 0.5, 50.0, 0.5, G_BE),
    _f("be_lock_short_pct", "BE lock trigger short %", 8.0, 0.5, 50.0, 0.5, G_BE),
    _f("be_lock_buffer_pct", "BE lock buffer %", 0.2, 0.0, 5.0, 0.05, G_BE),

    _b("use_ob_exit", "Order-block exit", True, G_OB),
    _i("ob_pivot_len", "OB pivot length", 47, 2, 150, G_OB),
    _b("exit_wick_rej", "Wick rejection exit", True, G_OB),
    _f("wick_body_ratio", "Wick/body ratio %", 25.0, 0.0, 200.0, 1.0, G_OB),
    _b("use_ob_trail", "Order-block trailing", True, G_OB),
    _i("ob_trail_pivot_len", "OB trail pivot length", 30, 2, 150, G_OB),
    _i("ob_trail_atr_len", "OB trail ATR length", 1, 1, 50, G_OB),
    _f("ob_trail_mult", "OB trail mult", 1.1, 0.0, 10.0, 0.1, G_OB),

    _f("leverage", "Leverage", 4.0, 1.0, 20.0, 0.5, G_RISK),
    _f("portfolio_risk", "Margin % of equity", 50.0, 1.0, 100.0, 1.0, G_RISK),
    _b("use_max_daily_loss", "Max daily loss stop", True, G_RISK),
    _f("max_daily_loss_pct", "Max daily loss %", 10.0, 1.0, 50.0, 0.5, G_RISK),
    _b("use_cooldown", "Cooldown after loss", True, G_RISK),
    _i("cooldown_bars", "Cooldown bars", 3, 0, 50, G_RISK, tunable=True),

    _p("entry_mode", "Mode entry", "choice", "bar_close", group=G_MTF, choices=ENTRY_MODES),
    _p("entry_tf", "Timeframe entry", "choice", "1h", group=G_MTF, choices=ENTRY_TFS),
    _i("entry_wait_bars", "Maks. tunggu (bar TF entry)", 4, 1, 96, G_MTF),
    _p("entry_band", "Patokan pullback", "choice", "atr", group=G_MTF, choices=["atr", "ema"]),
    _f("entry_atr_mult", "Jarak pullback/limit (x ATR)", 0.5, 0.0, 3.0, 0.05, G_MTF),
    _i("entry_atr_len", "Panjang ATR entry", 14, 2, 100, G_MTF),
    _i("entry_ema_len", "EMA TF entry", 20, 2, 200, G_MTF),
    _p("entry_timeout", "Jika tidak terisi", "choice", "skip", group=G_MTF, choices=["skip", "market"]),
    _i("limit_through_ticks", "Limit tembus (tick)", 1, 1, 20, G_MTF),
    _f("tick_size", "Tick size (0 = otomatis)", 0.0, 0.0, 100.0, 0.0001, G_MTF),
    _f("maker_fee_pct", "Fee maker % (limit)", 0.02, 0.0, 0.2, 0.005, G_MTF),
    _b("ltf_stop_check", "Cek SL di TF entry setelah fill", True, G_MTF),

    _i("warmup_bars", "Warm-up bars", 300, 100, 1000, G_ENGINE, step=50),
    _f("maintenance_margin_pct", "Maintenance margin %", 0.5, 0.1, 5.0, 0.05, G_ENGINE),
]

PARAM_INDEX = {p["key"]: p for p in PARAMS}
# Keys that live on the engine's EngineConfig rather than StrategyConfig.
ENGINE_KEYS = {"warmup_bars", "maintenance_margin_pct", "maker_fee_pct"}

MTF_KEYS = {p["key"] for p in PARAMS if p["group"] == G_MTF}

_TF_SEC = {"15m": 900, "30m": 1800, "1h": 3600, "4h": 14400, "1d": 86400}


def is_mtf(p: dict) -> bool:
    return p.get("entry_mode", "bar_close") != "bar_close"


def validate_for_timeframe(p: dict, tf: str) -> None:
    """Cross-check params against the run's (signal) timeframe."""
    if is_mtf(p):
        e = p["entry_tf"]
        if tf not in _TF_SEC or _TF_SEC[e] >= _TF_SEC[tf] or _TF_SEC[tf] % _TF_SEC[e]:
            raise ParamError(f"entry_tf {e} must be a lower timeframe that divides {tf} "
                             f"(entry_mode {p['entry_mode']})")


def defaults() -> dict[str, Any]:
    return {p["key"]: p["default"] for p in PARAMS}


def tunable_params() -> list[dict]:
    return [p for p in PARAMS if p.get("tunable")]


class ParamError(ValueError):
    pass


def validate_params(params: dict | None, partial_ok: bool = True) -> dict[str, Any]:
    """Merge user params over defaults, type-check and range-check every key.

    Unknown keys, wrong types and out-of-range values raise ParamError.
    Returns the full, normalised param dict.
    """
    params = dict(params or {})
    unknown = sorted(set(params) - set(PARAM_INDEX))
    if unknown:
        raise ParamError(f"unknown params: {', '.join(unknown)}")
    out = defaults()
    errors = []
    for key, val in params.items():
        spec = PARAM_INDEX[key]
        t = spec["type"]
        try:
            if t == "bool":
                if not isinstance(val, bool):
                    raise TypeError("expected bool")
                v: Any = val
            elif t == "int":
                if isinstance(val, bool) or not isinstance(val, (int, float)) or float(val) != int(val):
                    raise TypeError("expected int")
                v = int(val)
            elif t == "float":
                if isinstance(val, bool) or not isinstance(val, (int, float)):
                    raise TypeError("expected number")
                v = float(val)
                if v != v or v in (float("inf"), float("-inf")):
                    raise TypeError("must be finite")
            elif t == "choice":
                if val not in spec["choices"]:
                    raise TypeError(f"expected one of {spec['choices']}")
                v = val
            else:  # pragma: no cover
                raise TypeError(f"unsupported type {t}")
        except TypeError as e:
            errors.append(f"{key}: {e}")
            continue
        if t in ("int", "float"):
            if spec["min"] is not None and v < spec["min"]:
                errors.append(f"{key}: {v} < min {spec['min']}")
                continue
            if spec["max"] is not None and v > spec["max"]:
                errors.append(f"{key}: {v} > max {spec['max']}")
                continue
        out[key] = v
    if out["macd_fast_len"] >= out["macd_slow_len"]:
        errors.append("macd_fast_len must be < macd_slow_len")
    if out["adx_weak_threshold"] > out["adx_strong_threshold"]:
        errors.append("adx_weak_threshold must be <= adx_strong_threshold")
    if errors:
        raise ParamError("; ".join(errors))
    return out


def public_schema() -> dict:
    return {
        "id": TEMPLATE_ID,
        "name": NAME,
        "description": DESCRIPTION,
        "timeframes": list(TIMEFRAMES),
        "params": [dict(p) for p in PARAMS],
    }


N_TRIALS_OPTIONS = (10, 30, 60)


def resolve_search(search: dict | None) -> list[dict]:
    """Validate an optimize search spec and return the param specs to search.

    search = {"params": [keys], "ranges": {key: [min, max]}}; None -> all tunables
    with template ranges. Keys must be tunable; ranges are clamped to the
    template min/max (int params get integer bounds) and must stay non-empty.
    """
    tun = {p["key"]: p for p in tunable_params()}
    if not search:
        return [dict(p) for p in tun.values()]
    keys = list(search.get("params") or [])
    ranges = dict(search.get("ranges") or {})
    if not keys:
        keys = list(ranges) or list(tun)
    errors = []
    for k in keys + [k for k in ranges if k not in keys]:
        if k not in PARAM_INDEX:
            errors.append(f"{k}: unknown param")
        elif k not in tun:
            errors.append(f"{k}: not tunable (tunable: {', '.join(tun)})")
    for k in ranges:
        if k not in keys and k in tun:
            errors.append(f"{k}: range given but param not in search.params")
    if len(set(keys)) != len(keys):
        errors.append("duplicate keys in search.params")
    if errors:
        raise ParamError("; ".join(errors))
    out = []
    for k in keys:
        spec = dict(tun[k])
        if k in ranges:
            r = ranges[k]
            if not isinstance(r, (list, tuple)) or len(r) != 2 or any(
                    isinstance(x, bool) or not isinstance(x, (int, float)) for x in r):
                raise ParamError(f"{k}: range must be [min, max] numbers")
            lo, hi = max(float(r[0]), spec["min"]), min(float(r[1]), spec["max"])
            if spec["type"] == "int":
                import math
                lo, hi = int(math.ceil(lo)), int(math.floor(hi))
            if lo >= hi:
                raise ParamError(f"{k}: empty range after clamping to [{spec['min']}, {spec['max']}]")
            spec["min"], spec["max"] = lo, hi
        out.append(spec)
    return out
