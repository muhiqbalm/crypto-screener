"""Universal: point-in-time liquidity universe (universe_mode=liquidity) + delisted-data helper.

The default (universe_mode=static) must behave exactly as before, so the live paper watches
are unaffected."""
import io
import zipfile

import numpy as np
import pandas as pd
import pytest

from src.lab.universal import backtest as B
from src.lab.universal import params as P
from src.lab.universal import pit_data as D
from src.lab.universal import runner as R
from src.lab.universal import strategy as S

COSTS = {"commission_pct": 0.05, "slippage_pct": 0.05, "funding": True}


def frames(days=500, n=8, seed=3, start="2022-01-01", vols=None, ends=None, starts=None):
    """n coins; coin k trades quote volume vols[k] (default k+1) per bar."""
    rng = np.random.default_rng(seed)
    ts = pd.date_range(start, periods=days * 6, freq="4h", tz="UTC")
    o, f = {}, {}
    for k in range(n):
        s = f"C{k}USDT"
        regime = np.sign(np.sin(np.arange(len(ts)) / (6 * 40) + k))
        r = 0.0005 * regime + rng.normal(0, 0.012, len(ts))
        px = 50 * np.exp(np.cumsum(r))
        qv = np.full(len(ts), float(vols[k] if vols else k + 1))
        df = pd.DataFrame({"timestamp": ts, "open": px, "high": px, "low": px, "close": px,
                           "volume": qv / px, "quote_volume": qv})
        a = (starts or {}).get(s, 0)
        b = (ends or {}).get(s, len(ts))
        o[s] = df.iloc[a:b].reset_index(drop=True)
        fts = pd.date_range(start, periods=days * 3, freq="8h", tz="UTC")
        f[s] = pd.DataFrame({"timestamp": fts, "funding_rate": np.full(len(fts), 0.0001)})
    return o, f


def test_defaults_unchanged():
    p = P.validate_params({})
    assert p["universe_mode"] == "static"
    o, f = frames()
    pn = S.build_panel(o, f)
    feat = S.compute_features(pn, p)
    assert feat.in_universe is None
    # static features are the same with or without volume columns
    o2 = {s: df.drop(columns=["volume", "quote_volume"]) for s, df in o.items()}
    feat2 = S.compute_features(S.build_panel(o2, f), p)
    assert np.array_equal(feat.eligible, feat2.eligible)
    t = S.first_tradable_index(feat, p) + 50
    assert np.allclose(S.target_weights(feat, pn, t, p), S.target_weights(feat2, S.build_panel(o2, f), t, p))


def test_params_validation():
    with pytest.raises(P.ParamError):
        P.validate_params({"universe_mode": "survivors"})
    with pytest.raises(P.ParamError):
        P.validate_params({"universe_size": 1})
    p = P.validate_params({"universe_mode": "liquidity", "universe_size": 3, "liquidity_days": 14})
    assert (p["universe_size"], p["liquidity_days"]) == (3, 14)
    keys = {x["key"] for x in P.public_schema()["params"]}
    assert {"universe_mode", "universe_size", "liquidity_days"} <= keys
    assert not {"universe_mode", "universe_size", "liquidity_days"} & {x["key"] for x in P.tunable_params()}


def test_quote_volume_proxy_when_missing():
    o, f = frames(days=200, n=3)
    o = {s: df.drop(columns=["quote_volume"]) for s, df in o.items()}
    pn = S.build_panel(o, f)
    assert np.allclose(pn.quote_volume[10], [1.0, 2.0, 3.0])


def test_liquidity_universe_top_k_and_ranked_among_eligible_only():
    o, f = frames(n=8)
    p = P.validate_params({"universe_mode": "liquidity", "universe_size": 3, "min_universe": 2})
    pn = S.build_panel(o, f)
    feat = S.compute_features(pn, p)
    t = S.first_tradable_index(feat, p) + 100
    assert sorted(np.flatnonzero(feat.in_universe[t])) == [5, 6, 7]   # largest volumes
    assert feat.eligible[t].sum() <= 3
    assert not (feat.eligible & ~feat.in_universe).any()
    # weights only ever on universe members
    w = S.target_weights(feat, pn, t, p)
    assert set(np.flatnonzero(w)) <= {5, 6, 7}


def test_liquidity_universe_is_causal():
    o, f = frames(n=6)
    p = P.validate_params({"universe_mode": "liquidity", "universe_size": 2, "min_universe": 2})
    pn = S.build_panel(o, f)
    feat = S.compute_features(pn, p)
    t = S.first_tradable_index(feat, p) + 60
    # make coin 0 hugely liquid from t+1 on: nothing at <= t may change
    o2 = {s: df.copy() for s, df in o.items()}
    cut = pn.ts[t]
    m = o2["C0USDT"]["timestamp"] > cut
    o2["C0USDT"].loc[m, "quote_volume"] = 1e9
    feat2 = S.compute_features(S.build_panel(o2, f), p)
    assert np.array_equal(feat.in_universe[: t + 1], feat2.in_universe[: t + 1])
    assert np.allclose(S.target_weights(feat, pn, t, p), S.target_weights(feat2, S.build_panel(o2, f), t, p))
    # ... and it does enter the universe once the trailing window has seen the volume
    assert feat2.in_universe[t + 6 * 2, 0]


def test_new_listing_needs_history_and_delisted_coin_drops_out():
    days = 500
    o, f = frames(days=days, n=6, vols=[1, 2, 3, 4, 5, 100],
                  starts={"C5USDT": 6 * 200}, ends={"C4USDT": 6 * 400})
    p = P.validate_params({"universe_mode": "liquidity", "universe_size": 3, "min_history_days": 120,
                           "min_universe": 2})
    pn = S.build_panel(o, f)
    feat = S.compute_features(pn, p)
    c5, c4 = pn.index_of("C5USDT"), pn.index_of("C4USDT")
    listed = 6 * 200
    assert not feat.in_universe[listed + 6 * 100, c5]          # too young, even though it is the most liquid
    assert feat.in_universe[listed + 6 * 150, c5]
    assert not feat.in_universe[6 * 400 + 10:, c4].any()       # delisted: never again in the universe
    a, b = S.first_tradable_index(feat, p), len(pn.ts) - 1
    sim = B.simulate(pn, feat, p, COSTS, a, b)
    assert sim.last_weights[c4] == 0.0


def test_zero_volume_bars_are_not_in_universe():
    o, f = frames(n=4, vols=[5, 6, 7, 8])
    o["C3USDT"].loc[o["C3USDT"].index[-30:], "quote_volume"] = 0.0
    p = P.validate_params({"universe_mode": "liquidity", "universe_size": 2, "min_universe": 2})
    feat = S.compute_features(S.build_panel(o, f), p)
    assert not feat.in_universe[-30:, 3].any()
    assert feat.in_universe[-31, 3]


def test_subset_and_slice_keep_volume():
    o, f = frames(n=4)
    pn = S.build_panel(o, f)
    sub = S.subset_panel(pn, [1, 3])
    assert sub.symbols == ["C1USDT", "C3USDT"] and np.array_equal(sub.quote_volume, pn.quote_volume[:, [1, 3]])
    sl = S.slice_panel(pn, 100)
    assert sl.quote_volume.shape == (100, 4)


# ── pit_data ─────────────────────────────────────────────────────────────

def test_is_excluded():
    assert not D.is_excluded("LUNAUSDT") and not D.is_excluded("1000PEPEUSDT")
    for s in ["USDCUSDT", "BTCDOMUSDT", "BTCUSDT_230331", "ETHBUSD", "BTCUSDC", "DEFIUSDT"]:
        assert D.is_excluded(s), s


def _zip(name, text):
    b = io.BytesIO()
    with zipfile.ZipFile(b, "w") as z:
        z.writestr(name, text)
    return b.getvalue()


def _kline_csv(rows, header=True):
    h = "open_time,open,high,low,close,volume,close_time,quote_volume,count,tbv,tbqv,ignore\n" if header else ""
    return h + "".join(f"{t},{c},{c},{c},{c},{v},{t + 14399999},{v * c},1,0,0,0\n" for t, c, v in rows)


def _xml(prefixes=(), keys=(), truncated=False, nxt=""):
    ns = 'xmlns="http://s3.amazonaws.com/doc/2006-03-01/"'
    body = "".join(f"<CommonPrefixes><Prefix>{p}</Prefix></CommonPrefixes>" for p in prefixes)
    body += "".join(f"<Contents><Key>{k}</Key></Contents>" for k in keys)
    return (f'<?xml version="1.0"?><ListBucketResult {ns}><IsTruncated>{"true" if truncated else "false"}'
            f"</IsTruncated><NextMarker>{nxt}</NextMarker>{body}</ListBucketResult>").encode()


def test_list_symbols_follows_pagination():
    base = "data/futures/um/monthly/klines/"
    calls = []

    def get(url):
        calls.append(url)
        if "marker=" not in url:
            return _xml([base + "LUNAUSDT/", base + "BTCUSDT_230331/"], truncated=True, nxt=base + "LUNAUSDT/")
        return _xml([base + "FTTUSDT/", base + "USDCUSDT/", base + "ETHBUSD/"])
    assert D.list_um_symbols(get=get) == ["FTTUSDT", "LUNAUSDT"]
    assert len(calls) == 2


def test_fetch_symbol_monthly_plus_daily_tail_and_funding():
    t0 = int(pd.Timestamp("2026-09-01", tz="UTC").timestamp() * 1000)
    t1 = int(pd.Timestamp("2026-10-01", tz="UTC").timestamp() * 1000)
    td = int(pd.Timestamp("2026-11-01", tz="UTC").timestamp() * 1000)
    files = {
        "https://data.binance.vision/data/futures/um/monthly/klines/XUSDT/4h/XUSDT-4h-2026-09.zip":
            _zip("a.csv", _kline_csv([(t0, 1.0, 10.0)])),
        "https://data.binance.vision/data/futures/um/monthly/klines/XUSDT/4h/XUSDT-4h-2026-10.zip":
            _zip("b.csv", _kline_csv([(t1, 2.0, 10.0)], header=False)),
        "https://data.binance.vision/data/futures/um/daily/klines/XUSDT/4h/XUSDT-4h-2026-11-01.zip":
            _zip("c.csv", _kline_csv([(td, 3.0, 10.0)])),
        "https://data.binance.vision/data/futures/um/monthly/fundingRate/XUSDT/XUSDT-fundingRate-2026-09.zip":
            _zip("f.csv", f"calc_time,funding_interval_hours,last_funding_rate\n{t0},8,0.0001\n"),
    }

    def get(url):
        if "s3-ap-northeast-1" in url:
            if "fundingRate" in url:
                return _xml(keys=["data/futures/um/monthly/fundingRate/XUSDT/XUSDT-fundingRate-2026-09.zip",
                                  "data/futures/um/monthly/fundingRate/XUSDT/XUSDT-fundingRate-2026-09.zip.CHECKSUM"])
            return _xml(keys=["data/futures/um/monthly/klines/XUSDT/4h/XUSDT-4h-2026-09.zip",
                              "data/futures/um/monthly/klines/XUSDT/4h/XUSDT-4h-2026-10.zip"])
        return files.get(url)
    from datetime import date
    kl, fu = D.fetch_symbol("XUSDT", until=date(2026, 11, 3), get=get)
    assert list(kl["close"]) == [1.0, 2.0, 3.0]
    assert list(kl["quote_volume"]) == [10.0, 20.0, 30.0]
    assert len(fu) == 1 and fu["funding_rate"].iloc[0] == pytest.approx(0.0001)


def test_load_universe_panel_reads_pit_dir_not_main_cache(tmp_path, monkeypatch):
    pytest.importorskip("pyarrow")
    o, f = frames(days=300, n=6)
    d = tmp_path / "perp_pit"
    d.mkdir()
    for s, df in o.items():
        df.to_parquet(d / f"{s}_PERP_4h.parquet", index=False)
        f[s].to_parquet(d / f"{s}_PERP_funding.parquet", index=False)
    monkeypatch.setenv("LAB_PIT_DATA_DIR", str(d))
    p = P.validate_params({"universe_mode": "liquidity", "universe_size": 3, "min_universe": 2})
    assert R.universe_symbols(p) == sorted(o)
    pn = R.load_universe_panel(p)
    assert pn.symbols == sorted(o) and pn.quote_volume is not None
    res = R.evaluate_all(pn, p, COSTS, "backtest", None, None)
    held = {t["symbol"] for t in res["trades"]}
    assert held and held <= {"C3USDT", "C4USDT", "C5USDT"}
