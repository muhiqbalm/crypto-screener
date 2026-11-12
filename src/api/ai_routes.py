"""/api/v1/lab/ai/*: Ringkasan AI, READ access for any logged-in team account (same as the
Outlook / "Peluang koin"); the reason it is off, costs and validation details only for admins.

  GET /lab/ai/factors?symbol=ETH   the coin's summary for its CURRENT Outlook bar (or none)
  GET /lab/ai/status               on/off and why; admins also get model, budget and last run

SQL reads of lab.db only. The summaries are written by the lab worker (``ai_factor_summary``
job, src/lab/ai). The API never calls the AI provider, never imports its SDK and never
returns the API key (only whether one is configured). Information only: nothing here can
place, size or suggest a live order.
"""
from __future__ import annotations

import re
from typing import Annotated, Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Query

from src.lab.ai import JOB_KIND, LABEL
from src.lab.ai import store as AS
from src.lab.ai.config import FALLBACK_MODELS, REASON_TEXT, ai_config, off_reason, price_for, sdk_available
from src.lab.ai.schedule import BAR_KEY
from src.lab import db as labdb
from src.lab.outlook import store as S

from .lab_auth import lab_user
from .lab_routes import _conn

router = APIRouter(prefix="/api/v1/lab/ai", tags=["lab-ai"])
User = Annotated[dict, Depends(lab_user)]
Conn = Annotated[Any, Depends(_conn)]
Symbol = Annotated[str, Query(min_length=2, max_length=40, description="Koin: ETH, ETHUSDT, 1000PEPE, ...")]

_SYM = re.compile(r"^[A-Z0-9]{2,24}USDT$")
STATUS_TEXT = {
    "rejected": "Ringkasan AI terakhir ditolak validasi (memuat angka yang tidak ada di data), tidak ditampilkan",
    "refused": "Model menolak membuat ringkasan untuk koin ini",
    "error": "Ringkasan AI terakhir gagal dibuat",
}
PENDING_TEXT = "Ringkasan AI untuk close 4H terakhir belum dibuat"


def _symbol(raw: str) -> str:
    sym = raw.strip().upper().replace("/", "").replace(":USDT", "")
    sym = sym if sym.endswith("USDT") else sym + "USDT"
    if not _SYM.match(sym):
        raise HTTPException(422, "simbol tidak valid")
    return sym


def _current_bar(conn, sym: str) -> Optional[str]:
    S.ensure_schema(conn)
    r = conn.execute("SELECT last_bar FROM lab_outlook WHERE symbol=? AND row_json IS NOT NULL", (sym,)).fetchone()
    return r["last_bar"] if r else None


def _public(rec: dict, admin: bool) -> dict:
    out = rec.get("output") or {}
    pub = {"symbol": rec["symbol"], "bar": rec["bar"], "bar_close": rec.get("bar_close"),
           "created_at": rec.get("updated_at"), "sentence": out.get("sentence"),
           "factors": out.get("factors") or [], "data_gaps": out.get("data_gaps") or []}
    if admin:
        v = rec.get("validation") or {}
        pub["meta"] = {"model": rec.get("served_model") or rec.get("model"), "effort": rec.get("effort"),
                       "cost_usd": rec.get("cost_usd"), "input_tokens": rec.get("input_tokens"),
                       "output_tokens": rec.get("output_tokens"), "cache_read_tokens": rec.get("cache_read_tokens"),
                       "dropped_factors": len(v.get("dropped_factors") or []),
                       "effects_overridden": len(v.get("effects_overridden") or []),
                       "fallback_model": v.get("fallback_model")}
    return pub


@router.get("/factors")
def ai_factors(symbol: Symbol, user: User, conn: Conn) -> dict:
    sym = _symbol(symbol)
    admin = bool(user["is_admin"])
    cfg = ai_config()
    reason = off_reason(cfg)
    out: dict[str, Any] = {"symbol": sym, "enabled": reason is None, "label": LABEL, "summary": None,
                           "reason": None, "note": None}
    if reason:
        if admin:
            out["reason"], out["note"] = reason, REASON_TEXT[reason]
        return out
    cur = _current_bar(conn, sym)
    rec = AS.latest(conn, sym)
    if rec and cur and rec["bar"] == cur and rec["status"] == "ok" and rec.get("output"):
        out["summary"] = _public(rec, admin)
        return out
    if admin:
        if rec and cur and rec["bar"] == cur:
            out["reason"], out["note"] = rec["status"], STATUS_TEXT.get(rec["status"], PENDING_TEXT)
            if rec.get("error"):
                out["note"] += f": {rec['error']}"
        elif AS.spent_today(conn) >= cfg.daily_budget_usd:
            out["reason"], out["note"] = "over_budget", REASON_TEXT["over_budget"]
        else:
            out["reason"], out["note"] = "pending", PENDING_TEXT
    return out


@router.get("/status")
def ai_status(user: User, conn: Conn) -> dict:
    cfg = ai_config()
    reason = off_reason(cfg)
    spent = AS.spent_today(conn)
    over = reason is None and spent >= cfg.daily_budget_usd
    out: dict[str, Any] = {"enabled": reason is None, "active": reason is None and not over, "label": LABEL}
    if not user["is_admin"]:
        return out
    why = reason or ("over_budget" if over else None)
    price, src = price_for(cfg.model)
    job = conn.execute("SELECT id, status, created_at, started_at, finished_at, error, progress_json FROM lab_jobs "
                       "WHERE kind=? ORDER BY id DESC LIMIT 1", (JOB_KIND,)).fetchone()
    job = dict(job) if job else None
    if job:
        job["progress"] = labdb.loads(job.pop("progress_json"))
    last_bar = AS.last_bar(conn)
    out.update({
        "reason": why, "reason_text": REASON_TEXT.get(why) if why else None,
        "key_present": cfg.key_present, "flag_enabled": cfg.enabled, "sdk_installed": sdk_available(),
        "model": cfg.model, "effort": cfg.effort, "refusal_fallback": cfg.model in FALLBACK_MODELS,
        "price_per_mtok_usd": price, "price_source": src,
        "budget": {"daily_usd": cfg.daily_budget_usd, "spent_today_usd": round(spent, 4),
                   "remaining_usd": round(max(0.0, cfg.daily_budget_usd - spent), 4),
                   "day_utc": AS.day_start()[:10], "resets": "00:00 UTC (07:00 WIB)"},
        "last_run": S.kv_get(conn, "ai_meta"), "last_bar": last_bar, "last_bar_counts": AS.bar_counts(conn, last_bar),
        "scheduled_bar": S.kv_get(conn, BAR_KEY), "job": job,
        "how_to_enable": ["ANTHROPIC_API_KEY di .env server (crypto-screener)", "LAB_AI_ENABLED=1 di .env yang sama"],
    })
    return out
