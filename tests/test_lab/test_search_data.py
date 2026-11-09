import io
import sqlite3
import urllib.error
import zipfile

import pandas as pd
import pytest

from src.lab import data_cache as dc
from src.lab import engine_adapter as ea
from src.lab.templates import rosyade_family as T


# ── search space ─────────────────────────────────────────────────────────

def test_default_search_is_all_tunables():
    specs = T.resolve_search(None)
    assert [s["key"] for s in specs] == [p["key"] for p in T.tunable_params()]
    assert len(specs) == 12


def test_search_subset_and_clamping():
    specs = T.resolve_search({"params": ["long_sl_pct", "ema_htf_len"],
                              "ranges": {"long_sl_pct": [5, 999], "ema_htf_len": [100.4, 200.7]}})
    by = {s["key"]: s for s in specs}
    assert set(by) == {"long_sl_pct", "ema_htf_len"}
    assert (by["long_sl_pct"]["min"], by["long_sl_pct"]["max"]) == (5.0, 30.0)   # clamped to template max
    assert (by["ema_htf_len"]["min"], by["ema_htf_len"]["max"]) == (101, 200)    # int bounds
    # template itself unchanged
    assert T.PARAM_INDEX["long_sl_pct"]["max"] == 30.0


def test_ranges_only_implies_params():
    specs = T.resolve_search({"ranges": {"cooldown_bars": [1, 5]}})
    assert [s["key"] for s in specs] == ["cooldown_bars"]


@pytest.mark.parametrize("search,msg", [
    ({"params": ["nope"]}, "unknown"),
    ({"params": ["leverage"]}, "not tunable"),
    ({"params": ["long_sl_pct"], "ranges": {"short_sl_pct": [1, 2]}}, "not in search.params"),
    ({"params": ["long_sl_pct"], "ranges": {"long_sl_pct": [40, 50]}}, "empty range"),
    ({"params": ["long_sl_pct"], "ranges": {"long_sl_pct": [5]}}, "range must be"),
    ({"params": ["long_sl_pct", "long_sl_pct"]}, "duplicate"),
])
def test_invalid_search(search, msg):
    with pytest.raises(T.ParamError, match=msg):
        T.resolve_search(search)


# ── objective ────────────────────────────────────────────────────────────

class _Res:
    def __init__(self, eq):
        self.equity_curve = [(i, v) for i, v in enumerate(eq)]


def test_segment_returns():
    segs = ea.segment_returns(_Res([100, 110, 121, 110, 121]))
    assert segs == pytest.approx([10.0, 10.0, -9.0909, 10.0], abs=1e-3)


def test_robust_score_prefers_consistency_and_enough_trades():
    m = {"sharpe": 2.0, "trades": 40, "max_dd_pct": -20.0, "liquidations": 0, "net_return_pct": 50.0}
    full = ea.robust_score(m, [1, 1, 1, 1], 30)
    half = ea.robust_score(m, [1, -1, 1, -1], 30)
    few = ea.robust_score({**m, "trades": 15}, [1, 1, 1, 1], 30)
    deep = ea.robust_score({**m, "max_dd_pct": -60.0}, [1, 1, 1, 1], 30)
    assert full == pytest.approx(2.0) and half == pytest.approx(1.0) and few == pytest.approx(1.0)
    assert deep == pytest.approx(1.0)
    assert ea.robust_score({**m, "liquidations": 1}, [1, 1, 1, 1], 30) == -1e9
    assert ea.robust_score({**m, "sharpe": -0.5}, [1, 1, 1, 1], 30) < 0


# ── data download robustness ─────────────────────────────────────────────

def _zip_klines(ts_ms):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("k.csv", "open_time,open,high,low,close,volume\n" +
                   "".join(f"{t},1,2,0.5,1.5,10\n" for t in ts_ms))
    return buf.getvalue()


def test_http_get_retries_then_succeeds(monkeypatch):
    calls = {"n": 0}

    class _R:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def read(self):
            return b"ok"

    def fake_urlopen(req, timeout=0):
        calls["n"] += 1
        if calls["n"] < 3:
            raise ConnectionResetError(54, "Connection reset by peer")
        return _R()

    monkeypatch.setattr(dc.urllib.request, "urlopen", fake_urlopen)
    assert dc._http_get("http://x", backoff_s=0) == b"ok"
    assert calls["n"] == 3


def test_http_get_gives_up_and_404(monkeypatch):
    def reset(req, timeout=0):
        raise ConnectionResetError(54, "reset")
    monkeypatch.setattr(dc.urllib.request, "urlopen", reset)
    with pytest.raises(ConnectionError, match="3 attempts"):
        dc._http_get("http://x", backoff_s=0)

    def nf(req, timeout=0):
        raise urllib.error.HTTPError("http://x", 404, "nf", {}, None)
    monkeypatch.setattr(dc.urllib.request, "urlopen", nf)
    assert dc._http_get("http://x", backoff_s=0) is None


def test_failed_month_falls_back_to_ccxt(monkeypatch):
    jan = int(pd.Timestamp("2021-01-01", tz="UTC").value // 10**6)
    feb = int(pd.Timestamp("2021-02-01", tz="UTC").value // 10**6)

    def fake_get(url, **kw):
        if "2021-02" in url:
            raise ConnectionError("reset")
        if "2021-01" in url:
            return _zip_klines([jan, jan + 86400000])
        return None

    asked = []

    def fb(a, b):
        asked.append((a, b))
        return pd.DataFrame({"timestamp": pd.to_datetime([feb], unit="ms", utc=True), "open": [1.0],
                             "high": [2.0], "low": [0.5], "close": [1.5], "volume": [10.0]})

    monkeypatch.setattr(dc, "_http_get", fake_get)
    df = dc.fetch_vision_klines("ETHUSDT", "1d", pd.Timestamp("2021-01-01").date(), ccxt_fallback=fb)
    assert asked == [(feb, int(pd.Timestamp("2021-03-01", tz="UTC").value // 10**6))]
    assert len(df) == 3 and df["timestamp"].is_monotonic_increasing


def test_month_failing_everywhere_raises(monkeypatch):
    monkeypatch.setattr(dc, "_http_get", lambda url, **kw: (_ for _ in ()).throw(ConnectionError("reset"))
                        if "2021-01" in url else None)
    with pytest.raises(RuntimeError, match="2021-01"):
        dc.fetch_vision_klines("ETHUSDT", "1d", pd.Timestamp("2021-01-01").date(), ccxt_fallback=lambda a, b: None)


def test_cached_datasets_merges_index_and_files(lab_env):
    d = lab_env / "cache"
    d.mkdir(parents=True, exist_ok=True)
    (d / "SOLUSDT_PERP_1h.parquet").write_bytes(b"x")
    (d / "ETHUSDT_PERP_4h.parquet").write_bytes(b"x")
    (d / "ETHUSDT_PERP_funding.parquet").write_bytes(b"x")
    (d / "_index.json").write_text('{"ETHUSDT_4h": {"symbol": "ETHUSDT", "timeframe": "4h", "first": "a", '
                                   '"last": "b", "rows": 5}, "BTCUSDT_1d": {"symbol": "BTCUSDT", '
                                   '"timeframe": "1d", "first": "a", "last": "b", "rows": 1}}')
    out = dc.cached_datasets()
    assert set(out) == {"SOLUSDT_1h", "ETHUSDT_4h"}
    assert out["ETHUSDT_4h"]["rows"] == 5 and out["SOLUSDT_1h"]["rows"] is None


def test_old_lab_db_gets_new_columns(lab_env):
    path = lab_env / "old.db"
    c = sqlite3.connect(path)
    c.execute("CREATE TABLE lab_runs (id INTEGER PRIMARY KEY AUTOINCREMENT, job_id INTEGER, scan_id INTEGER, "
              "config_id INTEGER, template_id TEXT NOT NULL, symbol TEXT NOT NULL, timeframe TEXT NOT NULL, "
              "mode TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'queued', start_date TEXT, end_date TEXT, "
              "params_json TEXT NOT NULL, costs_json TEXT NOT NULL, verdict TEXT, checks_json TEXT, "
              "honesty_version TEXT, metrics_json TEXT, oos_metrics_json TEXT, best_params_json TEXT, "
              "extra_json TEXT, holdout_start TEXT, holdout_touches INTEGER, net_return_pct REAL, "
              "profit_factor REAL, max_dd_pct REAL, trades INTEGER, engine_commit TEXT, error TEXT, "
              "created_at TEXT NOT NULL, finished_at TEXT)")
    c.commit()
    c.close()
    from src.lab import db
    conn = db.connect(str(path))
    cols = {r[1] for r in conn.execute("PRAGMA table_info(lab_runs)")}
    conn.close()
    assert {"search_json", "n_trials", "trials_done", "top_trials_json"} <= cols
