"""Live-check tables in lab.db (created on demand, additive) + settings. Stdlib only."""
from __future__ import annotations

import os
import threading
from dataclasses import dataclass

from ..settings import REPO_ROOT, _read_dotenv

SCHEMA = """
-- Facts read from logs. Logs rotate away (nginx keeps 14 days), so every fact is kept
-- here, keyed by a hash of the source line (the line itself is never stored).
CREATE TABLE IF NOT EXISTS livecheck_evidence (
    hash        TEXT    PRIMARY KEY,
    source      TEXT    NOT NULL,             -- nginx | app
    kind        TEXT    NOT NULL,             -- hit | done | order | fail | dup | timing
    ts          REAL    NOT NULL,             -- epoch seconds (UTC)
    data_json   TEXT    NOT NULL,             -- sanitised fields only
    seen_at     TEXT    NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_livecheck_evidence_ts ON livecheck_evidence (ts);

-- One row per expected signal and/or delivery, rebuilt by every cycle.
CREATE TABLE IF NOT EXISTS livecheck_rows (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    bar_open_ts   TEXT    NOT NULL,           -- 4H bar the alert belongs to (open time, UTC)
    bar_close_ts  TEXT    NOT NULL,
    status        TEXT    NOT NULL,           -- cocok | tidak_terkirim | gagal | tak_terduga | harga_beda
                                              -- | tanpa_log | diabaikan
    perlu_dicek   INTEGER NOT NULL DEFAULT 0,
    causes_json   TEXT,                       -- ["warmup", "biaya", "intrabar", "beda_bar", ...]
    action        TEXT,                       -- open | close (NULL: unknown, nginx-only delivery)
    side          TEXT,                       -- long | short
    reason        TEXT,                       -- short human reason (Indonesian), sanitised
    price_diff_bps REAL,
    expected_json TEXT,
    delivery_json TEXT,
    computed_at   TEXT    NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_livecheck_rows_bar ON livecheck_rows (bar_open_ts);
"""

_lock = threading.Lock()


def ensure_schema(conn) -> None:
    have = conn.execute("SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name IN "
                        "('livecheck_evidence','livecheck_rows')").fetchone()[0]
    if have == 2:
        return
    with _lock:
        if conn.in_transaction:
            conn.commit()
        conn.executescript(SCHEMA)
        conn.commit()


DEFAULT_NGINX_GLOB = "/var/log/nginx/access.log*"
DEFAULT_APP_GLOBS = ("/root/.pm2/logs/bmtm-api-out*.log*", "/root/.pm2/logs/bmtm-api-error*.log*",
                     "/root/bmtm_webhook_evidence*.log")


@dataclass(frozen=True)
class LiveCheckSettings:
    enabled: bool = True
    preset_name: str = "4H-ETH-Basic"
    symbol: str = "ETHUSDT"
    tf: str = "4h"
    since: str = "2026-10-01"             # first bar we reconcile
    short_history_days: int = 60          # warm-up variant starts this many days before ``since``
    price_bps: float = 30.0               # |fill - expected| above this -> harga beda
    nginx_glob: str = DEFAULT_NGINX_GLOB
    app_globs: tuple = DEFAULT_APP_GLOBS
    local_ips: tuple = ()                 # extra "local" IPs (the server's own public IP is auto-detected)
    webhook_path: str = "/webhook/tradingview"
    delay_s: int = 120                    # run this long after a 4H close (data + alerts settled)
    pending_s: int = 600                  # a 202 with no outcome yet is "menunggu" this long


def _csv(s: str) -> tuple:
    return tuple(x.strip() for x in (s or "").split(",") if x.strip())


def livecheck_settings() -> LiveCheckSettings:
    env = _read_dotenv(REPO_ROOT / ".env")

    def g(k: str, d: str) -> str:
        return os.environ.get(k, env.get(k, d))

    d = LiveCheckSettings()
    try:
        bps = float(g("LAB_LIVECHECK_PRICE_BPS", str(d.price_bps)))
    except ValueError:
        bps = d.price_bps
    try:
        short_days = max(10, int(g("LAB_LIVECHECK_SHORT_HISTORY_DAYS", str(d.short_history_days))))
    except ValueError:
        short_days = d.short_history_days
    return LiveCheckSettings(
        enabled=g("LAB_LIVECHECK_ENABLED", "1") != "0",
        preset_name=g("LAB_LIVECHECK_PRESET", d.preset_name),
        since=g("LAB_LIVECHECK_SINCE", d.since),
        short_history_days=short_days,
        price_bps=bps,
        nginx_glob=g("LAB_LIVECHECK_NGINX_GLOB", d.nginx_glob),
        app_globs=_csv(g("LAB_LIVECHECK_APP_GLOBS", "")) or d.app_globs,
        local_ips=_csv(g("LAB_LIVECHECK_LOCAL_IPS", "")),
    )
