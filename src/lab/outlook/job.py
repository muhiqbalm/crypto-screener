"""outlook_refresh job (engine child, bmtm-v2 venv), queued after every 4H close once the
universe_refresh job of that bar is done (fresh 4H cache + Koin Terkuat).

For every coin with a 4H cache (29):
  1. strategies (store.strategies_for): the best PASS preset of ANY template / timeframe is the
     primary strategy; no PASS preset -> the live reference / Rosyade 4H default (honest
     fallback). Other PASS / FAIL presets run too for the agreement panel. Each strategy is one
     engine run on the coin's FULL cached history (path-stable start = first cached bar), with a
     trace hook for the resting SL / TP (replay.traced_run, same as the calibration).
  2. backtest statistics from the primary run's closed trades (holdout window when the preset
     has one, else the full history), by side and by BTC regime at entry (regime.py)
  3. MTF context from bars CLOSED at the 4H close (mtf.py: 1D trend, 1H momentum, BTC regime),
     context factors (screener + track record, funding, OI, headlines), keyakinan from the
     calibration (calib.assess, lab_kv 'outlook_calibration'), the actionable plan, what changed
     since the previous call, and the Indonesian explanation (logic.py)
  4. the call is stored in lab_outlook_calls; every still-open stored call is then walked
     forward over the new 4H bars (evaluate.py): the live track record
Plus the regime payload (BTC + ETH label, per-preset performance by regime) -> lab_kv 'regime'.

Read-only towards everything but lab.db (lab_outlook, lab_outlook_calls, lab_kv) and the parquet
cache refresh. No orders, no Telegram.
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import statistics
import time
from typing import Optional

from .. import db as labdb
from .. import queue as q
from .. import regime as R
from ..db import utcnow
from . import logic as L
from . import mtf as M
from . import sources as SRC
from . import store as S
from .evaluate import evaluate_call

log = logging.getLogger("lab.outlook")
CANDLES_OUT = 150
TRADES_OUT = 20
CALLS_OUT = 30
MAX_EXTRA_RUNS = 40   # engine runs for the agreement panel per job (the primary always runs): keeps the fast job bounded
BTC, ETH = "BTCUSDT", "ETHUSDT"
TF_S = {"15m": 900, "30m": 1800, "1h": 3600, "4h": 14400, "1d": 86400}


def _iso(ts) -> Optional[str]:
    from .. import engine_adapter as ea
    return ea._iso(ts)


def _iso_s(t_s: float) -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(t_s))


def _phash(params: dict) -> str:
    return hashlib.sha1(json.dumps(params, sort_keys=True, default=str).encode()).hexdigest()[:12]


class Runner:
    """Engine runs cached per (symbol, timeframe, template, params, costs); data per (symbol, tf)."""

    def __init__(self, offline: bool):
        self.offline = offline
        self._data: dict[tuple, tuple] = {}
        self._runs: dict[tuple, dict] = {}

    def data(self, symbol: str, tf: str = S.TIMEFRAME, funding: bool = True):
        from .. import data_cache as dc
        key = (symbol, tf)
        if key not in self._data:
            self._data[key] = dc.ensure(symbol, tf, funding=funding, offline=self.offline)
        return self._data[key]

    def closes(self, symbol: str, tf: str) -> Optional[tuple[list, list]]:
        """(open times epoch s, closes) of CLOSED bars (fresh to the last bar: max_stale_bars=0)."""
        from .. import data_cache as dc
        key = (symbol, tf, "closes")
        if key not in self._data:
            try:
                d, _ = dc.ensure(symbol, tf, funding=False, offline=self.offline, max_stale_bars=0)
                self._data[key] = ([int(x.value // 10**9) for x in d["timestamp"]], [float(x) for x in d["close"]])
            except Exception as e:  # noqa: BLE001 - a missing 1d/1h cache only drops that factor
                log.warning("outlook %s %s unavailable: %s", symbol, tf, e)
                self._data[key] = None
        return self._data[key]

    def bars4(self, symbol: str) -> list[tuple]:
        """[(open epoch s, open, high, low, close)] on the 4H grid (for the call evaluation)."""
        key = (symbol, "4h", "bars")
        if key not in self._data:
            o4, _ = self.data(symbol, "4h")
            self._data[key] = list(zip([int(x.value // 10**9) for x in o4["timestamp"]], o4["open"].astype(float),
                                       o4["high"].astype(float), o4["low"].astype(float), o4["close"].astype(float)))
        return self._data[key]

    def run(self, symbol: str, tf: str, template_id: str, params: dict, costs: dict) -> dict:
        key = (symbol, tf, template_id, _phash(params), _phash(costs))
        if key in self._runs:
            return self._runs[key]
        from .. import engine_adapter as ea
        from .replay import positions_by_bar, traced_run
        use_f = bool(costs.get("funding", True))
        ohlcv, fund = self.data(symbol, tf)
        tm = ea.template(template_id)
        p = tm.validate_params(params)
        cfg, ecfg = ea.build_configs(params, tf, costs, template_id)
        if tm.is_mtf(p):
            ltf, _ = self.data(symbol, cfg.entry_tf, funding=False)
            ohlcv = ea.attach_entry_bars(ohlcv, ltf, tf, cfg.entry_tf)
        df, _, _, _ = ea.prepare_frame(ohlcv, fund, tf, None, None, ecfg.warmup_period, use_f)
        res, _, trace = traced_run(df, cfg, ecfg)
        pos = positions_by_bar(res, trace, len(df))
        out = {"df": df, "res": res, "trades": ea.trades_out(res), "params": p, "template_id": template_id,
               "timeframe": tf, "last_state": pos[-1] if pos else None}
        self._runs[key] = out
        return out


# ── strategy position (same extraction as watch_eval.evaluate) ───────────

def position_from_run(run: dict) -> tuple[dict, float]:
    import pandas as pd
    from ..watch_eval import _signal
    df, res, trades, p = run["df"], run["res"], run["trades"], run["params"]
    tf = run.get("timeframe") or "4h"
    tid = run.get("template_id") or S.TEMPLATE_ID
    step = pd.Timedelta(seconds=TF_S.get(tf, 14400))
    last_bar = _iso(df["timestamp"].iloc[-1])
    last_close = _iso(df["timestamp"].iloc[-1] + step)
    price = float(df["close"].iloc[-1])
    op = res.open_position
    st: dict = {"last_bar": last_bar, "last_bar_close": last_close, "side": None, "timeframe": tf, "template_id": tid}
    position = None
    if op:
        position = {"side": op["direction"], "entry_price": op["entry_price"],
                    "entry_time": _iso(op["entry_timestamp"]), "sl": op["sl"], "tp": op["tp"]}
    st["last_signal"] = _signal(position, trades)
    if position:
        side, e = position["side"], float(position["entry_price"])
        s = L.SIDE_SIGN[side]
        trace = run.get("last_state")
        base_sl = trace[6] if trace and trace[6] is not None else None
        if base_sl is None and tid == S.TEMPLATE_ID:
            sl_pct = p["long_sl_pct"] if side == "long" else p["short_sl_pct"]
            base_sl = e * (1 - s * sl_pct / 100.0)
        r_unit = abs(e - base_sl) if base_sl is not None else None

        def lvl(use_key, pct_key):
            return e * (1 + s * p[pct_key] / 100.0) if tid == S.TEMPLATE_ID and p.get(use_key) else None

        sl, tp = position["sl"], position["tp"]
        entry_at = _iso(pd.Timestamp(position["entry_time"]) + step)
        st.update({
            "side": side, "entry_price": e, "entry_time": position["entry_time"], "entry_at": entry_at,
            "sl": sl, "tp": tp, "base_sl": base_sl,
            "tp1": lvl(f"use_{side}_tp1", f"{side}_tp1_pct"), "tp2": lvl(f"use_{side}_tp2", f"{side}_tp2_pct"),
            "breakeven_locked": bool(op.get("breakeven_locked")),
            "bars_in_trade": int(len(df) - 1 - int(op.get("entry_bar_index", len(df) - 1))),
            "fresh": position["entry_time"] == last_bar,
            "open_pnl_pct": (price / e - 1.0) * 100.0 * s,
            "dist_sl_pct": (price - sl) / price * 100.0 * s if sl else None,
            "dist_tp_pct": (tp - price) / price * 100.0 * s if tp else None,
            "r_unit_pct": r_unit / e * 100.0 if r_unit else None,
            "dist_sl_r": abs(price - sl) / r_unit if sl and r_unit else None,
            "dist_tp_r": abs(tp - price) / r_unit if tp and r_unit else None,
            "open_r": (price - e) * s / r_unit if r_unit else None,
        })
    elif trades:
        t = trades[-1]
        st["last_exit"] = {"time": t["exit_time"], "side": t["side"], "reason": t["exit_reason"],
                           "pnl_pct": t["pnl_pct"], "entry_price": t["entry_price"], "exit_price": t["exit_price"]}
    return st, price


# ── backtest statistics ──────────────────────────────────────────────────

def trade_stats(trades: list[dict], bar_hours: float = 4.0) -> dict:
    xs = [t["pnl_pct"] for t in trades if t.get("pnl_pct") is not None]
    wins = [x for x in xs if x > 0]
    losses = [x for x in xs if x <= 0]
    holds = [t["bars_held"] * bar_hours for t in trades if t.get("bars_held") is not None]
    return {
        "n": len(xs),
        "win_rate_pct": len(wins) / len(xs) * 100.0 if xs else None,
        "avg_win_pct": sum(wins) / len(wins) if wins else None,
        "avg_loss_pct": sum(losses) / len(losses) if losses else None,
        "mean_pct": sum(xs) / len(xs) if xs else None,
        "median_hold_hours": statistics.median(holds) if holds else None,
    }


def backtest_block(trades: list[dict], preset: Optional[dict], idx: R.RegimeIndex, tf: str = "4h") -> dict:
    bh = TF_S.get(tf, 14400) / 3600.0
    hs = (preset or {}).get("holdout_start")
    if hs:
        basis_trades = [t for t in trades if (t.get("entry_time") or "") >= hs[:19] + "Z"]
        basis = "holdout"
        text = (f"periode holdout {L.fdate(hs, False, True)} – {L.fdate(preset.get('holdout_end'), False, True)}, out-of-sample"
                + (", holdout tercemar" if preset.get("contaminated") else ""))
    else:
        basis_trades, basis = trades, "full_in_sample"
        first = trades[0]["entry_time"] if trades else None
        text = (f"seluruh riwayat sejak {L.fdate(first, False, True)} "
                + ("(in-sample, preset tanpa uji holdout)" if preset else "(setting default, belum divalidasi untuk koin ini)"))
    out = {"basis": basis, "basis_text": text, **trade_stats(basis_trades, bh),
           "by_side": {s: trade_stats([t for t in basis_trades if t["side"] == s], bh) for s in ("long", "short")},
           "full": trade_stats(trades, bh),
           "by_regime": R.perf_by_regime(trades, idx), "by_regime_basis": "seluruh riwayat (in-sample)",
           "first_trade": trades[0]["entry_time"] if trades else None}
    return out


# ── per-coin row ─────────────────────────────────────────────────────────

def _watch_check(conn, symbol: str, tf: str, params: dict) -> Optional[dict]:
    from ..presets import params_match
    for w in conn.execute("SELECT w.id, w.params_json, s.position_json, s.error FROM watches w "
                          "LEFT JOIN watch_state s ON s.watch_id=w.id WHERE w.active=1 AND w.symbol=? "
                          "AND w.timeframe=? ORDER BY w.id", (symbol, tf)):
        if w["error"] is None and params_match(labdb.loads(w["params_json"], {}), params):
            pos = labdb.loads(w["position_json"])
            return {"watch_id": w["id"], "side": (pos or {}).get("side")}
    return None


def mtf_context(runner: Runner, symbol: str, close_s: float, idx: R.RegimeIndex) -> tuple[dict, dict]:
    """({tren_1d, momentum_1h} states, {factor: absolute direction}) from bars closed at close_s."""
    states: dict = {"tren_1d": None, "momentum_1h": None}
    d1 = runner.closes(symbol, "1d")
    if d1:
        i = M.last_closed(d1[0], 86400, close_s)
        if i >= 0:
            states["tren_1d"] = M.trend_at(d1[1], M.ema_series(d1[1][:i + 1], M.TREND_EMA), i)
    h1 = runner.closes(symbol, "1h")
    if h1:
        i = M.last_closed(h1[0], 3600, close_s)
        if i >= 0:
            c = h1[1][:i + 1]
            states["momentum_1h"] = M.momentum_at(c, M.ema_series(c, M.MOM_FAST), M.ema_series(c, M.MOM_SLOW), i)
    dirs = {"tren_1d": (states["tren_1d"] or {}).get("direction"),
            "momentum_1h": (states["momentum_1h"] or {}).get("direction"),
            "regime_btc": M.regime_dir(idx.label_at(_iso_s(close_s)))}
    return states, dirs


def _strategy_state(conn, symbol: str, runner: Runner, d: dict) -> tuple[dict, float, dict]:
    from ..presets import DEFAULT_COSTS
    costs = d.get("costs") or dict(DEFAULT_COSTS)
    run = runner.run(symbol, d["timeframe"], d["template_id"], d["params"], costs)
    st, price = position_from_run(run)
    brief = S.preset_brief(d.get("preset"))
    st.update({"template_id": d["template_id"], "timeframe": d["timeframe"], "preset": brief, "name": d["name"],
               "param_source": "preset" if d.get("preset") else "template_default", "primary": d.get("primary")})
    st["evidence"] = L.strategy_evidence(st)
    return st, price, run


def build_row(conn, symbol: str, runner: Runner, presets: list[dict], ctx_common: dict) -> tuple[dict, dict, dict]:
    from ..templates import TEMPLATES
    from ..templates import rosyade_family as T
    descs = S.strategies_for(presets, symbol, templates=set(TEMPLATES), default_params=T.defaults())
    strategies = []
    st = price = run = None
    budget = ctx_common.setdefault("_extra_runs", {"left": MAX_EXTRA_RUNS})
    for d in descs:
        if not d.get("primary"):
            if budget["left"] <= 0:
                strategies.append({"name": d["name"], "template_id": d["template_id"], "timeframe": d["timeframe"],
                                   "verdict": (d.get("preset") or {}).get("verdict"), "primary": False,
                                   "error": "tidak dihitung (batas jumlah run per refresh)"})
                continue
            budget["left"] -= 1
        try:
            s_st, s_price, s_run = _strategy_state(conn, symbol, runner, d)
        except Exception as e:  # noqa: BLE001 - one broken preset must not hide the coin
            if d.get("primary"):
                raise
            log.warning("outlook %s strategy %s failed: %s", symbol, d["name"], e)
            strategies.append({"name": d["name"], "template_id": d["template_id"], "timeframe": d["timeframe"],
                               "verdict": (d.get("preset") or {}).get("verdict"), "primary": False,
                               "error": f"{type(e).__name__}: {str(e)[:160]}"})
            continue
        if d.get("primary"):
            st, price, run = s_st, s_price, s_run
        strategies.append({"name": d["name"], "template_id": d["template_id"], "timeframe": d["timeframe"],
                           "verdict": (d.get("preset") or {}).get("verdict"), "evidence": s_st["evidence"],
                           "primary": bool(d.get("primary")), "side": s_st.get("side"),
                           "entry_at": s_st.get("entry_at"), "entry_price": s_st.get("entry_price"),
                           "sl": s_st.get("sl"), "tp": s_st.get("tp"), "fresh": bool(s_st.get("fresh")),
                           "last_bar": s_st.get("last_bar"), "contaminated": (s_st.get("preset") or {}).get("contaminated")})
    # the call is made at the coin's last CLOSED 4H bar
    bars4 = runner.bars4(symbol)
    call_bar_s = bars4[-1][0]
    close_s = call_bar_s + 4 * 3600
    price4 = bars4[-1][4]
    if (run or {}).get("timeframe") != "4h":
        price = price4
    wc = _watch_check(conn, symbol, st["timeframe"], run["params"])
    if wc:
        wc["agrees"] = wc["side"] == st["side"]
        st["watch_check"] = wc
    bt = backtest_block(run["trades"], st.get("preset"), ctx_common["regime_index"], st["timeframe"])
    mtf_states, dirs = mtf_context(runner, symbol, close_s, ctx_common["regime_index"])
    sr = ctx_common["strength"].get(symbol)
    sc = ctx_common["screener"].get(symbol)
    if sc and ctx_common.get("screener_bar"):
        sc = {**sc, "age_hours": L.hours_between(ctx_common["screener_bar"], utcnow())}
    heads = SRC.headlines_for(ctx_common["headlines"], symbol) if ctx_common["headlines"] is not None else None
    calib = ctx_common.get("calibration")
    lifts = ((calib or {}).get("factor_lift") or {}).get("pool")
    ctx = {"strategy": st, "mtf": mtf_states, "regime": ctx_common["regime"], "regime_dir_at_call": dirs["regime_btc"],
           "lifts": lifts, "screener": sc, "track": ctx_common["track"], "strength": sr,
           "oi": ctx_common["oi"].get(symbol), "headlines": heads, "fear_greed": ctx_common["fear_greed"]}
    factors = L.build_factors(ctx)
    now = utcnow()
    bias = L.combine(factors, st, calib, now_iso=now, price=price)
    pl = L.plan(st, price, bias, now_iso=now)
    df = run["df"]
    per_coin = ((calib or {}).get("per_coin") or {}).get(symbol) or {}
    cls, side, fase = bias.get("cls"), st.get("side"), bias.get("fase")
    coin_stats = None
    if side and cls:
        coin_stats = {"key": f"{cls}|{side}|{fase}", "fase": per_coin.get(f"{cls}|{side}|{fase}"),
                      "side": per_coin.get(f"{cls}|{side}")}
    row = {
        "schema_version": L.SCHEMA_VERSION,
        "symbol": symbol, "coin": SRC.coin_of(symbol), "computed_at": now, "last_bar": _iso_s(call_bar_s),
        "last_bar_close": _iso_s(close_s), "price": price, "price_source": "close candle 4H terakhir",
        "strategy": st, "strategies": strategies, "agreement": L.agreement(strategies), "backtest": bt,
        "factors": factors, "bias": bias, "plan": pl, "mtf": {"states": mtf_states, "dirs": dirs},
        "coin_calibration": coin_stats,
        "market": {"strength": sr and {k: sr.get(k) for k in ("rank", "score", "trend", "ema_dist_pct", "ret_1d_pct",
                                                               "ret_7d_pct", "ret_30d_pct", "ret_90d_pct",
                                                               "vol_ann_pct", "funding_7d_apr_pct")},
                   "screener": sc, "oi": ctx_common["oi"].get(symbol), "headline_count": len(heads or [])},
    }
    row["peluang"] = L.peluang(row)
    call = {
        "symbol": symbol, "bar": row["last_bar"], "bar_close": row["last_bar_close"], "computed_at": now,
        "side": side, "keyakinan": bias.get("keyakinan"), "keyakinan_basis": bias.get("basis"), "cls": cls,
        "align": bias.get("align"), "fase": fase if side else None, "strategy": st.get("name"),
        "template_id": st.get("template_id"), "timeframe": st.get("timeframe"),
        "strategy_entry_time": st.get("entry_time"), "price": price, "sl": st.get("sl") if side else None,
        "tp": st.get("tp") if side else None, "horizon_bars": pl.get("horizon_bars"), "rr": pl.get("rr"),
        "ev_r": row["peluang"].get("score"),
        "call_json": {"dirs": dirs, "zone": pl.get("entry_zone"), "calib_key": (bias.get("calib") or {}).get("key"),
                      "mean_r": ((bias.get("calib") or {}).get("stats") or {}).get("mean_r"),
                      "n_pos": ((bias.get("calib") or {}).get("stats") or {}).get("n_pos"),
                      "action": pl.get("action")},
    }
    prev = S.prev_call(conn, symbol, call["bar"])
    row["changes"] = L.changes(call, prev)
    row["previous_call"] = prev and {k: prev.get(k) for k in ("bar", "side", "keyakinan", "sl", "tp", "price", "status")}
    row["explanation"] = L.narrate(row)
    tail = df.tail(CANDLES_OUT)
    candles = [[int(ts.value // 10**9), float(o), float(h), float(lo), float(c)]
               for ts, o, h, lo, c in zip(tail["timestamp"], tail["open"], tail["high"], tail["low"], tail["close"])]
    detail = {"candles": candles, "candles_tf": st["timeframe"], "recent_trades": run["trades"][-TRADES_OUT:],
              "headlines": heads or [], "params": run["params"], "costs": None}
    return row, detail, call


# ── stored calls: after-the-fact evaluation ──────────────────────────────

def evaluate_open_calls(conn, runner: Runner, symbols: Optional[set] = None) -> dict:
    """Walk every still-open stored call forward over the 4H bars that closed since."""
    out = {"evaluated": 0, "resolved": 0, "errors": 0}
    now = utcnow()
    for c in S.open_calls(conn):
        sym = c["symbol"]
        if symbols is not None and sym not in symbols:
            continue
        try:
            bars = runner.bars4(sym)
        except Exception:  # noqa: BLE001
            out["errors"] += 1
            continue
        opens = [b[0] for b in bars]
        t_call = labdb_epoch(c["bar"])
        try:
            k = opens.index(int(t_call))
        except ValueError:
            continue
        hz = int(c.get("horizon_bars") or L.horizon_bars(c.get("timeframe")))
        after = [b[1:] for b in bars[k + 1:k + 1 + hz]]
        invalid_at = None
        for lc in S.later_calls(conn, sym, c["bar"]):
            if lc["side"] != c["side"] or lc["strategy_entry_time"] != c["strategy_entry_time"] \
                    or lc["strategy"] != c["strategy"]:
                t = labdb_epoch(lc["bar"])
                if int(t) in opens:
                    invalid_at = opens.index(int(t)) - k
                break
        ev = evaluate_call(c["side"], c["price"], c["sl"], c["tp"], after, hz,
                           invalid_at=invalid_at if invalid_at and invalid_at > 0 else None)
        if ev["status"] in ("tp", "sl", "batal", "expired"):
            ev["resolved_at"] = _iso_s(opens[k] + 4 * 3600 * (1 + ev["bars"]))
            out["resolved"] += 1
        S.set_outcome(conn, c["id"], ev, now)
        out["evaluated"] += 1
    conn.commit()
    return out


def labdb_epoch(iso: str) -> float:
    from datetime import datetime, timezone
    return datetime.strptime(iso[:19], "%Y-%m-%dT%H:%M:%S").replace(tzinfo=timezone.utc).timestamp()


# ── regime payload ───────────────────────────────────────────────────────

def regime_payload(runner: Runner, presets: list[dict], btc_series: list[dict], eth_series: list[dict],
                   idx: R.RegimeIndex) -> dict:
    from ..presets import DEFAULT_COSTS
    out_presets = []
    for p in presets:
        if p["template_id"] != S.TEMPLATE_ID or p["timeframe"] != S.TIMEFRAME:
            continue
        try:
            run = runner.run(p["symbol"], p["timeframe"], p["template_id"], p["params"],
                             p.get("costs") or dict(DEFAULT_COSTS))
        except Exception as e:  # noqa: BLE001
            out_presets.append({"id": p["id"], "name": p["name"], "symbol": p["symbol"], "verdict": p.get("verdict"),
                                "error": f"{type(e).__name__}: {e}"})
            continue
        hs = (p.get("holdout") or {}).get("start")
        hold = [t for t in run["trades"] if hs and (t.get("entry_time") or "") >= hs[:19] + "Z"]
        out_presets.append({"id": p["id"], "name": p["name"], "symbol": p["symbol"], "verdict": p.get("verdict"),
                            "live_reference": p.get("live_reference"), "n_trades": len(run["trades"]),
                            "perf": R.perf_by_regime(run["trades"], idx),
                            "holdout_start": hs, "holdout_perf": R.perf_by_regime(hold, idx) if hs else None})
    btc = R.current(btc_series, BTC)
    lab = [x["label"] for x in btc_series if not x.get("warmup")]
    share = {k: (lab.count(k) / len(lab) * 100.0 if lab else None) for k in R.LABELS}
    return {"computed_at": utcnow(), "rule": R.RULE, "params": {"ema_fast": R.EMA_FAST, "ema_slow": R.EMA_SLOW,
                                                                 "slope_days": R.SLOPE_DAYS, "min_trades": R.MIN_TRADES},
            "btc": btc, "eth": R.current(eth_series, ETH), "btc_history_share_pct": share,
            "presets": out_presets,
            "note": "Kinerja per kondisi pasar dari backtest seluruh riwayat (in-sample) dan, jika ada, periode "
                    "holdout. Trade diklasifikasikan menurut label BTC saat entry. Bukan jaminan."}


# ── job ──────────────────────────────────────────────────────────────────

def _symbols() -> list[str]:
    from ..data_cache import cached_datasets
    return sorted({v["symbol"] for v in cached_datasets().values() if v["timeframe"] == S.TIMEFRAME})


def execute(conn, job: Optional[dict] = None, symbols: Optional[list[str]] = None) -> dict:
    from .. import data_cache as dc
    from .. import engine_adapter as ea
    from ..presets import list_presets
    from ..universal import strength as STR
    from .replay import load as load_calibration
    t0 = time.time()
    S.ensure_schema(conn)
    offline = os.environ.get("LAB_DATA_OFFLINE") == "1"
    job_id = (job or {}).get("id")

    def prog(stage, done=0, total=0):
        if job_id:
            q.set_progress(conn, job_id, {"stage": stage, "done": done, "total": total})

    prog("regime")
    series = {}
    for sym in (BTC, ETH):
        try:
            d1, _ = dc.ensure(sym, "1d", funding=False, offline=offline, max_stale_bars=0)
            series[sym] = R.label_series(d1)
        except Exception as e:  # noqa: BLE001
            log.warning("regime data %s failed: %s", sym, e)
            series[sym] = []
    idx = R.RegimeIndex(series[BTC])
    btc_now = R.current(series[BTC], BTC) if series[BTC] else None

    presets = list_presets(conn)
    strength = {r["symbol"]: r for r in ((STR.load() or {}).get("rows") or [])}
    screener, screener_bar = S.screener_snapshot(conn)
    track, track_info = S.track_map(conn)
    calibration = load_calibration(conn)
    prog("context")
    headlines = None if offline else SRC.fetch_headlines()
    fear_greed = None if offline else SRC.fetch_fear_greed()
    syms = symbols or _symbols()
    oi: dict[str, dict] = {}
    if not offline:
        for k, sym in enumerate(syms):
            prog("open interest", k, len(syms))
            r = SRC.oi_change(sym)
            if r:
                oi[sym] = r
            time.sleep(0.1)
    common = {"regime": btc_now, "regime_index": idx, "strength": strength, "screener": screener,
              "screener_bar": screener_bar, "track": track, "headlines": headlines, "fear_greed": fear_greed, "oi": oi,
              "calibration": calibration}
    runner = Runner(offline)
    errors: dict[str, str] = {}
    last_bars, n_calls = [], 0
    for k, sym in enumerate(syms):
        prog("coins", k, len(syms))
        try:
            row, detail, call = build_row(conn, sym, runner, presets, common)
            S.save_row(conn, sym, row, detail)
            S.save_call(conn, call)
            n_calls += 1 if call.get("side") else 0
            last_bars.append(row["last_bar"])
        except Exception as e:  # noqa: BLE001
            log.exception("outlook %s failed", sym)
            errors[sym] = f"{type(e).__name__}: {str(e)[:200]}"
            S.save_row(conn, sym, None, None, errors[sym])
        conn.commit()
    prog("rekam jejak", len(syms), len(syms))
    try:
        track_eval = evaluate_open_calls(conn, runner, set(syms))
    except Exception as e:  # noqa: BLE001
        log.exception("outlook call evaluation failed")
        track_eval = {"error": f"{type(e).__name__}: {e}"}
    prog("regime presets", len(syms), len(syms))
    try:
        R.save(conn, regime_payload(runner, presets, series[BTC], series[ETH], idx))
    except Exception as e:  # noqa: BLE001
        log.exception("regime payload failed")
        errors["_regime"] = f"{type(e).__name__}: {e}"
    meta = {
        "computed_at": utcnow(), "runtime_s": round(time.time() - t0, 1), "symbols": len(syms),
        "ok": len(syms) - len([s for s in errors if not s.startswith("_")]), "errors": errors,
        "last_bar": max(last_bars) if last_bars else None, "engine_commit": ea.engine_commit(),
        "fear_greed": fear_greed, "news": {"available": headlines is not None, "items": len(headlines or []),
                                           "source": "CoinTelegraph RSS"},
        "screener_bar": screener_bar, "track_record": track_info,
        "strength_computed_at": (STR.load() or {}).get("computed_at"), "regime": btc_now and
        {k: btc_now.get(k) for k in ("label", "label_text", "as_of", "days_in_label")},
        "oi_available": len(oi), "offline": offline, "schema_version": L.SCHEMA_VERSION,
        "calibration": calibration and {k: calibration.get(k) for k in ("computed_at", "counts", "version")},
        "calls": n_calls, "call_evaluation": track_eval,
    }
    S.kv_set(conn, S.META_KEY, meta)
    conn.commit()
    if errors and len([s for s in errors if not s.startswith("_")]) == len(syms):
        raise RuntimeError(f"outlook failed for every coin: {next(iter(errors.values()))}")
    return meta
