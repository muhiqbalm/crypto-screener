"""``ai_factor_summary`` job: one Ringkasan AI per coin for the latest Outlook bar.

Runs in the worker's child process under the screener venv (the only venv with the
``anthropic`` package), in the fast lane, after that bar's outlook_refresh finished.

  1. off (no key / LAB_AI_ENABLED=0 / no SDK) -> nothing is called, the job ends "done"
  2. coins in "Peluang terbaik" order (the most useful summaries first if the budget runs out);
     a coin that already has a row for this bar is skipped (cache: one call per coin per bar)
  3. the first call runs alone (it writes the prompt cache), the rest PARALLEL at a time;
     before every batch: today's spend + estimated cost must stay under the daily cap
  4. every answer is validated (validate.py) and stored with tokens + cost (store.py)

Reads lab.db and public market data only; writes lab_ai_summaries and lab_kv 'ai_meta'.
No orders, no Telegram, nothing in src/trading.
"""
from __future__ import annotations

import logging
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Callable, Optional

from .. import queue as q
from ..db import loads, utcnow
from ..outlook import logic as L
from ..outlook import store as S
from . import client as C
from . import facts as F
from . import store
from .config import AiConfig, ai_config, off_reason, price_for
from .validate import check

log = logging.getLogger("lab.ai")
META_KEY = "ai_meta"
PARALLEL = 3
DEADLINE_S = 600
EST_OUTPUT_TOKENS = 1200      # conservative (thinking + JSON) until real calls were observed


def estimate_call_cost(conn, cfg: AiConfig, facts_json: str) -> float:
    """Expected USD of the next call: 1.25 x today's average when >= 3 calls were made today
    with this model, else a static upper estimate (chars / 3.5 tokens, uncached)."""
    r = conn.execute("SELECT COUNT(*), AVG(cost_usd) FROM lab_ai_summaries WHERE model=? AND cost_usd > 0 AND "
                     "updated_at >= ?", (cfg.model, store.day_start())).fetchone()
    if r and r[0] and r[0] >= 3 and r[1]:
        return float(r[1]) * 1.25
    p, _ = price_for(cfg.model)
    tin = (len(C.SYSTEM_PROMPT) + len(facts_json)) / 3.5
    return (tin * p["in"] + EST_OUTPUT_TOKENS * p["out"]) / 1e6


def _rows(conn) -> tuple[list[dict], dict[str, list]]:
    rows, heads = [], {}
    for r in conn.execute("SELECT symbol, row_json, detail_json, error FROM lab_outlook ORDER BY symbol"):
        row = loads(r["row_json"])
        if not row or r["error"]:
            continue
        rows.append(row)
        heads[r["symbol"]] = (loads(r["detail_json"], {}) or {}).get("headlines")
    return L.rank_rows(rows), heads


def _record(conn, f: F.Facts, cfg: AiConfig, res: C.CallResult) -> str:
    status, output, validation = res.status, None, None
    if res.status == "ok":
        status, output, validation = check(res.data, f)
    if res.fallback_used:
        validation = {**(validation or {}), "fallback_model": res.served_model}
    store.save(conn, {
        "symbol": f.symbol, "bar": f.bar, "bar_close": f.bar_close,
        "input_hash": f.input_hash(C.PROMPT_VERSION, cfg.model, cfg.effort), "model": cfg.model,
        "served_model": res.served_model, "effort": cfg.effort, "status": status, "tokens": res.tokens,
        "cost_usd": res.cost_usd, "output": output, "validation": validation, "facts": f.facts, "error": res.error})
    conn.commit()
    return status


def execute(conn, job: Optional[dict] = None, *, client_factory: Optional[Callable[[AiConfig], Any]] = None,
            whales_fetcher: Optional[Callable[[], Optional[dict]]] = None, symbols: Optional[list[str]] = None) -> dict:
    t0 = time.time()
    store.ensure_schema(conn)
    S.ensure_schema(conn)
    cfg = ai_config(fresh=True)
    job_id = (job or {}).get("id")
    meta: dict[str, Any] = {"started_at": utcnow(), "model": cfg.model, "effort": cfg.effort,
                            "budget_usd": cfg.daily_budget_usd, "done": 0, "skipped_cached": 0,
                            "counts": {s: 0 for s in store.STATUSES}, "cost_usd": 0.0, "stopped": None}
    reason = off_reason(cfg)
    if reason:
        meta.update({"stopped": reason, "finished_at": utcnow()})
        S.kv_set(conn, META_KEY, meta)
        conn.commit()
        return meta

    rows, heads = _rows(conn)
    newest = max((r.get("last_bar") or "" for r in rows), default="") or None
    rows = [r for r in rows if r.get("last_bar") == newest]       # coins left on an older bar are stale
    if symbols:
        rows = [r for r in rows if r.get("symbol") in set(symbols)]
    meta["bar"] = newest
    omet = S.kv_get(conn, S.META_KEY) or {}
    todo_rows = []
    for r in rows:
        if store.get(conn, r["symbol"], r["last_bar"]) is not None:
            meta["skipped_cached"] += 1
            continue
        todo_rows.append(r)
    need_whales = any(F.coin_symbol(r) in F.WHALE_RATIO_COINS for r in todo_rows)
    whales = (whales_fetcher or F.fetch_whales)() if need_whales else None
    meta["whales"] = bool(whales)
    todo: list[F.Facts] = []
    for r in todo_rows:
        f = F.build(r, heads.get(r["symbol"]), omet.get("fear_greed"), whales)
        if f is not None:
            todo.append(f)
    meta["coins"] = len(todo)

    client = (client_factory or C.make_client)(cfg) if todo else None
    spent = store.spent_today(conn)
    i = 0
    while i < len(todo):
        if time.time() - t0 > DEADLINE_S:
            meta["stopped"] = "deadline"
            break
        size = 1 if i == 0 else PARALLEL           # the first call warms the prompt cache
        batch = todo[i:i + size]
        est = estimate_call_cost(conn, cfg, batch[0].json())
        fit = int(max(0.0, cfg.daily_budget_usd - spent) // est) if est > 0 else len(batch)
        if fit <= 0:
            meta["stopped"] = "over_budget"
            break
        batch = batch[:fit]
        if job_id:
            q.set_progress(conn, job_id, {"stage": "ringkasan AI", "done": i, "total": len(todo)})
        if len(batch) == 1:
            results = [C.call(client, cfg, batch[0].json())]
        else:
            with ThreadPoolExecutor(max_workers=len(batch)) as ex:
                results = list(ex.map(lambda f: C.call(client, cfg, f.json()), batch))
        fatal = None
        for f, res in zip(batch, results):
            st = _record(conn, f, cfg, res)
            meta["counts"][st] = meta["counts"].get(st, 0) + 1
            meta["done"] += 1
            meta["cost_usd"] += res.cost_usd
            spent += res.cost_usd
            if res.fatal:
                fatal = res.error
        i += len(batch)
        if fatal:
            meta["stopped"] = "fatal_error"
            meta["error"] = fatal
            break
    meta.update({"cost_usd": round(meta["cost_usd"], 6), "spent_today_usd": round(spent, 6),
                 "runtime_s": round(time.time() - t0, 1), "finished_at": utcnow(),
                 "left": len(todo) - meta["done"]})
    S.kv_set(conn, META_KEY, meta)
    conn.commit()
    log.info("ai summaries bar=%s done=%s counts=%s cost=$%.4f stopped=%s", meta.get("bar"), meta["done"],
             meta["counts"], meta["cost_usd"], meta["stopped"])
    if meta["stopped"] == "fatal_error":
        raise RuntimeError(f"Ringkasan AI berhenti: {meta.get('error')}")
    return meta
