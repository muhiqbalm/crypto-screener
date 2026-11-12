"""Calibration of Outlook calls (stdlib only): aggregate evaluated calls ("kasus") into
buckets, look up "kasus serupa" for a live call, and derive keyakinan from evidence.

A case is one historical (replay) or stored (live) call that has been evaluated
(evaluate.py). Classes of strategy evidence:

  lolos_uji    PASS preset, holdout bars only (out-of-sample)
  belum_diuji  template default on a coin it was not fitted on (out-of-sample per coin)
  gagal_uji    FAIL preset, holdout bars only
  pool         lolos_uji + belum_diuji together (the honest out-of-sample classes)

Bucket keys ``class|side|align|fase`` (``*`` = any). ``fase``: baru = the strategy entered
at this close (posisi baru), berjalan = joining a position that is already open.

What the replay showed (docs/riset-2026-11-12/04-outlook-v2.md) and why keyakinan v2 uses
class x side x fase and NOT the MTF alignment: the a-priori alignment buckets failed the
out-of-sample label check, while "baru beats berjalan" held in both halves of the history.

Consecutive calls of one position are correlated: every statistic carries ``n_cases`` and
``n_pos`` (distinct positions), standard errors are clustered by position, and the EV used
for ranking is shrunk towards 0 by n_pos / (n_pos + SHRINK_K).
"""
from __future__ import annotations

import math
from collections import namedtuple
from typing import Iterable, Optional

MIN_POS = 20            # a bucket needs this many distinct positions to be read
SHRINK_K = 20           # EV shrinkage: mean x n_pos / (n_pos + K)
TINGGI_MIN_POS = 30
TINGGI_MIN_R = 0.15     # tinggi: the strategy's OWN bucket, lower 95% bound > 0 and mean >= this
CLASS_CAP = {"lolos_uji": "tinggi", "belum_diuji": "sedang", "gagal_uji": "rendah"}
POOLED = ("lolos_uji", "belum_diuji")
LEVELS = ("rendah", "sedang", "tinggi")
CLASS_TEXT = {"lolos_uji": "strategi lolos uji (periode holdout)", "belum_diuji": "strategi default (belum diuji per koin)",
              "gagal_uji": "strategi gagal uji (periode holdout)", "pool": "semua strategi out-of-sample"}
FASE_TEXT = {"baru": "posisi baru", "berjalan": "menyusul posisi yang sudah berjalan"}
DONE = ("tp", "sl", "batal", "expired")

# compact case record (replay + live); dirs = (tren_1d, momentum_1h, regime_btc, funding) relative to the side
Case = namedtuple("Case", "coin cls side align fase t pos status r_net mfe_r bars rr dirs cfg")


def fr(x: Optional[float]) -> str:
    """R value, exchange-style digits (+0.12R / −0.05R)."""
    if x is None:
        return "tidak tersedia"
    return ("+" if x > 0 else "−" if x < 0 else "") + f"{abs(x):.2f}R"


def fint(n) -> str:
    """Count with exchange-style thousands (6,470)."""
    return f"{int(n):,}" if n is not None else "0"


def bucket_keys(cls: str, side: str, align: str, fase: str) -> list[str]:
    keys = [f"{cls}|{side}|{align}|{fase}", f"{cls}|{side}|{align}|*", f"{cls}|{side}|*|{fase}",
            f"{cls}|{side}|*|*", f"{cls}|*|*|*"]
    if cls in POOLED:
        keys += [f"pool|{side}|*|{fase}", f"pool|{side}|*|*", "pool|*|*|*"]
    return keys


def _q(xs: list[float], q: float) -> Optional[float]:
    if not xs:
        return None
    ys = sorted(xs)
    k = (len(ys) - 1) * q
    lo, hi = math.floor(k), math.ceil(k)
    return ys[lo] + (ys[hi] - ys[lo]) * (k - lo)


def stats(cases: Iterable) -> dict:
    """Statistics over evaluated cases (status in DONE); open / invalid ones are ignored."""
    done = [c for c in cases if c.status in DONE and c.r_net is not None]
    n = len(done)
    if not n:
        return {"n_cases": 0, "n_pos": 0}
    by_pos: dict[str, list[float]] = {}
    for c in done:
        by_pos.setdefault(c.pos, []).append(c.r_net)
    n_pos = len(by_pos)
    rs = [c.r_net for c in done]
    mean = sum(rs) / n
    se = None
    if n_pos > 1:
        ss = sum((sum(v) - len(v) * mean) ** 2 for v in by_pos.values())
        se = math.sqrt(ss * n_pos / (n_pos - 1)) / n
    cnt = {k: sum(1 for c in done if c.status == k) for k in DONE}
    mfe = [c.mfe_r for c in done if c.mfe_r is not None]
    bars = [c.bars for c in done if c.bars is not None]
    return {
        "n_cases": n, "n_pos": n_pos,
        "p_tp": cnt["tp"] / n, "p_sl": cnt["sl"] / n, "p_batal": cnt["batal"] / n, "p_expired": cnt["expired"] / n,
        "mean_r": mean, "se_r": se, "lo95_r": (mean - 1.96 * se) if se is not None else None,
        "median_r": _q(rs, 0.5), "ev_shrunk_r": mean * n_pos / (n_pos + SHRINK_K),
        "win_rate": sum(1 for r in rs if r > 0) / n,
        "median_mfe_r": _q(mfe, 0.5), "median_bars": _q([float(b) for b in bars], 0.5),
    }


def rounded(st: dict, nd: int = 4) -> dict:
    return {k: (round(v, nd) if isinstance(v, float) else v) for k, v in st.items()}


def aggregate(cases: list, key_fn) -> dict[str, dict]:
    groups: dict[str, list] = {}
    for c in cases:
        for k in key_fn(c):
            groups.setdefault(k, []).append(c)
    return {k: rounded(stats(v)) for k, v in groups.items()}


def case_buckets(cases: list) -> dict[str, dict]:
    return aggregate(cases, lambda c: bucket_keys(c.cls, c.side, c.align, c.fase))


def _enough(st: Optional[dict], min_pos: int = MIN_POS) -> bool:
    return bool(st) and (st.get("n_pos") or 0) >= min_pos


def _pos(st: Optional[dict]) -> bool:
    return _enough(st) and st.get("lo95_r") is not None and st["lo95_r"] > 0


def _cap(level: str, cap: str) -> str:
    return LEVELS[min(LEVELS.index(level), LEVELS.index(cap))]


def assess(buckets: dict, cls: str, side: str, fase: str, contaminated: bool = False) -> dict:
    """Keyakinan v2 from "kasus serupa".

    own    = this strategy class, same side and fase  (cls|side|*|fase)
    pooled = all out-of-sample classes, same side and fase (pool|side|*|fase)

      own enough and lower 95% bound > 0   -> tinggi if mean >= 0.15R and >= 30 positions, else sedang
      own enough and mean <= 0             -> rendah (this strategy's own similar calls lost)
      otherwise pooled enough and lo95 > 0 -> sedang
      otherwise                            -> rendah
    then capped: belum_diuji max sedang, gagal_uji rendah, contaminated holdout max sedang.
    The bucket shown as "kasus serupa" is the one the level was read from.
    """
    own_key, pool_key = f"{cls}|{side}|*|{fase}", f"pool|{side}|*|{fase}"
    own, pooled = buckets.get(own_key), buckets.get(pool_key)
    reasons: list[str] = []
    fase_txt = FASE_TEXT.get(fase, fase)
    if _enough(own) and own["lo95_r"] is not None and own["lo95_r"] > 0:
        raw = "tinggi" if own["mean_r"] >= TINGGI_MIN_R and own["n_pos"] >= TINGGI_MIN_POS else "sedang"
        conclusion, shown_key = "terbukti positif" + (" (kuat)" if raw == "tinggi" else ""), own_key
        reasons.append(f"Kasus serupa strategi ini ({fase_txt}) untung rata-rata {fr(own['mean_r'])} dari "
                       f"{fint(own['n_pos'])} posisi; batas bawah 95% di atas nol.")
    elif _enough(own) and (own.get("mean_r") or 0) <= 0:
        raw, conclusion, shown_key = "rendah", "tidak ada keunggulan", own_key
        reasons.append(f"Kasus serupa strategi ini ({fase_txt}) rata-rata {fr(own['mean_r'])} dari {fint(own['n_pos'])} "
                       "posisi: tidak ada keunggulan.")
    elif _pos(pooled):
        raw, shown_key = "sedang", pool_key
        conclusion = "terbukti positif di semua strategi (strategi ini sendiri belum bisa dinilai sendiri)"
        reasons.append(f"Kasus serupa semua strategi ({fase_txt}) untung rata-rata {fr(pooled['mean_r'])} dari "
                       f"{fint(pooled['n_pos'])} posisi; batas bawah 95% di atas nol."
                       + ("" if not own or not own.get("n_pos") else
                          f" Strategi ini sendiri baru {fint(own['n_pos'])} posisi, rata-rata {fr(own.get('mean_r'))} "
                          "(belum berbeda nyata dari nol)."))
    else:
        raw, conclusion = "rendah", "belum terbukti positif"
        shown_key = own_key if _enough(own) else pool_key if pooled else own_key
        ref = buckets.get(shown_key)
        if ref and ref.get("n_pos"):
            reasons.append(f"Kasus serupa ({fase_txt}) rata-rata {fr(ref['mean_r'])} dari {fint(ref['n_pos'])} posisi, "
                           "belum terbukti positif.")
        else:
            conclusion = "belum ada data"
            reasons.append("Belum ada kasus serupa yang terukur.")
    level = _cap(raw, CLASS_CAP.get(cls, "rendah"))
    if level != raw:
        reasons.append({"belum_diuji": "Strategi belum diuji untuk koin ini: keyakinan maksimal sedang.",
                        "gagal_uji": "Preset GAGAL uji: keyakinan maksimal rendah."}.get(cls, "Dibatasi bukti strategi."))
    if contaminated and level == "tinggi":
        level = "sedang"
        reasons.append("Holdout preset tercemar (sudah dilihat saat riset): keyakinan maksimal sedang.")
    shown = buckets.get(shown_key)
    return {"level": level, "raw": raw, "reasons": reasons, "conclusion": conclusion, "key": shown_key, "stats": shown,
            "own_key": own_key, "own": own, "pool_key": pool_key, "pooled": pooled,
            "enough": _enough(shown)}


def lookup_apriori(buckets: dict, cls: str, side: str, align: str, fase: str) -> tuple[Optional[str], Optional[dict], bool]:
    """The structure fixed BEFORE the replay (class|side|align|fase -> ... -> class), kept to report
    its out-of-sample check honestly. Not used for live keyakinan."""
    keys = [f"{cls}|{side}|{align}|{fase}", f"{cls}|{side}|{align}|*", f"{cls}|{side}|*|*", f"{cls}|*|*|*"]
    for k in keys:
        if _enough(buckets.get(k)):
            return k, buckets[k], True
    return None, None, False


def level_apriori(st: Optional[dict], enough: bool, cls: str) -> str:
    """A-priori rule (EV point estimate): kept only for the out-of-sample report."""
    if not st or not enough:
        return "rendah"
    raw = "rendah"
    if (st.get("n_pos") or 0) >= TINGGI_MIN_POS and (st.get("lo95_r") or -1) > 0 and (st.get("mean_r") or 0) >= TINGGI_MIN_R:
        raw = "tinggi"
    elif (st.get("ev_shrunk_r") or 0) > 0.03:
        raw = "sedang"
    return _cap(raw, CLASS_CAP.get(cls, "rendah"))


def _diff(a: dict, o: dict) -> tuple[Optional[float], Optional[float]]:
    if _enough(a) and _enough(o) and a.get("se_r") and o.get("se_r"):
        return a["mean_r"] - o["mean_r"], math.sqrt(a["se_r"] ** 2 + o["se_r"] ** 2)
    return None, None


def factor_lift(cases: list, idx: int, split_t: Optional[float] = None) -> dict:
    """Outcome when factor ``idx`` of Case.dirs points with the call (+1), against it (-1) or is neutral (0).

    verdict 'teruji' only if searah beats berlawanan by > 2 standard errors overall AND by more than one
    standard error in EACH half (before / after ``split_t``); 'terbalik' for the mirror case; else
    'belum_terbukti' (an effect that only exists in one period is not evidence)."""
    def groups(sub):
        g = {"searah": [], "netral": [], "berlawanan": []}
        for c in sub:
            d = c.dirs[idx] if c.dirs and len(c.dirs) > idx else None
            if d is not None:
                g["searah" if d > 0 else "berlawanan" if d < 0 else "netral"].append(c)
        return {k: rounded(stats(v)) for k, v in g.items()}

    out = groups(cases)
    diff, se = _diff(out["searah"], out["berlawanan"])
    halves = {}
    if split_t is not None:
        for name, sub in (("sebelum", [c for c in cases if c.t < split_t]), ("sesudah", [c for c in cases if c.t >= split_t])):
            g = groups(sub)
            d, s = _diff(g["searah"], g["berlawanan"])
            halves[name] = {"diff_r": None if d is None else round(d, 4), "se_diff_r": None if s is None else round(s, 4),
                            "n_pos_searah": g["searah"].get("n_pos", 0), "n_pos_berlawanan": g["berlawanan"].get("n_pos", 0)}
    verdict = "belum_terbukti"
    if diff is not None and se:
        consistent = all(h["diff_r"] is not None and h["se_diff_r"] and (h["diff_r"] > 0) == (diff > 0)
                         and abs(h["diff_r"]) > h["se_diff_r"] for h in halves.values())
        if abs(diff) > 2 * se and consistent:
            verdict = "teruji" if diff > 0 else "terbalik"
    out.update({"verdict": verdict, "diff_r": None if diff is None else round(diff, 4),
                "se_diff_r": None if se is None else round(se, 4), "halves": halves})
    return out
