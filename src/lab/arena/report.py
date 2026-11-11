"""Arena Paper report: leaderboard + drift check + equity curves. SQL over lab.db only.

A "paper preset" is a preset with a linked watch (lab_preset_links kind='watch')
whose auto-paper account is set. Every number comes from the paper tables; the
backtest side comes from the preset's stored holdout metrics (``holdout_json``).
The only exception is the read-only live reference 4H-ETH-Basic, which was seeded
from the template defaults and so has no stored holdout: its expectations are the
committed research run in docs/research/eth-v2/holdout-results.json (same params,
same 2x mirror sizing), and the row says so (``backtest.source = research_doc``).

Drift method (see ``drift``): per check a two-sided ~95 % acceptance range under the
backtest number, exact for counts (Poisson / binomial), t interval for the mean
per-trade return. A check reports "belum_cukup" below its minimum sample instead
of guessing. Nothing here writes to lab.db.
"""
from __future__ import annotations

import re
import time
from typing import Any, Optional

from ..db import loads
from ..ledger.store import iso, to_epoch
from . import stats
from .store import snapshots

REVIEW_MIN_TRADES = 30          # research decision rule: review after >= 30 paper trades per preset
MIN_TRADES_RATE = 10            # win rate / per-trade return need this many closed trades
MIN_EXPECTED_ENTRIES = 2.0      # trade frequency needs >= 2 expected entries before it says anything
MIN_SHARPE_DAYS = 30
DAYS_PER_MONTH = 30.4375
PAPER_SOURCES = ("paper_auto", "paper_manual")

# Live reference 4H-ETH-Basic: one Lab validate run, engine a259ceb, default params, 2x notional,
# costs 0.05 % + 0.05 % per side, funding on. Copied verbatim from
# docs/research/eth-v2/holdout-results.json results["4H-ETH-Basic"].holdout (+ monte_carlo.dd_p95).
LIVE_REFERENCE_BACKTEST = {
    "name": "4H-ETH-Basic",
    "net_return_pct": 18.788185729170024, "profit_factor": 1.032501052338789,
    "max_dd_pct": -73.80068747628185, "sharpe": 0.5182, "trades": 72,
    "win_rate_pct": 29.166666666666668, "mc_dd_p95_pct": -68.06530924941345,
    "start": "2025-07-06T04:00:00Z", "end": "2026-11-09T00:00:00Z", "contaminated": True,
    "source_note": "docs/research/eth-v2/holdout-results.json (preset referensi live tidak menyimpan holdout)",
}

FAMILY_LABEL = {"2x": "2× (bawaan)", "1x": "1×", "VT60": "VT60"}
_SUFFIX = re.compile(r"_(\d+(?:\.\d+)?x|VT\d+)$", re.IGNORECASE)

STATUS_SESUAI, STATUS_MENYIMPANG, STATUS_BELUM = "sesuai", "menyimpang", "belum_cukup"


# ── preset identity ───────────────────────────────────────────────────────

def coin(symbol: str) -> str:
    s = (symbol or "").upper()
    return s[:-4] if s.endswith("USDT") else s


def sizing_family(label: str, holdout: Optional[dict]) -> str:
    rule = str((holdout or {}).get("sizing_rule") or "")
    m = re.search(r"vol_target_(\d+)", rule)
    if m:
        return f"VT{m.group(1)}"
    m = re.search(r"fixed_(\d+(?:\.\d+)?)x", rule)
    if m:
        return f"{m.group(1)}x"
    m = _SUFFIX.search(label or "")
    if m:
        s = m.group(1)
        return s.upper() if s.upper().startswith("VT") else s.lower()
    return "2x"                     # the seed's mirror sizing: risk_pct 100, leverage_max 2


def base_label(label: str) -> str:
    return _SUFFIX.sub("", label or "")


# ── backtest expectations ─────────────────────────────────────────────────

def backtest_expectations(preset: dict) -> Optional[dict]:
    h = preset.get("holdout") or None
    source, note = "preset", "holdout_json preset (disimpan saat preset dibuat)"
    if not h and preset.get("live_reference") and preset.get("name") == LIVE_REFERENCE_BACKTEST["name"]:
        h, source, note = LIVE_REFERENCE_BACKTEST, "research_doc", LIVE_REFERENCE_BACKTEST["source_note"]
    if not h or not h.get("trades") or not h.get("start") or not h.get("end"):
        return None
    months = (to_epoch(h["end"]) - to_epoch(h["start"])) / 86400 / DAYS_PER_MONTH
    trades = int(h["trades"])
    net = h.get("net_return_pct")
    per_trade = None
    if isinstance(net, (int, float)) and net > -100 and trades:
        per_trade = ((1 + net / 100.0) ** (1.0 / trades) - 1) * 100.0
    return {
        "source": source, "source_note": note, "contaminated": bool(h.get("contaminated")),
        "start": h["start"], "end": h["end"], "months": months, "trades": trades,
        "trades_per_month": trades / months if months > 0 else None,
        "win_rate_pct": h.get("win_rate_pct"), "max_dd_pct": h.get("max_dd_pct"),
        "mc_dd_p95_pct": h.get("mc_dd_p95_pct"), "net_return_pct": net, "profit_factor": h.get("profit_factor"),
        "sharpe": h.get("sharpe"), "per_trade_ret_pct": per_trade, "sizing_rule": h.get("sizing_rule"),
        "failed_checks": h.get("failed_checks"),
    }


# ── paper side ────────────────────────────────────────────────────────────

def _paper_rows(conn, account_id: int) -> tuple[list[dict], list[dict]]:
    closed = [dict(r) for r in conn.execute(
        "SELECT id, source, side, entry_time, entry_price, exit_time, exit_price, pnl, r_multiple, exit_reason "
        f"FROM journal_entries WHERE account_id=? AND source IN ({','.join('?' * len(PAPER_SOURCES))}) "
        "ORDER BY exit_time, id", (account_id, *PAPER_SOURCES))]
    positions = [dict(r) for r in conn.execute(
        "SELECT * FROM paper_positions WHERE account_id=? ORDER BY entry_time, id", (account_id,))]
    return closed, positions


def _open_out(p: dict) -> dict:
    d = 1.0 if p["side"] == "long" else -1.0
    mark = p.get("mark_price")
    gross = (mark - p["entry_price"]) * p["qty"] * d if mark else None
    return {"id": p["id"], "side": p["side"], "entry_price": p["entry_price"], "entry_time": p["entry_time"],
            "qty": p["qty"], "sl": p["sl"], "tp": p["tp"], "mark_price": mark, "mark_time": p.get("mark_time"),
            "source": p["source"],
            "unrealized_pnl": None if gross is None else gross - (p["fees"] or 0) - (p["funding"] or 0)}


def _pct_pair(w: Optional[tuple[float, float]]) -> Optional[list[float]]:
    return [w[0] * 100.0, w[1] * 100.0] if w else None


def paper_stats(account: dict, closed: list[dict], positions: list[dict], snaps: list[dict], now: float) -> dict:
    start_bal = float(account["starting_balance"])
    open_pos = [p for p in positions if p["status"] == "open"]
    upnl = sum((_open_out(p)["unrealized_pnl"] or 0.0) for p in open_pos)
    equity = float(account["balance"]) + upnl

    # per-trade return on the equity at the time (balance before the close), all paper closes in order
    bal, rets_auto = start_bal, []
    curve: list[tuple[float, int, float]] = [(to_epoch(account["created_at"]), 0, start_bal)]
    for c in closed:
        pnl = float(c["pnl"] or 0.0)
        if c["source"] == "paper_auto" and bal > 0:
            rets_auto.append(pnl / bal * 100.0)
        bal += pnl
        if c["exit_time"]:
            curve.append((to_epoch(c["exit_time"]), 2, bal))
    for s in snaps:
        curve.append((to_epoch(s["ts"]), 1, float(s["equity"])))
    curve.append((now, 3, equity))
    curve.sort()
    points: dict[int, float] = {}
    for t, _, v in curve:                       # one point per second, the most exact source wins
        points[int(t)] = v
    series = sorted(points.items())

    auto = [c for c in closed if c["source"] == "paper_auto"]
    wins = sum(1 for c in auto if (c["pnl"] or 0) > 0)
    rs = [float(c["r_multiple"]) for c in auto if c["r_multiple"] is not None]
    entries_auto = [p for p in positions if p["source"] == "paper_auto"]
    daily: dict[str, float] = {}
    for t, v in series:
        daily[iso(t)[:10]] = v
    sharpe = stats.sharpe_daily(list(daily.values()), MIN_SHARPE_DAYS)
    days = max(0.0, (now - to_epoch(account["created_at"])) / 86400)
    return {
        "equity": equity, "balance": float(account["balance"]), "upnl": upnl,
        "return_pct": (equity / start_bal - 1) * 100.0 if start_bal else None,
        "n_closed": len(auto), "n_closed_manual": len(closed) - len(auto), "n_entries": len(entries_auto),
        "n_open": len(open_pos), "wins": wins,
        "win_rate_pct": wins / len(auto) * 100.0 if auto else None,
        "win_rate_ci_pct": _pct_pair(stats.wilson(wins, len(auto))),
        "avg_r": sum(rs) / len(rs) if rs else None,
        "avg_trade_ret_pct": sum(rets_auto) / len(rets_auto) if rets_auto else None,
        "trade_rets_pct": rets_auto,
        "max_dd_pct": stats.max_drawdown_pct([v for _, v in series]),
        "sharpe": sharpe, "sharpe_days": max(0, len(daily) - 1),
        "days_running": days, "progress_pct": min(100.0, len(auto) / REVIEW_MIN_TRADES * 100.0),
        "curve": [{"t": t, "equity": v} for t, v in series],
    }


def last_action(closed: list[dict], positions: list[dict]) -> Optional[dict]:
    events = []
    for p in positions:
        events.append({"time": p["entry_time"], "kind": "open", "side": p["side"], "price": p["entry_price"],
                       "reason": None, "pnl": None, "source": p["source"]})
    for c in closed:
        if c["exit_time"]:
            events.append({"time": c["exit_time"], "kind": "close", "side": c["side"], "price": c["exit_price"],
                           "reason": c["exit_reason"], "pnl": c["pnl"], "source": c["source"]})
    events = [e for e in events if e["time"]]
    return max(events, key=lambda e: (to_epoch(e["time"]), e["kind"] == "close")) if events else None


# ── drift ─────────────────────────────────────────────────────────────────

def _check(key: str, label: str, status: str, observed: Any, expected: Any, rng: Any, note: str) -> dict:
    return {"key": key, "label": label, "status": status, "observed": observed, "expected": expected,
            "range": rng, "note": note}


def drift(bt: Optional[dict], st: dict) -> dict:
    n = st["n_closed"]
    if bt is None:
        return {"status": STATUS_BELUM, "has_backtest": False, "checks": [],
                "summary": "Preset ini tidak menyimpan metrik backtest/holdout, jadi tidak ada acuan pembanding."}
    checks = []

    # 1) trade frequency: entries since the paper account started vs Poisson(rate x elapsed months)
    months = st["days_running"] / DAYS_PER_MONTH
    rate = bt["trades_per_month"]
    mu = (rate or 0.0) * months
    lo, hi = stats.poisson_range(mu)
    obs = st["n_entries"]
    if mu < MIN_EXPECTED_ENTRIES:
        s = STATUS_BELUM
        note = (f"Baru {st['days_running']:.1f} hari: backtest memperkirakan {mu:.1f} entry, terlalu sedikit untuk "
                f"dinilai (butuh perkiraan ≥ {MIN_EXPECTED_ENTRIES:.0f}).")
    else:
        s = STATUS_SESUAI if lo <= obs <= hi else STATUS_MENYIMPANG
        note = (f"Rentang 95% Poisson untuk {mu:.1f} entry yang diharapkan: {lo}–{hi}. Trade cenderung bergerombol "
                "per rezim pasar, jadi rentang sebenarnya sedikit lebih lebar.")
    checks.append(_check("frequency", "Frekuensi trade", s, obs, mu, [lo, hi], note))

    # 2) win rate: wins out of n vs Binomial(n, backtest win rate)
    p0 = bt["win_rate_pct"]
    if p0 is None:
        checks.append(_check("win_rate", "Win rate", STATUS_BELUM, st["win_rate_pct"], None, None,
                             "Backtest tidak menyimpan win rate."))
    else:
        wlo, whi = stats.binom_range(n, p0 / 100.0)
        if n < MIN_TRADES_RATE:
            s = STATUS_BELUM
            note = f"Baru {n} trade tertutup; win rate baru bisa dinilai setelah {MIN_TRADES_RATE} trade."
        else:
            s = STATUS_SESUAI if wlo <= st["wins"] <= whi else STATUS_MENYIMPANG
            note = (f"Dengan win rate backtest {p0:.0f}%, dari {n} trade diharapkan {wlo}–{whi} menang "
                    f"(rentang binomial 95%). Paper: {st['wins']} menang.")
        checks.append(_check("win_rate", "Win rate", s, st["win_rate_pct"], p0,
                             [wlo / n * 100, whi / n * 100] if n else None, note))

    # 3) mean per-trade return (% of equity) vs the backtest's geometric mean per trade
    g = bt["per_trade_ret_pct"]
    ci = stats.mean_ci(st["trade_rets_pct"])
    if g is None:
        s, note = STATUS_BELUM, "Backtest tidak menyimpan net return."
    elif n < MIN_TRADES_RATE or ci is None:
        s = STATUS_BELUM
        note = (f"Baru {n} trade tertutup; rata-rata hasil per trade baru bisa dinilai setelah {MIN_TRADES_RATE} "
                "trade. Backtest tidak menyimpan R per trade, jadi pembandingnya % ekuitas per trade.")
    else:
        s = STATUS_SESUAI if ci["lo"] <= g <= ci["hi"] else STATUS_MENYIMPANG
        note = (f"Interval t 95% rata-rata paper: {ci['lo']:+.2f}% s/d {ci['hi']:+.2f}% per trade; backtest "
                f"{g:+.2f}% (rata-rata geometrik, sedikit di bawah rata-rata biasa).")
    checks.append(_check("trade_return", "Hasil per trade (% ekuitas)", s, st["avg_trade_ret_pct"], g,
                         [ci["lo"], ci["hi"]] if ci else None, note))

    # 4) drawdown: one-sided. Deeper than the backtest MC DD95 tail is evidence; shallower proves little early on.
    # the deeper of MC DD95 and the realised holdout max DD: a DD the backtest itself went through is no drift
    limit = min((v for v in (bt["mc_dd_p95_pct"], bt["max_dd_pct"]) if v is not None), default=None)
    dd = st["max_dd_pct"]
    if limit is None or dd is None:
        s, note = STATUS_BELUM, "Backtest tidak menyimpan drawdown."
    elif dd < limit:
        s = STATUS_MENYIMPANG
        note = (f"DD paper {dd:.1f}% lebih dalam dari batas backtest {limit:.1f}% "
                "(yang lebih dalam dari MC DD95 dan max DD holdout).")
    elif n >= REVIEW_MIN_TRADES:
        s = STATUS_SESUAI
        note = f"DD paper {dd:.1f}% masih dalam batas backtest {limit:.1f}%."
    else:
        s = STATUS_BELUM
        note = (f"DD paper {dd:.1f}% belum menembus batas backtest {limit:.1f}%. DD dangkal di awal belum "
                f"membuktikan apa-apa; dinilai 'sesuai' setelah {REVIEW_MIN_TRADES} trade.")
    checks.append(_check("drawdown", "Max drawdown", s, dd, bt["max_dd_pct"],
                         [limit, 0.0] if limit is not None else None, note))

    # avg R: informative only (the stored backtest has no per-trade R)
    checks.append(_check("avg_r", "Rata-rata R", "info", st["avg_r"], None, None,
                         "Hanya info: backtest tidak menyimpan R per trade, jadi R tidak dibandingkan."))

    judged = [c for c in checks if c["status"] != "info"]
    if any(c["status"] == STATUS_MENYIMPANG for c in judged):
        status = STATUS_MENYIMPANG
        bad = ", ".join(c["label"].lower() for c in judged if c["status"] == STATUS_MENYIMPANG)
        summary = f"Menyimpang dari backtest: {bad}. Satu cek di luar rentang 95% bisa juga kebetulan (≈5% per cek)."
    elif n >= REVIEW_MIN_TRADES and all(c["status"] == STATUS_SESUAI for c in judged):
        status = STATUS_SESUAI
        summary = f"{n} trade, semua cek dalam rentang backtest. Siap direview (aturan ≥ {REVIEW_MIN_TRADES} trade)."
    else:
        status = STATUS_BELUM
        summary = (f"{n}/{REVIEW_MIN_TRADES} trade tertutup. Belum cukup data untuk menilai; "
                   "belum ada cek yang keluar dari rentang backtest.")
    return {"status": status, "has_backtest": True, "checks": checks, "summary": summary}


# ── assembly ──────────────────────────────────────────────────────────────

def _table_exists(conn, name: str) -> bool:
    return conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)).fetchone() is not None


def paper_presets(conn) -> list[dict]:
    """One row per (preset, its auto-paper watch). Newest watch wins if a preset has several."""
    if not (_table_exists(conn, "lab_presets") and _table_exists(conn, "lab_preset_links")):
        return []
    rows = conn.execute(
        "SELECT p.*, w.id AS w_id, w.active AS w_active, w.autopaper_enabled AS w_auto, "
        "w.autopaper_account_id AS acct_id, w.created_at AS w_created "
        "FROM lab_presets p JOIN lab_preset_links l ON l.preset_id=p.id AND l.kind='watch' "
        "JOIN watches w ON w.id=l.ref_id "
        "JOIN paper_accounts a ON a.id=w.autopaper_account_id "
        "WHERE p.archived=0 ORDER BY p.id, w.id DESC").fetchall()
    seen, out = set(), []
    for r in rows:
        if r["id"] in seen:
            continue
        seen.add(r["id"])
        out.append(dict(r))
    return out


def _watch_out(conn, r: dict, account: dict, paper_open: bool) -> dict:
    ws = conn.execute("SELECT computed_at, last_bar, position_json, last_signal_json, error FROM watch_state "
                      "WHERE watch_id=?", (r["w_id"],)).fetchone()
    pos = loads(ws["position_json"]) if ws else None
    strat = None
    if pos:
        before = bool(pos.get("entry_time")) and to_epoch(pos["entry_time"]) < to_epoch(account["created_at"])
        strat = {"side": pos.get("side"), "entry_price": pos.get("entry_price"), "entry_time": pos.get("entry_time"),
                 "opened_before_paper": before, "mirrored": paper_open}
    return {"id": r["w_id"], "active": bool(r["w_active"]), "autopaper_enabled": bool(r["w_auto"]),
            "last_eval_at": ws["computed_at"] if ws else None, "last_bar": ws["last_bar"] if ws else None,
            "last_signal": loads(ws["last_signal_json"]) if ws else None, "error": ws["error"] if ws else None,
            "strategy_position": strat}


def build(conn, now: Optional[float] = None, with_curves: bool = False) -> dict:
    now = now or time.time()
    presets = paper_presets(conn)
    snaps = snapshots(conn, [int(r["acct_id"]) for r in presets])
    rows = []
    for r in presets:
        holdout = loads(r["holdout_json"])
        preset = {"id": r["id"], "name": r["name"], "label": r["label"], "symbol": r["symbol"],
                  "coin": coin(r["symbol"]), "timeframe": r["timeframe"], "template_id": r["template_id"],
                  "verdict": r["verdict"], "live_reference": bool(r["live_reference"]), "holdout": holdout}
        fam = sizing_family(r["label"], holdout)
        preset.update({"family": fam, "family_label": FAMILY_LABEL.get(fam, fam),
                       "base": f"{coin(r['symbol'])}-{base_label(r['label'])}"})
        account = dict(conn.execute("SELECT * FROM paper_accounts WHERE id=?", (r["acct_id"],)).fetchone())
        closed, positions = _paper_rows(conn, account["id"])
        st = paper_stats(account, closed, positions, snaps.get(int(account["id"]), []), now)
        bt = backtest_expectations(preset)
        open_pos = [_open_out(p) for p in positions if p["status"] == "open"]
        dr = drift(bt, st)
        curve = st.pop("curve")
        st.pop("trade_rets_pct")
        row = {
            "preset": {k: v for k, v in preset.items() if k != "holdout"},
            "account": {"id": account["id"], "name": account["name"], "starting_balance": account["starting_balance"],
                        "leverage_max": account["leverage_max"], "risk_pct": account["risk_pct"],
                        "created_at": account["created_at"]},
            "watch": _watch_out(conn, r, account, bool(open_pos)),
            "stats": st, "open_position": open_pos[0] if open_pos else None, "n_open_positions": len(open_pos),
            "last_action": last_action(closed, positions), "backtest": bt, "drift": dr,
        }
        if with_curves:
            row["curve"] = curve
        rows.append(row)
    return {
        "generated_at": iso(now), "review_min_trades": REVIEW_MIN_TRADES,
        "method": {"confidence": 0.95, "min_trades_rate": MIN_TRADES_RATE,
                   "min_expected_entries": MIN_EXPECTED_ENTRIES, "min_sharpe_days": MIN_SHARPE_DAYS,
                   "snapshots": "per jam (job arena_snapshot)"},
        "rows": rows,
    }


def curves(conn, now: Optional[float] = None) -> dict:
    """Equity curves only (smaller payload for the chart)."""
    b = build(conn, now, with_curves=True)
    return {"generated_at": b["generated_at"], "series": [
        {"preset_id": r["preset"]["id"], "name": r["preset"]["name"], "coin": r["preset"]["coin"],
         "family": r["preset"]["family"], "base": r["preset"]["base"], "account_id": r["account"]["id"],
         "starting_balance": r["account"]["starting_balance"],
         "points": [{"t": iso(p["t"]), "equity": p["equity"]} for p in r["curve"]]} for r in b["rows"]]}
