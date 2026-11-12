"""/api/v1/lab/outlook + /api/v1/lab/regime: READ access for any logged-in user (CEO decision
12 Nov: "Peluang koin" is readable by every team account); refresh / calibrate stay admin-only.
Open positions (Lab paper accounts and the live bot's, read-only) are only shown to admins.

SQL reads of lab.db only: the outlook rows are computed by the lab worker
(``outlook_refresh`` job after every 4H close), the calibration by the heavy
``outlook_calibrate`` job (weekly / on demand). The money projection, the
"Peluang terbaik" ranking and the open-position flags are computed here per
request. Information only: nothing here places, sizes or suggests a live order.

v2 (additive): every row keeps the v1 fields and adds ``schema_version``, ``plan``,
``strategies``/``agreement``, ``mtf``, ``changes``, ``peluang``, ``positions``,
``coin_calibration``; the list response adds ``counts``, ``ranking``, ``calibration``
and ``track_record``. New: GET /outlook/track-record, GET /outlook/calibration,
POST /outlook/calibrate.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Annotated, Any, Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Query

from src.lab import db as labdb
from src.lab import queue as q
from src.lab import regime as R
from src.lab.outlook import JOB_KIND
from src.lab.outlook import logic as L
from src.lab.outlook import store as S
from src.lab.outlook.replay import JOB_KIND as CALIB_KIND
from src.lab.outlook.replay import load as load_calibration
from src.lab.outlook.schedule import enqueue_now

from .lab_auth import lab_admin, lab_user
from .lab_routes import _conn

router = APIRouter(prefix="/api/v1/lab", tags=["lab-outlook"])
Admin = Annotated[dict, Depends(lab_admin)]
User = Annotated[dict, Depends(lab_user)]
Conn = Annotated[Any, Depends(_conn)]

Capital = Annotated[float, Query(gt=0, le=1e9, description="Modal (USDT)")]
Leverage = Annotated[float, Query(ge=1, le=20, description="Leverage; posisi = modal x leverage (mode notional)")]
Sizing = Annotated[Literal["notional", "risk"], Query(description="notional = modal x leverage; risk = rugi di SL = risk_pct modal")]
RiskPct = Annotated[float, Query(gt=0, le=10)]
Arah = Annotated[Optional[Literal["long", "short", "netral"]], Query(description="filter arah")]
Keyakinan = Annotated[Optional[Literal["tinggi", "sedang", "rendah"]], Query(description="filter keyakinan")]
Posisi = Annotated[Optional[Literal["ada", "tidak"]], Query(description="filter: sudah ada posisi (paper/live) di koin ini")]
Sort = Annotated[Literal["peluang", "symbol"], Query(description="peluang = Peluang terbaik; symbol = A-Z")]

_DISCLAIMER = ("Bukan saran investasi; strategi bisa salah; preset GAGAL/belum diuji = keyakinan rendah. "
               "Angka proyeksi adalah hitungan, bukan jaminan.")


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _job(conn, kind: str = JOB_KIND) -> dict | None:
    r = conn.execute("SELECT id, status, created_at, started_at, finished_at, error, progress_json FROM lab_jobs WHERE kind=? "
                     "ORDER BY id DESC LIMIT 1", (kind,)).fetchone()
    if r is None:
        return None
    out = dict(r)
    out["progress"] = labdb.loads(out.pop("progress_json"))
    return out


def _positions(conn) -> tuple[dict, dict]:
    """({symbol: [positions]}, availability) from Lab paper accounts and the live bot (read-only)."""
    from src.lab.settings import get_lab_settings
    paper = S.paper_positions(conn)
    live = S.live_positions(get_lab_settings().trading_db_path)
    out: dict[str, list] = {}
    for src in (paper, live or {}):
        for sym, xs in src.items():
            out.setdefault(sym, []).extend(xs)
    return out, {"paper": True, "live": live is not None}


def _decorate(row: dict, now: str, capital: float, leverage: float, sizing: str, risk_pct: float,
              positions: Optional[dict] = None) -> dict:
    if row.get("unavailable"):
        return row
    age = L.hours_between(row.get("last_bar_close"), now)
    out = {**row, "age_hours": age, "stale": age is not None and age > L.STALE_HOURS}
    if out.get("plan"):
        fr = dict(out["plan"].get("freshness") or {})
        fr.update({"age_hours": age, "stale": out["stale"]})
        out["plan"] = {**out["plan"], "freshness": fr}
    out["projection"] = L.project(out, capital, leverage, sizing, risk_pct)
    out["peluang"] = L.peluang(out)
    if positions is not None:
        out["positions"] = positions.get(row.get("symbol"), [])
    return out


def _lite(row: dict) -> dict:
    out = dict(row)
    exp = row.get("explanation") or {}
    out["explanation"] = {"summary": exp.get("summary"), "narrator": exp.get("narrator")}
    return out


def _side_of(r: dict) -> str:
    return (r.get("strategy") or {}).get("side") or "netral"


def _match(r: dict, arah, keyakinan, posisi) -> bool:
    if r.get("unavailable"):
        return arah is None and keyakinan is None and posisi is None
    if arah and _side_of(r) != arah:
        return False
    if keyakinan and (r.get("bias") or {}).get("keyakinan") != keyakinan:
        return False
    if posisi == "ada" and not r.get("positions"):
        return False
    if posisi == "tidak" and r.get("positions"):
        return False
    return True


def _counts(rows: list[dict]) -> dict:
    ok = [r for r in rows if not r.get("unavailable")]
    return {
        "total": len(rows),
        "arah": {k: sum(1 for r in ok if _side_of(r) == k) for k in ("long", "short", "netral")},
        "keyakinan": {k: sum(1 for r in ok if (r.get("bias") or {}).get("keyakinan") == k) for k in ("tinggi", "sedang", "rendah")},
        "posisi": {"ada": sum(1 for r in ok if r.get("positions")), "tidak": sum(1 for r in ok if not r.get("positions"))},
        "peluang_positif": sum(1 for r in ok if (r.get("peluang") or {}).get("label") == "positif"),
        "sinyal_baru": sum(1 for r in ok if (r.get("strategy") or {}).get("fresh")),
    }


def _calib_brief(cal: Optional[dict]) -> Optional[dict]:
    if not cal:
        return None
    oos = cal.get("oos_check") or {}
    pick = lambda d: {k: v for k, v in (d or {}).items() if k.count("|") <= 1}  # noqa: E731
    return {
        "computed_at": cal.get("computed_at"), "version": cal.get("version"), "counts": cal.get("counts"),
        "split": cal.get("split"), "method": cal.get("method"), "excluded": cal.get("excluded"),
        "by_keyakinan": pick(cal.get("by_keyakinan")),
        "oos_check": {"split": oos.get("split"), "train_cases": oos.get("train_cases"), "test_cases": oos.get("test_cases"),
                      "v2": pick(oos.get("v2")), "apriori": pick(oos.get("apriori"))},
        "fase_split": cal.get("fase_split"),
        "factor_lift": {f: {k: v.get(k) for k in ("verdict", "diff_r", "se_diff_r", "halves", "searah", "berlawanan")}
                        for f, v in ((cal.get("factor_lift") or {}).get("pool") or {}).items()},
        "ambiguous_share": cal.get("ambiguous_share"), "engine_commit": cal.get("engine_commit"),
        "runtime_s": cal.get("runtime_s"),
    }


def _track_brief(conn) -> dict:
    tr = S.track_record(conn, limit=0)
    return {"since": tr.get("since"), "first_call": tr.get("first_call"),
            "groups": {k: v for k, v in tr["groups"].items()}}


@router.get("/outlook")
def outlook(user: User, conn: Conn, capital: Capital = 1000.0, leverage: Leverage = 1.0, sizing: Sizing = "notional",
            risk_pct: RiskPct = 1.0, arah: Arah = None, keyakinan: Keyakinan = None, posisi: Posisi = None,
            sort: Sort = "peluang") -> dict:
    S.ensure_schema(conn)
    now = _now_iso()
    admin = bool(user["is_admin"])
    pos, pos_avail = _positions(conn) if admin else (None, None)
    if not admin:
        posisi = None   # the position filter needs data a non-admin cannot see
    rows = [_decorate(r, now, capital, leverage, sizing, risk_pct, pos) for r in S.read_rows(conn)]
    counts = _counts(rows)
    ranked = L.rank_rows(rows) if sort == "peluang" else sorted(rows, key=lambda r: r.get("symbol") or "")
    if sort != "peluang":  # ranks still describe the Peluang order
        order = {r["symbol"]: (r.get("peluang") or {}).get("rank") for r in L.rank_rows([dict(x) for x in rows])}
        for r in ranked:
            if r.get("peluang") and order.get(r["symbol"]):
                r["peluang"] = {**r["peluang"], "rank": order[r["symbol"]]}
    shown = [_lite(r) for r in ranked if _match(r, arah, keyakinan, posisi)]
    reg = R.load(conn) or {}
    cal = load_calibration(conn)
    return {
        "schema_version": L.SCHEMA_VERSION, "can_refresh": admin,
        "meta": S.kv_get(conn, S.META_KEY), "refresh": _job(conn), "calibrate": _job(conn, CALIB_KIND), "now": now,
        "inputs": {"capital": capital, "leverage": leverage, "sizing": sizing, "risk_pct": risk_pct},
        "filters": {"arah": arah, "keyakinan": keyakinan, "posisi": posisi, "sort": sort},
        "counts": counts, "positions_available": pos_avail,
        "ranking": [r["symbol"] for r in ranked if (r.get("peluang") or {}).get("eligible")],
        "regime": {k: reg.get(k) and {x: reg[k].get(x) for x in ("label", "label_text", "as_of", "days_in_label",
                                                                  "dist_ema_slow_pct", "slope_pct", "available")}
                   for k in ("btc", "eth")},
        "calibration": _calib_brief(cal), "track_record": _track_brief(conn),
        "method": L.method(), "disclaimer": _DISCLAIMER, "rows": shown,
    }


@router.post("/outlook/refresh")
def outlook_refresh(_: Admin, conn: Conn) -> dict:
    j = _job(conn)
    if j and j["status"] in ("queued", "running"):
        return {"job_id": j["id"], "already": True}
    return {"job_id": enqueue_now(conn), "already": False}


@router.post("/outlook/calibrate")
def outlook_calibrate(_: Admin, conn: Conn) -> dict:
    """Queue the historical replay (heavy, sequential, nice'd; a few minutes)."""
    j = _job(conn, CALIB_KIND)
    if j and j["status"] in ("queued", "running"):
        return {"job_id": j["id"], "already": True}
    jid = q.enqueue(conn, CALIB_KIND, None, {"manual": True}, priority=3)
    conn.commit()
    return {"job_id": jid, "already": False}


@router.get("/outlook/track-record")
def outlook_track_record(_: User, conn: Conn, limit: Annotated[int, Query(ge=0, le=500)] = 100,
                         since: Annotated[Optional[str], Query(max_length=25)] = None) -> dict:
    """Live track record of the stored calls (evaluated after the fact) + the replay's label check."""
    tr = S.track_record(conn, since=since, limit=limit)
    cal = _calib_brief(load_calibration(conn))
    return {**tr, "calibration": cal and {k: cal[k] for k in ("computed_at", "counts", "by_keyakinan", "oos_check",
                                                              "fase_split", "split")},
            "statuses": {"tp": "kena TP dulu", "sl": "kena SL dulu", "batal": "dibatalkan (strategi keluar)",
                         "expired": "habis waktu", "open": "masih berjalan"},
            "note": "Setiap panggilan dinilai seperti instruksi halaman: masuk di close 4H, SL & TP terpasang, keluar di "
                    "close bila strategi menutup/membalik posisi, atau setelah horizon. R bersih setelah biaya 0,2%."}


@router.get("/outlook/calibration")
def outlook_calibration(_: User, conn: Conn, full: bool = False) -> dict:
    cal = load_calibration(conn)
    if cal is None:
        return {"available": False, "job": _job(conn, CALIB_KIND)}
    if full:
        return {"available": True, **cal, "job": _job(conn, CALIB_KIND)}
    return {"available": True, **(_calib_brief(cal) or {}), "configs": cal.get("configs"),
            "params": cal.get("params"), "job": _job(conn, CALIB_KIND)}


@router.get("/outlook/{symbol}")
def outlook_detail(symbol: str, user: User, conn: Conn, capital: Capital = 1000.0, leverage: Leverage = 1.0,
                   sizing: Sizing = "notional", risk_pct: RiskPct = 1.0) -> dict:
    sym = symbol.upper().replace("/", "").replace(":USDT", "")
    sym = sym if sym.endswith("USDT") else sym + "USDT"
    got = S.read_one(conn, sym)
    if got is None or got["row"] is None:
        raise HTTPException(404, f"outlook untuk {sym} belum tersedia")
    now = _now_iso()
    reg = R.load(conn) or {}
    admin = bool(user["is_admin"])
    pos, pos_avail = _positions(conn) if admin else (None, None)
    row = _decorate(got["row"], now, capital, leverage, sizing, risk_pct, pos)
    cal = load_calibration(conn)
    return {**row, "error": got["error"], "detail": got["detail"], "now": now, "can_refresh": admin,
            "inputs": {"capital": capital, "leverage": leverage, "sizing": sizing, "risk_pct": risk_pct},
            "positions_available": pos_avail,
            "calls": S.calls_for(conn, sym, 30),
            "coin_calibration_all": ((cal or {}).get("per_coin") or {}).get(sym),
            "regime": {"btc": reg.get("btc"), "eth": reg.get("eth"), "rule": reg.get("rule")},
            "method": L.method(), "disclaimer": _DISCLAIMER}


@router.get("/regime")
def regime(user: User, conn: Conn) -> dict:
    """BTC + ETH regime for any logged-in user; per-preset performance by regime for Lab admins only."""
    reg = R.load(conn)
    if reg is None:
        return {"computed_at": None, "rule": R.RULE, "btc": None, "eth": None, "presets": None,
                "available": False}
    out = {**reg, "available": True}
    if not user["is_admin"]:
        out["presets"] = None
        out.pop("btc_history_share_pct", None)
    return out
