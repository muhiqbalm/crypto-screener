"""Koin Terkuat: relative-strength table over the cached perp universe.

Uses the exact Universal v0 features (default params) so the table and the
strategy always agree on what "strong" means. Computed in the engine child
(universe_refresh job) after every 4H close; the API only reads the JSON artifact.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Optional

import numpy as np

from . import backtest as B
from . import params as P
from . import strategy as S

SPARK_DAYS = 30
DONCHIAN_DAYS = 50


def artifact_path() -> Path:
    from ..settings import get_lab_settings
    p = Path(get_lab_settings().artifacts_dir) / "strength.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


def _pct(a: float, b: float) -> Optional[float]:
    if not (np.isfinite(a) and np.isfinite(b)) or b <= 0:
        return None
    return float((a / b - 1.0) * 100.0)


def funding_7d_apr_pct(panel: S.Panel, t: int, j: int) -> Optional[float]:
    """Last 7 days of funding settlements actually in the data, summed and annualised.

    The window (42 bars) ends at the newest bar <= t that holds a settlement, not at t: the
    funding cache refreshes only when its newest settlement is > 9 h old, so right after a
    4H close the settlement at that close is usually not cached yet and a window ending at
    t summed 20 of the 21 settlements while annualising as 7 days (audit 2026-11-13 S1).
    Works for 8 h and 4 h funding intervals alike (21 or 42 settlements)."""
    end = t
    if panel.funding_n is not None:
        have = np.flatnonzero(panel.funding_n[: t + 1, j] > 0)
        if not len(have):
            return None
        end = int(have[-1])
    f7 = panel.funding[max(0, end - 7 * S.BARS_PER_DAY + 1): end + 1, j]
    return B._f(float(f7.sum()) * 365.0 / 7.0 * 100.0) if len(f7) else None


def compute(panel: S.Panel, p: Optional[dict] = None, now_iso: Optional[str] = None) -> dict:
    p = p or P.validate_params({})
    feat = S.compute_features(panel, p)
    t = len(panel.ts) - 1
    w = S.target_weights(feat, panel, t, p)
    close = panel.close
    hours = np.asarray(panel.ts.hour)
    day_idx = np.flatnonzero(hours == 20)  # bars closing at 00:00 UTC
    don = DONCHIAN_DAYS * S.BARS_PER_DAY
    rows = []
    for j, s in enumerate(panel.symbols):
        c = close[t, j]
        if not np.isfinite(c):
            continue
        last_present = int(np.flatnonzero(panel.present[:, j])[-1]) if panel.present[:, j].any() else -1

        def back(days: int) -> float:
            k = t - days * S.BARS_PER_DAY
            return close[k, j] if k >= 0 else np.nan

        win = close[max(0, t - don + 1): t + 1, j]
        win = win[np.isfinite(win)]
        hi, lo = (float(win.max()), float(win.min())) if len(win) else (np.nan, np.nan)
        spark_idx = [int(k) for k in day_idx if k < t][-(SPARK_DAYS - 1):] + [t]
        spark = [B._f(close[k, j]) for k in spark_idx]
        ema = feat.ema[t, j]
        rows.append({
            "symbol": s,
            "price": B._f(c),
            "score": B._f(feat.score[t, j]),
            "ret_1d_pct": _pct(c, back(1)),
            "ret_7d_pct": _pct(c, back(7)),
            "ret_30d_pct": _pct(c, back(30)),
            "ret_90d_pct": _pct(c, back(90)),
            "vol_ann_pct": B._f(feat.vol_ann[t, j] * 100.0),
            "trend": "up" if feat.up[t, j] else ("down" if feat.down[t, j] else None),
            "ema_dist_pct": _pct(c, ema),
            "donchian_pos": B._f((c - lo) / (hi - lo)) if np.isfinite(hi) and hi > lo else None,
            "funding_7d_apr_pct": funding_7d_apr_pct(panel, t, j),
            "eligible": bool(feat.eligible[t, j]),
            "target_weight_pct": B._f(w[j] * 100.0),
            "in_portfolio": bool(w[j] > 0),
            "spark": spark,
            "last_bar": B.iso(panel.ts[last_present]) if last_present >= 0 else None,
        })
    ranked = sorted((r for r in rows if r["eligible"] and r["score"] is not None), key=lambda r: -r["score"])
    for i, r in enumerate(ranked):
        r["rank"] = i + 1
    for r in rows:
        r.setdefault("rank", None)
    rows.sort(key=lambda r: (r["rank"] is None, r["rank"] or 0, r["symbol"]))
    import pandas as pd
    return {
        "computed_at": now_iso or B.iso(pd.Timestamp.now(tz="UTC")),
        "last_bar": B.iso(panel.ts[t]),
        "last_bar_close": B.iso(panel.ts[t] + pd.Timedelta(hours=4)),
        "params": {k: p[k] for k in ("mom_short_days", "mom_mid_days", "mom_long_days", "vol_days",
                                     "trend_ema_days", "min_history_days", "top_n")},
        "donchian_days": DONCHIAN_DAYS,
        "rows": rows,
    }


def save(obj: dict) -> None:
    from ..db import dumps
    path = artifact_path()
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(dumps(obj))
    os.replace(tmp, path)


def load(path: Optional[Path] = None) -> Optional[dict]:
    """Stdlib reader for the API."""
    if path is None:
        from ..settings import get_lab_settings
        path = Path(get_lab_settings().artifacts_dir) / "strength.json"
    try:
        return json.loads(Path(path).read_text())
    except (OSError, ValueError):
        return None
