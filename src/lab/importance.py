"""Parameter importance per template x timeframe, for the Lab form (read-only advice).

Sources, the first one that has data wins:

1. ``research``: ``src/lab/data/parameter_importance.json``, a snapshot of the parameter research
   (docs/riset-2026-11-12/parameter_importance.json). The format is described in
   ``data/PARAMETER_IMPORTANCE.md``. The loader is tolerant: a missing or broken file, or a malformed
   entry, is skipped and never raises.
2. ``runs``: the sensitivity stored with finished validate / optimize runs. It is computed on the
   training segment only, never on the holdout. Per run, the params are ranked by how far the net
   result moves when the param is nudged (+-10/20 %). The response is the median rank over at least
   MIN_RUNS runs of this template x timeframe. Runs do not persist Optuna importances, so they are
   not used.
3. ``template``: a fixed order of the template's ``tunable`` params. Nothing is measured.

Importance is advice for the UI only. It never changes a parameter value, a preset, a run, a watch,
the holdout lock or the cost model: this module only reads. Stdlib only (imported by the API process).
"""
from __future__ import annotations

import json
import math
import re
import sqlite3
import threading
from pathlib import Path
from statistics import median
from typing import Any, Optional

from . import db as labdb

DATA_PATH = Path(__file__).with_name("data") / "parameter_importance.json"

LABEL_STABLE = "penting & stabil"
LABEL_UNSTABLE = "penting tapi tidak stabil"
LABEL_NONE = "tidak berpengaruh"
LABELS = (LABEL_STABLE, LABEL_UNSTABLE, LABEL_NONE)

MIN_RUNS = 5            # audit 02 §3.9 phase 2: fewer runs -> fall back to the template order
MAX_RUNS = 200          # newest runs considered for the "runs" source
# Runs source: "penting" = median share >= 1/d (so important in at least half of the runs);
# "stabil" = important in >= 75 % of the runs. 50-75 % -> "penting tapi tidak stabil".
STABLE_FRACTION = 0.75

# Template fallback: params listed first when nothing is measured; the other tunables keep the
# template order. Donchian (4 tunables) and Mean reversion (5) simply keep their template order.
FALLBACK_ORDER: dict[str, list[str]] = {
    "rosyade_family": ["long_sl_pct", "short_sl_pct", "atr_mult_medium_long", "atr_mult_medium_short",
                       "cooldown_bars"],
}

_MONTHS = ("Jan", "Feb", "Mar", "Apr", "Mei", "Jun", "Jul", "Agu", "Sep", "Okt", "Nov", "Des")
_WINDOW_RE = re.compile(r"(\d{4}-\d{2}-\d{2})\s*(?:\.\.|–|s/d|to)\s*(\d{4}-\d{2}-\d{2})")


# ── small coercions (never raise) ────────────────────────────────────────

def _num(v: Any) -> Optional[float]:
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        return None
    f = float(v)
    return f if math.isfinite(f) else None


def _int(v: Any) -> Optional[int]:
    f = _num(v)
    return int(f) if f is not None and f >= 0 else None


def _str(v: Any) -> Optional[str]:
    return (v.strip() or None) if isinstance(v, str) else None


def _pair(v: Any) -> Optional[list[float]]:
    if not isinstance(v, (list, tuple)) or len(v) != 2:
        return None
    lo, hi = _num(v[0]), _num(v[1])
    if lo is None or hi is None or lo > hi:
        return None
    return [lo, hi]


def _scalar(v: Any) -> Any:
    return v if isinstance(v, (str, int, float, bool)) and not (isinstance(v, float) and not math.isfinite(v)) else None


def _day(iso: Optional[str]) -> Optional[str]:
    """'2026-11-12' -> '12 Nov 2026' (Indonesian month names)."""
    if not iso or not re.match(r"^\d{4}-\d{2}-\d{2}", iso):
        return None
    y, m, d = int(iso[:4]), int(iso[5:7]), int(iso[8:10])
    if not 1 <= m <= 12:
        return None
    return f"{d} {_MONTHS[m - 1]} {y}"


# ── research file ────────────────────────────────────────────────────────

def _norm_recommended(rec: Any, row: dict) -> Optional[dict]:
    if isinstance(rec, dict):
        rng, vals, dflt, inside = _pair(rec.get("range")), rec.get("values"), rec.get("default"), rec.get("current_inside")
    else:  # flat format: recommended_range / recommended_values / recommended_default on the row
        rng, vals, dflt, inside = (_pair(row.get("recommended_range")), row.get("recommended_values"),
                                   row.get("recommended_default"), None)
    values = [x for x in (_scalar(v) for v in vals) if x is not None] if isinstance(vals, list) else []
    dflt = _scalar(dflt)
    if rng is None and not values and dflt is None:
        return None
    return {"range": rng, "values": values or None, "default": dflt,
            "current_inside": inside if isinstance(inside, bool) else None}


def _norm_param(p: Any) -> Optional[dict]:
    """One research param -> normalised dict, or None when it is unusable."""
    if not isinstance(p, dict):
        return None
    name = _str(p.get("param")) or _str(p.get("key"))
    if not name:
        return None
    keys = p.get("lab_keys")
    lab_keys = [k for k in keys if isinstance(k, str) and k] if isinstance(keys, list) else []
    label = p.get("stability_label", p.get("label"))
    fan = p.get("fanova") if isinstance(p.get("fanova"), dict) else {}
    # Score + the CI of that same estimate. combined_share (the research ranking: mean of the fANOVA
    # and model-free shares) has no CI of its own, so none is invented for it.
    score, ci = _num(p.get("combined_share")), None
    if score is None:
        score, ci = _num(p.get("importance_mean")), _pair(p.get("importance_ci"))
    if score is None:
        score, ci = _num(fan.get("mean")), _pair(fan.get("ci90"))
    folds = p.get("folds_important")
    return {
        "param": name,
        "lab_keys": lab_keys or [name],
        "label": label if label in LABELS else None,
        "score": score,
        "score_ci": ci if score is not None else None,
        "coins_frac_important": _num(p.get("coins_frac_important")),
        "folds_important": [bool(x) for x in folds] if isinstance(folds, list) else None,
        "current_default": _scalar(p.get("current_default")),
        "recommended": _norm_recommended(p.get("recommended"), p),
    }


def _entry_meta(t: dict) -> dict:
    coins = t.get("coins")
    n_coins = len(coins) if isinstance(coins, list) else _int(t.get("n_coins"))
    return {"n_trials": _int(t.get("n_trials")), "n_coins": n_coins, "n_live": _int(t.get("n_live"))}


def normalise_research(raw: Any) -> Optional[dict]:
    """Research JSON (nested ``templates[]`` and/or flat ``rows[]``) -> {meta, entries}; None if empty."""
    if not isinstance(raw, dict):
        return None
    entries: dict[tuple[str, str], dict] = {}
    templates = raw.get("templates")
    for t in templates if isinstance(templates, list) else []:
        if not isinstance(t, dict):
            continue
        tid = _str(t.get("template_id")) or _str(t.get("template"))
        tf = _str(t.get("tf")) or _str(t.get("timeframe"))
        params = t.get("params")
        if not tid or not tf or not isinstance(params, list):
            continue
        rows = [x for x in (_norm_param(p) for p in params) if x]
        if rows:
            entries[(tid, tf.lower())] = {"meta": _entry_meta(t), "params": rows}
    flat = raw.get("rows")
    for r in flat if isinstance(flat, list) else []:
        if not isinstance(r, dict):
            continue
        tid = _str(r.get("template_id")) or _str(r.get("template"))
        tf = _str(r.get("tf")) or _str(r.get("timeframe"))
        p = _norm_param(r)
        if not tid or not tf or p is None:
            continue
        e = entries.setdefault((tid, tf.lower()), {"meta": _entry_meta(r), "params": []})
        if all(x["param"] != p["param"] for x in e["params"]):
            e["params"].append(p)
    if not entries:
        return None
    basis = _str(raw.get("basis"))
    m = _WINDOW_RE.search(basis or "")
    return {"meta": {"version": _str(raw.get("version")), "date": _str(raw.get("date")),
                     "status": _str(raw.get("status")), "basis_raw": basis,
                     "window": {"start": m.group(1), "end": m.group(2)} if m else None},
            "entries": entries}


_cache_lock = threading.Lock()
_cache: dict[str, tuple[tuple[int, int], Optional[dict]]] = {}


def load_research(path: Optional[Path] = None) -> Optional[dict]:
    """Normalised research file, or None when missing / unreadable. Re-read when the file changes."""
    p = Path(path) if path is not None else DATA_PATH
    try:
        st = p.stat()
    except OSError:
        return None
    sig = (st.st_mtime_ns, st.st_size)
    with _cache_lock:
        hit = _cache.get(str(p))
        if hit and hit[0] == sig:
            return hit[1]
    try:
        data = normalise_research(json.loads(p.read_text(encoding="utf-8")))
    except (OSError, ValueError, UnicodeDecodeError, RecursionError):
        data = None
    with _cache_lock:
        _cache[str(p)] = (sig, data)
    return data


# ── response rows ────────────────────────────────────────────────────────

def _row(index: dict, *, key: str, lab_keys: list[str], rank: int, score: Optional[float] = None,
         score_ci: Optional[list[float]] = None, label: Optional[str] = None, **extra: Any) -> dict:
    spec = index[lab_keys[0]]
    return {
        "key": key, "lab_keys": lab_keys, "rank": rank, "score": score, "score_ci": score_ci, "label": label,
        "tunable": all(bool(index[k].get("tunable")) for k in lab_keys), "group": spec.get("group"),
        "coins_frac_important": extra.get("coins_frac_important"),
        "folds_important": extra.get("folds_important"),
        "runs": extra.get("runs"),
        "runs_frac_important": extra.get("runs_frac_important"),
        "current_default": extra.get("current_default", spec.get("default") if len(lab_keys) == 1 else None),
        "recommended": extra.get("recommended"),
    }


def _response(tm, tf: str, source: str, params: list[dict], *, basis: str, basis_detail: str,
              date: Optional[str] = None, n_runs: Optional[int] = None, n_trials: Optional[int] = None,
              n_coins: Optional[int] = None, window: Optional[dict] = None, status: Optional[str] = None,
              note: Optional[str] = None) -> dict:
    return {"template_id": tm.TEMPLATE_ID, "timeframe": tf, "source": source, "basis": basis,
            "basis_detail": basis_detail, "date": date, "n_runs": n_runs, "n_trials": n_trials,
            "n_coins": n_coins, "window": window, "status": status, "note": note,
            "labels": {lb: sum(1 for p in params if p["label"] == lb) for lb in LABELS},
            "params": params}


def research_source(tm, tf: str, data: Optional[dict] = None) -> Optional[dict]:
    data = data if data is not None else load_research()
    if not data:
        return None
    entry = data["entries"].get((tm.TEMPLATE_ID, tf))
    if not entry:
        return None
    index = tm.PARAM_INDEX
    picked = []
    for p in entry["params"]:
        keys = [k for k in p["lab_keys"] if k in index]
        if keys:  # params that no longer exist in the Lab template are skipped
            picked.append((p, keys))
    if not picked:
        return None
    picked.sort(key=lambda x: (x[0]["score"] is None, -(x[0]["score"] or 0.0)))
    rows = [_row(index, key=p["param"], lab_keys=keys, rank=i, score=p["score"], score_ci=p["score_ci"],
                 label=p["label"], coins_frac_important=p["coins_frac_important"],
                 folds_important=p["folds_important"], current_default=p["current_default"],
                 recommended=p["recommended"])
            for i, (p, keys) in enumerate(picked, 1)]
    meta, fmeta = entry["meta"], data["meta"]
    date = fmeta.get("date") or fmeta.get("version")
    window = fmeta.get("window")
    day = _day(date)
    parts = []
    if meta.get("n_trials"):
        parts.append(f"{meta['n_trials']:,} setting acak")
    if meta.get("n_coins"):
        parts.append(f"{meta['n_coins']} koin")
    detail = " di ".join(parts) if parts else "Riset parameter"
    if window:
        detail += f"; diukur dari Sharpe harian {_day(window['start'])} s/d {_day(window['end'])}, dengan biaya Lab"
    note = None
    if window:
        note = (f"Riset memakai data {window['start'][:4]}–{window['end'][:4]}, yang ikut mencakup data baru "
                "(holdout) Lab. Pakai sebagai petunjuk parameter mana yang perlu diperhatikan, bukan sebagai bukti. "
                "Nilai saran riset tidak pernah dipakai otomatis.")
    return _response(tm, tf, "research", rows, basis=f"riset {day}" if day else "riset parameter",
                     basis_detail=detail + ".", date=date, n_trials=meta.get("n_trials"),
                     n_coins=meta.get("n_coins"), window=window, status=fmeta.get("status"), note=note)


def run_effects(sens: Any, index: dict) -> dict[str, float]:
    """{param: swing of log-growth across its sensitivity variations} for one run's stored sensitivity."""
    out: dict[str, float] = {}
    if not isinstance(sens, dict) or not isinstance(sens.get("params"), list):
        return out
    for row in sens["params"]:
        if not isinstance(row, dict) or row.get("param") not in index:
            continue
        variations = row.get("variations") if isinstance(row.get("variations"), list) else []
        nets = [_num(v.get("net_pct")) for v in variations if isinstance(v, dict)]
        g = [math.log1p(max(x, -99.99) / 100.0) for x in nets if x is not None]
        if len(g) >= 2:
            out[row["param"]] = max(g) - min(g)
    return out


def runs_source(conn: sqlite3.Connection, tm, tf: str, min_runs: int = MIN_RUNS,
                limit: int = MAX_RUNS) -> Optional[dict]:
    try:
        rows = conn.execute(
            "SELECT id, extra_json FROM lab_runs WHERE template_id=? AND timeframe=? AND status='done' "
            "AND mode IN ('validate', 'optimize') AND extra_json IS NOT NULL ORDER BY id DESC LIMIT ?",
            (tm.TEMPLATE_ID, tf, int(limit))).fetchall()
    except sqlite3.Error:
        return None
    index = tm.PARAM_INDEX
    agg: dict[str, dict[str, list]] = {}
    n_runs = 0
    for r in rows:
        extra = labdb.loads(r["extra_json"], {}) or {}
        effects = run_effects(extra.get("sensitivity") if isinstance(extra, dict) else None, index)
        total = sum(effects.values())
        if len(effects) < 2 or total <= 0:
            continue
        n_runs += 1
        d = len(effects)
        for rank, (k, e) in enumerate(sorted(effects.items(), key=lambda kv: -kv[1]), 1):
            a = agg.setdefault(k, {"ranks": [], "shares": [], "dims": [], "hits": []})
            share = e / total
            a["ranks"].append(rank)
            a["shares"].append(share)
            a["dims"].append(d)
            a["hits"].append(share >= 1.0 / d)
    if n_runs < min_runs:
        return None
    stats = []
    for k, a in agg.items():
        share = median(a["shares"])
        important = share >= 1.0 / median(a["dims"])
        frac = sum(a["hits"]) / len(a["hits"])
        label = (LABEL_STABLE if frac >= STABLE_FRACTION else LABEL_UNSTABLE) if important else LABEL_NONE
        stats.append((median(a["ranks"]), -share, k, share, label, len(a["ranks"]), frac))
    stats.sort()
    params = [_row(index, key=k, lab_keys=[k], rank=i, score=share, label=label, runs=n, runs_frac_important=frac)
              for i, (_r, _s, k, share, label, n, frac) in enumerate(stats, 1)]
    return _response(tm, tf, "runs", params, basis=f"dari {n_runs} run", n_runs=n_runs,
                     basis_detail=(f"Sensitivitas {n_runs} run Uji jujur / Cari setting terbaik {tf} yang sudah "
                                   "selesai: tiap parameter digeser ±10–20% di data latih, lalu dilihat "
                                   "seberapa jauh hasilnya berubah."),
                     note="Hanya mencakup parameter yang dicek sensitivitasnya oleh Lab.")


def template_source(tm, tf: str) -> dict:
    tun = [p for p in tm.PARAMS if p.get("tunable")]
    pos = {k: i for i, k in enumerate(FALLBACK_ORDER.get(tm.TEMPLATE_ID, []))}
    idx = {p["key"]: i for i, p in enumerate(tun)}
    tun = sorted(tun, key=lambda p: (pos.get(p["key"], len(pos)), idx[p["key"]]))
    params = [_row(tm.PARAM_INDEX, key=p["key"], lab_keys=[p["key"]], rank=i) for i, p in enumerate(tun, 1)]
    return _response(tm, tf, "template", params, basis="urutan bawaan template",
                     basis_detail=(f"Belum ada data riset atau minimal {MIN_RUNS} run selesai untuk {tf}, jadi "
                                   "urutannya bawaan template dan belum diukur."))


def for_template(conn: Optional[sqlite3.Connection], tm, tf: str, data: Optional[dict] = None) -> dict:
    """Importance for template module ``tm`` at timeframe ``tf``: research -> runs -> template."""
    out = research_source(tm, tf, data)
    if out is None and conn is not None:
        out = runs_source(conn, tm, tf)
    return out if out is not None else template_source(tm, tf)
