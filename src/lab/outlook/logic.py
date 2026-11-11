"""Outlook Koin: pure logic (stdlib only, unit-tested, imported by the API and the job).

  * build_factors  -> one row per factor with direction (+1 long / -1 short / 0) and an
                      evidence label saying how proven that factor is
  * combine        -> bias + keyakinan. The STRATEGY POSITION IS PRIMARY: the bias is always
                      the strategy's side; other factors only raise or lower keyakinan
  * narrate        -> deterministic Indonesian explanation (template based, no LLM).
                      ``NARRATORS`` is the extension point for an optional AI summary later
  * project        -> money projection for a capital / leverage / sizing chosen by the client

Weights and thresholds are module constants and are returned by the API (``method()``)
so the UI can show exactly how a bias was reached.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Optional

# ── method constants (documented in the UI via method()) ─────────────────

# Secondary factor weights. The strategy itself has no weight: it sets the direction.
WEIGHTS = {"screener": 1.0, "tren": 1.0, "momentum": 1.0, "regime": 1.0, "funding": 0.5, "oi": 0.5, "berita": 0.0}
# Factors whose evidence is a Signal Ledger track record count fully only when proven.
EVIDENCE_MULT = {"terbukti": 1.0, "belum_terbukti": 0.5, "belum_cukup_data": 0.5, "negatif": 0.0}
MOMENTUM_THRESHOLD_PCT = 5.0       # |30-day return| below this = no momentum direction
SUPPORT_HIGH = 2.0                 # PASS preset + support >= this -> keyakinan tinggi
SUPPORT_LOW = -1.5                 # PASS preset + support <= this -> keyakinan rendah
LEAN_MIN = 2.0                     # FLAT: |lean| >= this -> "condong naik/turun"
STALE_HOURS = 9.0                  # strategy bar older than this -> keyakinan rendah + warning
MIN_SIDE_TRADES = 10               # EV per side needs at least this many backtest trades
SMALL_SAMPLE = 30                  # below this the EV line is flagged "sampel kecil"
COST_PER_SIDE_PCT = {"commission": 0.05, "slippage": 0.05}

EVIDENCE_TEXT = {
    "lolos_uji": "Lolos uji holdout",
    "gagal_uji": "Gagal uji holdout",
    "belum_diuji": "Belum diuji",
    "terbukti": "Terbukti (Catatan Sinyal)",
    "negatif": "Rekam jejak negatif",
    "belum_terbukti": "Belum terbukti",
    "belum_cukup_data": "Belum cukup data",
    "historis": "Statistik backtest",
    "konteks": "Konteks, bukan sinyal",
    "tidak_tersedia": "Tidak tersedia",
}
SIGNAL_DIR = {"BULLISH": 1, "BUY": 1, "BEARISH": -1, "SELL": -1}
REGIME_DIR = {"naik": 1, "turun": -1, "datar": 0}
SIDE_SIGN = {"long": 1, "short": -1}
LEVELS = ("rendah", "sedang", "tinggi")

# ── Indonesian formatting ────────────────────────────────────────────────

_MONTHS = ("Jan", "Feb", "Mar", "Apr", "Mei", "Jun", "Jul", "Agu", "Sep", "Okt", "Nov", "Des")
WIB = timezone(timedelta(hours=7))
MINUS = "−"


def _swap(s: str) -> str:
    return s.replace(",", "\x00").replace(".", ",").replace("\x00", ".")


def fnum(x: Optional[float], dec: int = 1, signed: bool = False) -> str:
    if x is None:
        return "tidak tersedia"
    s = _swap(f"{abs(x):,.{dec}f}")
    if signed:
        return ("+" if x > 0 else MINUS if x < 0 else "") + s
    return (MINUS if x < 0 else "") + s


def fpct(x: Optional[float], dec: int = 1, signed: bool = True) -> str:
    return "tidak tersedia" if x is None else fnum(x, dec, signed) + "%"


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


# ── factors ──────────────────────────────────────────────────────────────

def _factor(key: str, label: str, direction: int, value: str, detail: str, evidence: str, source: str,
            available: bool = True, mult: float = 1.0) -> dict:
    w = WEIGHTS.get(key, 0.0)
    return {"key": key, "label": label, "direction": int(direction), "weight": w,
            "used_weight": round(w * mult, 3) if available else 0.0, "value": value, "detail": detail,
            "evidence": evidence, "evidence_text": EVIDENCE_TEXT[evidence], "source": source, "available": available}


def _track(track: dict, stype: str, d: int) -> str:
    return (track or {}).get(f"{stype}:{d}") or "belum_cukup_data"


def strategy_evidence(strategy: dict) -> str:
    p = strategy.get("preset")
    if not p or not p.get("verdict"):
        return "belum_diuji"
    return "lolos_uji" if p["verdict"] == "PASS" else "gagal_uji"


def strategy_label(strategy: dict) -> str:
    p = strategy.get("preset")
    if not p:
        return "Strategi Rosyade default"
    return f"Strategi {p['name']}"


def build_factors(ctx: dict) -> list[dict]:
    """ctx keys: strategy, screener (live snapshot | None), track {"type:dir": verdict}, strength (row | None),
    oi ({change_24h_pct} | None), regime (BTC current | None), regime_perf (by_regime of this strategy | None),
    headlines (list), fear_greed (dict | None)."""
    st = ctx["strategy"]
    side = st.get("side")
    out: list[dict] = []

    # 1. strategy (primary; no weight)
    ev = strategy_evidence(st)
    if st.get("error"):
        out.append(_factor("strategi", "Posisi strategi", 0, "tidak tersedia", f"Gagal menghitung: {st['error']}",
                           "tidak_tersedia", "Strategy Lab", available=False))
    else:
        val = side.upper() if side else "FLAT"
        p = st.get("preset")
        if p and p.get("verdict"):
            fc = ", ".join(p.get("failed_checks") or [])
            det = f"Preset {p['name']}: {'LOLOS' if p['verdict'] == 'PASS' else 'GAGAL'} uji holdout" + \
                  (f" (gagal: {fc})" if fc else "") + \
                  ("; holdout sudah pernah dilihat saat riset (tercemar)" if p.get("contaminated") else "") + "."
        elif p:
            det = f"Preset {p['name']} belum punya hasil uji holdout."
        else:
            det = "Belum ada preset untuk koin ini; memakai setting default template (aslinya untuk ETH 4H). " \
                  "Belum diuji untuk koin ini."
        out.append(_factor("strategi", "Posisi strategi", SIDE_SIGN.get(side or "", 0), val, det, ev, "Strategy Lab"))

    # 2. screener composite
    sc = ctx.get("screener")
    if sc and sc.get("signal"):
        d = SIGNAL_DIR.get(sc["signal"], 0)
        stype = "komposit_high" if sc.get("confidence_tier") == "HIGH" else "komposit"
        ev = _track(ctx.get("track"), stype, d) if d else "belum_cukup_data"
        tier = f", tier {sc['tier']}" if sc.get("tier") else ""
        conf = f", keyakinan screener {fnum(sc.get('confidence_pct'), 0, False)}%" if sc.get("confidence_pct") is not None else ""
        out.append(_factor("screener", "Screener komposit", d, f"{sc['signal']}{tier}",
                           f"Sinyal komposit screener: {sc['signal']}{tier}{conf} (snapshot {fdate(sc.get('bar'))}).",
                           ev, "Screener + Catatan Sinyal", mult=EVIDENCE_MULT.get(ev, 0.5) if d else 1.0))
    else:
        out.append(_factor("screener", "Screener komposit", 0, "tidak tersedia",
                           "Belum ada snapshot screener untuk koin ini.", "tidak_tersedia", "Screener", available=False))

    # 3. trend vs EMA (Koin Terkuat)
    sr = ctx.get("strength")
    if sr and sr.get("trend") in ("up", "down"):
        d = 1 if sr["trend"] == "up" else -1
        out.append(_factor("tren", "Tren (EMA 50 hari)", d, ("di atas" if d > 0 else "di bawah") + " EMA",
                           f"Harga {fpct(sr.get('ema_dist_pct'))} dari EMA 50 hari (Koin Terkuat).",
                           "belum_diuji", "Koin Terkuat"))
    else:
        out.append(_factor("tren", "Tren (EMA 50 hari)", 0, "tidak tersedia" if not sr else "netral",
                           "Data tren tidak tersedia." if not sr else "Tren belum jelas (data kurang).",
                           "tidak_tersedia" if not sr else "belum_diuji", "Koin Terkuat", available=bool(sr)))

    # 4. momentum (30-day return; 7/90 shown)
    r30 = sr.get("ret_30d_pct") if sr else None
    if r30 is not None:
        d = 1 if r30 > MOMENTUM_THRESHOLD_PCT else -1 if r30 < -MOMENTUM_THRESHOLD_PCT else 0
        out.append(_factor("momentum", "Momentum 30 hari", d, fpct(r30),
                           f"Perubahan 7 hari {fpct(sr.get('ret_7d_pct'))}, 30 hari {fpct(r30)}, "
                           f"90 hari {fpct(sr.get('ret_90d_pct'))}. Arah dihitung jika |30 hari| > "
                           f"{fnum(MOMENTUM_THRESHOLD_PCT, 0)}%.", "belum_diuji", "Koin Terkuat"))
    else:
        out.append(_factor("momentum", "Momentum 30 hari", 0, "tidak tersedia", "Data momentum tidak tersedia.",
                           "tidak_tersedia", "Koin Terkuat", available=False))

    # 5. funding (crowding, contrarian: the screener's funding signal)
    apr = sr.get("funding_7d_apr_pct") if sr else None
    fsig = sc.get("funding_rate_signal") if sc else None
    if fsig:
        d = SIGNAL_DIR.get(fsig, 0)
        ev = _track(ctx.get("track"), "funding", d) if d else "belum_cukup_data"
        crowd = "long ramai (funding positif)" if d < 0 else "short ramai (funding negatif)" if d > 0 else "tidak ekstrem"
        rate = sc.get("funding_rate")
        out.append(_factor("funding", "Funding / keramaian", d, crowd,
                           f"Funding sekarang {fnum(rate, 4, True) + '%' if rate is not None else 'tidak tersedia'}"
                           f", rata-rata 7 hari {fpct(apr)} per tahun. Funding ekstrem dibaca berlawanan arah "
                           "(posisi ramai rawan dibalik).", ev, "Screener + Koin Terkuat",
                           mult=EVIDENCE_MULT.get(ev, 0.5) if d else 1.0))
    elif apr is not None:
        out.append(_factor("funding", "Funding / keramaian", 0, f"APR {fpct(apr)}",
                           f"Rata-rata funding 7 hari {fpct(apr)} per tahun (tanpa sinyal screener).",
                           "belum_diuji", "Koin Terkuat"))
    else:
        out.append(_factor("funding", "Funding / keramaian", 0, "tidak tersedia", "Data funding tidak tersedia.",
                           "tidak_tersedia", "Screener", available=False))

    # 6. open interest
    oi = ctx.get("oi") or {}
    osig = sc.get("oi_signal") if sc else None
    chg = oi.get("change_24h_pct")
    if osig or chg is not None:
        d = SIGNAL_DIR.get(osig or "", 0)
        ev = _track(ctx.get("track"), "oi", d) if d else ("belum_cukup_data" if osig else "konteks")
        out.append(_factor("oi", "Open interest", d, f"OI 24 jam {fpct(chg)}" if chg is not None else (osig or "—"),
                           f"Sinyal OI screener: {osig or 'tidak tersedia'}; perubahan OI 24 jam (Binance): {fpct(chg)}.",
                           ev, "Screener + Binance", mult=EVIDENCE_MULT.get(ev, 0.5) if d else 1.0))
    else:
        out.append(_factor("oi", "Open interest", 0, "tidak tersedia", "Data open interest tidak tersedia.",
                           "tidak_tersedia", "Binance", available=False))

    # 7. BTC regime
    rg = ctx.get("regime")
    if rg and rg.get("label"):
        lab = rg["label"]
        perf = ((ctx.get("regime_perf") or {}).get(side or "", {}) or {}).get(lab) if side else None
        if perf and perf.get("n"):
            hist = (f"Historis strategi ini: {perf['n']} trade {side} saat pasar {lab}, rata-rata "
                    f"{fpct(perf.get('mean_pct'), 2)}/trade, menang {fnum(perf.get('win_rate_pct'), 0)}%"
                    + ("" if perf.get("enough") else " (sampel kecil)") + ".")
            ev = "historis"
        else:
            hist = "Belum ada trade historis strategi ini di kondisi pasar ini untuk sisi ini." if side else ""
            ev = "belum_diuji"
        out.append(_factor("regime", "Kondisi pasar (BTC)", REGIME_DIR[lab], rg.get("label_text", lab),
                           f"BTC {fpct(rg.get('dist_ema_slow_pct'))} dari EMA 200 hari, EMA 50 "
                           f"{'naik' if (rg.get('slope_pct') or 0) > 0 else 'turun'} "
                           f"({fpct(rg.get('slope_pct'), 2)} dalam 10 hari), label ini sudah "
                           f"{rg.get('days_in_label')} hari. {hist}".strip(), ev, "Regime BTC"))
    else:
        out.append(_factor("regime", "Kondisi pasar (BTC)", 0, "tidak tersedia", "Regime BTC tidak tersedia.",
                           "tidak_tersedia", "Regime BTC", available=False))

    # 8. news (context only, never a direction)
    hl = ctx.get("headlines") or []
    fg = ctx.get("fear_greed")
    fg_txt = f"Fear & Greed pasar {fg['value']} ({fg.get('classification') or '-'})" if fg else \
        "Fear & Greed tidak tersedia"
    out.append(_factor("berita", "Berita & sentimen", 0,
                       f"{len(hl)} headline" if hl else "tidak ada headline",
                       f"{len(hl)} headline terbaru menyebut koin ini. {fg_txt}. Ditampilkan sebagai konteks; "
                       "tidak dihitung sebagai sinyal (belum ada sentimen per koin yang teruji).",
                       "konteks", "CoinTelegraph RSS + alternative.me"))
    return out


# ── bias + keyakinan ─────────────────────────────────────────────────────

def _down(level: str) -> str:
    return LEVELS[max(0, LEVELS.index(level) - 1)]


def combine(factors: list[dict], strategy: dict, regime: Optional[dict], regime_perf: Optional[dict],
            now_iso: Optional[str] = None) -> dict:
    side = strategy.get("side")
    sec = [f for f in factors if f["key"] != "strategi"]
    reasons: list[str] = []
    if strategy.get("error"):
        return {"bias": "NETRAL", "keyakinan": None, "condong": None, "support": None, "lean": None,
                "max_support": None, "reasons": ["Posisi strategi tidak bisa dihitung."]}
    lean = round(sum(f["used_weight"] * f["direction"] for f in sec), 3)
    max_support = round(sum(f["used_weight"] for f in sec), 3)
    if not side:
        condong = "naik" if lean >= LEAN_MIN else "turun" if lean <= -LEAN_MIN else None
        reasons.append("Strategi FLAT: tidak ada bias. " + (
            f"Faktor lain condong {condong} (skor {fnum(lean, 1, True)})." if condong else
            f"Faktor lain tidak condong jelas (skor {fnum(lean, 1, True)})."))
        return {"bias": "NETRAL", "keyakinan": None, "condong": condong, "support": None, "lean": lean,
                "max_support": max_support, "reasons": reasons}
    s = SIDE_SIGN[side]
    support = round(lean * s, 3)
    ev = strategy_evidence(strategy)
    if ev == "lolos_uji":
        level = "sedang"
        reasons.append("Preset lolos uji holdout: mulai dari keyakinan sedang.")
        contaminated = bool((strategy.get("preset") or {}).get("contaminated"))
        if support >= SUPPORT_HIGH and contaminated:
            reasons.append(f"Faktor lain mendukung (skor {fnum(support, 1, True)}), tetapi holdout preset tercemar "
                           "(sudah dilihat saat riset): keyakinan maksimal sedang.")
        elif support >= SUPPORT_HIGH:
            level = "tinggi"
            reasons.append(f"Faktor lain mendukung (skor {fnum(support, 1, True)} ≥ {fnum(SUPPORT_HIGH, 1, True)}): naik ke tinggi.")
        elif support <= SUPPORT_LOW:
            level = "rendah"
            reasons.append(f"Faktor lain menentang (skor {fnum(support, 1, True)} ≤ {fnum(SUPPORT_LOW, 1, True)}): turun ke rendah.")
        else:
            reasons.append(f"Faktor lain campuran (skor {fnum(support, 1, True)}).")
    else:
        level = "rendah"
        reasons.append("Preset GAGAL uji / belum diuji: keyakinan maksimal rendah, apa pun faktor lainnya "
                       f"(skor faktor lain {fnum(support, 1, True)}).")
    lab = (regime or {}).get("label")
    perf = ((regime_perf or {}).get(side) or {}).get(lab) if lab else None
    if perf and perf.get("enough") and (perf.get("mean_pct") or 0) < 0 and level != "rendah":
        level = _down(level)
        reasons.append(f"Historis strategi ini rugi saat pasar {lab} untuk posisi {side} "
                       f"({perf['n']} trade, rata-rata {fpct(perf['mean_pct'], 2)}): keyakinan diturunkan.")
    age = hours_between(strategy.get("last_bar_close"), now_iso) if now_iso else None
    if age is not None and age > STALE_HOURS:
        level = "rendah"
        reasons.append(f"Data strategi sudah {fnum(age, 0)} jam (basi): keyakinan rendah.")
    return {"bias": side.upper(), "keyakinan": level, "condong": None, "support": support, "lean": lean,
            "max_support": max_support, "reasons": reasons}


# ── narrative (template; extension point for an AI summary) ──────────────

def _strategy_sentence(st: dict, price: Optional[float]) -> str:
    ev = strategy_evidence(st)
    tag = {"lolos_uji": "LOLOS uji", "gagal_uji": "GAGAL uji", "belum_diuji": "belum diuji untuk koin ini"}[ev]
    head = f"{strategy_label(st)} ({tag})"
    if st.get("error"):
        return f"{head}: posisi tidak bisa dihitung ({st['error']})."
    if st.get("side"):
        s = (f"{head} sedang {st['side'].upper()} sejak {fdate(st.get('entry_at'))} di {fprice(st.get('entry_price'))}"
             + (" (sinyal baru di close terakhir)" if st.get("fresh") else "") + f"; harga sekarang {fprice(price)}"
             + (f" ({fpct(st.get('open_pnl_pct'))} dari entry)" if st.get("open_pnl_pct") is not None else "") + ". ")
        s += f"SL {fprice(st.get('sl'))}"
        if st.get("dist_sl_pct") is not None:
            s += f" ({fpct(st['dist_sl_pct'], 1, False)} lagi"
            s += f", {fnum(st['dist_sl_r'], 2, False)}R)" if st.get("dist_sl_r") is not None else ")"
        s += f", TP {fprice(st.get('tp'))}"
        if st.get("dist_tp_pct") is not None:
            s += f" ({fpct(st['dist_tp_pct'], 1, False)} lagi"
            s += f", {fnum(st['dist_tp_r'], 2, False)}R)" if st.get("dist_tp_r") is not None else ")"
        return s + "."
    last = st.get("last_exit")
    s = f"{head} sedang FLAT (tidak punya posisi)"
    if last:
        s += (f"; posisi terakhir {last['side'].upper()} ditutup {fdate(last.get('time'))} "
              f"({last.get('reason') or '-'}, {fpct(last.get('pnl_pct'))})")
    return s + "."


_PHRASE = {
    ("screener", 1): "screener komposit bullish", ("screener", -1): "screener komposit bearish",
    ("tren", 1): "tren di atas EMA", ("tren", -1): "tren di bawah EMA",
    ("momentum", 1): "momentum 30 hari {v}", ("momentum", -1): "momentum 30 hari {v}",
    ("funding", 1): "funding negatif (short ramai)", ("funding", -1): "funding positif (long ramai)",
    ("oi", 1): "sinyal OI bullish", ("oi", -1): "sinyal OI bearish",
    ("regime", 1): "pasar BTC naik", ("regime", -1): "pasar BTC turun",
}


def _phrase(f: dict) -> str:
    return _PHRASE.get((f["key"], f["direction"]), f["label"].lower()).format(v=f["value"])


def narrate_template(row: dict) -> dict:
    st, factors, bias = row["strategy"], row["factors"], row["bias"]
    side = st.get("side")
    sec = [f for f in factors if f["key"] not in ("strategi", "berita") and f["available"] and f["direction"]]
    paras = [_strategy_sentence(st, row.get("price"))]
    summary_bits: list[str] = []
    if side:
        s = SIDE_SIGN[side]
        pro = [_phrase(f) for f in sec if f["direction"] == s]
        con = [_phrase(f) for f in sec if f["direction"] == -s]
        if pro:
            paras.append(f"Mendukung {side}: " + ", ".join(pro) + ".")
        if con:
            paras.append(f"Menentang {side}: " + ", ".join(con) + ".")
        if not pro and not con:
            paras.append("Faktor lain netral atau tidak tersedia.")
        summary_bits = [", ".join(pro) + f" → mendukung {side}" if pro else "",
                        ("tetapi " + ", ".join(con)) if con else ""]
    else:
        up = [_phrase(f) for f in sec if f["direction"] > 0]
        dn = [_phrase(f) for f in sec if f["direction"] < 0]
        if up:
            paras.append("Mengarah naik: " + ", ".join(up) + ".")
        if dn:
            paras.append("Mengarah turun: " + ", ".join(dn) + ".")
    rg = next((f for f in factors if f["key"] == "regime" and f["available"]), None)
    if rg:
        paras.append(f"Kondisi pasar: {rg['detail']}")
    notes = []
    ev = strategy_evidence(st)
    if ev == "gagal_uji":
        notes.append("preset strategi GAGAL uji holdout, jadi sinyalnya belum bisa dipercaya")
    elif ev == "belum_diuji":
        notes.append("strategi belum diuji untuk koin ini (setting default ETH 4H)")
    if (st.get("preset") or {}).get("contaminated"):
        notes.append("holdout preset sudah pernah dilihat saat riset, hasil ujinya bisa terlalu optimis")
    sc = next((f for f in factors if f["key"] == "screener"), None)
    if sc and sc["available"] and sc["evidence"] in ("belum_terbukti", "belum_cukup_data"):
        notes.append("rekam jejak sinyal screener belum terbukti")
    if sc and sc["evidence"] == "negatif":
        notes.append("rekam jejak sinyal screener negatif (tidak dihitung)")
    if st.get("watch_check") and st["watch_check"].get("agrees") is False:
        notes.append(f"Pantau #{st['watch_check']['watch_id']} menunjukkan posisi berbeda (jendela data berbeda)")
    bt = row.get("backtest") or {}
    if bt.get("n") is not None and bt["n"] < SMALL_SAMPLE:
        notes.append(f"statistik backtest hanya {bt['n']} trade")
    if notes:
        paras.append("Catatan: " + "; ".join(notes) + ".")
    if side:
        paras.append(f"→ Bias {bias['bias']}, keyakinan {bias['keyakinan']}. " + " ".join(bias["reasons"]))
    else:
        paras.append("→ Bias NETRAL" + (f", condong {bias['condong']}" if bias.get("condong") else "") + ". "
                     + " ".join(bias["reasons"]))
    paras.append("Ini informasi, bukan jaminan atau saran investasi.")
    first = _strategy_sentence(st, None).split("; harga sekarang")[0].split(". SL")[0].rstrip(".")
    if side:
        extra = "; ".join(b for b in summary_bits if b)
        summary = first + (f"; {extra}" if extra else "") + "."
    else:
        summary = first + "." + (f" Faktor lain condong {bias['condong']}." if bias.get("condong") else "")
    if notes:
        summary += " Catatan: " + notes[0] + "."
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
    slippage per side (COST_PER_SIDE_PCT). Funding is not included (see the note)."""
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
            "caveat": (f"Rata-rata hasil backtest ({bt.get('basis_text') or 'backtest'}, {n} trade, {basis_side}); "
                       "sudah termasuk biaya & funding di backtest. Bukan jaminan: hasil masa depan bisa jauh berbeda"
                       + ("; sampel kecil" if n < SMALL_SAMPLE else "") + "."),
        }
    return {**base, "available": True, "basis_price": price, "basis_text": "jika masuk sekarang di harga close 4H terakhir",
            "side": side, "notional": notional, "margin": notional / leverage if leverage else notional, "qty": qty,
            "at_tp": res_tp, "at_tp1": res_tp1, "at_sl": res_sl, "rr": rr, "expected": ev, "warnings": warnings,
            "note": "Biaya: komisi 0,05% + slippage 0,05% per sisi. Funding tidak termasuk dalam angka TP/SL. "
                    "TP adalah batas keras strategi; strategi biasanya keluar lebih awal (trailing/exit lain)."}


def method() -> dict:
    return {
        "weights": WEIGHTS, "evidence_mult": EVIDENCE_MULT, "momentum_threshold_pct": MOMENTUM_THRESHOLD_PCT,
        "support_high": SUPPORT_HIGH, "support_low": SUPPORT_LOW, "lean_min": LEAN_MIN, "stale_hours": STALE_HOURS,
        "evidence_text": EVIDENCE_TEXT,
        "text": [
            "Arah (bias) selalu mengikuti posisi strategi Rosyade 4H. Faktor lain tidak pernah membalik arah.",
            "Skor dukungan = Σ bobot × arah faktor × arah posisi. Bobot: screener 1, tren 1, momentum 1, "
            "kondisi pasar BTC 1, funding 0,5, OI 0,5, berita 0 (konteks).",
            "Faktor dari Catatan Sinyal (screener, funding, OI) dihitung penuh hanya jika rekam jejaknya terbukti; "
            "belum terbukti = setengah; negatif = tidak dihitung.",
            "Preset LOLOS uji mulai dari keyakinan sedang: skor ≥ +2 → tinggi (kecuali holdout tercemar: maks. sedang), "
            "skor ≤ −1,5 → rendah. "
            "Preset GAGAL / belum diuji → keyakinan rendah.",
            "Jika historis strategi rugi di kondisi pasar BTC saat ini untuk sisi tersebut (≥ 5 trade), "
            "keyakinan turun satu tingkat.",
            "Strategi FLAT → NETRAL; jika |skor| ≥ 2 ditampilkan 'condong naik/turun'.",
        ],
    }
