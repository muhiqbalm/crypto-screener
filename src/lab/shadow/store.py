"""Shadow-execution tables in lab.db (created on demand, additive) + settings. Stdlib only."""
from __future__ import annotations

import os
import threading
from dataclasses import dataclass

from ..settings import REPO_ROOT, _read_dotenv

SCHEMA = """
CREATE TABLE IF NOT EXISTS shadow_signals (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    key            TEXT    NOT NULL UNIQUE,      -- SYMBOL|action|side|bar_close
    symbol         TEXT    NOT NULL,             -- ETHUSDT
    action         TEXT    NOT NULL,             -- open | close
    side           TEXT    NOT NULL,             -- long | short (position side from the alert)
    trade_dir      INTEGER NOT NULL,             -- +1 buy, -1 sell (open long / close short = buy)
    tf             TEXT    NOT NULL,             -- signal timeframe (4h)
    bar_close_ts   TEXT    NOT NULL,             -- close time of the bar that fired the alert
    arrival_ts     TEXT    NOT NULL,             -- earliest timestamp trade_logs has for the alert
    arrival_basis  TEXT,                         -- column it came from (received_at | created_at ...)
    off_close      INTEGER NOT NULL DEFAULT 0,   -- 1: arrival far from a bar close (manual / intrabar alert)
    n_rows         INTEGER,
    n_users        INTEGER,
    statuses_json  TEXT,
    fill_price     REAL,                         -- qty-weighted market fill from trade_logs (NULL: none)
    fill_qty       REAL,
    fill_ts        TEXT,                         -- fill time if trade_logs has one
    fill_ts_basis  TEXT,
    bar_close_px   REAL,
    atr            REAL,                         -- ATR(14) of the signal timeframe at the signal bar
    p0             REAL,                         -- first public trade at/after arrival (market proxy)
    p0_basis       TEXT,                         -- aggtrades | klines_1m
    slippage_bps   REAL,                         -- dir * (fill - close) / close   (cost > 0)
    drift_bps      REAL,                         -- dir * (p0 - close) / close
    impact_bps     REAL,                         -- dir * (fill - p0) / p0
    latency_s      REAL,                         -- arrival - bar close
    exec_latency_s REAL,                         -- fill time - arrival (only when trade_logs has a fill time)
    status         TEXT    NOT NULL DEFAULT 'pending',  -- pending | partial | done | no_data | error
    error          TEXT,
    next_due       TEXT,                         -- when the job should (re)evaluate it
    computed_at    TEXT,
    created_at     TEXT    NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_shadow_signals_due ON shadow_signals (status, next_due);

CREATE TABLE IF NOT EXISTS shadow_results (
    signal_id        INTEGER NOT NULL,
    k                REAL    NOT NULL,           -- ATR multiple; > 0 = further on the passive side
    ttl_min          INTEGER NOT NULL,           -- how long the limit rests
    limit_px         REAL,
    outcome          TEXT    NOT NULL,           -- filled | missed | postonly
    fill_ts          TEXT,
    time_to_fill_s   REAL,
    price_diff_bps   REAL,                       -- dir * (ref - limit) / ref  (> 0: limit cheaper)
    saving_bps       REAL,                       -- policy saving vs ref: fill -> price diff + fee diff;
                                                 -- miss -> chase at expiry; post-only -> 0
    end_px           REAL,
    runaway_end_bps  REAL,                       -- dir * (price at expiry - ref) / ref
    runaway_max_bps  REAL,                       -- max of the same inside the window
    ref_px           REAL,
    ref_basis        TEXT,                       -- fill (actual market fill) | proxy (first public trade)
    data_basis       TEXT,                       -- aggtrades | klines_1m
    PRIMARY KEY (signal_id, k, ttl_min)
);
"""

_lock = threading.Lock()


def ensure_schema(conn) -> None:
    have = conn.execute("SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name IN "
                        "('shadow_signals','shadow_results')").fetchone()[0]
    if have == 2:
        return
    with _lock:
        if conn.in_transaction:
            conn.commit()
        conn.executescript(SCHEMA)
        conn.commit()


def _floats(s: str, default: tuple) -> tuple:
    try:
        vals = tuple(sorted({round(float(x), 4) for x in s.split(",") if x.strip()}))
        return vals or default
    except ValueError:
        return default


@dataclass(frozen=True)
class ShadowSettings:
    enabled: bool = True
    tf: str = "4h"
    ks: tuple = (-0.1, 0.0, 0.1, 0.25, 0.5)
    ttls_min: tuple = (5, 15, 60, 240)
    taker_bps: float = 5.0
    maker_bps: float = 2.0
    first_delay_s: int = 180          # first look a few minutes after the alert
    off_close_s: int = 1800           # arrival later than this after a bar close = not a bar-close alert

    @property
    def fee_diff_bps(self) -> float:
        return self.taker_bps - self.maker_bps


def shadow_settings() -> ShadowSettings:
    env = _read_dotenv(REPO_ROOT / ".env")

    def g(k: str, d: str) -> str:
        return os.environ.get(k, env.get(k, d))

    d = ShadowSettings()
    tf = g("LAB_SHADOW_TF", d.tf)
    try:
        taker, maker = float(g("LAB_SHADOW_TAKER_BPS", "5")), float(g("LAB_SHADOW_MAKER_BPS", "2"))
    except ValueError:
        taker, maker = d.taker_bps, d.maker_bps
    ttls = tuple(int(x) for x in _floats(g("LAB_SHADOW_TTLS", ""), d.ttls_min) if 1 <= x <= 1440)
    return ShadowSettings(
        enabled=g("LAB_SHADOW_ENABLED", "1") != "0",
        tf=tf if tf in ("15m", "1h", "4h", "1d") else d.tf,
        ks=tuple(k for k in _floats(g("LAB_SHADOW_KS", ""), d.ks) if -1 <= k <= 3),
        ttls_min=ttls or d.ttls_min,
        taker_bps=taker, maker_bps=maker,
    )
