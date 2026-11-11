"""Shared machinery for templates that run an engine ``strategy_family`` other than Rosyade.

A family template module builds a :class:`FamilyTemplate` and re-exports its
methods, so it offers the same module API as ``rosyade_family`` (PARAMS,
validate_params, resolve_search, public_schema, is_mtf, is_sized, ...) plus
``engine_fields(p)`` -> the full engine StrategyConfig kwargs.

The engine's StrategyConfig still requires every Rosyade field; they are filled
with the Rosyade defaults and the Rosyade-only exits/filters switched off (the
engine ignores them for a non-rosyade family anyway). Shared params keep the
Rosyade keys (enable_long, use_ema_htf, ema_htf_len, ema_htf_tf, leverage,
portfolio_risk, sizing, MTF entry ...) so adapter code (HTF warm-up, MTF data,
sizing in watches) works unchanged.
"""
from __future__ import annotations

import math
from typing import Any, Callable, Optional

from . import rosyade_family as R
from .rosyade_family import ParamError  # one error class for every template (API catches it)

TIMEFRAMES = list(R.TIMEFRAMES)
HTF_CHOICES = list(R.HTF_CHOICES)

G_DIR, G_HTF, G_RISK, G_SIZE, G_MTF, G_ENGINE = (
    "Arah", "Filter trend HTF", "Risiko", R.G_SIZE, R.G_MTF, R.G_ENGINE)


def p(key, label, type_, default, min_=None, max_=None, step=None, group="Umum", choices=None,
      tunable=False, help=None) -> dict:
    d = {"key": key, "label": label, "type": type_, "default": default, "min": min_, "max": max_,
         "step": step, "group": group, "tunable": tunable}
    if choices is not None:
        d["choices"] = choices
    if help:
        d["help"] = help
    return d


def b(key, label, default, group, help=None):
    return p(key, label, "bool", default, group=group, help=help)


def i(key, label, default, lo, hi, group, step=1, tunable=False, help=None):
    return p(key, label, "int", default, lo, hi, step, group, tunable=tunable, help=help)


def f(key, label, default, lo, hi, step, group, tunable=False, help=None):
    return p(key, label, "float", default, lo, hi, step, group, tunable=tunable, help=help)


def c(key, label, default, choices, group, help=None):
    return p(key, label, "choice", default, group=group, choices=choices, help=help)


def _from_rosyade(key: str, group: str, **over) -> dict:
    d = dict(R.PARAM_INDEX[key])
    d["group"] = group
    d["tunable"] = False
    d.update(over)
    return d


def direction_params() -> list[dict]:
    return [b("enable_long", "Aktifkan long", True, G_DIR), b("enable_short", "Aktifkan short", True, G_DIR)]


def htf_params(use: bool, length: int, tf: str, tunable_len: bool) -> list[dict]:
    return [
        b("use_ema_htf", "Filter trend EMA HTF", use, G_HTF,
          help="Long hanya bila close di atas EMA timeframe besar, short hanya bila di bawahnya. "
               "EMA dihitung dari bar HTF yang sudah close (tanpa lookahead)."),
        i("ema_htf_len", "Panjang EMA HTF", length, 10, 400, G_HTF, tunable=tunable_len),
        c("ema_htf_tf", "Timeframe EMA HTF", tf, HTF_CHOICES, G_HTF,
          help="'same' = timeframe run itu sendiri. Pilihan <= timeframe run otomatis jadi 'same'."),
    ]


def risk_params(leverage: float = 2.0) -> list[dict]:
    """Default leverage 2: isolated-margin liquidation ~-50% stays beyond the family's ATR stops
    (at 4x it sits ~-25%, inside a 4-ATR stop on volatile alts). Margin mode: 50% x 2 = 1x notional."""
    return [
        f("leverage", "Leverage", leverage, 1.0, 20.0, 0.5, G_RISK,
          help="Untuk margin isolated & likuidasi. Notional (mode margin) = ekuitas x margin% x leverage."),
        f("portfolio_risk", "Margin % ekuitas (mode margin)", 50.0, 1.0, 100.0, 1.0, G_RISK),
        i("cooldown_bars", "Jeda setelah trade rugi (bar)", 0, 0, 50, G_RISK,
          help="Setelah trade rugi, tunggu sekian bar sebelum entry lagi (0 = tanpa jeda)."),
        b("use_max_daily_loss", "Stop rugi harian", False, G_RISK),
        f("max_daily_loss_pct", "Batas rugi harian % (modal awal)", 10.0, 1.0, 50.0, 0.5, G_RISK),
    ]


def sizing_params(**defaults) -> list[dict]:
    """Same keys / labels as Rosyade; for mode "risk" the stop distance is the family's ATR stop."""
    out = [_from_rosyade(k, G_SIZE, **({"default": defaults[k]} if k in defaults else {})) for k in ("sizing_mode", "risk_per_trade_pct", "max_notional_mult",
                                              "vol_target_pct", "vol_lookback", "dd_derisk_pct",
                                              "dd_derisk_mult")]
    out[1]["label"] = "Risiko per trade (% ekuitas, mode risk; jarak = stop ATR)"
    return out


def mtf_params() -> list[dict]:
    return [_from_rosyade(k, G_MTF) for k in R.PARAM_INDEX if R.PARAM_INDEX[k]["group"] == R.G_MTF]


def engine_params() -> list[dict]:
    return [_from_rosyade("warmup_bars", G_ENGINE, label="Bar pemanasan (warm-up)"),
            _from_rosyade("maintenance_margin_pct", G_ENGINE, label="Maintenance margin %")]


# Rosyade-only behaviour switched off in the filler (ignored by the engine for other families).
_ROSYADE_OFF = {
    "use_tp_check": False, "use_ema_exit": False, "use_adaptive_exit": False,
    "use_structure_exit_long": False, "use_structure_exit_short": False, "use_exit_rsi": False,
    "use_atr_trailing_long": False, "use_atr_trailing_short": False, "use_dcb_entry": False,
    "use_dcb_reverse": False, "use_dcb_htf_exit": False, "use_dcb_close": False,
    "use_entry_volume": False, "use_entry_rsi": False, "use_entry_adx": False, "use_entry_macd": False,
    "use_entry_bb": False, "use_candle": False, "use_atr_filter": False, "use_chop": False,
    "use_slope": False, "use_sqz": False, "use_rvol": False, "use_short_oversold": False,
    "use_short_drop_filter": False, "use_be_lock": False, "use_ob_exit": False, "use_ob_trail": False,
}


class FamilyTemplate:
    def __init__(self, *, template_id: str, name: str, description: str, family: str, params: list[dict],
                 cross_check: Optional[Callable[[dict], list[str]]] = None,
                 lookbacks: Optional[Callable[[dict], int]] = None):
        self.TEMPLATE_ID, self.NAME, self.DESCRIPTION, self.FAMILY = template_id, name, description, family
        self.PARAMS = params
        self.PARAM_INDEX = {x["key"]: x for x in params}
        assert len(self.PARAM_INDEX) == len(params), "duplicate param keys"
        self.ENGINE_KEYS = {"warmup_bars", "maintenance_margin_pct", "maker_fee_pct"}
        self.MTF_KEYS = {x["key"] for x in params if x["group"] == G_MTF}
        self.SIZING_KEYS = {x["key"] for x in params if x["group"] == G_SIZE}
        self._cross = cross_check
        self._lookbacks = lookbacks

    # ── same API as rosyade_family ──
    def is_mtf(self, p: dict) -> bool:
        return p.get("entry_mode", "bar_close") != "bar_close"

    def is_sized(self, p: dict) -> bool:
        """Always: the paper mirror (autopaper) copies the engine's notional / equity at entry, because a
        family's sizing differs from the Rosyade live default (1x margin or ATR risk sizing)."""
        return True

    def validate_for_timeframe(self, p: dict, tf: str) -> None:
        R.validate_for_timeframe(p, tf)   # MTF entry_tf rule only

    def defaults(self) -> dict[str, Any]:
        return {x["key"]: x["default"] for x in self.PARAMS}

    def tunable_params(self) -> list[dict]:
        return [x for x in self.PARAMS if x.get("tunable")]

    def min_warmup(self, p: dict) -> int:
        """Bars of history the family indicators need (+25% head-room for sensitivity / optimiser nudges)."""
        return int(math.ceil(self._lookbacks(p) * 1.25)) + 2 if self._lookbacks else 0

    def validate_params(self, params: dict | None, partial_ok: bool = True) -> dict[str, Any]:
        params = dict(params or {})
        unknown = sorted(set(params) - set(self.PARAM_INDEX))
        if unknown:
            raise ParamError(f"unknown params: {', '.join(unknown)}")
        out = self.defaults()
        errors = []
        for key, val in params.items():
            spec = self.PARAM_INDEX[key]
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
        if not errors and not (out["enable_long"] or out["enable_short"]):
            errors.append("enable_long / enable_short: at least one side must be enabled")
        if not errors and self._cross:
            errors += self._cross(out)
        if errors:
            raise ParamError("; ".join(errors))
        return out

    def public_schema(self) -> dict:
        return {"id": self.TEMPLATE_ID, "name": self.NAME, "description": self.DESCRIPTION,
                "timeframes": list(TIMEFRAMES), "params": [dict(x) for x in self.PARAMS]}

    def resolve_search(self, search: dict | None) -> list[dict]:
        """Same contract as rosyade_family.resolve_search, over this template's tunables."""
        tun = {x["key"]: x for x in self.tunable_params()}
        if not search:
            return [dict(x) for x in tun.values()]
        keys = list(search.get("params") or [])
        ranges = dict(search.get("ranges") or {})
        if not keys:
            keys = list(ranges) or list(tun)
        errors = []
        for k in keys + [k for k in ranges if k not in keys]:
            if k not in self.PARAM_INDEX:
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
                    lo, hi = int(math.ceil(lo)), int(math.floor(hi))
                if lo >= hi:
                    raise ParamError(f"{k}: empty range after clamping to [{spec['min']}, {spec['max']}]")
                spec["min"], spec["max"] = lo, hi
            out.append(spec)
        return out

    # ── engine translation ──
    def engine_fields(self, p: dict) -> dict[str, Any]:
        """Full StrategyConfig kwargs (minus base_timeframe / initial_capital, set by the adapter)."""
        base = {k: v for k, v in R.defaults().items() if k not in R.ENGINE_KEYS}
        base.update(_ROSYADE_OFF)
        own = {k: v for k, v in p.items() if k not in self.ENGINE_KEYS}
        base.update(own)
        base["use_cooldown"] = True          # cooldown_bars = 0 -> no pause (engine: use_cooldown=False blocks entries)
        base["strategy_family"] = self.FAMILY
        return base

    def export(self, ns: dict) -> None:
        """Expose the template API as module-level names of a template module."""
        for name in ("TEMPLATE_ID", "NAME", "DESCRIPTION", "FAMILY", "PARAMS", "PARAM_INDEX", "ENGINE_KEYS",
                     "MTF_KEYS", "SIZING_KEYS"):
            ns[name] = getattr(self, name)
        for name in ("is_mtf", "is_sized", "validate_for_timeframe", "defaults", "tunable_params", "min_warmup",
                     "validate_params", "public_schema", "resolve_search", "engine_fields"):
            ns[name] = getattr(self, name)
        ns["TIMEFRAMES"] = list(TIMEFRAMES)
        ns["HTF_CHOICES"] = list(HTF_CHOICES)
        ns["ParamError"] = ParamError
