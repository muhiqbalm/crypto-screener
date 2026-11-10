"""Universal v0 parameter schema + validation. Stdlib only (API imports this).

Defaults are chosen from the published literature, NOT tuned on our data:
  * momentum horizons 1w / 1m / 3m (crypto cross-sectional momentum is strongest
    at 1-4 week horizons, time-series trend at 1-3 months)
  * trend filter: price above its 50-day EMA (classic medium-term trend rule)
  * inverse-volatility weights, 30-day realised vol, portfolio vol target 40%/yr
  * daily rebalance with a minimum trade size to keep turnover/fees down
"""
from __future__ import annotations

from typing import Any

from . import TEMPLATE_ID

NAME = "Universal v0 (portofolio multi-koin)"
DESCRIPTION = ("Satu aturan untuk semua koin: pegang top-N koin dengan momentum terkuat yang juga sedang "
               "uptrend, ukuran posisi berbasis volatilitas (inverse-vol) ke target volatilitas portofolio, "
               "rebalance berkala. Opsional: short koin terlemah yang downtrend.")

REBALANCE_CHOICES = ["1d", "4h"]

G_SEL, G_SIG, G_RISK, G_EXEC = "Seleksi koin", "Sinyal", "Risiko & ukuran", "Eksekusi"


class ParamError(ValueError):
    pass


def _p(key, label, type_, default, min_=None, max_=None, step=None, group=G_SEL, choices=None,
       tunable=False, help_=""):
    d = {"key": key, "label": label, "type": type_, "default": default, "min": min_, "max": max_,
         "step": step, "group": group, "tunable": tunable, "help": help_}
    if choices is not None:
        d["choices"] = choices
    return d


PARAMS: list[dict] = [
    _p("top_n", "Jumlah koin long (top-N)", "int", 5, 1, 15, 1, G_SEL, tunable=True,
       help_="Berapa koin terkuat yang dipegang sekaligus."),
    _p("allow_short", "Aktifkan short", "bool", False, group=G_SEL,
       help_="Short koin terlemah yang sedang downtrend."),
    _p("bottom_n", "Jumlah koin short (bottom-N)", "int", 3, 1, 15, 1, G_SEL,
       help_="Dipakai hanya jika short aktif."),
    _p("min_history_days", "Minimal umur data (hari)", "int", 120, 30, 720, 10, G_SEL,
       help_="Koin baru listing belum boleh dipilih sebelum punya data sepanjang ini."),
    _p("min_universe", "Minimal koin layak", "int", 5, 2, 30, 1, G_SEL,
       help_="Backtest mulai saat minimal sekian koin sudah layak dipilih."),

    _p("mom_short_days", "Momentum pendek (hari)", "int", 7, 2, 30, 1, G_SIG, tunable=True),
    _p("mom_mid_days", "Momentum menengah (hari)", "int", 30, 10, 90, 1, G_SIG, tunable=True),
    _p("mom_long_days", "Momentum panjang (hari)", "int", 90, 30, 365, 5, G_SIG, tunable=True),
    _p("vol_days", "Jendela volatilitas (hari)", "int", 30, 7, 120, 1, G_SIG, tunable=True),
    _p("trend_ema_days", "EMA tren (hari)", "int", 50, 10, 200, 5, G_SIG, tunable=True,
       help_="Uptrend = harga di atas EMA ini."),
    _p("require_trend", "Wajib searah tren", "bool", True, group=G_SIG,
       help_="Long hanya jika uptrend, short hanya jika downtrend."),
    _p("regime_filter", "Filter rezim BTC", "bool", False, group=G_SIG,
       help_="Long hanya saat BTC di atas EMA tren; short hanya saat BTC di bawahnya."),

    _p("target_vol_pct", "Target volatilitas portofolio (%/tahun)", "float", 40.0, 5.0, 150.0, 5.0, G_RISK,
       tunable=True),
    _p("max_gross", "Maks. eksposur bruto (x ekuitas)", "float", 1.0, 0.1, 3.0, 0.1, G_RISK,
       help_="1.0 = tanpa leverage."),
    _p("max_weight_pct", "Maks. bobot per koin (%)", "float", 35.0, 5.0, 100.0, 5.0, G_RISK),
    _p("cov_days", "Jendela korelasi (hari)", "int", 60, 14, 180, 1, G_RISK),

    _p("rebalance", "Rebalance", "choice", "1d", group=G_EXEC, choices=REBALANCE_CHOICES,
       help_="1d = setiap close candle harian (00:00 UTC); 4h = setiap close candle 4 jam."),
    _p("min_trade_pct", "Minimal perubahan bobot untuk trade (%)", "float", 2.0, 0.0, 20.0, 0.5, G_EXEC,
       tunable=True, help_="Perubahan lebih kecil dari ini diabaikan (hemat biaya)."),
    _p("initial_capital", "Modal awal (USDT)", "float", 10000.0, 100.0, 1e8, 100.0, G_EXEC),
]
PARAM_INDEX = {p["key"]: p for p in PARAMS}
SYMBOLS_MAX = 60


def defaults() -> dict[str, Any]:
    return {p["key"]: p["default"] for p in PARAMS}


def tunable_params() -> list[dict]:
    return [p for p in PARAMS if p.get("tunable")]


def _coerce(spec: dict, val: Any) -> Any:
    t = spec["type"]
    if t == "bool":
        if not isinstance(val, bool):
            raise TypeError("expected bool")
        return val
    if t == "int":
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
        return val
    else:  # pragma: no cover
        raise TypeError(f"unsupported type {t}")
    if spec["min"] is not None and v < spec["min"]:
        raise TypeError(f"{v} < min {spec['min']}")
    if spec["max"] is not None and v > spec["max"]:
        raise TypeError(f"{v} > max {spec['max']}")
    return v


def norm_symbols(symbols: Any) -> list[str]:
    if symbols in (None, ""):
        return []
    if not isinstance(symbols, (list, tuple)):
        raise ParamError("symbols must be a list")
    out: list[str] = []
    for s in symbols:
        if not isinstance(s, str):
            raise ParamError("symbols must be strings")
        n = s.upper().replace("/", "").replace(":USDT", "").replace("-", "")
        if n.endswith("USDTUSDT"):
            n = n[:-4]
        if not (n.endswith("USDT") and 6 <= len(n) <= 24 and n.isalnum()):
            raise ParamError(f"invalid symbol {s}")
        if n not in out:
            out.append(n)
    if len(out) > SYMBOLS_MAX:
        raise ParamError(f"at most {SYMBOLS_MAX} symbols")
    return out


def validate_params(params: dict | None) -> dict[str, Any]:
    """Defaults merged with user values; unknown keys / bad types / ranges -> ParamError.

    ``symbols`` (list) selects the universe; empty = every coin with cached 4H data.
    """
    params = dict(params or {})
    symbols = norm_symbols(params.pop("symbols", None))
    unknown = sorted(set(params) - set(PARAM_INDEX))
    if unknown:
        raise ParamError(f"unknown params: {', '.join(unknown)}")
    out = defaults()
    errors = []
    for key, val in params.items():
        try:
            out[key] = _coerce(PARAM_INDEX[key], val)
        except TypeError as e:
            errors.append(f"{key}: {e}")
    if not out["mom_short_days"] < out["mom_mid_days"] < out["mom_long_days"]:
        errors.append("momentum horizons must satisfy short < mid < long")
    if out["max_weight_pct"] / 100.0 > out["max_gross"] + 1e-9:
        errors.append("max_weight_pct cannot exceed max_gross")
    if errors:
        raise ParamError("; ".join(errors))
    out["symbols"] = symbols
    return out


def public_schema() -> dict:
    return {"id": TEMPLATE_ID, "name": NAME, "description": DESCRIPTION, "timeframes": ["4h"],
            "params": [dict(p) for p in PARAMS]}


def resolve_search(search: dict | None) -> list[dict]:
    """{"params": [keys], "ranges": {key: [min, max]}} -> param specs to search (tunables only)."""
    tun = {p["key"]: p for p in tunable_params()}
    if not search:
        keys = ["top_n", "trend_ema_days", "mom_long_days", "target_vol_pct"]
        return [dict(tun[k]) for k in keys]
    keys = list(search.get("params") or []) or list((search.get("ranges") or {}).keys()) or list(tun)
    ranges = dict(search.get("ranges") or {})
    errors = [f"{k}: not tunable (tunable: {', '.join(tun)})" for k in keys if k not in tun]
    errors += [f"{k}: range for a param not in search.params" for k in ranges if k not in keys]
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
                lo, hi = float(int(-(-lo // 1))), float(int(hi // 1))
            if lo > hi:
                raise ParamError(f"{k}: empty range")
            spec["min"], spec["max"] = (int(lo), int(hi)) if spec["type"] == "int" else (lo, hi)
        out.append(spec)
    return out
