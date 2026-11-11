"""universe_refresh job (engine child), queued by the scheduler after every 4H close:

  1. refresh the 4H parquet cache (+ funding) for every coin in the universe
  2. recompute the Koin Terkuat table -> artifacts/strength.json
  3. for every active Universal watch: compute target weights on the just-closed bar;
     on a rebalance boundary, move the paper account to the targets (paper_auto orders,
     journal entries for every realised leg) and queue a Telegram alert

Paper only — prices come from public market data, nothing is sent to an exchange.
"""
from __future__ import annotations

import logging
import os
from typing import Callable, Optional

import numpy as np

from .. import paper
from ..db import dumps, loads, utcnow
from . import alerts
from . import backtest as B
from . import params as P
from . import strategy as S
from . import strength as ST
from .runner import load_panel, universe_symbols

log = logging.getLogger("lab.universal")


def ref_of(watch_id: int) -> str:
    return f"universal:{watch_id}"


# ── paper execution ──────────────────────────────────────────────────────

def _open_positions(conn, account_id: int, ref: str) -> list[dict]:
    return [dict(r) for r in conn.execute(
        "SELECT * FROM paper_positions WHERE account_id=? AND status='open' AND source='paper_auto' "
        "AND strategy_ref=? ORDER BY id", (account_id, ref))]


def account_equity(conn, account_id: int, prices: dict) -> float:
    a = paper.get_account(conn, account_id)
    eq = a["balance"]
    for p in conn.execute("SELECT * FROM paper_positions WHERE account_id=? AND status='open'", (account_id,)):
        p = dict(p)
        px = prices.get(p["symbol"]) or p["mark_price"] or p["entry_price"]
        eq += paper.unrealized(p, px) - p["fees"] - p["funding"]
    return float(eq)


def _insert_position(conn, *, account_id, symbol, side, qty, fill, ref, note, when) -> int:
    fee = qty * fill * paper.COMMISSION_PCT / 100.0
    cur = conn.execute(
        "INSERT INTO paper_positions (account_id, symbol, side, qty, entry_price, entry_time, sl, tp, fees, funding, "
        "risk_amount, source, watch_id, note, status, mark_price, mark_time, strategy_ref, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?, NULL, NULL, ?, 0, NULL, 'paper_auto', NULL, ?, 'open', ?, ?, ?, ?)",
        (account_id, symbol, side, qty, fill, when, fee, note, fill, when, ref, utcnow()))
    return int(cur.lastrowid)


def _reduce(conn, pos: dict, qty: float, price: float, slippage_pct: float, when: str, reason: str) -> dict:
    """Partial close of `qty` (< pos qty): realise PnL on that slice and journal it."""
    frac = qty / pos["qty"]
    exit_px = paper._slip(price, pos["side"], "exit", slippage_pct)
    d = 1.0 if pos["side"] == "long" else -1.0
    gross = (exit_px - pos["entry_price"]) * qty * d
    fee_part = pos["fees"] * frac
    fund_part = pos["funding"] * frac
    exit_fee = qty * exit_px * paper.COMMISSION_PCT / 100.0
    pnl = gross - fee_part - exit_fee - fund_part
    conn.execute("UPDATE paper_positions SET qty=qty-?, fees=fees-?, funding=funding-? WHERE id=?",
                 (qty, fee_part, fund_part, pos["id"]))
    conn.execute("UPDATE paper_accounts SET balance=balance+?, realized_pnl=realized_pnl+? WHERE id=?",
                 (pnl, pnl, pos["account_id"]))
    conn.execute(
        "INSERT INTO journal_entries (account_id, source, watch_id, symbol, side, entry_time, entry_price, exit_time, "
        "exit_price, qty, fees, funding, sl, tp, risk_amount, pnl, r_multiple, exit_reason, notes, tags, "
        "strategy_ref, created_at) VALUES (?, 'paper_auto', NULL, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, NULL, NULL, ?, "
        "NULL, ?, ?, ?, ?, ?)",
        (pos["account_id"], pos["symbol"], pos["side"], pos["entry_time"], pos["entry_price"], when, exit_px, qty,
         fee_part + exit_fee, fund_part, pnl, reason, pos["note"], dumps(["universal", "partial"]),
         pos["strategy_ref"], utcnow()))
    return {"fill": exit_px, "pnl": pnl}


def rebalance_paper(conn, watch: dict, targets: dict, price_fn: Callable[[str], float], p: dict,
                    costs: dict, when: Optional[str] = None) -> tuple[list[dict], float]:
    """Move the watch's paper positions to `targets` ({symbol: weight}, signed fraction of equity).

    Same min-trade band as the backtest. Returns (orders, equity_before)."""
    acct_id = watch["account_id"]
    acct = paper.get_account(conn, acct_id)
    ref = ref_of(watch["id"])
    when = when or utcnow()
    slip = float(costs.get("slippage_pct", paper.DEFAULT_SLIPPAGE_PCT))
    min_trade = float(p.get("min_trade_pct", 0.0)) / 100.0
    held = {r["symbol"]: r for r in _open_positions(conn, acct_id, ref)}
    syms = sorted(set(held) | {s for s, w in targets.items() if w != 0})
    prices = {s: float(price_fn(s)) for s in syms}
    equity = account_equity(conn, acct_id, prices)
    if equity <= 0:
        raise paper.PaperError("paper account equity <= 0")
    tg = {s: float(targets.get(s, 0.0)) for s in syms}
    gross = sum(abs(v) for v in tg.values())
    if gross > acct["leverage_max"]:
        tg = {s: v * acct["leverage_max"] / gross for s, v in tg.items()}
    orders: list[dict] = []
    note = f"universal watch {watch['id']}"
    # closes/reductions first so freed margin is available for opens
    plan = []
    for s in syms:
        px = prices[s]
        pos = held.get(s)
        cur_q = 0.0 if pos is None else pos["qty"] * (1 if pos["side"] == "long" else -1)
        cur_w = cur_q * px / equity
        tw = tg[s]
        if pos is not None and (tw == 0 or np.sign(tw) != np.sign(cur_w)):
            plan.append((0, s, "close", pos, cur_w, tw))
            if tw != 0 and abs(tw) >= min_trade:
                plan.append((2, s, "open", None, 0.0, tw))
        elif pos is not None:
            if abs(tw - cur_w) < min_trade:
                continue
            plan.append((0 if abs(tw) < abs(cur_w) else 1, s, "reduce" if abs(tw) < abs(cur_w) else "add",
                         pos, cur_w, tw))
        elif tw != 0 and abs(tw) >= min_trade:
            plan.append((2, s, "open", None, 0.0, tw))
    plan.sort(key=lambda x: (x[0], x[1]))
    for _, s, action, pos, cur_w, tw in plan:
        px = prices[s]
        side = "long" if (tw if action in ("open", "add") else cur_w) > 0 else "short"
        if action == "close":
            out = paper.close_position(conn, pos["id"], px, "universal_rebalance", when=when, slippage_pct=slip)
            conn.execute("UPDATE journal_entries SET strategy_ref=?, tags=? WHERE id=?",
                         (ref, dumps(["universal"]), out["journal_id"]))
            orders.append({"symbol": s, "action": "close", "side": pos["side"], "qty": pos["qty"],
                           "price": out["exit_price"], "weight_from": cur_w * 100, "weight_to": 0.0,
                           "pnl": out["pnl"]})
        elif action == "reduce":
            dq = (abs(cur_w) - abs(tw)) * equity / px
            r = _reduce(conn, pos, dq, px, slip, when, "universal_rebalance")
            orders.append({"symbol": s, "action": "reduce", "side": pos["side"], "qty": dq, "price": r["fill"],
                           "weight_from": cur_w * 100, "weight_to": tw * 100, "pnl": r["pnl"]})
        elif action == "add":
            fill = paper._slip(px, pos["side"], "entry", slip)
            dq = (abs(tw) - abs(cur_w)) * equity / px
            new_q = pos["qty"] + dq
            avg = (pos["qty"] * pos["entry_price"] + dq * fill) / new_q
            conn.execute("UPDATE paper_positions SET qty=?, entry_price=?, fees=fees+? WHERE id=?",
                         (new_q, avg, dq * fill * paper.COMMISSION_PCT / 100.0, pos["id"]))
            orders.append({"symbol": s, "action": "add", "side": pos["side"], "qty": dq, "price": fill,
                           "weight_from": cur_w * 100, "weight_to": tw * 100})
        else:  # open
            fill = paper._slip(px, side, "entry", slip)
            q = abs(tw) * equity / px
            _insert_position(conn, account_id=acct_id, symbol=s, side=side, qty=q, fill=fill, ref=ref, note=note,
                             when=when)
            orders.append({"symbol": s, "action": "open", "side": side, "qty": q, "price": fill,
                           "weight_from": 0.0, "weight_to": tw * 100})
    conn.commit()
    return orders, equity


# ── watch evaluation ─────────────────────────────────────────────────────

def subset_panel(panel: S.Panel, symbols: list[str]) -> S.Panel:
    idx = [panel.symbols.index(s) for s in symbols if s in panel.symbols]
    if not idx:
        raise ValueError("none of the watch's symbols have data")
    return S.subset_panel(panel, idx)


def _targets_list(panel: S.Panel, feat: S.Features, t: int, w: np.ndarray) -> list[dict]:
    return [{"symbol": panel.symbols[i], "weight_pct": float(w[i] * 100.0), "score": B._f(feat.score[t, i]),
             "vol_ann_pct": B._f(feat.vol_ann[t, i] * 100.0)}
            for i in np.argsort(-np.abs(w)) if w[i] != 0]


STALE_BARS = 2


def evaluate_watch(conn, watch: dict, panel: S.Panel, price_fn: Optional[Callable[[str], float]] = None,
                   now=None) -> dict:
    import pandas as pd
    p = P.validate_params(loads(watch["params_json"], {}))
    costs = loads(watch["costs_json"], {}) or {}
    wp = subset_panel(panel, p["symbols"]) if p["symbols"] else panel
    wp = S.slice_panel(wp, S.last_complete_index(wp) + 1)
    feat = S.compute_features(wp, p)
    t = len(wp.ts) - 1
    now_ts = pd.Timestamp(now) if now is not None else pd.Timestamp.now(tz="UTC")
    if wp.ts[t] + pd.Timedelta(hours=4 * (1 + STALE_BARS)) < now_ts:
        raise RuntimeError(f"stale data: last complete bar {B.iso(wp.ts[t])}; refusing to rebalance")
    w = S.target_weights(feat, wp, t, p)
    mask = S.rebalance_mask(wp, p["rebalance"])
    boundary = int(np.flatnonzero(mask[: t + 1])[-1]) if mask[: t + 1].any() else t
    boundary_iso = B.iso(wp.ts[boundary])
    step_h = 4 if p["rebalance"] == "4h" else 24
    next_reb = B.iso(wp.ts[boundary] + pd.Timedelta(hours=4 + step_h))
    targets = _targets_list(wp, feat, t, w)
    order = np.argsort(-np.nan_to_num(feat.score[t], nan=-1e9))
    ranks = [{"symbol": wp.symbols[i], "score": B._f(feat.score[t, i]), "eligible": bool(feat.eligible[t, i]),
              "trend": "up" if feat.up[t, i] else ("down" if feat.down[t, i] else None)} for i in order[:10]]
    bar_close = B.iso(wp.ts[t] + pd.Timedelta(hours=4))
    conn.execute(
        "INSERT INTO universal_state (watch_id, computed_at, last_bar, targets_json, ranks_json, next_rebalance, error) "
        "VALUES (?, ?, ?, ?, ?, ?, NULL) ON CONFLICT(watch_id) DO UPDATE SET computed_at=excluded.computed_at, "
        "last_bar=excluded.last_bar, targets_json=excluded.targets_json, ranks_json=excluded.ranks_json, "
        "next_rebalance=excluded.next_rebalance, error=NULL",
        (watch["id"], utcnow(), B.iso(wp.ts[t]), dumps(targets), dumps(ranks), next_reb))
    conn.commit()
    due = watch["last_rebalance_bar"] is None or watch["last_rebalance_bar"] < boundary_iso
    result = {"due": due, "targets": targets, "orders": [], "bar_close": bar_close}
    if not due:
        return result
    orders, equity = [], None
    autopaper = bool(watch["autopaper_enabled"] and watch["account_id"])
    if autopaper:
        if price_fn is None:
            from .. import market
            price_fn = market.last_price
        tmap = {x["symbol"]: x["weight_pct"] / 100.0 for x in targets}
        orders, equity = rebalance_paper(conn, watch, tmap, price_fn, p, costs)
    prev = conn.execute("SELECT targets_json FROM universal_rebalances WHERE watch_id=? ORDER BY id DESC LIMIT 1",
                        (watch["id"],)).fetchone()
    prev_syms = sorted(x["symbol"] for x in (loads(prev["targets_json"], []) if prev else []))
    changed = prev is None or prev_syms != sorted(x["symbol"] for x in targets)
    conn.execute("INSERT INTO universal_rebalances (watch_id, bar, targets_json, orders_json, equity, note, created_at) "
                 "VALUES (?, ?, ?, ?, ?, ?, ?)",
                 (watch["id"], bar_close, dumps(targets), dumps(orders), equity,
                  None if autopaper else "signal only (autopaper off)", utcnow()))
    conn.execute("UPDATE universal_watches SET last_rebalance_bar=? WHERE id=?", (boundary_iso, watch["id"]))
    conn.commit()
    if watch["telegram_enabled"] and (orders or changed):
        alerts.enqueue(conn, ref_of(watch["id"]),
                       alerts.rebalance_text(watch, bar_close, targets, orders, equity, autopaper))
    result.update(orders=orders, equity=equity, alerted=bool(watch["telegram_enabled"] and (orders or changed)))
    return result


def _active_watches(conn) -> list[dict]:
    return [dict(r) for r in conn.execute("SELECT * FROM universal_watches WHERE active=1 ORDER BY id")]


def execute_refresh(conn, job: dict, price_fn: Optional[Callable[[str], float]] = None) -> dict:
    offline = os.environ.get("LAB_DATA_OFFLINE") == "1"
    watches = _active_watches(conn)
    syms = set(universe_symbols({}))
    for w in watches:
        syms |= set(P.validate_params(loads(w["params_json"], {}))["symbols"])
    syms_l = sorted(syms)
    from ..queue import set_progress
    panel = load_panel(syms_l, funding=True, refresh=not offline, offline=offline,
                       progress=lambda st, d, t: set_progress(conn, job["id"], {"stage": st, "done": d, "total": t}))
    out = {"symbols": len(syms_l), "watches": {}}
    try:
        st = ST.compute(S.slice_panel(panel, S.last_complete_index(panel) + 1))
        ST.save(st)
        conn.execute("INSERT INTO lab_kv (key, value) VALUES ('strength_computed_at', ?) "
                     "ON CONFLICT(key) DO UPDATE SET value=excluded.value", (st["computed_at"],))
        conn.commit()
        out["strength_last_bar"] = st["last_bar"]
    except Exception as e:  # noqa: BLE001
        log.exception("strength computation failed")
        out["strength_error"] = f"{type(e).__name__}: {e}"
    for w in watches:
        try:
            r = evaluate_watch(conn, w, panel, price_fn)
            out["watches"][w["id"]] = {"due": r["due"], "orders": len(r["orders"])}
        except Exception as e:  # noqa: BLE001
            log.exception("universal watch %s failed", w["id"])
            conn.execute(
                "INSERT INTO universal_state (watch_id, computed_at, error) VALUES (?, ?, ?) ON CONFLICT(watch_id) "
                "DO UPDATE SET computed_at=excluded.computed_at, error=excluded.error",
                (w["id"], utcnow(), f"{type(e).__name__}: {e}"))
            conn.commit()
            out["watches"][w["id"]] = {"error": f"{type(e).__name__}"}
    conn.execute("INSERT INTO lab_kv (key, value) VALUES ('universe_refresh_result', ?) "
                 "ON CONFLICT(key) DO UPDATE SET value=excluded.value", (dumps({**out, "at": utcnow()}),))
    conn.commit()
    if "strength_error" in out and not watches:
        raise RuntimeError(out["strength_error"])
    return out

