"""Basket report for the API (read-only): one entry per basket with progress to 30 closed
trades across coins, a per-coin breakdown, the account equity, the pre-registered checkpoint
outcome and the paper-vs-engine fidelity check (08-praregistrasi-basket.md §6-§9).

Every number comes from lab.db: the basket account's paper positions and journal, the member
watches' watch_state (the engine's own trades over the same bars) and the hourly arena equity
snapshots. Equity, drawdown and win rate use the Arena Paper maths (arena.report.paper_stats)
so a basket and a preset are measured the same way. Nothing here writes to lab.db.
"""
from __future__ import annotations

import statistics
import time
from typing import Optional

from ..arena import report as arena
from ..arena import stats as astats
from ..arena.store import snapshots
from ..db import loads
from ..ledger.store import iso, to_epoch
from . import rules, store

TF_SECONDS = {"15m": 900, "30m": 1800, "1h": 3600, "4h": 14400, "1d": 86400}
SPARK_POINTS = 60
TEMPLATE_LABEL = {"rosyade_family": "Rosyade", "donchian_breakout": "Donchian breakout",
                  "mean_reversion_range": "Mean reversion (range)"}


def coin(symbol: str) -> str:
    s = (symbol or "").upper()
    return s[:-4] if s.endswith("USDT") else s


def _rules_out() -> dict:
    return {"prereg_id": rules.PREREG_ID, "doc": rules.PREREG_DOC, "json": rules.PREREG_JSON,
            "commit": rules.PREREG_COMMIT, "review_min_trades": rules.REVIEW_MIN_TRADES,
            "checkpoints": {str(k): v for k, v in rules.CHECKPOINTS.items()}, "deadline_days": rules.DEADLINE_DAYS,
            "pf_fail": {str(k): v for k, v in rules.PF_FAIL.items()}, "pf_pass": rules.PF_PASS,
            "dd_limit_floor_pct": rules.DD_LIMIT_FLOOR_PCT, "dd_limit_mult": rules.DD_LIMIT_MULT,
            "kill_dd_pct": rules.KILL_DD_PCT, "fidelity_coverage_min": rules.FIDELITY_COVERAGE_MIN,
            "fidelity_max_median_abs_diff_pp": rules.FIDELITY_MAX_MEDIAN_ABS_DIFF_PP,
            "entry_window_s": list(rules.ENTRY_WINDOW_S)}


# ── data ───────────────────────────────────────────────────────────────────

class _Ctx:
    """Everything one basket's report reads, loaded once."""

    def __init__(self, conn, basket: dict, now: float):
        self.basket, self.now = basket, now
        self.tf_s = TF_SECONDS.get(basket["timeframe"], 14400)
        a = conn.execute("SELECT * FROM paper_accounts WHERE id=?", (basket["account_id"],)).fetchone()
        self.account = dict(a) if a is not None else None
        self.start_s = to_epoch(self.account["created_at"] if self.account else basket["created_at"])
        self.members = store.members(conn, basket["id"])
        aid = basket["account_id"]
        self.journal = [dict(r) for r in conn.execute(
            "SELECT id, source, watch_id, symbol, side, entry_time, entry_price, exit_time, exit_price, qty, fees, "
            "funding, pnl, r_multiple, exit_reason FROM journal_entries WHERE account_id=? "
            "AND source IN ('paper_auto','paper_manual') ORDER BY exit_time, id", (aid,))]
        self.auto = [j for j in self.journal if j["source"] == "paper_auto"]
        self.positions = [dict(r) for r in conn.execute(
            "SELECT * FROM paper_positions WHERE account_id=? ORDER BY entry_time, id", (aid,))]
        wids = [m["watch_id"] for m in self.members] or [-1]
        ph = ",".join("?" * len(wids))
        self.watches = {r["id"]: dict(r) for r in conn.execute(
            f"SELECT id, symbol, active, autopaper_enabled, autopaper_account_id, created_at FROM watches "
            f"WHERE id IN ({ph})", wids)}
        self.states = {r["watch_id"]: dict(r) for r in conn.execute(
            f"SELECT watch_id, computed_at, last_bar, position_json, recent_trades_json, last_signal_json, error "
            f"FROM watch_state WHERE watch_id IN ({ph})", wids)}
        self.events = store.events(conn, basket["id"], limit=1000)
        self.snaps = snapshots(conn, [aid]).get(aid, []) if self.account else []
        self.stats = (arena.paper_stats(self.account, self.journal, self.positions, self.snaps, now)
                      if self.account else None)


# ── fidelity: paper vs the engine's own trades on the same bars ──────────────

def _engine_entries(state: Optional[dict]) -> list[dict]:
    if not state:
        return []
    out = [dict(t) for t in loads(state["recent_trades_json"], []) or []]
    pos = loads(state["position_json"])
    if pos and pos.get("entry_time"):
        out.append({"entry_time": pos["entry_time"], "side": pos.get("side"), "exit_time": None, "open": True})
    return out


def _paper_ret_pct(p: dict) -> Optional[float]:
    notional = (p.get("qty") or 0) * (p.get("entry_price") or 0)
    if p.get("pnl") is None or notional <= 0:
        return None
    return float(p["pnl"]) / notional * 100.0


def fidelity(ctx: _Ctx, until_s: Optional[float] = None) -> dict:
    """Do the paper entries and results follow the engine trades of the same watches?

    Expected = engine entries whose signal bar closed after the basket start and before
    ``until_s``. A paper twin has the same side and was opened between the signal close
    -5 min and +2 h. Returns coverage, the median |paper - engine| return per closed pair
    (% of notional, net), the engine PF over return_on_equity_pct (closed before until_s)
    and every missed entry with the logged reason."""
    until = until_s if until_s is not None else ctx.now
    lo, hi = rules.ENTRY_WINDOW_S
    skips: dict[tuple, str] = {}
    for e in ctx.events:
        if e["kind"] == "skip" and e.get("bar"):
            skips.setdefault((e["watch_id"], e["bar"]), e["reason"])
    expected = matched = 0
    diffs: list[float] = []
    eng_roe: list[float] = []
    missed: list[dict] = []
    used: set[int] = set()
    for m in ctx.members:
        wid = m["watch_id"]
        papers = [p for p in ctx.positions if p["watch_id"] == wid and p["source"] == "paper_auto"]
        for e in sorted(_engine_entries(ctx.states.get(wid)), key=lambda x: x["entry_time"]):
            close_s = to_epoch(e["entry_time"]) + ctx.tf_s
            if close_s <= ctx.start_s or close_s >= until:
                continue
            expected += 1
            twin = next((p for p in papers if p["id"] not in used and p["side"] == e.get("side")
                         and close_s + lo <= to_epoch(p["entry_time"]) <= close_s + hi), None)
            eng_closed = bool(e.get("exit_time")) and to_epoch(e["exit_time"]) + ctx.tf_s <= until
            if eng_closed and e.get("return_on_equity_pct") is not None:
                eng_roe.append(float(e["return_on_equity_pct"]))
            if twin is None:
                missed.append({"symbol": m["symbol"], "coin": coin(m["symbol"]), "side": e.get("side"),
                               "signal_time": e["entry_time"],
                               "reason": skips.get((wid, e["entry_time"]), "tidak_tercatat")})
                continue
            used.add(twin["id"])
            matched += 1
            pret = _paper_ret_pct(twin)
            if (eng_closed and twin["status"] == "closed" and twin.get("exit_time")
                    and to_epoch(twin["exit_time"]) <= until and pret is not None and e.get("pnl_pct") is not None):
                diffs.append(abs(pret - float(e["pnl_pct"])))
    extra = sum(1 for p in ctx.positions if p["source"] == "paper_auto" and p["id"] not in used
                and to_epoch(p["entry_time"]) < until)
    coverage = matched / expected if expected else None
    median_diff = statistics.median(diffs) if diffs else None
    return {"expected": expected, "matched": matched, "coverage": coverage, "closed_pairs": len(diffs),
            "median_abs_diff_pp": median_diff, "engine_closed": len(eng_roe),
            "engine_pf": rules.profit_factor(eng_roe), "extra_paper": extra, "missed": missed[-50:],
            "coverage_ok": coverage is not None and coverage >= rules.FIDELITY_COVERAGE_MIN,
            "diff_ok": median_diff is not None and median_diff <= rules.FIDELITY_MAX_MEDIAN_ABS_DIFF_PP}


# ── checkpoints ───────────────────────────────────────────────────────────

def _points(ctx: _Ctx) -> list[dict]:
    return [{"id": t["id"], "symbol": t["symbol"], "entry_s": to_epoch(t["entry_time"]),
             "exit_s": to_epoch(t["exit_time"]), "pnl": float(t["pnl"] or 0.0)}
            for t in ctx.auto if t.get("exit_time") and t.get("entry_time") and to_epoch(t["exit_time"]) <= ctx.now]


def _dd_until(ctx: _Ctx, until_s: float) -> Optional[float]:
    curve = (ctx.stats or {}).get("curve") or []
    return astats.max_drawdown_pct([p["equity"] for p in curve if p["t"] <= until_s])


def _num(v):
    """JSON-safe number: inf (PF without a losing trade) -> None + flag elsewhere."""
    return None if v is None or v == float("inf") else v


def _public_fid(fid: dict, with_missed: bool = False) -> dict:
    out = {k: v for k, v in fid.items() if k != "missed"}
    out["engine_pf_infinite"] = fid["engine_pf"] == float("inf")
    out["engine_pf"] = _num(fid["engine_pf"])
    if with_missed:
        out["missed"] = fid["missed"]
    return out


def judge(ctx: _Ctx, checkpoint: int, at_s: float) -> dict:
    """Pre-registered outcome of one checkpoint, using only trades closed before at_s."""
    pts = [p for p in _points(ctx) if p["exit_s"] < at_s]
    pf = rules.profit_factor([p["pnl"] for p in pts])
    dd = _dd_until(ctx, at_s)
    limit = rules.dd_limit_pct((ctx.basket.get("expect") or {}).get("max_dd_pct"))
    fid = fidelity(ctx, at_s)
    pf_dec = rules.pf_decision(pf, checkpoint)
    eng_dec = rules.pf_decision(fid["engine_pf"], checkpoint)
    same = pf_dec is not None and pf_dec == eng_dec
    dd_ok = None if (limit is None or dd is None) else dd >= limit
    reasons = []
    if not fid["coverage_ok"]:
        reasons.append("cakupan")
    if not fid["diff_ok"]:
        reasons.append("selisih_hasil")
    if not same:
        reasons.append("keputusan_beda")
    if limit is None:
        reasons.append("acuan_dd_tidak_ada")
    if reasons:
        verdict = rules.TIDAK_SAH
    elif pf_dec == rules.GAGAL or dd_ok is False:
        verdict = rules.GAGAL
    elif pf_dec == rules.LULUS and dd_ok:
        verdict = rules.LULUS
    else:
        verdict = rules.LANJUT if checkpoint == 1 else rules.GAGAL
    return {"checkpoint": checkpoint, "at": iso(at_s), "trades": len(pts), "pf": _num(pf), "pf_infinite": pf == float("inf"),
            "pf_decision": pf_dec, "engine_pf": _num(fid["engine_pf"]), "engine_decision": eng_dec,
            "dd_pct": dd, "dd_limit_pct": limit, "dd_ok": dd_ok, "fidelity": _public_fid(fid),
            "invalid_reasons": reasons, "verdict": verdict}


def _kill_from_curve(ctx: _Ctx) -> Optional[dict]:
    """First point where equity sat >= kill_dd_pct below its running peak (the kill switch rule
    holds at any time, also when no new entry came to trip it in sizing.entry_plan)."""
    limit = -float((ctx.basket.get("sizing") or {}).get("kill_dd_pct") or rules.KILL_DD_PCT)
    peak = None
    for p in (ctx.stats or {}).get("curve") or []:
        v = p["equity"]
        peak = v if peak is None or v > peak else peak
        if peak and (v / peak - 1.0) * 100.0 <= limit:
            return {"at": iso(p["t"]), "dd_pct": (v / peak - 1.0) * 100.0, "limit_pct": limit, "equity": v,
                    "peak": peak, "source": "kurva"}
    return None


def evaluation(ctx: _Ctx) -> dict:
    now, start = ctx.now, ctx.start_s
    pts = _points(ctx)
    deadline = start + rules.DEADLINE_DAYS * rules.DAY_S
    kill_ev = next((e for e in reversed(ctx.events) if e["kind"] == "kill"), None)
    out: dict = {"status": rules.BELUM, "deadline": iso(deadline), "kill": None, "checkpoints": [],
                 "next": None}
    kill = ({"at": kill_ev["created_at"], **(kill_ev.get("detail") or {}), "source": "entry"}
            if kill_ev is not None else _kill_from_curve(ctx))
    if kill is not None:
        out["kill"] = kill
    cp1 = rules.checkpoint_due(pts, start, 1)
    if cp1 is None or cp1["met_s"] > deadline:
        out["status"] = rules.TIDAK_CUKUP_DATA if now > deadline else rules.BELUM
        out["next"] = {"checkpoint": 1, "due": None, "earliest": iso(rules.next_monday(start + 28 * rules.DAY_S))}
    elif now < cp1["due_s"]:
        out["next"] = {"checkpoint": 1, "due": iso(cp1["due_s"]), "earliest": iso(cp1["due_s"])}
    else:
        r1 = judge(ctx, 1, cp1["due_s"])
        out["checkpoints"].append(r1)
        out["status"] = r1["verdict"]
        if r1["verdict"] == rules.LANJUT:
            cp2 = rules.checkpoint_due(pts, start, 2)
            if cp2 is None or now < cp2["due_s"]:
                out["next"] = {"checkpoint": 2, "due": iso(cp2["due_s"]) if cp2 else None,
                               "earliest": iso(rules.next_monday(start + 56 * rules.DAY_S))}
            else:
                r2 = judge(ctx, 2, cp2["due_s"])
                out["checkpoints"].append(r2)
                out["status"] = r2["verdict"]
    if kill is not None:
        out["status"] = rules.GAGAL          # the kill switch is a failure at any time (§7)
        out["next"] = None
    return out


# ── per coin ──────────────────────────────────────────────────────────────

def coins(ctx: _Ctx) -> list[dict]:
    b = ctx.basket
    n_skip: dict[int, int] = {}
    for e in ctx.events:
        if e["kind"] == "skip" and e.get("watch_id") is not None:
            n_skip[e["watch_id"]] = n_skip.get(e["watch_id"], 0) + 1
    out = []
    for m in ctx.members:
        wid = m["watch_id"]
        trades = [t for t in ctx.auto if t["watch_id"] == wid]
        open_p = next((p for p in ctx.positions if p["watch_id"] == wid and p["status"] == "open"
                       and p["source"] == "paper_auto"), None)
        st = ctx.states.get(wid)
        w = ctx.watches.get(wid)
        pos = loads(st["position_json"]) if st else None
        strat = None
        if pos and pos.get("entry_time"):
            before = to_epoch(pos["entry_time"]) + ctx.tf_s <= ctx.start_s
            strat = {"side": pos.get("side"), "entry_price": pos.get("entry_price"), "entry_time": pos["entry_time"],
                     "opened_before_paper": before, "mirrored": open_p is not None}
        if w is None:
            status = "watch_hilang"
        elif not (w["active"] and w["autopaper_enabled"] and w["autopaper_account_id"] == b["account_id"]):
            status = "paper_mati"
        elif st and st["error"]:
            status = "error"
        elif open_p is not None:
            status = "posisi_terbuka"
        elif strat and strat["opened_before_paper"]:
            status = "menunggu_sinyal_baru"   # the strategy holds a position from before paper started
        elif st is None:
            status = "belum_dihitung"
        else:
            status = "menunggu_sinyal"
        pnl = sum(float(t["pnl"] or 0.0) for t in trades)
        out.append({
            "symbol": m["symbol"], "coin": coin(m["symbol"]), "watch_id": wid, "status": status,
            "trades": len(trades), "wins": sum(1 for t in trades if (t["pnl"] or 0) > 0), "pnl": pnl,
            "last_exit": trades[-1]["exit_time"] if trades else None,
            "open_position": arena._open_out(open_p) if open_p else None,
            "strategy_position": strat, "skips": n_skip.get(wid, 0),
            "last_eval_at": st["computed_at"] if st else None, "last_bar": st["last_bar"] if st else None,
            "error": st["error"] if st else None,
        })
    return out


# ── assembly ──────────────────────────────────────────────────────────────

def _expect_bt(expect: Optional[dict]) -> Optional[dict]:
    """The frozen reference numbers in the shape arena.report.drift() reads."""
    if not expect or not expect.get("trades"):
        return None
    return {"source": "basket_expectation", "source_note": expect.get("source_note") or rules.PREREG_DOC,
            "contaminated": bool(expect.get("contaminated")), "start": expect.get("start"), "end": expect.get("end"),
            "months": expect.get("months"), "trades": expect.get("trades"),
            "trades_per_month": expect.get("trades_per_month"), "win_rate_pct": expect.get("win_rate_pct"),
            "max_dd_pct": expect.get("max_dd_pct"), "mc_dd_p95_pct": expect.get("mc_dd_p95_pct"),
            "net_return_pct": expect.get("net_return_pct"), "profit_factor": expect.get("profit_factor"),
            "sharpe": expect.get("sharpe"), "per_trade_ret_pct": expect.get("per_trade_ret_pct"),
            "sizing_rule": expect.get("sizing_rule"), "failed_checks": None}


def _row(conn, basket: dict, now: float, detail: bool) -> dict:
    ctx = _Ctx(conn, basket, now)
    st = dict(ctx.stats or {})
    curve = st.pop("curve", [])
    st.pop("trade_rets_pct", None)
    pts = _points(ctx)
    entry_days = {int(p["entry_s"] // rules.DAY_S) for p in pts}
    days = max(0.0, (now - ctx.start_s) / rules.DAY_S)
    need = rules.CHECKPOINTS[1]
    coin_rows = coins(ctx)
    bt = _expect_bt(basket.get("expect"))
    fid = fidelity(ctx)
    waiting = [c["coin"] for c in coin_rows if c["status"] == "menunggu_sinyal_baru"]
    row = {
        "basket": {"id": basket["id"], "name": basket["name"], "label": basket["label"], "title": basket["title"],
                   "template_id": basket["template_id"],
                   "template_label": TEMPLATE_LABEL.get(basket["template_id"], basket["template_id"]),
                   "timeframe": basket["timeframe"], "n_coins": len(basket["symbols"]),
                   "coins": [coin(s) for s in basket["symbols"]], "sizing": basket["sizing"],
                   "active": basket["active"], "created_at": basket["created_at"], "prereg": basket.get("prereg")},
        "account": ({"id": ctx.account["id"], "name": ctx.account["name"],
                     "starting_balance": ctx.account["starting_balance"], "created_at": ctx.account["created_at"]}
                    if ctx.account else None),
        "stats": st or None,
        "progress": {"n": len(pts), "of": rules.REVIEW_MIN_TRADES},
        "gate": {"trades": len(pts), "need_trades": need["min_trades"],
                 "coins": len({p["symbol"] for p in pts}), "need_coins": need["min_coins"],
                 "entry_days": len(entry_days), "need_entry_days": need["min_entry_days"],
                 "days": days, "need_days": need["min_days"]},
        "evaluation": evaluation(ctx),
        "coins": coin_rows,
        "waiting": {"n": len(waiting), "coins": waiting},
        "open_positions": sum(1 for c in coin_rows if c["open_position"]),
        "fidelity": _public_fid(fid, with_missed=detail),
        "expect": basket.get("expect"),
        "drift": arena.drift(bt, ctx.stats) if (bt and ctx.stats) else None,
        "last_action": arena.last_action(
            [{"exit_time": j["exit_time"], "side": j["side"], "exit_price": j["exit_price"],
              "exit_reason": j["exit_reason"], "pnl": j["pnl"], "source": j["source"]} for j in ctx.journal],
            ctx.positions),
        "spark": [p["equity"] for p in curve[-SPARK_POINTS:]],
    }
    if detail:
        row["curve"] = [{"t": iso(p["t"]), "equity": p["equity"]} for p in curve]
        row["trades"] = [{k: t[k] for k in ("id", "symbol", "side", "entry_time", "entry_price", "exit_time",
                                             "exit_price", "qty", "pnl", "r_multiple", "exit_reason")}
                         for t in reversed(ctx.auto[-100:])]
        row["events"] = ctx.events[:100]
        row["rules"] = _rules_out()
    return row


def build(conn, now: Optional[float] = None) -> dict:
    now = now or time.time()
    return {"generated_at": iso(now), "rules": _rules_out(),
            "rows": [_row(conn, b, now, detail=False) for b in store.list_baskets(conn)]}


def detail(conn, basket_id: int, now: Optional[float] = None) -> Optional[dict]:
    b = store.get(conn, basket_id)
    if b is None:
        return None
    now = now or time.time()
    return {"generated_at": iso(now), **_row(conn, b, now, detail=True)}
