"""Point-in-time historical replay of the Outlook -> calibration (engine child, pandas).

Job kind ``outlook_calibrate`` (heavy: NOT a fast-lane kind; weekly + on demand) and a CLI
for offline measurement:

    LAB_ENGINE_PATH=<engine> LAB_DATA_DIR=<cache> LAB_DATA_OFFLINE=1 \
        python -m src.lab.outlook.replay --db <lab.db copy> --out calib.json --workers 2

For every coin and every strategy the live Outlook can pick (template default
Rosyade 4H, PASS / FAIL presets of any template and timeframe):

  1. ONE engine run over the full cached history (the same path-stable start as the
     live job). A trace hook records the resting SL / TP after every bar, so the
     state at each bar equals what a run truncated at that bar would report
     (checked by ``verify_trace`` and a test) - no look-ahead, no re-runs.
  2. At every 4H close where the strategy holds a position, the call the live page
     would have shown: side, entry = that close, SL / TP = the resting levels,
     MTF factor states from bars CLOSED at that time (mtf.py), BTC regime label
     valid at that time (regime.py).
  3. The call is walked forward (evaluate.py): TP first / SL first / batal
     (strategy closed) / expired after the horizon.
  4. Cases are aggregated into buckets (calib.py) and stored in lab_kv
     ``outlook_calibration``; a time split (train < SPLIT <= test) checks that
     keyakinan labels derived on old data still rank outcomes on newer data, for the
     v2 rule (class x side x fase) and, for the record, the a-priori MTF-alignment rule.

Honesty rules: PASS / FAIL presets only contribute calls from their holdout period
(out-of-sample); the default on ETH (designed on ETH 4H) is in-sample and kept out
of the pooled classes; news, open interest and the screener have no honest history
and are NOT part of the replay (stated in the payload).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import logging
import os
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

from . import calib as C
from . import mtf as M
from .evaluate import evaluate_call

log = logging.getLogger("lab.outlook.replay")

JOB_KIND = "outlook_calibrate"
KV_KEY = "outlook_calibration"
CALIB_VERSION = 1
BAR4_S = 4 * 3600
TF_S = {"15m": 900, "30m": 1800, "1h": 3600, "4h": 14400, "1d": 86400}
HORIZON_HOURS = {"15m": 24, "30m": 48, "1h": 72, "4h": 168, "1d": 720}
SPLIT_ISO = "2024-07-01T00:00:00Z"         # train < split <= test (fixed before running)
FUND_HIGH_APR, FUND_LOW_APR = 30.0, -5.0   # 7-day funding APR: crowded longs / shorts (lift table only)
DEFAULT_TEMPLATE = "rosyade_family"
DEFAULT_TF = "4h"
INSAMPLE_DEFAULT = {"ETHUSDT"}             # the default params were designed on ETH 4H
EXCLUDED = [
    {"factor": "berita", "reason": "Headline RSS hanya tersedia beberapa hari terakhir; tidak ada arsip per koin."},
    {"factor": "open interest", "reason": "Riwayat OI Binance hanya ~30 hari; tidak cukup untuk diuji ulang."},
    {"factor": "screener komposit", "reason": "Snapshot screener baru tersimpan sejak Catatan Sinyal aktif; "
                                              "rekam jejaknya dinilai terpisah di Catatan Sinyal."},
    {"factor": "funding (sinyal screener)", "reason": "Sinyal funding versi screener tidak punya arsip; versi "
                                                      "sederhana (APR 7 hari) diuji ulang hanya sebagai tabel lift."},
]


def horizon_bars(tf: str) -> int:
    return max(1, HORIZON_HOURS.get(tf, 168) // 4)


def _iso(t_s: float) -> str:
    return datetime.fromtimestamp(t_s, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _epoch(iso: Optional[str]) -> Optional[float]:
    if not iso:
        return None
    return datetime.strptime(iso[:19], "%Y-%m-%dT%H:%M:%S").replace(tzinfo=timezone.utc).timestamp()


def _phash(obj) -> str:
    return hashlib.sha1(json.dumps(obj, sort_keys=True, default=str).encode()).hexdigest()[:12]


# ── strategy configs ─────────────────────────────────────────────────────

@dataclass
class Cfg:
    symbol: str
    template_id: str
    timeframe: str
    params: dict
    costs: dict
    cls: str                         # lolos_uji | belum_diuji | gagal_uji | in_sample
    names: list = field(default_factory=list)
    oos_start: Optional[str] = None  # holdout start (presets): calls before it are not counted
    contaminated: bool = False

    @property
    def key(self) -> str:
        return f"{self.symbol}|{self.template_id}|{self.timeframe}|{_phash(self.params)}"


def preset_class(p: dict) -> Optional[str]:
    v = p.get("verdict")
    return "lolos_uji" if v == "PASS" else "gagal_uji" if v == "FAIL" else None


def configs_for(presets: list[dict], symbols: list[str]) -> list[Cfg]:
    """Template default per coin + every PASS / FAIL preset (any template / timeframe), deduplicated."""
    from ..presets import DEFAULT_COSTS
    from ..templates import get_template
    out: dict[str, Cfg] = {}
    t = get_template(DEFAULT_TEMPLATE)
    for sym in symbols:
        cls = "in_sample" if sym in INSAMPLE_DEFAULT else "belum_diuji"
        c = Cfg(sym, DEFAULT_TEMPLATE, DEFAULT_TF, t.defaults(), dict(DEFAULT_COSTS), cls, names=["default"])
        out.setdefault(c.key, c)
    for p in presets:
        cls = preset_class(p)
        h = p.get("holdout") or {}
        if cls is None or p["symbol"] not in symbols or not h.get("start") or p["timeframe"] not in TF_S \
                or get_template(p["template_id"]) is None:
            continue   # no verdict / no holdout -> no out-of-sample calls to count
        c = Cfg(p["symbol"], p["template_id"], p["timeframe"], p["params"], p.get("costs") or dict(DEFAULT_COSTS),
                cls, names=[p["name"]], oos_start=h.get("start"), contaminated=bool(h.get("contaminated")))
        if c.key in out:
            prev = out[c.key]
            prev.names.append(p["name"])
            if prev.cls in ("belum_diuji", "in_sample") or (prev.cls == "gagal_uji" and cls == "lolos_uji"):
                prev.cls, prev.oos_start, prev.contaminated = cls, c.oos_start, c.contaminated
        else:
            out[c.key] = c
    return list(out.values())


# ── engine run with a stop / target trace ────────────────────────────────

def _num(x) -> Optional[float]:
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return None if v != v else v


def traced_run(df, cfg, ecfg):
    """Engine run that also returns {bar index: (side, entry, entry_bar, sl, tp, base_sl)} - the
    resting levels registered at the END of every bar with an open position (what
    ``result.open_position`` would report if the run stopped at that bar)."""
    from .. import engine_adapter as ea
    ea._engine()
    import backtest_engine.engine.backtest_loop as BL
    orig = BL.register_pending_orders
    trace: dict[int, tuple] = {}

    def hook(state):
        orig(state)
        p, tr = state.position, state.trailing
        if p.direction is not None:
            trace[int(state.meta.current_bar_index)] = (
                p.direction, float(p.entry_price), int(p.entry_bar_index),
                _num(tr.pending_sl_price), _num(tr.pending_tp_price), _num(tr.base_sl_price))

    BL.register_pending_orders = hook
    try:
        res, ind = ea.run(df, cfg, ecfg)
    finally:
        BL.register_pending_orders = orig
    return res, ind, trace


def positions_by_bar(res, trace: dict, n: int) -> list[Optional[tuple]]:
    """Per strategy bar: (side, entry, entry_bar, exit_bar|None, sl, tp, base_sl) open at that bar's close."""
    spans = [(t.entry_bar_index, t.exit_bar_index) for t in res.trades]
    op = res.open_position
    if op:
        spans.append((int(op["entry_bar_index"]), None))
    out: list[Optional[tuple]] = [None] * n
    for e, x in spans:
        last = None
        for i in range(e, n if x is None else x):
            tr = trace.get(i)
            if tr is not None and tr[2] == e:
                last = tr
            if last is None:
                continue
            out[i] = (last[0], last[1], e, x, last[3], last[4], last[5])
    return out


# ── per-coin data ────────────────────────────────────────────────────────

class CoinData:
    """Closed-bar series of one coin (4H grid + 1D + 1H + funding) and the BTC regime index."""

    def __init__(self, symbol: str, offline: bool, regime_index):
        from .. import data_cache as dc
        self.symbol = symbol
        self.offline = offline
        o4, self.funding = dc.ensure(symbol, "4h", funding=True, offline=offline)
        self.o4 = o4
        self.t4 = [int(x.value // 10**9) for x in o4["timestamp"]]
        self.bars4 = list(zip(o4["open"].astype(float), o4["high"].astype(float), o4["low"].astype(float),
                              o4["close"].astype(float)))
        self.d1 = self._series(symbol, "1d")
        self.h1 = self._series(symbol, "1h")
        self.d1_ema = M.ema_series(self.d1[1], M.TREND_EMA) if self.d1 else None
        self.h1_fast = M.ema_series(self.h1[1], M.MOM_FAST) if self.h1 else None
        self.h1_slow = M.ema_series(self.h1[1], M.MOM_SLOW) if self.h1 else None
        self.regime_index = regime_index
        if self.funding is not None and len(self.funding):
            self.f_t = [int(x.value // 10**9) for x in self.funding["timestamp"]]
            self.f_r = [float(x) for x in self.funding["funding_rate"]]
        else:
            self.f_t, self.f_r = [], []
        self._frames: dict[str, object] = {"4h": o4}

    def _series(self, symbol: str, tf: str):
        from .. import data_cache as dc
        try:
            d, _ = dc.ensure(symbol, tf, funding=False, offline=self.offline, max_stale_bars=0)
        except Exception as e:  # noqa: BLE001 - a missing 1d/1h cache only drops that factor
            log.warning("replay %s %s unavailable: %s", symbol, tf, e)
            return None
        return [int(x.value // 10**9) for x in d["timestamp"]], [float(x) for x in d["close"]]

    def frame(self, tf: str):
        from .. import data_cache as dc
        if tf not in self._frames:
            self._frames[tf], _ = dc.ensure(self.symbol, tf, funding=False, offline=self.offline)
        return self._frames[tf]

    def dirs_at(self, close_s: float) -> dict:
        """Factor directions (absolute, +1 long / -1 short / 0) from bars closed at close_s."""
        out: dict = {"tren_1d": None, "momentum_1h": None, "regime_btc": None, "funding": None}
        if self.d1:
            i = M.last_closed(self.d1[0], 86400, close_s)
            st = M.trend_at(self.d1[1], self.d1_ema, i) if i >= 0 else None
            out["tren_1d"] = st and st["direction"]
        if self.h1:
            i = M.last_closed(self.h1[0], 3600, close_s)
            st = M.momentum_at(self.h1[1], self.h1_fast, self.h1_slow, i) if i >= 0 else None
            out["momentum_1h"] = st and st["direction"]
        if self.regime_index is not None:
            out["regime_btc"] = M.regime_dir(self.regime_index.label_at(_iso(close_s)))
        out["funding"] = self.funding_dir(close_s)
        return out

    def funding_dir(self, close_s: float) -> Optional[int]:
        import bisect
        if not self.f_t:
            return None
        j = bisect.bisect_right(self.f_t, close_s) - 1
        i0 = bisect.bisect_right(self.f_t, close_s - 7 * 86400)
        if j < 0 or j - i0 + 1 < 15:
            return None
        rates = self.f_r[i0:j + 1]
        apr = sum(rates) / len(rates) * 3 * 365 * 100.0
        return -1 if apr > FUND_HIGH_APR else 1 if apr < FUND_LOW_APR else 0


# ── replay one strategy on one coin ──────────────────────────────────────

def replay_config(cfg: Cfg, data: CoinData) -> tuple[list, dict]:
    """(cases, info) for one strategy config on one coin."""
    from .. import engine_adapter as ea
    t0 = time.time()
    tf, tf_s = cfg.timeframe, TF_S[cfg.timeframe]
    ohlcv = data.frame(tf)
    fund = data.funding if cfg.costs.get("funding", True) else None
    scfg, ecfg = ea.build_configs(cfg.params, tf, cfg.costs, cfg.template_id)
    tm = ea.template(cfg.template_id)
    if tm.is_mtf(tm.validate_params(cfg.params)):
        ohlcv = ea.attach_entry_bars(ohlcv, data.frame(scfg.entry_tf), tf, scfg.entry_tf)
    df, _, _, _ = ea.prepare_frame(ohlcv, fund, tf, None, None, ecfg.warmup_period, bool(cfg.costs.get("funding", True)))
    res, _, trace = traced_run(df, scfg, ecfg)
    n = len(df)
    pos = positions_by_bar(res, trace, n)
    opens = [int(x.value // 10**9) for x in df["timestamp"]]
    hz = horizon_bars(tf)
    oos = _epoch(cfg.oos_start) if cfg.oos_start else None
    warm_end = opens[min(ecfg.warmup_period, n - 1)]
    cases = []
    invalid = ambiguous = 0
    for k, t_open in enumerate(data.t4):
        close_s = t_open + BAR4_S
        if close_s <= warm_end or (oos is not None and t_open < oos):
            continue
        j = M.last_closed(opens, tf_s, close_s)
        if j < 0 or pos[j] is None:
            continue
        side, entry_px, e, x, sl, tp, _base = pos[j]
        s = 1 if side == "long" else -1
        entry_ref = data.bars4[k][3]
        cancel = None
        if x is not None:
            exit_close = opens[x] + tf_s
            # first 4H close at/after the strategy's exit bar close
            kk = M.last_closed(data.t4, BAR4_S, exit_close)
            if kk >= 0 and data.t4[kk] + BAR4_S < exit_close:
                kk += 1
            cancel = max(1, kk - k) if kk > k else 1
        ev = evaluate_call(side, entry_ref, sl, tp, data.bars4[k + 1:k + 1 + hz], hz, invalid_at=cancel)
        if ev["status"] == "invalid":
            invalid += 1
            continue
        ambiguous += 1 if ev.get("ambiguous") else 0
        dirs = data.dirs_at(close_s)
        rel = tuple(None if dirs[f] is None else dirs[f] * s for f in ("tren_1d", "momentum_1h", "regime_btc", "funding"))
        score, _n = M.align_score(s, dirs)
        entry_close = opens[e] + tf_s
        fase = "baru" if entry_close > close_s - BAR4_S else "berjalan"
        rr = abs(tp - entry_ref) / abs(entry_ref - sl) if tp is not None and sl is not None and entry_ref != sl else None
        cases.append(C.Case(cfg.symbol, cfg.cls, side, M.align_group(score), fase, close_s,
                            f"{cfg.key}|{e}", ev["status"], ev["r_net"], ev["mfe_r"], ev["bars"], rr, rel,
                            "+".join(cfg.names)))
    info = {"key": cfg.key, "symbol": cfg.symbol, "template_id": cfg.template_id, "timeframe": tf,
            "names": cfg.names, "cls": cfg.cls, "oos_start": cfg.oos_start, "contaminated": cfg.contaminated,
            "trades": len(res.trades), "cases": len(cases), "invalid": invalid, "ambiguous": ambiguous,
            "first_bar": _iso(opens[0]), "last_bar": _iso(opens[-1]), "runtime_s": round(time.time() - t0, 2)}
    return cases, info


def verify_trace(cfg: Cfg, data: CoinData, sample_bars: list[int]) -> list[dict]:
    """Compare the traced state with runs truncated at ``sample_bars`` (strategy-bar indices)."""
    from .. import engine_adapter as ea
    scfg, ecfg = ea.build_configs(cfg.params, cfg.timeframe, cfg.costs, cfg.template_id)
    ohlcv = data.frame(cfg.timeframe)
    df, _, _, _ = ea.prepare_frame(ohlcv, data.funding, cfg.timeframe, None, None, ecfg.warmup_period, True)
    res, _, trace = traced_run(df, scfg, ecfg)
    pos = positions_by_bar(res, trace, len(df))
    out = []
    for j in sample_bars:
        sub = df.iloc[:j + 1].reset_index(drop=True)
        r2, _ = ea.run(sub, scfg, ecfg)
        op = r2.open_position
        a = pos[j]
        got = None if a is None else {"side": a[0], "entry": round(a[1], 8), "sl": a[4] and round(a[4], 8),
                                      "tp": a[5] and round(a[5], 8)}
        want = None if op is None else {"side": op["direction"], "entry": round(op["entry_price"], 8),
                                        "sl": op["sl"] and round(op["sl"], 8), "tp": op["tp"] and round(op["tp"], 8)}
        out.append({"bar": j, "match": got == want, "trace": got, "truncated": want})
    return out


# ── aggregation ──────────────────────────────────────────────────────────

def _dedupe(cases: list) -> list:
    """The same position at the same close counted once per class (near-identical presets)."""
    seen, out = set(), []
    for c in cases:
        k = (c.coin, c.cls, c.t, c.side, c.pos.rsplit("|", 1)[-1])
        if k in seen:
            continue
        seen.add(k)
        out.append(c)
    return out


def label_cases(cases: list, buckets: dict, contaminated: set) -> list[tuple]:
    """(keyakinan v2, case) for every case, from ``buckets``."""
    return [(C.assess(buckets, c.cls, c.side, c.fase, c.cfg in contaminated)["level"], c) for c in cases]


def label_cases_apriori(cases: list, buckets: dict) -> list[tuple]:
    out = []
    for c in cases:
        _k, st, enough = C.lookup_apriori(buckets, c.cls, c.side, c.align, c.fase)
        out.append((C.level_apriori(st, enough, c.cls), c))
    return out


def _by_level(labelled: list[tuple]) -> dict:
    groups: dict[str, list] = {}
    for lvl, c in labelled:
        for k in (f"*|{lvl}", f"{c.side}|{lvl}", f"{c.cls}|{lvl}", f"{c.cls}|{c.side}|{lvl}"):
            groups.setdefault(k, []).append(c)
    return {k: C.rounded(C.stats(v)) for k, v in groups.items()}


def summarise(cases: list, infos: list[dict], split_iso: str = SPLIT_ISO) -> dict:
    pooled = _dedupe([c for c in cases if c.cls != "in_sample"])
    buckets = C.case_buckets(pooled)
    contaminated = {"+".join(i["names"]) for i in infos if i.get("contaminated")}
    by_kv = _by_level(label_cases(pooled, buckets, contaminated))
    # out-of-sample check of the labels: buckets from the older half, outcomes of the newer half
    split = _epoch(split_iso)
    train = [c for c in pooled if c.t < split]
    test = [c for c in pooled if c.t >= split]
    tb = C.case_buckets(train)
    lifts = {}
    for cls in ("belum_diuji", "lolos_uji", "pool"):
        sub = [c for c in pooled if (c.cls in C.POOLED if cls == "pool" else c.cls == cls)]
        if sub:
            lifts[cls] = {f: C.factor_lift(sub, i, split) for i, f in enumerate(("tren_1d", "momentum_1h",
                                                                                 "regime_btc", "funding"))}
    fase = {}
    for name, sub in (("sebelum", train), ("sesudah", test), ("semua", pooled)):
        g: dict[str, list] = {}
        for c in sub:
            if c.cls in C.POOLED:
                g.setdefault(f"{c.side}|{c.fase}", []).append(c)
        fase[name] = {k: C.rounded(C.stats(v)) for k, v in g.items()}
    per_coin: dict[str, dict] = {}
    groups: dict[tuple, list] = {}
    for c in _dedupe(cases):
        for k in (f"{c.cls}|{c.side}", f"{c.cls}|{c.side}|{c.fase}"):
            groups.setdefault((c.coin, k), []).append(c)
    for (coin, k), v in groups.items():
        per_coin.setdefault(coin, {})[k] = C.rounded(C.stats(v))
    all_done = [c for c in pooled if c.status in C.DONE]
    return {
        "buckets": buckets, "by_keyakinan": by_kv, "factor_lift": lifts, "fase_split": fase, "per_coin": per_coin,
        "oos_check": {"split": split_iso, "train_cases": len(train), "test_cases": len(test),
                      "v2": _by_level(label_cases(test, tb, contaminated)),
                      "apriori": _by_level(label_cases_apriori(test, tb))},
        "counts": {"cases": len(pooled), "done": len(all_done),
                   "positions": len({c.pos for c in all_done}),
                   "coins": len({c.coin for c in pooled}),
                   "first": _iso(min(c.t for c in pooled)) if pooled else None,
                   "last": _iso(max(c.t for c in pooled)) if pooled else None},
    }


def method_text() -> list[str]:
    return [
        "Setiap close 4H di masa lalu dihitung ulang seperti halaman Outlook saat itu: posisi strategi, SL/TP "
        "yang sedang terpasang, faktor 1D/1H/BTC dari candle yang SUDAH close. Tanpa melihat masa depan.",
        "Panggilan dinilai seperti instruksi halaman: masuk di harga close, SL & TP terpasang, batal (keluar di "
        "close) jika strategi menutup/membalik posisi, habis waktu setelah horizon. SL & TP di candle yang sama "
        "dihitung SL (konservatif). R bersih sudah dipotong biaya 0,2% pulang-pergi; funding tidak dihitung.",
        "Preset LOLOS/GAGAL hanya dihitung di periode holdout-nya (out-of-sample). Setting default di ETH "
        "dirancang di ETH 4H (in-sample) sehingga tidak masuk kelompok gabungan.",
        "Panggilan berurutan dari satu posisi saling terkait: setiap angka disertai jumlah posisi berbeda; "
        "galat baku dikelompokkan per posisi; nilai harapan untuk peringkat dikecilkan n/(n+20).",
        f"Uji label keyakinan: kelompok dibuat dari data sebelum {SPLIT_ISO[:10]}, lalu dicek di data sesudahnya. "
        "Aturan awal (keselarasan faktor 1D/1H/BTC) GAGAL uji ini; aturan v2 memakai kelas strategi x arah x fase "
        "(posisi baru vs menyusul) yang konsisten di kedua periode.",
        "Faktor 1D/1H/BTC/funding hanya disebut 'teruji' bila efeknya > 2 galat baku secara total DAN > 1 galat "
        "baku di masing-masing periode; selain itu 'belum terbukti'.",
        "Berita, open interest dan screener tidak diuji ulang (tidak ada riwayat yang jujur); di halaman "
        "ditampilkan sebagai konteks dan tidak mengubah keyakinan.",
    ]


def compute(conn, symbols: Optional[list[str]] = None, workers: int = 1, progress=None,
            offline: Optional[bool] = None, cases_sink=None) -> dict:
    from .. import data_cache as dc
    from .. import regime as R
    from ..presets import list_presets
    from ..data_cache import cached_datasets
    t0 = time.time()
    offline = (os.environ.get("LAB_DATA_OFFLINE") == "1") if offline is None else offline
    syms = symbols or sorted({v["symbol"] for v in cached_datasets().values() if v["timeframe"] == "4h"})
    presets = list_presets(conn)
    cfgs = configs_for(presets, syms)
    by_sym: dict[str, list[Cfg]] = {}
    for c in cfgs:
        by_sym.setdefault(c.symbol, []).append(c)
    btc_d1, _ = dc.ensure("BTCUSDT", "1d", funding=False, offline=offline)
    idx = R.RegimeIndex(R.label_series(btc_d1))
    jobs = sorted(by_sym.items())
    results = []
    if workers > 1:
        from concurrent.futures import ProcessPoolExecutor
        with ProcessPoolExecutor(max_workers=workers) as ex:
            futs = [ex.submit(_replay_symbol, sym, cl, offline) for sym, cl in jobs]
            for k, f in enumerate(futs):
                results.append(f.result())
                if progress:
                    progress("replay", k + 1, len(jobs))
    else:
        for k, (sym, cl) in enumerate(jobs):
            results.append(_replay_symbol(sym, cl, offline, idx))
            if progress:
                progress("replay", k + 1, len(jobs))
    cases, infos, errors = [], [], {}
    for sym, cs, inf, err in results:
        cases.extend(cs)
        infos.extend(inf)
        if err:
            errors[sym] = err
    if cases_sink is not None:
        cases_sink(cases)
    out = summarise(cases, infos)
    from .. import engine_adapter as ea
    out.update({
        "version": CALIB_VERSION, "computed_at": _iso(time.time()), "runtime_s": round(time.time() - t0, 1),
        "engine_commit": ea.engine_commit(), "method": method_text(), "excluded": EXCLUDED,
        "horizon_hours": HORIZON_HOURS, "split": SPLIT_ISO, "configs": infos, "errors": errors,
        "params": {"min_pos": C.MIN_POS, "shrink_k": C.SHRINK_K, "tinggi_min_pos": C.TINGGI_MIN_POS,
                   "tinggi_min_r": C.TINGGI_MIN_R, "class_cap": C.CLASS_CAP,
                   "cost_roundtrip_pct": 0.2, "mtf": {"trend_ema": M.TREND_EMA, "trend_slope_bars": M.TREND_SLOPE_BARS,
                                                      "mom_fast": M.MOM_FAST, "mom_slow": M.MOM_SLOW},
                   "funding_apr": [FUND_LOW_APR, FUND_HIGH_APR]},
        "ambiguous_share": (sum(i["ambiguous"] for i in infos) / max(1, sum(i["cases"] for i in infos))),
    })
    return out


def _replay_symbol(sym: str, cfgs: list[Cfg], offline: bool, idx=None):
    """Worker entry: all configs of one coin (own process when workers > 1)."""
    try:
        if idx is None:
            from .. import data_cache as dc
            from .. import regime as R
            d, _ = dc.ensure("BTCUSDT", "1d", funding=False, offline=offline)
            idx = R.RegimeIndex(R.label_series(d))
        data = CoinData(sym, offline, idx)
        cases, infos = [], []
        for c in cfgs:
            try:
                cs, inf = replay_config(c, data)
            except Exception as e:  # noqa: BLE001
                log.exception("replay %s %s failed", sym, c.names)
                infos.append({"key": c.key, "symbol": sym, "names": c.names, "cls": c.cls,
                              "error": f"{type(e).__name__}: {e}"[:300]})
                continue
            cases.extend(cs)
            infos.append(inf)
        return sym, cases, infos, None
    except Exception as e:  # noqa: BLE001
        log.exception("replay %s failed", sym)
        return sym, [], [], f"{type(e).__name__}: {e}"[:300]


def save(conn, payload: dict) -> None:
    from ..db import dumps
    conn.execute("INSERT INTO lab_kv (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                 (KV_KEY, dumps(payload)))
    conn.commit()


def load(conn) -> Optional[dict]:
    from ..db import loads
    try:
        r = conn.execute("SELECT value FROM lab_kv WHERE key=?", (KV_KEY,)).fetchone()
    except Exception:  # noqa: BLE001
        return None
    return loads(r["value"]) if r else None


def execute(conn, job: Optional[dict] = None) -> dict:
    """Job entry (``outlook_calibrate``): sequential, nice'd by the worker; writes lab_kv only."""
    from .. import queue as q
    job_id = (job or {}).get("id")

    def prog(stage, done=0, total=0):
        if job_id:
            q.set_progress(conn, job_id, {"stage": stage, "done": done, "total": total})

    prog("replay", 0, 0)
    payload = compute(conn, workers=1, progress=prog)
    if not payload["counts"]["cases"]:
        raise RuntimeError(f"replay produced no cases: {payload.get('errors')}")
    save(conn, payload)
    return {k: payload[k] for k in ("computed_at", "runtime_s", "counts")}


def main(argv: Optional[list[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="Outlook historical replay -> calibration JSON")
    ap.add_argument("--db", help="lab.db (a COPY when measuring offline); presets are read from it")
    ap.add_argument("--out", required=True)
    ap.add_argument("--workers", type=int, default=1)
    ap.add_argument("--symbols", default="")
    ap.add_argument("--cases-out", default="", help="optional JSONL dump of every case")
    a = ap.parse_args(argv)
    logging.basicConfig(level=logging.WARNING)
    if a.db:
        os.environ["LAB_DB_PATH"] = a.db
        from ..settings import get_lab_settings
        get_lab_settings.cache_clear()
    from .. import db as labdb
    conn = labdb.connect()
    syms = [s.strip().upper() for s in a.symbols.split(",") if s.strip()] or None
    def sink(cases):
        if a.cases_out:
            with open(a.cases_out, "w") as f:
                for c in cases:
                    f.write(json.dumps(c._asdict()) + "\n")

    payload = compute(conn, syms, workers=max(1, min(4, a.workers)), cases_sink=sink,
                      progress=lambda st, d, t: print(f"{st} {d}/{t}", file=sys.stderr, flush=True))
    with open(a.out, "w") as f:
        json.dump(payload, f, indent=1, default=str)
    print(json.dumps(payload["counts"]), file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
