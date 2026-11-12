"""Outlook Koin: pure logic (stdlib only, unit-tested, imported by the API and the job).

  * build_factors  -> one row per factor with direction (+1 long / -1 short / 0), group
                      (utama / mtf / konteks) and an evidence label saying how proven it is
  * combine        -> bias + keyakinan. The STRATEGY POSITION IS PRIMARY: the bias is always the
                      primary strategy's side. Keyakinan v2 comes from the measured outcome of
                      "kasus serupa" in the historical replay (calib.assess); other factors never
                      change it (none of them proved to add an edge in the replay)
  * plan           -> the actionable call: entry zone, SL / TP, invalidation ("batal kalau ..."),
                      horizon, R:R, typical target, freshness
  * changes        -> what changed since the previous 4H call
  * narrate        -> deterministic Indonesian explanation: decision -> why -> evidence -> risks.
                      ``NARRATORS`` is the extension point for an optional AI summary later
  * project        -> money projection for a capital / leverage / sizing chosen by the client
  * peluang / rank -> ordering of the "Peluang terbaik" list (evidence-weighted expected R)

Thresholds are module constants and are returned by the API (``method()``).
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Optional

from . import calib as C

# ── method constants (documented in the UI via method()) ─────────────────

SCHEMA_VERSION = 2
# v1 weights, kept for the API shape: v2 factors no longer change keyakinan (used_weight = 0)
WEIGHTS = {"screener": 0.0, "tren_1d": 0.0, "momentum_1h": 0.0, "regime": 0.0, "funding": 0.0, "oi": 0.0, "berita": 0.0}
EVIDENCE_MULT = {"terbukti": 1.0, "searah_pasar": 0.5, "belum_terbukti": 0.5, "belum_cukup_data": 0.5, "negatif": 0.0}
LEAN_MIN = 2                       # FLAT: |MTF score| >= this -> "condong naik/turun"
STALE_HOURS = 9.0                  # strategy bar older than this -> keyakinan rendah + warning
MIN_SIDE_TRADES = 10               # EV per side needs at least this many backtest trades
SMALL_SAMPLE = 30                  # below this the EV line is flagged "sampel kecil"
COST_PER_SIDE_PCT = {"commission": 0.05, "slippage": 0.05}
ZONE_R = 0.25                      # entry zone = close +/- 0.25 x (distance to SL)
HORIZON_HOURS = {"15m": 24, "30m": 48, "1h": 72, "4h": 168, "1d": 720}
KEYAKINAN_RANK = {"rendah": 1, "sedang": 2, "tinggi": 3}

EVIDENCE_TEXT = {
    "lolos_uji": "Lolos uji holdout",
    "gagal_uji": "Gagal uji holdout",
    "belum_diuji": "Belum diuji",
    "terbukti": "Terbukti (Catatan Sinyal)",
    "searah_pasar": "Searah pasar (Catatan Sinyal; belum terbukti dibanding BTC)",
    "negatif": "Rekam jejak negatif",
    "belum_terbukti": "Belum terbukti",
    "belum_cukup_data": "Belum cukup data",
    "historis": "Statistik backtest",
    "konteks": "Konteks, bukan sinyal",
    "tidak_tersedia": "Tidak tersedia",
    "teruji_replay": "Teruji (simulasi historis)",
    "belum_terbukti_replay": "Belum terbukti (simulasi historis)",
    "terbalik_replay": "Simulasi historis: berlawanan",
}
LIFT_EVIDENCE = {"teruji": "teruji_replay", "belum_terbukti": "belum_terbukti_replay", "terbalik": "terbalik_replay"}
SIGNAL_DIR = {"BULLISH": 1, "BUY": 1, "BEARISH": -1, "SELL": -1}
REGIME_DIR = {"naik": 1, "turun": -1, "datar": 0}
SIDE_SIGN = {"long": 1, "short": -1}
LEVELS = ("rendah", "sedang", "tinggi")
TEMPLATE_NAMES = {"rosyade_family": "Rosyade", "donchian_breakout": "Donchian breakout",
                  "mean_reversion_range": "Mean reversion"}

# ── formatting: exchange-style numbers (1,234.56), WIB times with Indonesian months ──

_MONTHS = ("Jan", "Feb", "Mar", "Apr", "Mei", "Jun", "Jul", "Agu", "Sep", "Okt", "Nov", "Des")
WIB = timezone(timedelta(hours=7))
MINUS = "−"


def _swap(s: str) -> str:
    """Kept as the single place to localise digits; exchange style (CEO decision 12 Nov) = unchanged."""
    return s


def fnum(x: Optional[float], dec: int = 1, signed: bool = False) -> str:
    if x is None:
        return "tidak tersedia"
    s = _swap(f"{abs(x):,.{dec}f}")
    if signed:
        return ("+" if x > 0 else MINUS if x < 0 else "") + s
    return (MINUS if x < 0 else "") + s


def fpct(x: Optional[float], dec: int = 1, signed: bool = True) -> str:
    return "tidak tersedia" if x is None else fnum(x, dec, signed) + "%"


def fr(x: Optional[float], dec: int = 2) -> str:
    return "tidak tersedia" if x is None else fnum(x, dec, True) + "R"


def fprice(p: Optional[float]) -> str:
    if p is None:
        return "tidak tersedia"
    a = abs(p)
    if a >= 1000:
        dec = 0
    elif a >= 100:
        dec = 2
    elif a >= 1:
        dec = 3
    else:
        dec = 4
        q = a
        while q and q < 0.1 and dec < 10:
            q *= 10
            dec += 1
    return fnum(p, dec)


def fusd(x: Optional[float], signed: bool = True) -> str:
    if x is None:
        return "tidak tersedia"
    return ("+" if signed and x > 0 else MINUS if x < 0 else "") + "$" + _swap(f"{abs(x):,.2f}")


def _dt(iso: Optional[str]) -> Optional[datetime]:
    if not iso:
        return None
    try:
        return datetime.strptime(iso[:19], "%Y-%m-%dT%H:%M:%S").replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def _iso(d: datetime) -> str:
    return d.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def fdate(iso: Optional[str], with_time: bool = True, year: bool = False) -> str:
    d = _dt(iso)
    if d is None:
        return "tidak tersedia"
    w = d.astimezone(WIB)
    s = f"{w.day} {_MONTHS[w.month - 1]}" + (f" {w.year}" if year else "")
    return f"{s} {w:%H:%M} WIB" if with_time else s


def hours_between(a: Optional[str], b: Optional[str]) -> Optional[float]:
    da, db = _dt(a), _dt(b)
    if da is None or db is None:
        return None
    return (db - da).total_seconds() / 3600.0


def fpp(p: Optional[float]) -> str:
    """Probability (0..1) as a whole Indonesian percent."""
    return "tidak tersedia" if p is None else f"{round(p * 100):.0f}%"


# ── strategy helpers ─────────────────────────────────────────────────────

def strategy_evidence(strategy: dict) -> str:
    p = strategy.get("preset")
    if not p or not p.get("verdict"):
        return "belum_diuji"
    return "lolos_uji" if p["verdict"] == "PASS" else "gagal_uji"


def strategy_label(strategy: dict) -> str:
    p = strategy.get("preset")
    if not p:
        return "Strategi " + (strategy.get("name") or "Rosyade default 4H")
    return f"Strategi {p['name']}"


def template_text(strategy: dict) -> str:
    tid = strategy.get("template_id") or "rosyade_family"
    return f"{TEMPLATE_NAMES.get(tid, tid)} {(strategy.get('timeframe') or '4h').upper()}"


def fase_of(strategy: dict) -> str:
    return "baru" if strategy.get("fresh") else "berjalan"


# ── factors ──────────────────────────────────────────────────────────────

def _factor(key: str, label: str, direction: int, value: str, detail: str, evidence: str, source: str,
            group: str, available: bool = True, lift: Optional[dict] = None) -> dict:
    return {"key": key, "label": label, "group": group, "direction": int(direction), "weight": 0.0,
            "used_weight": 0.0, "in_keyakinan": key == "strategi", "value": value, "detail": detail,
            "evidence": evidence, "evidence_text": EVIDENCE_TEXT[evidence], "source": source,
            "available": available, "lift": lift}


def _track(track: dict, stype: str, d: int) -> str:
    return (track or {}).get(f"{stype}:{d}") or "belum_cukup_data"


def _lift_text(lift: Optional[dict]) -> tuple[str, str, Optional[dict]]:
    """(evidence code, sentence, compact lift) from a calibration factor_lift entry."""
    if not lift:
        return "belum_terbukti", "Belum dikalibrasi di simulasi historis.", None
    a, o = lift.get("searah") or {}, lift.get("berlawanan") or {}
    code = LIFT_EVIDENCE.get(lift.get("verdict"), "belum_terbukti_replay")
    compact = {"verdict": lift.get("verdict"), "searah_mean_r": a.get("mean_r"), "searah_n_pos": a.get("n_pos"),
               "berlawanan_mean_r": o.get("mean_r"), "berlawanan_n_pos": o.get("n_pos"),
               "diff_r": lift.get("diff_r"), "se_diff_r": lift.get("se_diff_r"), "halves": lift.get("halves")}
    if a.get("n_pos") and o.get("n_pos"):
        txt = (f"Simulasi historis: saat searah rata-rata {fr(a.get('mean_r'))} ({a['n_pos']} posisi), saat berlawanan "
               f"{fr(o.get('mean_r'))} ({o['n_pos']} posisi) → "
               + {"teruji": "konsisten membantu.", "terbalik": "justru lebih buruk saat searah (tidak dipakai).",
                  "belum_terbukti": "belum terbukti menambah keunggulan (tidak dipakai untuk keyakinan)."}
               .get(lift.get("verdict"), "belum terbukti."))
    else:
        txt = "Simulasi historis: data belum cukup untuk menilai faktor ini."
    return code, txt, compact


def build_factors(ctx: dict) -> list[dict]:
    """ctx keys: strategy, mtf ({tren_1d, momentum_1h} states | None), regime (BTC current | None),
    regime_dir_at_call (int | None), lifts ({factor: lift} from the calibration | None), screener,
    track, strength, oi, headlines, fear_greed."""
    st = ctx["strategy"]
    side = st.get("side")
    lifts = ctx.get("lifts") or {}
    mtf = ctx.get("mtf") or {}
    out: list[dict] = []

    # 1. strategy (primary)
    ev = strategy_evidence(st)
    if st.get("error"):
        out.append(_factor("strategi", "Posisi strategi", 0, "tidak tersedia", f"Gagal menghitung: {st['error']}",
                           "tidak_tersedia", "Strategy Lab", "utama", available=False))
    else:
        val = side.upper() if side else "FLAT"
        p = st.get("preset")
        if p and p.get("verdict"):
            fc = ", ".join(p.get("failed_checks") or [])
            det = (f"Preset {p['name']} ({template_text(st)}): {'LOLOS' if p['verdict'] == 'PASS' else 'GAGAL'} uji holdout"
                   + (f" (gagal: {fc})" if fc else "")
                   + ("; holdout sudah pernah dilihat saat riset (tercemar)" if p.get("contaminated") else "") + ".")
        elif p:
            det = f"Preset {p['name']} ({template_text(st)}) belum punya hasil uji holdout."
        else:
            det = ("Belum ada preset yang lolos uji untuk koin ini; memakai setting default Rosyade 4H (aslinya "
                   "untuk ETH 4H). Belum diuji untuk koin ini.")
        if side:
            det += " " + ("Posisi baru di close terakhir." if st.get("fresh") else
                          f"Posisi sudah berjalan sejak {fdate(st.get('entry_at'))}.")
        out.append(_factor("strategi", "Posisi strategi", SIDE_SIGN.get(side or "", 0), val, det, ev, "Strategy Lab",
                           "utama"))

    # 2. trend 1D
    t = mtf.get("tren_1d")
    code, ltxt, lc = _lift_text(lifts.get("tren_1d"))
    if t:
        d = t["direction"]
        val = {1: "naik", -1: "turun", 0: "campuran"}[d]
        out.append(_factor("tren_1d", "Tren 1D", d, val,
                           f"Close harian {fpct(t.get('dist_pct'))} dari EMA50 harian, EMA50 "
                           f"{'naik' if (t.get('slope_pct') or 0) > 0 else 'turun'} {fpct(t.get('slope_pct'), 2)} "
                           f"dalam 10 hari. {ltxt}", code, "Candle 1D (close)", "mtf", lift=lc))
    else:
        out.append(_factor("tren_1d", "Tren 1D", 0, "tidak tersedia", "Data candle 1D tidak tersedia.",
                           "tidak_tersedia", "Candle 1D", "mtf", available=False))

    # 3. momentum 1H
    m = mtf.get("momentum_1h")
    code, ltxt, lc = _lift_text(lifts.get("momentum_1h"))
    if m:
        d = m["direction"]
        val = {1: "naik", -1: "turun", 0: "campuran"}[d]
        out.append(_factor("momentum_1h", "Momentum 1H", d, val,
                           f"Close 1H vs EMA20/EMA50 1H: {'di atas keduanya' if d > 0 else 'di bawah keduanya' if d < 0 else 'campuran'}; "
                           f"perubahan 24 jam {fpct(m.get('ret_24h_pct'))}. {ltxt}", code, "Candle 1H (close)", "mtf",
                           lift=lc))
    else:
        out.append(_factor("momentum_1h", "Momentum 1H", 0, "tidak tersedia", "Data candle 1H tidak tersedia.",
                           "tidak_tersedia", "Candle 1H", "mtf", available=False))

    # 4. BTC regime
    rg = ctx.get("regime")
    code, ltxt, lc = _lift_text(lifts.get("regime_btc"))
    if rg and rg.get("label"):
        lab = rg["label"]
        d = ctx.get("regime_dir_at_call")
        d = REGIME_DIR.get(lab, 0) if d is None else d
        out.append(_factor("regime", "Kondisi pasar (BTC)", d, rg.get("label_text", lab),
                           f"BTC {fpct(rg.get('dist_ema_slow_pct'))} dari EMA 200 hari, EMA 50 "
                           f"{'naik' if (rg.get('slope_pct') or 0) > 0 else 'turun'} ({fpct(rg.get('slope_pct'), 2)} "
                           f"dalam 10 hari), label ini sudah {rg.get('days_in_label')} hari. {ltxt}", code,
                           "Regime BTC", "mtf", lift=lc))
    else:
        out.append(_factor("regime", "Kondisi pasar (BTC)", 0, "tidak tersedia", "Regime BTC tidak tersedia.",
                           "tidak_tersedia", "Regime BTC", "mtf", available=False))

    # 5. funding (crowding, contrarian; context)
    sc = ctx.get("screener")
    sr = ctx.get("strength")
    apr = sr.get("funding_7d_apr_pct") if sr else None
    fsig = sc.get("funding_rate_signal") if sc else None
    _c, fl_txt, fl = _lift_text(lifts.get("funding"))
    if fsig:
        d = SIGNAL_DIR.get(fsig, 0)
        ev = _track(ctx.get("track"), "funding", d) if d else "konteks"
        crowd = "long ramai (funding positif)" if d < 0 else "short ramai (funding negatif)" if d > 0 else "tidak ekstrem"
        rate = sc.get("funding_rate")
        out.append(_factor("funding", "Funding / keramaian", d, crowd,
                           f"Funding sekarang {fnum(rate, 4, True) + '%' if rate is not None else 'tidak tersedia'}"
                           f", rata-rata 7 hari {fpct(apr)} per tahun. Dibaca berlawanan arah (posisi ramai rawan "
                           f"dibalik). Konteks: tidak mengubah keyakinan. {fl_txt}", ev, "Screener + Koin Terkuat",
                           "konteks", lift=fl))
    elif apr is not None:
        out.append(_factor("funding", "Funding / keramaian", 0, f"APR {fpct(apr)}",
                           f"Rata-rata funding 7 hari {fpct(apr)} per tahun (tanpa sinyal screener). Konteks.",
                           "konteks", "Koin Terkuat", "konteks", lift=fl))
    else:
        out.append(_factor("funding", "Funding / keramaian", 0, "tidak tersedia", "Data funding tidak tersedia.",
                           "tidak_tersedia", "Screener", "konteks", available=False))

    # 6. open interest (context)
    oi = ctx.get("oi") or {}
    osig = sc.get("oi_signal") if sc else None
    chg = oi.get("change_24h_pct")
    if osig or chg is not None:
        d = SIGNAL_DIR.get(osig or "", 0)
        ev = _track(ctx.get("track"), "oi", d) if d else "konteks"
        out.append(_factor("oi", "Open interest", d, f"OI 24 jam {fpct(chg)}" if chg is not None else (osig or "—"),
                           f"Sinyal OI screener: {osig or 'tidak tersedia'}; perubahan OI 24 jam (Binance): {fpct(chg)}. "
                           "Konteks: riwayat OI terlalu pendek untuk diuji ulang.", ev, "Screener + Binance", "konteks"))
    else:
        out.append(_factor("oi", "Open interest", 0, "tidak tersedia", "Data open interest tidak tersedia.",
                           "tidak_tersedia", "Binance", "konteks", available=False))

    # 7. screener composite (context, with its own Signal Ledger track record)
    if sc and sc.get("signal"):
        d = SIGNAL_DIR.get(sc["signal"], 0)
        stype = "komposit_high" if sc.get("confidence_tier") == "HIGH" else "komposit"
        ev = _track(ctx.get("track"), stype, d) if d else "konteks"
        tier = f", tier {sc['tier']}" if sc.get("tier") else ""
        conf = f", keyakinan screener {fnum(sc.get('confidence_pct'), 0, False)}%" if sc.get("confidence_pct") is not None else ""
        out.append(_factor("screener", "Screener komposit", d, f"{sc['signal']}{tier}",
                           f"Sinyal komposit screener: {sc['signal']}{tier}{conf} (snapshot {fdate(sc.get('bar'))}). "
                           "Rekam jejaknya dinilai di Catatan Sinyal; tidak mengubah keyakinan.", ev,
                           "Screener + Catatan Sinyal", "konteks"))
    else:
        out.append(_factor("screener", "Screener komposit", 0, "tidak tersedia",
                           "Belum ada snapshot screener untuk koin ini.", "tidak_tersedia", "Screener", "konteks",
                           available=False))

    # 8. news (context only, never a direction)
    hl = ctx.get("headlines")
    fg = ctx.get("fear_greed")
    fg_txt = f"Fear & Greed pasar {fg['value']} ({fg.get('classification') or '-'})" if fg else \
        "Fear & Greed tidak tersedia"
    if hl is None:
        out.append(_factor("berita", "Berita & sentimen", 0, "tidak tersedia",
                           f"Headline tidak tersedia (sumber gagal dimuat). {fg_txt}.", "tidak_tersedia",
                           "CoinTelegraph RSS + alternative.me", "konteks", available=False))
    else:
        out.append(_factor("berita", "Berita & sentimen", 0, f"{len(hl)} headline" if hl else "tidak ada headline",
                           f"{len(hl)} headline terbaru menyebut koin ini. {fg_txt}. Konteks saja: tidak ada arsip "
                           "berita per koin untuk diuji, jadi tidak dihitung sebagai sinyal.", "konteks",
                           "CoinTelegraph RSS + alternative.me", "konteks"))
    return out


def mtf_score(factors: list[dict], side_sign: int = 1) -> tuple[int, int]:
    """(score, n available) over the MTF factors relative to ``side_sign`` (+1 = long)."""
    score, n = 0, 0
    for f in factors:
        if f.get("group") == "mtf" and f["available"]:
            score += f["direction"] * side_sign
            n += 1
    return score, n


def align_group(score: int) -> str:
    return "searah" if score >= 2 else "berlawanan" if score <= -2 else "campuran"


# ── bias + keyakinan ─────────────────────────────────────────────────────

def _calib_brief(st: Optional[dict]) -> Optional[dict]:
    if not st:
        return None
    keys = ("n_cases", "n_pos", "p_tp", "p_sl", "p_batal", "p_expired", "mean_r", "lo95_r", "median_r",
            "ev_shrunk_r", "win_rate", "median_mfe_r", "median_bars")
    return {k: st.get(k) for k in keys}


def combine(factors: list[dict], strategy: dict, calibration: Optional[dict] = None,
            now_iso: Optional[str] = None, price: Optional[float] = None) -> dict:
    side = strategy.get("side")
    if strategy.get("error"):
        return {"bias": "NETRAL", "keyakinan": None, "condong": None, "support": None, "lean": None,
                "max_support": None, "reasons": ["Posisi strategi tidak bisa dihitung."], "basis": None}
    lean, n = mtf_score(factors, 1)
    if not side:
        condong = "naik" if lean >= LEAN_MIN else "turun" if lean <= -LEAN_MIN else None
        txt = (f"Faktor 1D/1H/BTC condong {condong} (skor {fnum(lean, 0, True)} dari {n}); belum terbukti sebagai sinyal."
               if condong else f"Faktor 1D/1H/BTC tidak condong jelas (skor {fnum(lean, 0, True)} dari {n}).")
        return {"bias": "NETRAL", "keyakinan": None, "condong": condong, "support": None, "lean": lean,
                "max_support": n, "reasons": ["Strategi FLAT: tidak ada posisi, jadi tidak ada arah.", txt],
                "basis": None}
    s = SIDE_SIGN[side]
    support = lean * s
    cls = strategy_evidence(strategy)
    fase = fase_of(strategy)
    contaminated = bool((strategy.get("preset") or {}).get("contaminated"))
    buckets = (calibration or {}).get("buckets")
    out: dict[str, Any] = {"bias": side.upper(), "condong": None, "support": support, "lean": lean,
                           "max_support": n, "cls": cls, "fase": fase, "align": align_group(support)}
    if buckets:
        a = C.assess(buckets, cls, side, fase, contaminated)
        level, reasons, basis = a["level"], list(a["reasons"]), "kalibrasi"
        out["conclusion"] = a.get("conclusion")
        out["calib"] = {"key": a["key"], "enough": a["enough"], "stats": _calib_brief(a["stats"]),
                        "own_key": a["own_key"], "own": _calib_brief(a["own"]),
                        "pool_key": a["pool_key"], "pooled": _calib_brief(a["pooled"]),
                        "computed_at": calibration.get("computed_at")}
    else:
        basis = "aturan"
        level = "sedang" if cls == "lolos_uji" else "rendah"
        reasons = ["Kalibrasi historis belum tersedia: memakai aturan sederhana (preset LOLOS = sedang, "
                   "lainnya rendah)."]
        out["calib"] = None
        out["conclusion"] = "belum dikalibrasi"
    if price is not None and strategy.get("sl") is not None and (price - strategy["sl"]) * s <= 0:
        level = "rendah"
        reasons.append("Harga sudah melewati SL strategi: posisi kemungkinan tertutup di candle berikutnya.")
    age = hours_between(strategy.get("last_bar_close"), now_iso) if now_iso else None
    if age is not None and age > STALE_HOURS:
        level = "rendah"
        reasons.append(f"Data strategi sudah {fnum(age, 0)} jam (basi): keyakinan rendah.")
    out.update({"keyakinan": level, "reasons": reasons, "basis": basis})
    return out


# ── actionable plan ──────────────────────────────────────────────────────

def horizon_bars(tf: Optional[str]) -> int:
    return max(1, HORIZON_HOURS.get(tf or "4h", 168) // 4)


def plan(strategy: dict, price: Optional[float], bias: dict, now_iso: Optional[str] = None) -> dict:
    """The call as instructions: entry zone, SL, TP, R:R, typical target, invalidation, horizon."""
    side, sl, tp = strategy.get("side"), strategy.get("sl"), strategy.get("tp")
    tf = strategy.get("timeframe") or "4h"
    bar_close = strategy.get("last_bar_close")
    age = hours_between(bar_close, now_iso) if now_iso else None
    fresh = {"bar_close": bar_close, "age_hours": age, "stale": age is not None and age > STALE_HOURS,
             "fresh_signal": bool(strategy.get("fresh"))}
    if not side or not price:
        return {"action": "tunggu", "side": None, "freshness": fresh,
                "text": "Tidak ada sinyal: strategi utama FLAT. Tunggu sampai strategi membuka posisi."}
    s = SIDE_SIGN[side]
    hb = horizon_bars(tf)
    hours = hb * 4
    d_close = _dt(bar_close)
    until = _iso(d_close + timedelta(hours=hours)) if d_close else None
    out: dict[str, Any] = {"side": side, "price": price, "sl": sl, "tp": tp, "timeframe": tf, "horizon_bars": hb,
                           "horizon_hours": hours, "valid_until": until, "freshness": fresh,
                           "fase": fase_of(strategy)}
    r_unit = (price - sl) * s if sl is not None else None
    if r_unit is None or r_unit <= 0:
        out.update({"action": "jangan_masuk", "geometry_ok": False,
                    "text": "Harga sudah melewati SL strategi: jangan masuk; posisi strategi kemungkinan tertutup."})
        return out
    hw = ZONE_R * r_unit
    worse = price + s * hw          # entry closer to TP = worse R:R
    better = price - s * hw
    rr = (tp - price) * s / r_unit if tp is not None and (tp - price) * s > 0 else None
    rr_worse = (tp - worse) * s / ((worse - sl) * s) if tp is not None and (tp - worse) * s > 0 else None
    st = ((bias.get("calib") or {}).get("stats")) or {}
    mfe = st.get("median_mfe_r")
    typical = price + s * mfe * r_unit if mfe is not None and mfe > 0 else None
    warns = []
    if rr is not None and rr < 1:
        warns.append(f"R:R {fnum(rr, 2, False)} : 1 — TP lebih dekat daripada SL.")
    if tp is None:
        warns.append("Strategi ini tidak memasang TP tetap (keluar lewat trailing stop / exit lain).")
    inval = [f"harga menyentuh SL {fprice(sl)} ({fpct(r_unit / price * 100, 1, False)} dari harga sekarang)",
             "strategi menutup atau membalik posisi (dicek setiap close 4H di halaman ini)",
             f"sampai {fdate(until)} belum kena TP/SL (horizon {hours // 24} hari)"]
    out.update({
        "action": "masuk" if out["fase"] == "baru" else "menyusul",
        "geometry_ok": True, "r_unit": r_unit, "r_unit_pct": r_unit / price * 100.0, "rr": rr,
        "entry_zone": [min(worse, better), max(worse, better)], "dont_chase": worse, "rr_at_dont_chase": rr_worse,
        "target_typical": typical, "target_typical_r": mfe,
        "invalidation": inval, "batal_kalau": "Batal kalau " + "; atau ".join(inval) + ".", "warnings": warns,
        "saran": saran(out["fase"], bias.get("keyakinan"), rr),
        "text": ("Posisi baru: rencana masuk di zona entry." if out["fase"] == "baru" else
                 f"Posisi strategi sudah berjalan sejak {fdate(strategy.get('entry_at'))}; masuk sekarang = menyusul."),
    })
    return out


def saran(fase: str, keyakinan: Optional[str], rr: Optional[float]) -> str:
    """One evidence-based guidance line (the page's "what to do"), never a promise."""
    if fase == "baru":
        if keyakinan in ("sedang", "tinggi"):
            s = "Posisi baru dengan bukti historis positif: layak dipertimbangkan sesuai rencana di bawah."
        else:
            s = "Posisi baru, tetapi bukti historisnya belum positif: hati-hati, ukuran kecil atau lewati."
    elif keyakinan in ("sedang", "tinggi"):
        s = "Menyusul posisi yang sudah berjalan masih punya bukti positif, tetapi lebih lemah daripada posisi baru."
    else:
        s = ("Lebih baik tunggu posisi baru: menyusul posisi yang sudah berjalan secara historis tidak punya "
             "keunggulan.")
    if rr is not None and rr < 1:
        s += " R:R di bawah 1."
    return s


# ── what changed since the previous 4H call ──────────────────────────────

def _lvl(x: Optional[str]) -> str:
    return x or "—"


def changes(cur: dict, prev: Optional[dict]) -> list[str]:
    """``cur``/``prev``: call records (store.save_call shape; ``call`` = compact extras)."""
    if prev is None:
        return ["Panggilan pertama yang tercatat untuk koin ini."]
    out = []
    cs, ps = cur.get("side"), prev.get("side")
    if cs != ps:
        if cs and not ps:
            out.append(f"Arah berubah: FLAT → {cs.upper()}" + (" (posisi baru)." if cur.get("fase") == "baru" else "."))
        elif ps and not cs:
            out.append(f"Arah berubah: {ps.upper()} → FLAT (strategi keluar posisi).")
        else:
            out.append(f"Arah berbalik: {ps.upper()} → {cs.upper()}.")
    elif cs and cur.get("strategy_entry_time") != prev.get("strategy_entry_time"):
        out.append("Strategi membuka posisi baru di arah yang sama.")
    if (cur.get("strategy") or "") != (prev.get("strategy") or "") and cs:
        out.append(f"Strategi utama berganti: {prev.get('strategy') or '—'} → {cur.get('strategy')}.")
    if cs and ps == cs:
        if cur.get("keyakinan") != prev.get("keyakinan"):
            a, b = KEYAKINAN_RANK.get(prev.get("keyakinan") or "", 0), KEYAKINAN_RANK.get(cur.get("keyakinan") or "", 0)
            out.append(f"Keyakinan {'naik' if b > a else 'turun'}: {_lvl(prev.get('keyakinan'))} → {_lvl(cur.get('keyakinan'))}.")
        for k, name in (("sl", "SL"), ("tp", "TP")):
            a, b = prev.get(k), cur.get(k)
            if a is not None and b is not None and abs(a - b) > 1e-9 * max(1.0, abs(a)):
                out.append(f"{name} bergeser dari {fprice(a)} ke {fprice(b)}" + (" (trailing stop)." if k == "sl" else "."))
            elif (a is None) != (b is None):
                out.append(f"{name}: {fprice(a)} → {fprice(b)}.")
        if prev.get("fase") == "baru" and cur.get("fase") == "berjalan":
            out.append("Posisi kemarin bukan lagi posisi baru: masuk sekarang = menyusul.")
    pdirs, cdirs = (prev.get("call") or {}).get("dirs") or {}, (cur.get("call") or {}).get("dirs") or {}
    names = {"tren_1d": "Tren 1D", "momentum_1h": "Momentum 1H", "regime_btc": "Kondisi pasar BTC"}
    word = {1: "naik", -1: "turun", 0: "campuran"}
    for k, nm in names.items():
        a, b = pdirs.get(k), cdirs.get(k)
        if a is not None and b is not None and a != b:
            out.append(f"{nm} berubah: {word.get(a, a)} → {word.get(b, b)}.")
    pp, cp = prev.get("price"), cur.get("price")
    if pp and cp:
        out.append(f"Harga {fpct((cp / pp - 1) * 100, 1)} sejak close 4H sebelumnya ({fprice(pp)} → {fprice(cp)}).")
    return out or ["Tidak ada perubahan berarti sejak close 4H sebelumnya."]


# ── strategies agreement ─────────────────────────────────────────────────

def agreement(strategies: list[dict]) -> dict:
    """Counts of LONG / SHORT / FLAT among the strategies run for a coin (validated ones apart)."""
    def count(xs):
        return {"long": sum(1 for x in xs if x.get("side") == "long"),
                "short": sum(1 for x in xs if x.get("side") == "short"),
                "flat": sum(1 for x in xs if not x.get("side") and not x.get("error")),
                "error": sum(1 for x in xs if x.get("error")), "n": len(xs)}
    valid = [x for x in strategies if x.get("verdict") == "PASS"]
    return {"all": count(strategies), "lolos_uji": count(valid)}


def _agree_sentence(strategies: list[dict], side: Optional[str]) -> Optional[str]:
    others = [x for x in strategies if not x.get("primary")]
    if not others:
        return None
    if side:
        same = [x["name"] for x in others if x.get("side") == side]
        opp = [x["name"] for x in others if x.get("side") and x.get("side") != side]
        flat = [x["name"] for x in others if not x.get("side") and not x.get("error")]
        bits = []
        if same:
            bits.append(f"{len(same)} strategi lain juga {side.upper()} ({', '.join(same[:3])})")
        if opp:
            bits.append(f"{len(opp)} berlawanan ({', '.join(opp[:3])})")
        if flat:
            bits.append(f"{len(flat)} FLAT")
        return "Strategi lain: " + "; ".join(bits) + "." if bits else None
    act = [f"{x['name']} {x['side'].upper()}" for x in others if x.get("side")]
    return ("Strategi lain yang sedang punya posisi: " + ", ".join(act[:4]) + " (bukan strategi utama).") if act else None


# ── narrative (template; extension point for an AI summary) ──────────────

def _strategy_sentence(st: dict, price: Optional[float]) -> str:
    ev = strategy_evidence(st)
    tag = {"lolos_uji": "LOLOS uji", "gagal_uji": "GAGAL uji", "belum_diuji": "belum diuji untuk koin ini"}[ev]
    head = f"{strategy_label(st)} ({template_text(st)}, {tag})"
    if st.get("error"):
        return f"{head}: posisi tidak bisa dihitung ({st['error']})."
    if st.get("side"):
        s = (f"{head} sedang {st['side'].upper()} sejak {fdate(st.get('entry_at'))} di {fprice(st.get('entry_price'))}"
             + (" (posisi baru di close terakhir)" if st.get("fresh") else "") + f"; harga sekarang {fprice(price)}"
             + (f" ({fpct(st.get('open_pnl_pct'))} dari entry strategi)" if st.get("open_pnl_pct") is not None else "")
             + ".")
        return s
    last = st.get("last_exit")
    s = f"{head} sedang FLAT (tidak punya posisi)"
    if last:
        s += (f"; posisi terakhir {last['side'].upper()} ditutup {fdate(last.get('time'))} "
              f"({last.get('reason') or '-'}, {fpct(last.get('pnl_pct'))})")
    return s + "."


_WORD = {1: "naik", -1: "turun", 0: "campuran"}


def _mtf_sentence(factors: list[dict], side: Optional[str]) -> Optional[str]:
    mt = [f for f in factors if f.get("group") == "mtf" and f["available"]]
    if not mt:
        return "Faktor 1D/1H/BTC tidak tersedia."
    parts = [f"{f['label']} {_WORD.get(f['direction'], '?')}" for f in mt]
    if side:
        s = SIDE_SIGN[side]
        pro = sum(1 for f in mt if f["direction"] * s > 0)
        con = sum(1 for f in mt if f["direction"] * s < 0)
        return (f"Konteks: {', '.join(parts)} → {pro} searah, {con} berlawanan dengan {side.upper()}. "
                "Di simulasi historis faktor-faktor ini belum terbukti menambah keunggulan, jadi tidak mengubah keyakinan.")
    return f"Konteks: {', '.join(parts)}."


def _evidence_sentence(bias: dict) -> Optional[str]:
    cal = bias.get("calib") or {}
    st = cal.get("stats")
    if not st or not st.get("n_cases"):
        return None
    key = cal.get("key") or ""
    cls = key.split("|")[0]
    fase = key.split("|")[-1]
    who = C.CLASS_TEXT.get(cls, cls)
    s = (f"Kasus serupa — {C.FASE_TEXT.get(fase, fase)}, {who}: {fnum(st['n_cases'], 0)} panggilan dari {fnum(st['n_pos'], 0)} posisi; "
         f"kena TP dulu {fpp(st.get('p_tp'))}, kena SL dulu {fpp(st.get('p_sl'))}, dibatalkan karena strategi keluar "
         f"{fpp(st.get('p_batal'))}, habis waktu {fpp(st.get('p_expired'))}. Rata-rata {fr(st.get('mean_r'))} per "
         f"panggilan (median {fr(st.get('median_r'))}, menang {fpp(st.get('win_rate'))}).")
    if st.get("median_mfe_r"):
        s += f" Setengah kasus sempat untung ≥ {fr(st['median_mfe_r'])} sebelum ditutup."
    if not cal.get("enough"):
        s += " Sampel kecil: baca dengan hati-hati."
    return s


def narrate_template(row: dict) -> dict:
    st, factors, bias = row["strategy"], row["factors"], row["bias"]
    side = st.get("side")
    coin = row.get("coin") or str(row.get("symbol", "")).replace("USDT", "")
    pl = row.get("plan") or {}
    paras: list[str] = []
    # 1. decision first
    if side:
        k = bias.get("keyakinan")
        head = f"Keputusan: {coin} cenderung {side.upper()}, keyakinan {k}."
        if pl.get("geometry_ok"):
            z = pl.get("entry_zone") or [None, None]
            head += (f" Rencana: entry {fprice(z[0])}–{fprice(z[1])}, SL {fprice(st.get('sl'))}, "
                     f"TP {fprice(st.get('tp')) if st.get('tp') is not None else 'tidak ada (strategi keluar lewat trailing/exit)'}"
                     + (f", R:R {fnum(pl.get('rr'), 1, False)} : 1" if pl.get("rr") else "")
                     + f"; berlaku sampai {fdate(pl.get('valid_until'))}.")
            if pl.get("saran"):
                head += " " + pl["saran"]
        else:
            head += " " + (pl.get("text") or "")
    else:
        head = f"Keputusan: {coin} tidak ada sinyal (strategi FLAT) — tunggu."
        if bias.get("condong"):
            head += f" Faktor konteks condong {bias['condong']}, tetapi itu belum terbukti sebagai sinyal."
    paras.append(head)
    # 2. why
    why = [_strategy_sentence(st, row.get("price"))]
    ag = _agree_sentence(row.get("strategies") or [], side)
    if ag:
        why.append(ag)
    ms = _mtf_sentence(factors, side)
    if ms:
        why.append(ms)
    paras.append("Kenapa: " + " ".join(why))
    # 3. evidence
    if side:
        es = _evidence_sentence(bias)
        extra = [r for r in (bias.get("reasons") or [])[1:]] if bias.get("basis") == "kalibrasi" else list(bias.get("reasons") or [])
        concl = f"Kesimpulan: keyakinan {bias.get('keyakinan')} — {bias.get('conclusion') or 'tidak tersedia'}."
        paras.append("Bukti: " + (es or "Belum ada kasus serupa yang terukur di simulasi historis.") + " " + concl
                     + (" " + " ".join(extra) if extra else ""))
    # 4. risks
    notes = []
    ev = strategy_evidence(st)
    if ev == "gagal_uji":
        notes.append("preset strategi GAGAL uji holdout")
    elif ev == "belum_diuji":
        notes.append("strategi belum diuji untuk koin ini (setting default Rosyade 4H)")
    if (st.get("preset") or {}).get("contaminated"):
        notes.append("holdout preset sudah pernah dilihat saat riset, hasil ujinya bisa terlalu optimis")
    if st.get("watch_check") and st["watch_check"].get("agrees") is False:
        notes.append(f"Pantau #{st['watch_check']['watch_id']} menunjukkan posisi berbeda (jendela data berbeda)")
    if (row.get("freshness") or pl.get("freshness") or {}).get("stale"):
        notes.append("data sudah basi (lebih dari 9 jam sejak close 4H)")
    hl = next((f for f in factors if f["key"] == "berita"), None)
    if hl and hl["available"] and hl["value"] not in ("tidak ada headline",):
        notes.append(f"ada {hl['value']} terkait (baca sendiri; tidak dihitung)")
    if side:
        risk = "Risiko: " + ("; ".join(notes) + ". " if notes else "") + (pl.get("batal_kalau") or "")
        paras.append(risk.strip())
    elif notes:
        paras.append("Catatan: " + "; ".join(notes) + ".")
    paras.append("Ini informasi, bukan jaminan atau saran investasi.")
    # summary (list view)
    if side:
        cal = (bias.get("calib") or {}).get("stats") or {}
        summary = (f"{side.upper()} · keyakinan {bias.get('keyakinan')} · "
                   + ("posisi baru" if st.get("fresh") else f"menyusul (sejak {fdate(st.get('entry_at'), False)})")
                   + f" · {strategy_label(st).replace('Strategi ', '')} ({ {'lolos_uji': 'lolos uji', 'gagal_uji': 'gagal uji', 'belum_diuji': 'belum diuji'}[ev] })"
                   + (f" · kasus serupa {fr(cal.get('mean_r'))} ({fnum(cal.get('n_pos'), 0)} posisi)" if cal.get("n_pos") else "")
                   + ".")
    else:
        summary = "Tidak ada sinyal (strategi FLAT)." + (f" Konteks condong {bias['condong']} (belum terbukti)." if bias.get("condong") else "")
    return {"summary": summary, "paragraphs": paras}


# Extension point: name -> fn(row) -> {"summary", "paragraphs"}. An AI narrator can be added
# here later; the template narrative stays the default and the source of truth.
NARRATORS: dict[str, Callable[[dict], dict]] = {"template": narrate_template}


def narrate(row: dict, narrator: str = "template") -> dict:
    out = NARRATORS[narrator](row)
    return {**out, "narrator": narrator, "ai_summary": None}


# ── money projection ─────────────────────────────────────────────────────

def _side_stats(bt: dict, side: str) -> tuple[Optional[dict], str]:
    s = (bt.get("by_side") or {}).get(side) or {}
    if (s.get("n") or 0) >= MIN_SIDE_TRADES:
        return s, f"trade {side}"
    if bt.get("n"):
        return bt, "semua trade (trade " + side + f" < {MIN_SIDE_TRADES})"
    return None, ""


def project(row: dict, capital: float, leverage: float = 1.0, sizing: str = "notional",
            risk_pct: float = 1.0) -> dict:
    """Money projection if a position is opened NOW at the last 4H close, with the strategy's SL/TP.

    sizing='notional': position = capital x leverage. sizing='risk': position sized so the SL
    loss (incl. costs) is risk_pct of capital, capped at capital x leverage. Costs: commission +
    slippage per side (COST_PER_SIDE_PCT). Funding is not included (see the note).
    ``calibrated`` = the average result of similar historical calls (R) converted to dollars."""
    st = row.get("strategy") or {}
    side, price, sl, tp = st.get("side"), row.get("price"), st.get("sl"), st.get("tp")
    base = {"capital": capital, "leverage": leverage, "sizing": sizing, "risk_pct": risk_pct if sizing == "risk" else None,
            "cost_per_side_pct": sum(COST_PER_SIDE_PCT.values())}
    if not side or not price:
        return {**base, "available": False, "reason": "Strategi tidak punya posisi (FLAT): tidak ada TP/SL untuk diproyeksikan."}
    if sl is None:
        return {**base, "available": False, "reason": "SL strategi tidak tersedia."}
    s = SIDE_SIGN[side]
    c = sum(COST_PER_SIDE_PCT.values()) / 100.0
    sl_frac = abs(price - sl) / price
    warnings = []
    if (sl - price) * s >= 0:
        warnings.append("Harga sudah melewati SL strategi; posisi kemungkinan tertutup di candle berikutnya.")
    if tp is not None and (tp - price) * s <= 0:
        warnings.append("Harga sudah melewati TP strategi.")
    cap_notional = capital * leverage
    if sizing == "risk":
        per_unit_loss = sl_frac + c + c * (sl / price)
        notional = min(cap_notional, capital * risk_pct / 100.0 / per_unit_loss) if per_unit_loss > 0 else cap_notional
    else:
        notional = cap_notional
    qty = notional / price
    entry_cost = notional * c

    def at(x: Optional[float]) -> Optional[dict]:
        if x is None:
            return None
        gross = qty * (x - price) * s
        exit_cost = qty * x * c
        net = gross - entry_cost - exit_cost
        return {"price": x, "move_pct": (x - price) / price * 100.0 * s, "gross": gross, "fees": entry_cost + exit_cost,
                "net": net, "net_pct_of_capital": net / capital * 100.0 if capital else None}

    res_tp, res_sl, res_tp1 = at(tp), at(sl), None
    tp1 = st.get("tp1")
    if tp1 is not None and (tp1 - price) * s > 0 and (tp is None or abs(tp1 - price) < abs(tp - price)):
        res_tp1 = at(tp1)
    pl = row.get("plan") or {}
    res_typ = at(pl.get("target_typical")) if pl.get("target_typical") is not None else None
    rr = (res_tp["net"] / -res_sl["net"]) if res_tp and res_sl and res_sl["net"] < 0 and res_tp["net"] > 0 else None
    if leverage > 1 and sl_frac >= 0.9 / leverage:
        warnings.append(f"Dengan leverage {fnum(leverage, 1, False)}× jarak SL ({fpct(sl_frac * 100, 1, False)}) "
                        "mendekati/melewati jarak likuidasi: posisi bisa terlikuidasi sebelum SL.")
    ev = None
    bt = row.get("backtest") or {}
    stats, basis_side = _side_stats(bt, side)
    if stats and stats.get("mean_pct") is not None:
        n = stats.get("n") or 0
        ev = {
            "basis": bt.get("basis"), "basis_text": bt.get("basis_text"), "subset": basis_side, "n": n,
            "win_rate_pct": stats.get("win_rate_pct"), "avg_win_pct": stats.get("avg_win_pct"),
            "avg_loss_pct": stats.get("avg_loss_pct"), "mean_pct": stats.get("mean_pct"),
            "median_hold_hours": stats.get("median_hold_hours"),
            "ev_usd": notional * stats["mean_pct"] / 100.0,
            "avg_win_usd": notional * stats["avg_win_pct"] / 100.0 if stats.get("avg_win_pct") is not None else None,
            "avg_loss_usd": notional * stats["avg_loss_pct"] / 100.0 if stats.get("avg_loss_pct") is not None else None,
            "small_sample": n < SMALL_SAMPLE,
            "caveat": (f"Rata-rata hasil trade backtest strategi ({bt.get('basis_text') or 'backtest'}, {n} trade, "
                       f"{basis_side}); sudah termasuk biaya & funding di backtest. Bukan jaminan"
                       + ("; sampel kecil" if n < SMALL_SAMPLE else "") + "."),
        }
    cal = ((row.get("bias") or {}).get("calib") or {})
    cst = cal.get("stats") or {}
    calibrated = None
    if cst.get("mean_r") is not None and (sl - price) * s < 0:
        risk_usd = qty * abs(price - sl)
        calibrated = {
            "key": cal.get("key"), "n_cases": cst.get("n_cases"), "n_pos": cst.get("n_pos"),
            "mean_r": cst.get("mean_r"), "ev_shrunk_r": cst.get("ev_shrunk_r"), "lo95_r": cst.get("lo95_r"),
            "p_tp": cst.get("p_tp"), "p_sl": cst.get("p_sl"), "p_batal": cst.get("p_batal"),
            "p_expired": cst.get("p_expired"), "win_rate": cst.get("win_rate"), "risk_usd": risk_usd,
            "ev_usd": cst["mean_r"] * risk_usd,
            "lo95_usd": cst["lo95_r"] * risk_usd if cst.get("lo95_r") is not None else None,
            "enough": cal.get("enough"),
            "caveat": ("Rata-rata hasil panggilan serupa di simulasi historis (biaya sudah dipotong, funding belum), "
                       "dikonversi ke dolar dengan jarak SL posisi ini. Bukan jaminan."),
        }
    return {**base, "available": True, "basis_price": price, "basis_text": "jika masuk sekarang di harga close 4H terakhir",
            "side": side, "notional": notional, "margin": notional / leverage if leverage else notional, "qty": qty,
            "at_tp": res_tp, "at_tp1": res_tp1, "at_sl": res_sl, "at_typical": res_typ, "rr": rr,
            "rr_text": f"{fnum(rr, 2, False)} : 1" if rr else None,
            "expected": ev, "calibrated": calibrated, "warnings": warnings,
            "note": "Biaya: komisi 0.05% + slippage 0.05% per sisi. Funding tidak termasuk dalam angka TP/SL. "
                    "TP adalah batas keras strategi; strategi biasanya keluar lebih awal (trailing/exit lain)."}


# ── "Peluang terbaik": ordering ──────────────────────────────────────────

def peluang(row: dict) -> dict:
    """Evidence-weighted expected R of the call (shrunk EV of its "kasus serupa")."""
    st = row.get("strategy") or {}
    bias = row.get("bias") or {}
    pl = row.get("plan") or {}
    if row.get("unavailable") or not st.get("side"):
        return {"eligible": False, "score": None, "label": "tidak_ada_sinyal", "reason": "Strategi FLAT."}
    if not pl.get("geometry_ok", True):
        return {"eligible": False, "score": None, "label": "tidak_valid", "reason": "Harga sudah melewati SL."}
    if (pl.get("freshness") or {}).get("stale") or row.get("stale"):
        return {"eligible": False, "score": None, "label": "basi", "reason": "Data basi."}
    cal = (bias.get("calib") or {}).get("stats") or {}
    ev = cal.get("ev_shrunk_r")
    if ev is None:
        return {"eligible": True, "score": None, "label": "belum_terukur",
                "reason": "Kalibrasi belum tersedia untuk panggilan seperti ini."}
    lo, mean = cal.get("lo95_r"), cal.get("mean_r")
    label = "positif" if lo is not None and lo > 0 else "negatif" if mean is not None and mean <= 0 else "belum_jelas"
    text = {"positif": "terbukti positif", "negatif": "tidak ada keunggulan", "belum_jelas": "belum berbeda nyata dari nol"}
    return {"eligible": True, "score": ev, "label": label,
            "reason": f"Nilai harapan kasus serupa {fr(ev)} (dikecilkan sesuai jumlah sampel): {text[label]}."}


def rank_key(row: dict):
    p = row.get("peluang") or {}
    b = row.get("bias") or {}
    rr = (row.get("plan") or {}).get("rr")
    return (0 if p.get("eligible") else 1,
            0 if p.get("score") is not None else 1,
            -(p.get("score") or 0.0),
            -KEYAKINAN_RANK.get(b.get("keyakinan") or "", 0),
            -(rr or 0.0),
            row.get("symbol") or "")


def rank_rows(rows: list[dict]) -> list[dict]:
    out = sorted(rows, key=rank_key)
    r = 0
    for row in out:
        if (row.get("peluang") or {}).get("eligible"):
            r += 1
            row["peluang"] = {**row["peluang"], "rank": r}
    return out


def method() -> dict:
    return {
        "schema_version": SCHEMA_VERSION, "weights": WEIGHTS, "evidence_mult": EVIDENCE_MULT, "lean_min": LEAN_MIN,
        "stale_hours": STALE_HOURS, "zone_r": ZONE_R, "horizon_hours": HORIZON_HOURS, "evidence_text": EVIDENCE_TEXT,
        "calibration": {"min_pos": C.MIN_POS, "shrink_k": C.SHRINK_K, "tinggi_min_pos": C.TINGGI_MIN_POS,
                        "tinggi_min_r": C.TINGGI_MIN_R, "class_cap": C.CLASS_CAP},
        "text": [
            "Arah selalu mengikuti posisi strategi utama koin itu: preset yang LOLOS uji (template & timeframe apa "
            "pun); kalau belum ada, setting default Rosyade 4H (belum diuji untuk koin itu). Faktor lain tidak "
            "pernah membalik arah.",
            "Keyakinan berasal dari hasil 'kasus serupa' di simulasi historis (setiap close 4H sejak 2020 dihitung "
            "ulang tanpa melihat masa depan): kelas bukti strategi × arah × fase (posisi baru atau menyusul).",
            "sedang = kasus serupa untung dengan batas bawah 95% di atas nol; tinggi = sama, untuk strategi itu "
            f"sendiri, rata-rata ≥ {fnum(C.TINGGI_MIN_R, 2, True)}R dan ≥ {C.TINGGI_MIN_POS} posisi; selain itu "
            "rendah. Maksimal sedang untuk strategi belum diuji, rendah untuk preset GAGAL, sedang untuk holdout "
            "tercemar. Data basi (> 9 jam) atau harga sudah melewati SL = rendah.",
            "Faktor 1D, 1H, kondisi BTC, funding, OI, screener dan berita ditampilkan sebagai konteks dengan label "
            "buktinya; tidak ada yang terbukti menambah keunggulan di simulasi, jadi tidak mengubah keyakinan.",
            "Peluang terbaik diurutkan dari nilai harapan kasus serupa (R, dikecilkan n/(n+20)), lalu keyakinan, "
            "lalu R:R. R = kelipatan jarak SL; biaya 0.2% pulang-pergi sudah dipotong.",
            "Strategi FLAT → NETRAL (tunggu); jika ≥ 2 faktor konteks searah, ditulis 'condong naik/turun'.",
        ],
    }
