"""Watch evaluation job (engine child): recompute a strategy on recent closed
bars, store watch_state, and (optionally) mirror signals onto a paper account.

The evaluation window is anchored at the watch's creation time minus
HISTORY_BARS (plus warm-up), so the path-dependent strategy state is stable
from one evaluation to the next. No real orders, no notifications.
"""
from __future__ import annotations

import logging
from typing import Optional

from . import db as labdb
from . import paper
from .db import dumps, loads, utcnow

log = logging.getLogger("lab.watch")
HISTORY_BARS = 1000


def _signal(position: Optional[dict], trades: list[dict]) -> Optional[dict]:
    last_trade = trades[-1] if trades else None
    if position and (last_trade is None or position["entry_time"] >= (last_trade["exit_time"] or "")):
        return {"time": position["entry_time"], "action": "open", "side": position["side"],
                "price": position["entry_price"]}
    if last_trade:
        return {"time": last_trade["exit_time"], "action": "close", "side": last_trade["side"],
                "price": last_trade["exit_price"], "reason": last_trade["exit_reason"]}
    return None


def evaluate(watch: dict, offline: bool = False) -> dict:
    """Run the strategy on the watch's anchored window. Returns the state dict."""
    import pandas as pd
    from . import data_cache as dc
    from . import engine_adapter as ea
    params, costs, tf = loads(watch["params_json"], {}), loads(watch["costs_json"], {}), watch["timeframe"]
    ohlcv, fund = dc.ensure(watch["symbol"], tf, funding=bool(costs.get("funding", True)), offline=offline)
    cfg, ecfg = ea.build_configs(params, tf, costs)
    anchor = pd.Timestamp(watch["created_at"].replace("Z", "")).tz_localize("UTC") \
        - pd.Timedelta(seconds=ea.TF_SECONDS[tf] * HISTORY_BARS)
    df, _, _, _ = ea.prepare_frame(ohlcv, fund, tf, anchor.strftime("%Y-%m-%d %H:%M:%S"), None,
                                   ecfg.warmup_period, bool(costs.get("funding", True)))
    res, _ = ea.run(df, cfg, ecfg)
    trades = ea.trades_out(res)
    op = res.open_position
    position = None
    if op:
        position = {"side": op["direction"], "entry_price": op["entry_price"],
                    "entry_time": ea._iso(op["entry_timestamp"]), "sl": op["sl"], "tp": op["tp"]}
        if ea.T.is_sized(ea.T.validate_params(params)):
            # research sizing (vol target, ...): the paper mirror copies the engine's notional / equity
            # at entry. Closed equity while open = equity after the last closed trade.
            eq = res.trades[-1].equity_at_exit if res.trades else float(cfg.initial_capital)
            if eq > 0 and op.get("position_value"):
                position["notional_mult"] = float(op["position_value"]) / float(eq)
    last_bar = ea._iso(df["timestamp"].iloc[-1])
    return {"last_bar": last_bar, "position": position, "recent_trades": trades[-50:],
            "last_signal": _signal(position, trades)}


def _autopaper(conn, watch: dict, prev_signal: Optional[dict], state: dict) -> None:
    acct = watch["autopaper_account_id"]
    if not (watch["autopaper_enabled"] and acct):
        return
    from . import market
    open_auto = conn.execute(
        "SELECT * FROM paper_positions WHERE watch_id=? AND account_id=? AND status='open' AND source='paper_auto'",
        (watch["id"], acct)).fetchone()
    sig, pos = state["last_signal"], state["position"]
    fresh = sig is not None and sig != prev_signal and sig["time"] == state["last_bar"]
    if open_auto is not None and pos is None:
        # strategy is flat -> close the mirror (signal or stop handled by the engine)
        px = market.last_price(watch["symbol"])
        paper.close_position(conn, open_auto["id"], px,
                             f"strategy_exit:{(sig or {}).get('reason', 'flat')}")
        return
    if open_auto is not None and pos is not None:
        if pos["side"] != open_auto["side"]:
            px = market.last_price(watch["symbol"])
            paper.close_position(conn, open_auto["id"], px, "strategy_reverse")
        else:
            paper.update_stops(conn, open_auto["id"], pos["sl"], pos["tp"])  # follow trailing stop
            return
    if pos is not None and fresh and sig["action"] == "open" and pos["sl"]:
        px = market.last_price(watch["symbol"])
        qty = None
        if pos.get("notional_mult"):  # engine-sized preset: same notional multiple (capped by leverage_max)
            qty = paper.get_account(conn, acct)["balance"] * float(pos["notional_mult"]) / float(px)
        try:
            paper.open_position(conn, account_id=acct, symbol=watch["symbol"], side=pos["side"], price=px,
                                sl=pos["sl"], tp=pos["tp"], qty=qty, watch_id=watch["id"], source="paper_auto",
                                note=f"auto from watch {watch['id']}")
        except paper.PaperError as e:
            log.warning("autopaper open skipped for watch %s: %s", watch["id"], e)


def _evaluate_one(conn, w: dict, offline: bool) -> None:
    prev = conn.execute("SELECT * FROM watch_state WHERE watch_id=?", (w["id"],)).fetchone()
    prev_signal = loads(prev["last_signal_json"]) if prev else None
    try:
        state = evaluate(w, offline=offline)
    except Exception as e:
        conn.execute(
            "INSERT INTO watch_state (watch_id, computed_at, error) VALUES (?, ?, ?) "
            "ON CONFLICT(watch_id) DO UPDATE SET computed_at=excluded.computed_at, error=excluded.error",
            (w["id"], utcnow(), f"{type(e).__name__}: {e}"))
        conn.commit()
        raise
    conn.execute(
        "INSERT INTO watch_state (watch_id, computed_at, last_bar, position_json, recent_trades_json, "
        "last_signal_json, error) VALUES (?, ?, ?, ?, ?, ?, NULL) ON CONFLICT(watch_id) DO UPDATE SET "
        "computed_at=excluded.computed_at, last_bar=excluded.last_bar, position_json=excluded.position_json, "
        "recent_trades_json=excluded.recent_trades_json, last_signal_json=excluded.last_signal_json, error=NULL",
        (w["id"], utcnow(), state["last_bar"], dumps(state["position"]), dumps(state["recent_trades"]),
         dumps(state["last_signal"])))
    conn.commit()
    _autopaper(conn, w, prev_signal, labdb.loads(dumps(state)))


def execute_watch(conn, job: dict) -> None:
    """One watch (ref_id) or a batch (payload.watch_ids, same timeframe/bar).

    A batch runs in one engine child: watches are grouped by symbol so each
    symbol's cache is refreshed once (later watches find it fresh, no network),
    and the process-wide ccxt instance rate-limits every tail fetch. One failing
    watch records its error in watch_state and does not stop the others; the
    job errors only when every watch in it failed."""
    import os
    payload = loads(job.get("payload_json"), {}) or {}
    ids = [int(i) for i in (payload.get("watch_ids") or [job["ref_id"]])]
    marks = ",".join("?" * len(ids))
    rows = [dict(r) for r in conn.execute(f"SELECT * FROM watches WHERE id IN ({marks})", ids)]
    rows.sort(key=lambda w: (w["symbol"], w["timeframe"], w["id"]))
    offline = os.environ.get("LAB_DATA_OFFLINE") == "1"
    errors = []
    for w in rows:  # deleted watches are simply absent
        try:
            _evaluate_one(conn, w, offline)
        except Exception as e:  # noqa: BLE001
            log.warning("watch %s evaluation failed: %s", w["id"], e)
            errors.append(e)
    if errors and len(errors) == len(rows):
        raise errors[0]
