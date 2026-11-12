"""Skor kualitas sinyal: one letter per Outlook call (stdlib only, unit-tested).

The letter says how much the MEASURED evidence supports acting on the call:

  A  bukti kuat        lower end of the 95% range of the similar cases >= +0.05R, from >= 100 positions
  B  bukti cukup       lower end of the 95% range > 0
  C  belum jelas       average > 0 but the range includes 0, or fewer than 20 positions
  D  tanpa keunggulan  average <= 0 (with >= 20 positions)

Base = the SAME "kasus serupa" bucket keyakinan reads (calib.assess: this strategy's evidence
class x side x fase, else all out-of-sample strategies). Using the lower end of the range (mean
- 1.96 x standard error clustered per position) is what keeps 12 cases from ever looking as strong
as 3,000: the range of a small sample is wide.

Agreement with regime / track record can only LOWER the letter, one step each (max two):
  * a factor that is PROVEN points against the call: simulation lift verdict 'teruji'
    (1D trend, 1H momentum, BTC regime) or Catatan Sinyal verdict 'terbukti' (screener, funding, OI).
    Unproven factors are shown but never counted (the replay found most add no edge).
  * the LIVE record of the same group (class x side x fase) is clearly negative: >= 20 resolved
    positions and the upper end of its 95% range < 0.
Cap: preset GAGAL uji -> at best C. No letter for FLAT, stale data, price beyond SL or no calibration.

Calls store the letter they had when they were made (lab_outlook_calls.kualitas), so the grade
itself is graded afterwards ("Rekam jejak skor"). Nothing here places or sizes an order.
"""
from __future__ import annotations

import math
from collections import namedtuple
from typing import Any, Optional

from . import calib as C
from . import logic as L
from . import store as S

RULE_VERSION = 1
GRADES = ("A", "B", "C", "D")
RANK = {"A": 4, "B": 3, "C": 2, "D": 1}
LABEL = {"A": "Bukti kuat", "B": "Bukti cukup", "C": "Belum jelas", "D": "Tanpa keunggulan"}
NO_GRADE = "-"                 # a call without a letter (stale, beyond SL, no calibration)
A_MIN_LO = 0.05                # A: lower 95% bound at least this many R ...
A_MIN_POS = 100                # ... from at least this many distinct positions
MIN_POS = C.MIN_POS            # below this the similar cases are too few to grade above C
LIVE_MIN_POS = 20              # live record of a group counts once it has this many resolved positions
MAX_STEPS = 2
Z95 = 1.96
PROVEN = {"teruji_replay": "simulasi historis", "terbukti": "Catatan Sinyal"}
CHECK_KEYS = ("momentum_1h", "tren_1d", "regime", "screener", "oi", "funding")
DIR_KEY = {"tren_1d": "tren_1d", "momentum_1h": "momentum_1h", "regime": "regime_btc"}
LIFT_KEY = {"tren_1d": "tren_1d", "momentum_1h": "momentum_1h", "regime": "regime_btc"}
FACTOR_LABEL = {"tren_1d": "Tren 1D", "momentum_1h": "Momentum 1H", "regime": "Kondisi pasar (BTC)"}
DONE = C.DONE

_Live = namedtuple("_Live", "pos status r_net mfe_r bars")


def _num(x: Any) -> Optional[float]:
    return float(x) if isinstance(x, (int, float)) and math.isfinite(x) else None


def rule_text() -> list[str]:
    return [
        "A = batas bawah rentang 95% kasus serupa ≥ +0.05R dari ≥ 100 posisi; B = batas bawah di atas nol; "
        "C = rata-rata positif tapi rentangnya masih mencakup nol (atau < 20 posisi); D = rata-rata ≤ 0.",
        "Rentang dihitung dari galat baku per posisi, jadi sampel kecil punya rentang lebar dan tidak bisa dapat A.",
        "Turun satu tingkat bila faktor yang SUDAH terbukti (simulasi historis atau Catatan Sinyal) berlawanan arah, "
        "dan satu tingkat lagi bila rekam jejak live kelompok yang sama jelas negatif (≥ 20 posisi). "
        "Faktor yang belum terbukti ditampilkan tetapi tidak dihitung; skor tidak pernah dinaikkan.",
        "Preset GAGAL uji maksimal C. Tanpa skor: strategi FLAT, data basi, harga sudah melewati SL, atau belum ada kalibrasi.",
    ]


# ── evidence ─────────────────────────────────────────────────────────────

def base_grade(st: Optional[dict]) -> tuple[Optional[str], str]:
    """(letter, reason) from one similar-case bucket (calib.stats shape)."""
    if not st or not st.get("n_pos"):
        return None, "Belum ada kasus serupa yang terukur."
    n = int(st["n_pos"])
    mean, lo = _num(st.get("mean_r")), _num(st.get("lo95_r"))
    if mean is None:
        return None, "Belum ada kasus serupa yang terukur."
    if n < MIN_POS:
        return "C", f"Baru {C.fint(n)} posisi serupa (perlu ≥ {MIN_POS}): terlalu sedikit untuk dinilai lebih tinggi."
    if mean <= 0:
        return "D", f"Kasus serupa rata-rata {C.fr(mean)} dari {C.fint(n)} posisi: tidak ada keunggulan."
    if lo is not None and lo >= A_MIN_LO and n >= A_MIN_POS:
        return "A", f"Batas bawah {C.fr(lo)} dari {C.fint(n)} posisi: tetap untung walau di ujung pesimis rentangnya."
    if lo is not None and lo > 0:
        why = f"batas bawah {C.fr(lo)}" + ("" if n >= A_MIN_POS else f", baru {C.fint(n)} posisi")
        return "B", f"Untung dengan rentang di atas nol ({why}), tapi belum cukup lebar untuk A."
    return "C", (f"Rata-rata {C.fr(mean)} dari {C.fint(n)} posisi, tapi rentangnya masih mencakup nol"
                 + (f" (batas bawah {C.fr(lo)})" if lo is not None else "") + ".")


def _pct(p: Optional[float]) -> str:
    return "—" if p is None else f"{round(p * 100):.0f}%"


def evidence(cal: Optional[dict]) -> Optional[dict]:
    """The similar-case bucket shown with the grade, plus its 95% range."""
    st = (cal or {}).get("stats") or None
    if not st or not st.get("n_pos"):
        return None
    key = (cal or {}).get("key") or ""
    parts = key.split("|")
    cls, fase = (parts[0], parts[3]) if len(parts) == 4 else (None, None)
    mean, lo = _num(st.get("mean_r")), _num(st.get("lo95_r"))
    half = (mean - lo) if mean is not None and lo is not None else None
    scope = "semua_strategi" if cls == "pool" else "strategi_ini"
    label = C.CLASS_TEXT.get(cls or "", cls or "") + (f", {C.FASE_TEXT.get(fase, fase)}" if fase else "")
    return {"key": key, "scope": scope, "label": label, "n_cases": st.get("n_cases"), "n_pos": st.get("n_pos"),
            "p_tp": st.get("p_tp"), "p_sl": st.get("p_sl"), "p_batal": st.get("p_batal"),
            "p_expired": st.get("p_expired"), "win_rate": st.get("win_rate"), "mean_r": mean, "lo95_r": lo,
            "hi95_r": (mean + half) if half is not None else None, "half_r": half}


def outcome_text(ev: Optional[dict]) -> Optional[str]:
    """"Dari 3,435 kasus serupa: untung di target 14% · rugi di SL 49% · ditutup strategi 37% ·
    rata-rata +0.14R (rentang ±0.06R)." (shares are of calls; positions named when they differ)."""
    if not ev:
        return None
    n_cases, n_pos = ev.get("n_cases") or 0, ev.get("n_pos") or 0
    head = (f"Dari {C.fint(n_cases)} kasus serupa" if n_cases == n_pos or not n_cases else
            f"Dari {C.fint(n_cases)} kasus serupa ({C.fint(n_pos)} posisi berbeda)")
    parts = [f"untung di target {_pct(ev.get('p_tp'))}", f"rugi di SL {_pct(ev.get('p_sl'))}",
             f"ditutup strategi {_pct(ev.get('p_batal'))}"]
    if (ev.get("p_expired") or 0) >= 0.005:
        parts.append(f"habis waktu {_pct(ev.get('p_expired'))}")
    avg = f"rata-rata {C.fr(ev.get('mean_r'))}"
    if ev.get("half_r") is not None:
        avg += f" (rentang ±{abs(ev['half_r']):.2f}R)"
    return f"{head}: " + " · ".join(parts) + f" · {avg}."


# ── agreement (only proven evidence counts) ──────────────────────────────

def checks(row: dict) -> list[dict]:
    """One item per context factor: does it point with the call, and is it proven?"""
    side = (row.get("strategy") or {}).get("side")
    sign = 1 if side == "long" else -1 if side == "short" else 0
    out = []
    by_key = {f.get("key"): f for f in (row.get("factors") or [])}
    for k in CHECK_KEYS:
        f = by_key.get(k)
        if not f:
            continue
        avail = bool(f.get("available"))
        d = int(f.get("direction") or 0)
        agree = d * sign if avail else 0
        code = f.get("evidence")
        proven = avail and code in PROVEN
        effect = -1 if proven and agree < 0 else 0
        out.append({"key": k, "label": f.get("label") or k, "value": f.get("value"), "available": avail,
                    "agree": agree, "proven": proven, "evidence": code, "evidence_text": f.get("evidence_text"),
                    "source": PROVEN.get(code) if proven else None, "effect": effect})
    return out


def checks_from_dirs(dirs: Optional[dict], side: str, lifts: Optional[dict]) -> list[dict]:
    """Agreement for a STORED call (backfill): only the 1D/1H/BTC directions are kept per call."""
    sign = 1 if side == "long" else -1
    out = []
    for k in ("momentum_1h", "tren_1d", "regime"):
        d = (dirs or {}).get(DIR_KEY[k])
        if d is None:
            continue
        verdict = ((lifts or {}).get(LIFT_KEY[k]) or {}).get("verdict")
        code = "teruji_replay" if verdict == "teruji" else "belum_terbukti_replay"
        agree = int(d) * sign
        proven = code in PROVEN
        out.append({"key": k, "label": FACTOR_LABEL[k], "value": {1: "naik", -1: "turun", 0: "campuran"}.get(int(d)),
                    "available": True, "agree": agree, "proven": proven, "evidence": code, "evidence_text": None,
                    "source": PROVEN.get(code) if proven else None, "effect": -1 if proven and agree < 0 else 0})
    return out


# ── live record of a group (class x side x fase) ─────────────────────────

def _live_case(r: dict) -> _Live:
    pos = f"{r.get('symbol')}|{r.get('strategy')}|{r.get('strategy_entry_time')}"
    return _Live(pos, r.get("status"), r.get("r_net"), r.get("mfe_r"), r.get("bars_to_resolve"))


def live_stats(rows: list[dict]) -> dict:
    st = C.stats([_live_case(r) for r in rows])
    if st.get("n_cases"):
        se = st.get("se_r")
        st["hi95_r"] = st["mean_r"] + Z95 * se if se is not None else None
    return C.rounded(st)


def live_groups(conn, as_of: Optional[str] = None) -> dict[str, dict]:
    """{"cls|side|fase": stats} over the RESOLVED stored calls (optionally resolved before ``as_of``)."""
    S.ensure_schema(conn)
    q = ("SELECT symbol, cls, side, fase, strategy, strategy_entry_time, status, r_net, mfe_r, bars_to_resolve, "
         "resolved_at FROM lab_outlook_calls WHERE side IS NOT NULL AND r_net IS NOT NULL "
         "AND status IN ('tp','sl','batal','expired')" + (" AND resolved_at <= ?" if as_of else ""))
    groups: dict[str, list] = {}
    for r in conn.execute(q, (as_of,) if as_of else ()):
        r = dict(r)
        groups.setdefault(f"{r['cls']}|{r['side']}|{r['fase']}", []).append(r)
    return {k: live_stats(v) for k, v in groups.items()}


def _live_brief(key: Optional[str], st: Optional[dict]) -> dict:
    st = st or {}
    n_pos = st.get("n_pos") or 0
    return {"key": key, "n_done": st.get("n_cases") or 0, "n_pos": n_pos, "mean_r": st.get("mean_r"),
            "lo95_r": st.get("lo95_r"), "hi95_r": st.get("hi95_r"), "win_rate": st.get("win_rate"),
            "enough": n_pos >= LIVE_MIN_POS, "need_pos": LIVE_MIN_POS,
            "negative": n_pos >= LIVE_MIN_POS and st.get("hi95_r") is not None and st["hi95_r"] < 0}


# ── the grade ────────────────────────────────────────────────────────────

def _down(letter: str, steps: int) -> str:
    return GRADES[min(len(GRADES) - 1, GRADES.index(letter) + steps)]


def _result(letter: Optional[str], base: Optional[str], base_reason: str, ev: Optional[dict], chk: list,
            live: Optional[dict], adjustments: list[dict], why_none: Optional[str] = None,
            basis: str = "saat_panggilan") -> dict:
    if letter:
        summary = f"{letter} · {LABEL[letter]}: " + (adjustments[-1]["text"] if adjustments else base_reason)
    else:
        summary = why_none or base_reason
    return {"grade": letter, "label": LABEL.get(letter or "", "Tidak dinilai"), "rank": RANK.get(letter or "", 0),
            "base": base, "base_reason": base_reason, "summary": summary, "why_none": why_none,
            "evidence": ev, "outcome_text": outcome_text(ev), "checks": chk, "live": live,
            "adjustments": adjustments, "rule_version": RULE_VERSION, "basis": basis}


def grade_parts(cal: Optional[dict], chk: list[dict], live: Optional[dict], cls: Optional[str],
                why_none: Optional[str] = None, basis: str = "saat_panggilan") -> dict:
    ev = evidence(cal)
    base, base_reason = base_grade((cal or {}).get("stats"))
    if why_none or base is None:
        return _result(None, base, base_reason, ev, chk, live, [], why_none or base_reason, basis)
    letter, adjustments = base, []
    against = [c for c in chk if c["effect"] < 0]
    if against:
        names = ", ".join(f"{c['label']} ({c['source']})" for c in against)
        adjustments.append({"step": -1, "kind": "faktor",
                            "text": f"Turun satu tingkat: faktor yang sudah terbukti berlawanan arah — {names}."})
    if live and live.get("negative"):
        adjustments.append({"step": -1, "kind": "live",
                            "text": f"Turun satu tingkat: rekam jejak live kelompok ini negatif "
                                    f"({C.fr(live.get('mean_r'))} dari {C.fint(live.get('n_pos'))} posisi)."})
    steps = min(MAX_STEPS, sum(-a["step"] for a in adjustments))
    letter = _down(letter, steps)
    if cls == "gagal_uji" and RANK[letter] > RANK["C"]:
        letter = "C"
        adjustments.append({"step": 0, "kind": "batas", "text": "Preset GAGAL uji: skor maksimal C."})
    return _result(letter, base, base_reason, ev, chk, live, adjustments, None, basis)


def grade(row: dict, live: Optional[dict] = None) -> Optional[dict]:
    """Grade of one Outlook row (API / job). None when the strategy has no position (no call)."""
    st = row.get("strategy") or {}
    side = st.get("side")
    if row.get("unavailable") or not side or st.get("error"):
        return None
    bias = row.get("bias") or {}
    pl = row.get("plan") or {}
    cls, fase = bias.get("cls"), bias.get("fase")
    key = f"{cls}|{side}|{fase}"
    lv = _live_brief(key, (live or {}).get(key))
    why_none = None
    if pl and not pl.get("geometry_ok", True):
        why_none = "Harga sudah melewati SL: panggilan ini tidak berlaku, jadi tidak dinilai."
    elif row.get("stale") or (pl.get("freshness") or {}).get("stale"):
        why_none = "Data strategi basi (lebih dari 9 jam): tidak dinilai sampai close 4H berikutnya."
    elif not bias.get("calib"):
        why_none = "Belum ada kalibrasi kasus serupa: skor belum bisa dihitung."
    return grade_parts(bias.get("calib"), checks(row), lv, cls, why_none)


def letter(q: Optional[dict]) -> Optional[str]:
    """What a stored call keeps: A-D, '-' for a call without a letter, None when there is no call."""
    if q is None:
        return None
    return q.get("grade") or NO_GRADE


def compact(q: Optional[dict]) -> Optional[dict]:
    """The stored copy (lab_outlook_calls.kualitas_json): enough to explain the letter later."""
    if q is None:
        return None
    ev = q.get("evidence") or {}
    lv = q.get("live") or {}
    return {"grade": q.get("grade"), "base": q.get("base"), "rule_version": q.get("rule_version"),
            "basis": q.get("basis"), "why_none": q.get("why_none"),
            "evidence": {k: ev.get(k) for k in ("key", "n_pos", "mean_r", "lo95_r")} if ev else None,
            "against": [c["key"] for c in q.get("checks") or [] if c.get("effect", 0) < 0],
            "live": {k: lv.get(k) for k in ("key", "n_pos", "mean_r", "hi95_r")} if lv else None,
            "adjustments": [a.get("kind") for a in q.get("adjustments") or []]}


# ── stored calls: backfill + the graded grade ("Rekam jejak skor") ───────

def backfill(conn, calibration: Optional[dict], limit: int = 500) -> int:
    """Give a letter to calls stored BEFORE grading existed, with the same rule and only what the call
    knew: its similar-case bucket (re-read from the calibration in force when it was made), its stored
    1D/1H/BTC directions and the live record as it was then. Catatan Sinyal factors were not stored per
    call, so they are left out (flagged). Calls older than the current calibration stay ungraded."""
    if not calibration or not calibration.get("buckets"):
        return 0
    S.ensure_schema(conn)
    cal_at = calibration.get("computed_at") or ""
    rows = [dict(r) for r in conn.execute(
        "SELECT * FROM lab_outlook_calls WHERE side IS NOT NULL AND kualitas IS NULL AND computed_at >= ? "
        "ORDER BY bar LIMIT ?", (cal_at, int(limit)))]
    if not rows:
        return 0
    lifts = ((calibration.get("factor_lift") or {}).get("pool")) or {}
    n = 0
    for r in rows:
        call = S.loads(r.get("call_json"), {}) or {}
        cls, side, fase = r.get("cls"), r.get("side"), r.get("fase")
        if not cls or not fase or r.get("status") == "invalid":
            why = ("Harga sudah melewati SL saat panggilan: tidak dinilai." if r.get("status") == "invalid" else
                   "Panggilan lama tanpa kelas bukti: tidak dinilai.")
            q = _result(None, None, "", None, [], None, [], why, "dihitung_ulang")
        else:
            a = C.assess(calibration["buckets"], cls, side, fase)
            cal = {"key": a["key"], "stats": a["stats"]}
            key = f"{cls}|{side}|{fase}"
            lv = _live_brief(key, live_groups(conn, as_of=r.get("computed_at")).get(key))
            q = grade_parts(cal, checks_from_dirs(call.get("dirs"), side, lifts), lv, cls,
                            basis="dihitung_ulang")
            q["partial"] = "Catatan Sinyal tidak tersimpan per panggilan; tidak ikut dihitung."
        comp = compact(q) or {}
        comp["partial"] = q.get("partial")
        conn.execute("UPDATE lab_outlook_calls SET kualitas=?, kualitas_json=? WHERE id=?",
                     (letter(q), S.dumps(comp), r["id"]))
        n += 1
    conn.commit()
    return n


def _verdict(st: dict) -> str:
    if (st.get("n_pos") or 0) < LIVE_MIN_POS:
        return "belum_cukup"
    if st.get("lo95_r") is not None and st["lo95_r"] > 0:
        return "positif"
    if st.get("hi95_r") is not None and st["hi95_r"] < 0:
        return "negatif"
    return "belum_jelas"


def _combine(parts: list[dict]) -> dict:
    """Pool disjoint groups (weights = calls), standard errors added in quadrature."""
    parts = [p for p in parts if p and p.get("n_cases")]
    n = sum(p["n_cases"] for p in parts)
    if not n:
        return {"n_cases": 0, "n_pos": 0}
    mean = sum(p["mean_r"] * p["n_cases"] for p in parts) / n
    ses = [p.get("se_r") for p in parts]
    se = math.sqrt(sum((s * p["n_cases"]) ** 2 for s, p in zip(ses, parts))) / n if all(s is not None for s in ses) else None
    out = {"n_cases": n, "n_pos": sum(p.get("n_pos") or 0 for p in parts), "mean_r": mean, "se_r": se,
           "lo95_r": mean - Z95 * se if se is not None else None, "hi95_r": mean + Z95 * se if se is not None else None}
    for k in ("p_tp", "p_sl", "p_batal", "p_expired", "win_rate"):
        if all(p.get(k) is not None for p in parts):
            out[k] = sum(p[k] * p["n_cases"] for p in parts) / n
    return C.rounded(out)


def sim_check(calibration: Optional[dict]) -> Optional[dict]:
    """The grading rule applied to the SIMULATION's older half, judged on its newer half (group level:
    side x fase, all out-of-sample strategies). Simulation, not live results; the rule was written after
    the data existed, so this is a consistency check, not proof."""
    fs = (calibration or {}).get("fase_split") or {}
    before, after = fs.get("sebelum") or {}, fs.get("sesudah") or {}
    if not before or not after:
        return None
    groups, agg = [], {}
    for key in ("short|baru", "long|baru", "short|berjalan", "long|berjalan"):
        b, a = before.get(key), after.get(key)
        if not b or not a:
            continue
        g, _why = base_grade(b)
        if g is None:
            continue
        side, fase = key.split("|")
        groups.append({"key": key, "side": side, "fase": fase, "grade": g,
                       "before": {k: b.get(k) for k in ("n_pos", "mean_r", "lo95_r")},
                       "after": {k: a.get(k) for k in ("n_cases", "n_pos", "mean_r", "lo95_r", "p_tp", "p_sl", "p_batal")}})
        agg.setdefault(g, []).append(a)
    if not groups:
        return None
    return {"split": calibration.get("split"), "computed_at": calibration.get("computed_at"), "groups": groups,
            "by_grade": {g: _combine(v) for g, v in agg.items()},
            "note": (f"Skor dihitung dari data sebelum {L.fdate(calibration.get('split'), with_time=False, year=True)}, "
                     "lalu hasilnya dicek di data sesudahnya. Aturan ditulis setelah data ini ada: cek konsistensi, "
                     "bukan bukti.")}


def scoreboard(conn, calibration: Optional[dict] = None, recent: int = 20) -> dict:
    """How the calls of each letter actually turned out (live, stored calls only)."""
    S.ensure_schema(conn)
    have = {r[1] for r in conn.execute("PRAGMA table_info(lab_outlook_calls)")}
    extra = ", ".join(c if c in have else f"NULL AS {c}" for c in ("kualitas", "kualitas_json"))  # read-only, pre-migration
    rows = [dict(r) for r in conn.execute(
        "SELECT id, symbol, bar, bar_close, side, fase, cls, strategy, strategy_entry_time, status, r_net, mfe_r, "
        f"bars_to_resolve, price, resolved_at, {extra} FROM lab_outlook_calls "
        "WHERE side IS NOT NULL ORDER BY bar, symbol")]
    graded = [r for r in rows if r.get("kualitas") in GRADES]
    no_letter = [r for r in rows if r.get("kualitas") == NO_GRADE]
    ungraded = [r for r in rows if r.get("kualitas") is None]
    by_grade = {}
    for g in GRADES:
        sub = [r for r in graded if r["kualitas"] == g]
        st = live_stats(sub)
        by_grade[g] = {"grade": g, "label": LABEL[g], "n_calls": len(sub),
                       "n_open": sum(1 for r in sub if r.get("status") == "open"),
                       "n_done": st.get("n_cases") or 0, "n_pos": st.get("n_pos") or 0,
                       "mean_r": st.get("mean_r"), "lo95_r": st.get("lo95_r"), "hi95_r": st.get("hi95_r"),
                       "win_rate": st.get("win_rate"), "p_tp": st.get("p_tp"), "p_sl": st.get("p_sl"),
                       "p_batal": st.get("p_batal"), "p_expired": st.get("p_expired"),
                       "sum_r": round(sum(r["r_net"] for r in sub if r.get("status") in DONE
                                          and r.get("r_net") is not None), 4),
                       "enough": (st.get("n_pos") or 0) >= LIVE_MIN_POS, "verdict": _verdict(st)}
    done_pos = {(r["symbol"], r.get("strategy"), r.get("strategy_entry_time")) for r in graded
                if r.get("status") in DONE and r.get("r_net") is not None}
    backfilled = sum(1 for r in graded + no_letter
                     if (S.loads(r.get("kualitas_json"), {}) or {}).get("basis") == "dihitung_ulang")
    last = sorted(graded + no_letter, key=lambda r: (r["bar"], r["symbol"]), reverse=True)[:max(0, int(recent))]
    return {
        "rule_version": RULE_VERSION, "rule": rule_text(), "need_pos": LIVE_MIN_POS,
        "first_graded": min((r.get("bar_close") or r["bar"] for r in graded), default=None),
        "n_calls": len(rows), "n_graded": len(graded), "n_no_letter": len(no_letter), "n_ungraded": len(ungraded),
        "n_backfilled": backfilled, "n_done": sum(v["n_done"] for v in by_grade.values()), "n_pos_done": len(done_pos),
        "enough_any": any(v["enough"] for v in by_grade.values()),
        "by_grade": by_grade,
        "recent": [{"id": r["id"], "symbol": r["symbol"], "bar": r["bar"], "bar_close": r.get("bar_close"),
                    "side": r["side"], "fase": r.get("fase"), "kualitas": r.get("kualitas"), "status": r.get("status"),
                    "r_net": r.get("r_net"), "price": r.get("price"), "resolved_at": r.get("resolved_at"),
                    "basis": (S.loads(r.get("kualitas_json"), {}) or {}).get("basis")} for r in last],
        "simulasi": sim_check(calibration),
        "note": ("Hanya panggilan live yang tersimpan, dinilai setelah kejadian (masuk di close 4H, SL & TP terpasang, "
                 "keluar saat strategi menutup posisi atau setelah 7 hari; R bersih setelah biaya). Sebuah skor baru "
                 f"dianggap teruji setelah ≥ {LIVE_MIN_POS} posisi selesai."),
    }


def sort_key(row: dict) -> int:
    return -int(((row.get("kualitas") or {}).get("rank")) or 0)
