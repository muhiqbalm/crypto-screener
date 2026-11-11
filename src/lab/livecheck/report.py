"""Aggregates for the "Cek bot live vs strategi" API (stdlib, lab.db only)."""
from __future__ import annotations

import time
from typing import Optional

from ..db import loads
from ..ledger.store import iso, kv_get
from .store import ensure_schema, livecheck_settings

STATUSES = ("cocok", "harga_beda", "gagal", "tidak_terkirim", "tak_terduga", "menunggu", "tanpa_log", "diabaikan")
STEP = 14400
MAX_BARS = 2000

CAUSES = {
    "warmup": "Sinyal hilang kalau Lab mulai menghitung dari riwayat pendek: bergantung pada posisi/riwayat "
              "jauh sebelumnya (warm-up). Pine menghitung dari bar pertama chart.",
    "biaya": "Sinyal hilang kalau Lab memakai biaya preset: filter daily-loss / cooldown memakai PnL "
             "terealisasi. Pine di skrip ini tanpa komisi, kecuali diatur di Properties chart.",
    "intrabar": "Exit SL/TP keras: di TradingView terisi saat harga menyentuh level di tengah bar; Lab memakai "
                "OHLC bar 4H, urutan sentuhan bisa beda.",
    "beda_bar": "Kiriman satu bar 4H lebih awal/lambat dari sinyal Lab (timing bar / data).",
    "beda_waktu_exit": "Exit live terjadi di waktu lain dalam posisi yang sama (trailing/SL Pine vs Lab).",
    "varian_lain": "Varian Lab lain (riwayat pendek atau dengan biaya) punya sinyal ini.",
    "data_belum": "Data Lab belum sampai bar ini; dihitung ulang setelah data masuk.",
    "tengah_bar": "Kiriman tiba di tengah bar: SL/TP intrabar Pine atau alert manual.",
}


def build(conn, bars: int = 270, now: Optional[float] = None) -> dict:
    ensure_schema(conn)
    cfg = livecheck_settings()
    now = now or time.time()
    bars = max(6, min(int(bars), MAX_BARS))
    last_close = now - now % STEP
    start = last_close - bars * STEP
    rows = [dict(r) for r in conn.execute(
        "SELECT id, bar_open_ts, bar_close_ts, status, perlu_dicek, causes_json, action, side, reason, "
        "price_diff_bps, expected_json, delivery_json, computed_at FROM livecheck_rows WHERE bar_open_ts >= ? "
        "ORDER BY bar_open_ts DESC, id DESC", (iso(start),))]
    out_rows = []
    counts = {s: 0 for s in STATUSES}
    perlu = 0
    for r in rows:
        r["causes"] = loads(r.pop("causes_json"), []) or []
        r["expected"] = loads(r.pop("expected_json"), None)
        r["delivery"] = loads(r.pop("delivery_json"), None)
        r["perlu_dicek"] = bool(r["perlu_dicek"])
        counts[r["status"]] = counts.get(r["status"], 0) + 1
        perlu += r["perlu_dicek"]
        out_rows.append(r)
    last = kv_get(conn, "livecheck_last_cycle", None)
    return {
        "preset": cfg.preset_name, "symbol": cfg.symbol, "timeframe": cfg.tf, "since": cfg.since,
        "price_bps": cfg.price_bps,
        "window": {"bars": bars, "start": iso(start), "end": iso(last_close)},
        "summary": {"counts": counts, "perlu_dicek": perlu, "rows": len(out_rows),
                    "expected": sum(1 for r in out_rows if r["expected"]),
                    "deliveries": sum(1 for r in out_rows if r["delivery"] and r["status"] != "diabaikan")},
        "rows": out_rows,
        "causes": CAUSES,
        "last_cycle": last,
    }
