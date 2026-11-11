"""outlook_refresh job (engine child, bmtm-v2 venv), queued after every 4H close once the
universe_refresh job of that bar is done (fresh 4H cache + Koin Terkuat).

For every coin with a 4H cache (29):
  1. strategy position now: the Rosyade-family engine on that coin's FULL cached 4H history
     (path-stable start = first cached bar), with the coin's own preset (PASS preferred) or the
     template defaults. Same position extraction as the watch evaluation (watch_eval).
     No watches are created; nothing touches paper accounts.
  2. backtest statistics from the same run's closed trades (holdout window when the preset has
     one, else the full history), by side and by BTC regime at entry (regime.py)
  3. factors (screener snapshot + track record, Koin Terkuat, funding, OI, BTC regime, headlines),
     bias / keyakinan and the Indonesian explanation (logic.py)
Plus the regime payload (BTC + ETH label, per-preset performance by regime) -> lab_kv 'regime'.

Read-only towards everything but lab.db (lab_outlook, lab_kv) and the parquet cache refresh.
No orders, no Telegram.
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
from . import sources as SRC
from . import store as S

log = logging.getLogger("lab.outlook")
CANDLES_OUT = 150
TRADES_OUT = 20
BTC, ETH = "BTCUSDT", "ETHUSDT"


def _iso(ts) -> Optional[str]:
    from .. import engine_adapter as ea
    return ea._iso(ts)


def _phash(params: dict) -> str:
    return hashlib.sha1(json.dumps(params, sort_keys=True, default=str).encode()).hexdigest()[:12]


class Runner:
    """Engine runs cached per (symbol, params) so presets sharing params run once."""

    def __init__(self, offline: bool):
        self.offline = offline
        self._data: dict[str, tuple] = {}
        self._runs: dict[tuple, dict] = {}

    def data(self, symbol: str):
        from .. import data_cache as dc
        if symbol not in self._data:
            self._data[symbol] = dc.ensure(symbol, S.TIMEFRAME, funding=True, offline=self.offline)
        return self._data[symbol]

    def run(self, symbol: str, params: dict, costs: dict) -> dict:
        key = (symbol, _phash(params), _phash(costs))
        if key in self._runs:
            return self._runs[key]
        from .. import engine_adapter as ea
        ohlcv, fund = self.data(symbol)
        cfg, ecfg = ea.build_configs(params, S.TIMEFRAME, costs)
        df, _, _, _ = ea.prepare_frame(ohlcv, fund, S.TIMEFRAME, None, None, ecfg.warmup_period,
                                       bool(costs.get("funding", True)))
        res, _ = ea.run(df, cfg, ecfg)
        out = {"df": df, "res": res, "trades": ea.trades_out(res), "params": ea.T.validate_params(params)}
        self._runs[key] = out
        return out


# ── strategy position (same extraction as watch_eval.evaluate) ───────────

def position_from_run(run: dict) -> dict:
    import pandas as pd
    from ..watch_eval import _signal
    df, res, trades, p = run["df"], run["res"], run["trades"], run["params"]
    last_bar = _iso(df["timestamp"].iloc[-1])
    last_close = _iso(df["timestamp"].iloc[-1] + pd.Timedelta(hours=4))
    price = float(df["close"].iloc[-1])
    op = res.open_position
    st: dict = {"last_bar": last_bar, "last_bar_close": last_close, "side": None}
    position = None
    if op:
        position = {"side": op["direction"], "entry_price": op["entry_price"],
                    "entry_time": _iso(op["entry_timestamp"]), "sl": op["sl"], "tp": op["tp"]}
    st["last_signal"] = _signal(position, trades)
    if position:
        side, e = position["side"], float(position["entry_price"])
        s = L.SIDE_SIGN[side]
        sl_pct = p["long_sl_pct"] if side == "long" else p["short_sl_pct"]
        base_sl = e * (1 - s * sl_pct / 100.0)
        r_unit = abs(e - base_sl)

        def lvl(use_key, pct_key):
            return e * (1 + s * p[pct_key] / 100.0) if p.get(use_key) else None

        sl, tp = position["sl"], position["tp"]
        entry_at = _iso(pd.Timestamp(position["entry_time"]) + pd.Timedelta(hours=4))
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

def trade_stats(trades: list[dict]) -> dict:
    xs = [t["pnl_pct"] for t in trades if t.get("pnl_pct") is not None]
    wins = [x for x in xs if x > 0]
    losses = [x for x in xs if x <= 0]
    holds = [t["bars_held"] * 4 for t in trades if t.get("bars_held") is not None]
    return {
        "n": len(xs),
        "win_rate_pct": len(wins) / len(xs) * 100.0 if xs else None,
        "avg_win_pct": sum(wins) / len(wins) if wins else None,
        "avg_loss_pct": sum(losses) / len(losses) if losses else None,
        "mean_pct": sum(xs) / len(xs) if xs else None,
        "median_hold_hours": statistics.median(holds) if holds else None,
    }


def backtest_block(trades: list[dict], preset: Optional[dict], idx: R.RegimeIndex) -> dict:
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
    out = {"basis": basis, "basis_text": text, **trade_stats(basis_trades),
           "by_side": {s: trade_stats([t for t in basis_trades if t["side"] == s]) for s in ("long", "short")},
           "full": trade_stats(trades),
           "by_regime": R.perf_by_regime(trades, idx), "by_regime_basis": "seluruh riwayat (in-sample)",
           "first_trade": trades[0]["entry_time"] if trades else None}
    return out


# ── per-coin row ─────────────────────────────────────────────────────────

def _watch_check(conn, symbol: str, params: dict) -> Optional[dict]:
    from ..presets import params_match
    for w in conn.execute("SELECT w.id, w.params_json, s.position_json, s.error FROM watches w "
                          "LEFT JOIN watch_state s ON s.watch_id=w.id WHERE w.active=1 AND w.symbol=? "
                          "AND w.timeframe=? ORDER BY w.id", (symbol, S.TIMEFRAME)):
        if w["error"] is None and params_match(labdb.loads(w["params_json"], {}), params):
            pos = labdb.loads(w["position_json"])
            return {"watch_id": w["id"], "side": (pos or {}).get("side")}
    return None


def build_row(conn, symbol: str, runner: Runner, presets: list[dict], ctx_common: dict) -> tuple[dict, dict]:
    from ..templates import rosyade_family as T
    from ..presets import DEFAULT_COSTS
    preset = S.pick_preset(presets, symbol)
    params = preset["params"] if preset else T.defaults()
    costs = (preset or {}).get("costs") or dict(DEFAULT_COSTS)
    brief = S.preset_brief(preset)
    run = runner.run(symbol, params, costs)
    st, price = position_from_run(run)
    st.update({"template_id": S.TEMPLATE_ID, "timeframe": S.TIMEFRAME, "preset": brief,
               "param_source": "preset" if preset else "template_default"})
    st["evidence"] = L.strategy_evidence(st)
    wc = _watch_check(conn, symbol, run["params"])
    if wc:
        wc["agrees"] = wc["side"] == st["side"]
        st["watch_check"] = wc
    bt = backtest_block(run["trades"], brief, ctx_common["regime_index"])
    sr = ctx_common["strength"].get(symbol)
    sc = ctx_common["screener"].get(symbol)
    if sc and ctx_common.get("screener_bar"):
        sc = {**sc, "age_hours": L.hours_between(ctx_common["screener_bar"], utcnow())}
    heads = SRC.headlines_for(ctx_common["headlines"] or [], symbol) if ctx_common["headlines"] is not None else []
    ctx = {"strategy": st, "screener": sc, "track": ctx_common["track"], "strength": sr,
           "oi": ctx_common["oi"].get(symbol), "regime": ctx_common["regime"], "regime_perf": bt["by_regime"],
           "headlines": heads, "fear_greed": ctx_common["fear_greed"]}
    factors = L.build_factors(ctx)
    bias = L.combine(factors, st, ctx_common["regime"], bt["by_regime"], now_iso=utcnow())
    df = run["df"]
    row = {
        "symbol": symbol, "coin": SRC.coin_of(symbol), "computed_at": utcnow(), "last_bar": st["last_bar"],
        "last_bar_close": st["last_bar_close"], "price": price, "price_source": "close candle 4H terakhir",
        "strategy": st, "backtest": bt, "factors": factors, "bias": bias,
        "market": {"strength": sr and {k: sr.get(k) for k in ("rank", "score", "trend", "ema_dist_pct", "ret_1d_pct",
                                                               "ret_7d_pct", "ret_30d_pct", "ret_90d_pct",
                                                               "vol_ann_pct", "funding_7d_apr_pct")},
                   "screener": sc, "oi": ctx_common["oi"].get(symbol), "headline_count": len(heads)},
    }
    row["explanation"] = L.narrate(row)
    tail = df.tail(CANDLES_OUT)
    candles = [[int(ts.value // 10**9), float(o), float(h), float(lo), float(c)]
               for ts, o, h, lo, c in zip(tail["timestamp"], tail["open"], tail["high"], tail["low"], tail["close"])]
    detail = {"candles": candles, "recent_trades": run["trades"][-TRADES_OUT:], "headlines": heads,
              "params": run["params"], "costs": costs}
    return row, detail


# ── regime payload ───────────────────────────────────────────────────────

def regime_payload(runner: Runner, presets: list[dict], btc_series: list[dict], eth_series: list[dict],
                   idx: R.RegimeIndex) -> dict:
    out_presets = []
    for p in presets:
        if p["template_id"] != S.TEMPLATE_ID or p["timeframe"] != S.TIMEFRAME:
            continue
        try:
            run = runner.run(p["symbol"], p["params"], p.get("costs") or {})
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
    # share of history in each label (context for the per-regime numbers)
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
            d1, _ = dc.ensure(sym, "1d", funding=False, offline=offline)
            series[sym] = R.label_series(d1)
        except Exception as e:  # noqa: BLE001
            log.warning("regime data %s failed: %s", sym, e)
            series[sym] = []
    idx = R.RegimeIndex(series[BTC])
    btc_now = R.current(series[BTC], BTC) if series[BTC] else None

    presets = list_presets(conn, template_id=S.TEMPLATE_ID)
    strength = {r["symbol"]: r for r in ((STR.load() or {}).get("rows") or [])}
    screener, screener_bar = S.screener_snapshot(conn)
    track, track_info = S.track_map(conn)
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
              "screener_bar": screener_bar, "track": track, "headlines": headlines, "fear_greed": fear_greed, "oi": oi}
    runner = Runner(offline)
    errors: dict[str, str] = {}
    last_bars = []
    for k, sym in enumerate(syms):
        prog("coins", k, len(syms))
        try:
            row, detail = build_row(conn, sym, runner, presets, common)
            S.save_row(conn, sym, row, detail)
            last_bars.append(row["last_bar"])
        except Exception as e:  # noqa: BLE001
            log.exception("outlook %s failed", sym)
            errors[sym] = f"{type(e).__name__}: {str(e)[:200]}"
            S.save_row(conn, sym, None, None, errors[sym])
        conn.commit()
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
        "oi_available": len(oi), "offline": offline,
    }
    S.kv_set(conn, S.META_KEY, meta)
    conn.commit()
    if errors and len([s for s in errors if not s.startswith("_")]) == len(syms):
        raise RuntimeError(f"outlook failed for every coin: {next(iter(errors.values()))}")
    return meta
