#!/usr/bin/env python3
"""Seed research presets + forward paper watches into the Strategy Lab (idempotent).

Reads ``lab_presets_seed.json`` (next to this file) and, for every entry:
  1. preset  : 4H-ETH-Basic is the read-only live reference (presets.seed()); any other
               entry is inserted into lab_presets with its research provenance (verdict,
               holdout numbers, snooping/holdout-touch counts, docs path) when no
               non-archived preset of that name exists. An existing preset with the same
               name but different params is NOT touched (reported as a conflict).
  2. account : a paper account "Paper <preset>" (simulated money only), reused by name.
  3. watch   : a signal watch started from the preset with auto-paper on that account,
               through the same code path as POST /api/v1/lab/presets/{id}/watch. Skipped
               when an active watch linked to the preset already auto-papers that account.

Paper only: no exchange keys, no orders, nothing under src/trading. Lab watches never
send Telegram; this script also forces LAB_TELEGRAM_ENABLED=0 for its own process and
never edits .env.

Dry-run by default; pass --apply to write.

    /root/crypto-screener/.venv/bin/python ops/lab_seed_presets.py --repo /root/crypto-screener          # plan
    /root/crypto-screener/.venv/bin/python ops/lab_seed_presets.py --repo /root/crypto-screener --apply  # write
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent


def _args(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--repo", default=str(HERE.parent), help="crypto-screener checkout whose src/ to use")
    ap.add_argument("--manifest", default=str(HERE / "lab_presets_seed.json"))
    ap.add_argument("--db", default=None, help="lab.db path (default: LAB_DB_PATH from the repo .env)")
    ap.add_argument("--only", default="", help="comma list of preset names (default: all in the manifest)")
    ap.add_argument("--balance", type=float, default=None, help="override starting balance (USDT)")
    ap.add_argument("--apply", action="store_true", help="write (default: dry-run)")
    return ap.parse_args(argv)


def paper_sizing(entry: dict, params: dict) -> tuple[float, float]:
    """(risk_pct, leverage_max) of the paper account.

    "mirror" (default) reproduces the backtest's sizing: notional = equity x leverage x
    margin%, independent of the stop distance (4H-ETH-Basic: 4 x 50% = 2x). The paper
    engine sizes risk_pct/stop-distance capped at leverage_max, so risk_pct=100 with
    leverage_max = the backtest notional multiple always hits the cap.
    """
    s = entry.get("paper", {})
    if s.get("sizing", "mirror") == "mirror":
        return 100.0, round(float(params["leverage"]) * float(params["portfolio_risk"]) / 100.0, 4)
    return float(s.get("risk_pct", 0.5)), float(s.get("leverage_max", 5.0))


def main(argv=None) -> int:
    a = _args(argv)
    os.environ["LAB_TELEGRAM_ENABLED"] = "0"
    if a.db:
        os.environ["LAB_DB_PATH"] = a.db
    sys.path.insert(0, str(Path(a.repo).resolve()))
    from src.api import lab_routes
    from src.api.lab_models import PresetWatch
    from src.lab import db as labdb
    from src.lab import paper
    from src.lab import presets as pr
    from src.lab.settings import get_lab_settings
    from src.lab.templates import get_template
    from fastapi import HTTPException

    s = get_lab_settings()
    manifest = json.loads(Path(a.manifest).read_text())
    only = {x.strip() for x in a.only.split(",") if x.strip()}
    entries = [e for e in manifest["presets"] if not only or e["name"] in only]
    if only - {e["name"] for e in entries}:
        print(f"unknown names in --only: {sorted(only - {e['name'] for e in entries})}", file=sys.stderr)
        return 2
    print(f"lab.db: {s.db_path}  mode: {'APPLY' if a.apply else 'dry-run'}  "
          f"lab telegram enabled: {s.telegram_enabled} (watches never alert)")
    conn = labdb.connect()
    pr.ensure_schema(conn)
    had_live = conn.execute("SELECT 1 FROM lab_presets WHERE name=? AND archived=0 AND live_reference=1",
                            (pr.LIVE_NAME,)).fetchone() is not None
    if a.apply:
        pr.seed(conn)
    report, rc = [], 0
    for e in entries:
        name, row = e["name"], {"name": e["name"]}
        t = get_template(e["template_id"])
        if t is None:
            raise SystemExit(f"{name}: unknown template {e['template_id']}")
        # ── 1. preset ──
        if e.get("live_reference"):
            if name != pr.LIVE_NAME:
                raise SystemExit(f"{name}: only {pr.LIVE_NAME} can be the live reference")
            r = conn.execute("SELECT * FROM lab_presets WHERE name=? AND archived=0 AND live_reference=1",
                             (name,)).fetchone()
            params = dict(t.defaults()) if r is None else labdb.loads(r["params_json"], {})
            row["preset"] = ("exists (live reference)" if had_live else
                             "seeded (live reference)" if r is not None else "would seed (live reference)")
        else:
            params = lab_routes._validate(t, e["timeframe"], e["params"])
            if pr.make_name(e["timeframe"], e["symbol"], e["label"]) != name:
                raise SystemExit(f"{name}: name does not match {e['timeframe']}/{e['symbol']}/{e['label']}")
            r = conn.execute("SELECT * FROM lab_presets WHERE name=? AND archived=0", (name,)).fetchone()
            if r is not None:
                same = (r["template_id"] == e["template_id"] and r["symbol"] == e["symbol"]
                        and r["timeframe"] == e["timeframe"] and pr.params_match(labdb.loads(r["params_json"], {}),
                                                                                  params))
                row["preset"] = "exists" if same else "CONFLICT: same name, different params (left untouched)"
                if not same:
                    rc = 1
                    report.append(row)
                    continue
            elif a.apply:
                pr._insert(conn, label=e["label"], template_id=e["template_id"], symbol=e["symbol"],
                           timeframe=e["timeframe"], params=params, costs=e.get("costs") or dict(pr.DEFAULT_COSTS),
                           notes=e.get("notes"), source_run_id=e.get("source_run_id"),
                           source_mode=e.get("source_mode", "research"), verdict=e.get("verdict"),
                           holdout=e.get("holdout"), snooping=e.get("snooping"))
                row["preset"] = "created"
            else:
                row["preset"] = "would create"
        pid_row = conn.execute("SELECT id FROM lab_presets WHERE name=? AND archived=0", (name,)).fetchone()
        pid = pid_row["id"] if pid_row else None
        row["preset_id"] = pid

        # ── 2. paper account ──
        acct_name = f"Paper {name}"
        risk_pct, lev_max = paper_sizing(e, params)
        balance = a.balance or float(e.get("paper", {}).get("balance", 10000.0))
        ar = conn.execute("SELECT id FROM paper_accounts WHERE name=? ORDER BY id LIMIT 1", (acct_name,)).fetchone()
        if ar is not None:
            aid, row["account"] = ar["id"], "exists"
        elif a.apply:
            aid = paper.create_account(conn, acct_name, balance, risk_pct, lev_max)
            row["account"] = "created"
        else:
            aid, row["account"] = None, "would create"
        row.update(account_id=aid, account_name=acct_name, balance=balance, risk_pct=risk_pct, leverage_max=lev_max)

        # ── 3. watch + auto-paper ──
        w = None
        if pid is not None:
            w = conn.execute(
                "SELECT w.id, w.autopaper_account_id, w.autopaper_enabled FROM watches w JOIN lab_preset_links l "
                "ON l.kind='watch' AND l.ref_id=w.id WHERE l.preset_id=? AND w.active=1 ORDER BY w.id",
                (pid,)).fetchall()
            w = next((x for x in w if aid is not None and x["autopaper_account_id"] == aid), None)
        if w is not None:
            row["watch"], row["watch_id"] = ("exists" if w["autopaper_enabled"] else "exists (auto-paper OFF)"), w["id"]
        elif a.apply:
            try:
                res = lab_routes.watch_from_preset(pid, PresetWatch(autopaper_account_id=aid), None, conn)
            except HTTPException as ex:
                row["watch"], rc = f"ERROR {ex.status_code}: {ex.detail}", 1
            else:
                row["watch"], row["watch_id"] = "created (auto-paper on)", res["watch_id"]
        else:
            row["watch"] = "would create (auto-paper on)"
        report.append(row)
    conn.close()
    for row in report:
        print(json.dumps(row, ensure_ascii=False))
    if not a.apply:
        print("dry-run only: nothing written. Re-run with --apply.")
    return rc


if __name__ == "__main__":
    sys.exit(main())
